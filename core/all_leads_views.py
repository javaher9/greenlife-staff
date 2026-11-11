"""Read-only, cursor-paginated management archive; no synthetic lead data."""
from datetime import date, datetime, time, timedelta
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db.models import Case, CharField, OuterRef, Q, Subquery, Value, When
from django.db.models.functions import Cast
from .models import AuditLog
from .country_workspace import scoped_queryset
from .supervision_text import safe_label
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET

from .call_center_identity import call_center_display_name
from .jalali import format_jalali, gregorian_to_jalali, jalali_to_gregorian
from .lead_management_views import ALLOWED_ROLES, _lead_hub_queryset
from .models import Branch, CallCenterLeadGroup, EmployeeProfile, ReferralLead, VisitAppointment

PAGE_SIZE = 120
CURSOR_SALT = 'management-all-leads-v1'
STATES = {
    'new': 'جدید', 'contacted': 'تماس گرفته شد', 'follow_up': 'نیاز به پیگیری',
    'no_answer': 'پاسخ نداد', 'appointment': 'نوبت داده شد', 'visited': 'مراجعه کرد',
    'no_show': 'مراجعه نکرد', 'won': 'پکیج موفق', 'sale_lost': 'پکیج ناموفق',
    'not_interested': 'تمایل ندارد', 'cancelled': 'نوبت لغو شد',
}


def management_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        profile = getattr(request.user, 'profile', None)
        if not (request.user.is_active and profile and profile.is_active and profile.role in ALLOWED_ROLES):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def archive_queryset(request):
    latest = VisitAppointment.objects.filter(lead_id=OuterRef('pk')).order_by('-created_at', '-pk')
    base = _lead_hub_queryset(request, ReferralLead.objects.all())
    if request.user.profile.role == 'internal_manager':
        base = scoped_queryset(request, base)
    elif request.user.profile.role == 'manager':
        base = base.filter(appointments__branch_id=request.user.profile.branch_id).distinct() if request.user.profile.branch_id else base.none()
    actions = AuditLog.objects.filter(object_type='ReferralLead', object_id=Cast(OuterRef('pk'),CharField()),action='lead_contact_result').order_by('-created_at')
    qs = base.annotate(
        last_action=Subquery(actions.values('created_at')[:1]),
        last_visit_status=Subquery(latest.values('status')[:1]),
        last_branch=Subquery(latest.values('branch_id')[:1]),
        last_plan_status=Subquery(latest.values('consultation_plan__status')[:1]),
    )
    # A missing payment, expired appointment or draft plan is not a failed sale/no-show.
    return qs.annotate(archive_state=Case(
        When(Q(last_plan_status__in=('paid', 'partial_paid')) | Q(sale__status__in=('approved', 'paid')) | Q(status='won'), then=Value('won')),
        When(last_plan_status='no_sale', then=Value('sale_lost')),
        When(contact_result='won', then=Value('won')),
        When(contact_result='sale_lost', then=Value('sale_lost')),
        When(last_visit_status='no_show', then=Value('no_show')),
        When(Q(last_visit_status__in=('arrived', 'completed')) | Q(status='visited'), then=Value('visited')),
        When(last_visit_status='booked', then=Value('appointment')),
        When(last_visit_status='cancelled', then=Value('cancelled')),
        *[When(contact_result=key, then=Value(key)) for key in ('follow_up', 'no_answer', 'appointment', 'not_interested')],
        When(status='appointment', then=Value('appointment')),
        When(status='lost', then=Value('not_interested')),
        When(status='contacted', next_follow_up__isnull=False, then=Value('follow_up')),
        When(status='contacted', then=Value('contacted')),
        default=Value('new'), output_field=CharField(),
    ))


@require_GET
@management_required
def all_leads(request):
    supervisory=request.user.profile.role == 'internal_manager'
    qs=archive_queryset(request)
    flowers=EmployeeProfile.objects.filter(pk__in=qs.values('assigned_to_id')).select_related('user').distinct()
    branches=Branch.objects.filter(pk__in=qs.values('last_branch')).order_by('name')
    groups=CallCenterLeadGroup.objects.filter(pk__in=qs.values('group_id')).order_by('name')
    return render(request, 'core/all_leads.html', {
        'flowers':[(p.pk,safe_label(call_center_display_name(p))) for p in flowers],
        'branches':[{'pk':b.pk,'name':safe_label(b.name)} for b in branches],
        'groups':[{'pk':g.pk,'name':safe_label(g.name)} for g in groups],
        'states': STATES.items(), 'supervisory':supervisory,
    })



def date_boundary(value):
    digits = value.translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
    year, month, day = map(int, digits.replace('-', '/').split('/'))
    if not (1300 <= year <= 1500 and 1 <= month <= 12 and 1 <= day <= (31 if month <= 6 else 30)):
        raise ValueError('تاریخ نامعتبر است.')
    converted = date(*jalali_to_gregorian(year, month, day))
    if gregorian_to_jalali(converted.year, converted.month, converted.day) != (year, month, day):
        raise ValueError('تاریخ نامعتبر است.')
    return timezone.make_aware(datetime.combine(converted, time.min))


@require_GET
@management_required
def all_leads_data(request):
    params = {key: request.GET.get(key, '').strip() for key in ('q', 'flower', 'branch', 'group', 'state', 'from', 'to', 'untouched', 'overdue', 'sort')}
    qs = archive_queryset(request)
    try:
        for key, field in (('flower', 'assigned_to_id'), ('branch', 'last_branch'), ('group', 'group_id')):
            if params[key]:
                if params[key] == 'none':
                    qs = qs.filter(**{field + '__isnull': True})
                else:
                    qs = qs.filter(**{field: int(params[key])})
        if params['state']:
            if params['state'] not in STATES:
                raise ValueError('وضعیت نامعتبر است.')
            qs = qs.filter(archive_state=params['state'])
        if params['untouched'] == '1':
            qs = qs.filter(status='new', contact_result='', archive_state='new', last_action__isnull=True)
        if params['overdue'] == '1':
            qs = qs.filter(next_follow_up__lt=timezone.localdate(), status__in=('new','contacted','appointment'))
        if params['from']:
            qs = qs.filter(created_at__gte=date_boundary(params['from']))
        if params['to']:
            qs = qs.filter(created_at__lt=date_boundary(params['to']) + timedelta(days=1))
        if params['from'] and params['to'] and date_boundary(params['from']) > date_boundary(params['to']):
            raise ValueError('تاریخ شروع باید قبل از پایان باشد.')
        if params['q']:
            query = params['q'][:160].translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789'))
            if request.user.profile.role == 'internal_manager':
                qs = qs.filter(full_name__icontains=query) if not any(c.isdigit() for c in query) else qs.none()
            else:
                qs = qs.filter(Q(full_name__icontains=query) | Q(phone__icontains=query) | Q(alternate_phone__icontains=query))
        total = None if request.GET.get('cursor') else qs.count()
        ascending = params['sort'] == 'oldest'
        if request.GET.get('cursor'):
            cursor = signing.loads(request.GET['cursor'], salt=CURSOR_SALT, max_age=86400)
            if cursor['filters'] != params:
                raise ValueError('فیلترها تغییر کرده‌اند؛ فهرست را تازه کنید.')
            point = parse_datetime(cursor['date'])
            if point is None:
                raise ValueError('نشانگر نامعتبر است.')
            op = 'gt' if ascending else 'lt'
            qs = qs.filter(Q(**{'created_at__' + op: point}) | Q(created_at=point, **{'pk__' + op: cursor['id']}))
        order = ('created_at', 'pk') if ascending else ('-created_at', '-pk')
        rows = list(qs.select_related('assigned_to__user').order_by(*order)[:PAGE_SIZE + 1])
    except (ValueError, TypeError, KeyError, signing.BadSignature):
        return JsonResponse({'error': 'فیلتر یا تاریخ نامعتبر است؛ تاریخ را به شکل 1405/08/19 وارد کنید.'}, status=400)
    more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    next_cursor = signing.dumps({'date': rows[-1].created_at.isoformat(), 'id': rows[-1].pk, 'filters': params}, salt=CURSOR_SALT) if more else None
    response = JsonResponse({'total': total, 'next': next_cursor, 'items': [{
        'id': lead.pk, 'name': safe_label(lead.full_name),
        'flower': safe_label(call_center_display_name(lead.assigned_to)) if lead.assigned_to_id else 'بدون مسئول',
        'date': format_jalali(timezone.localtime(lead.created_at), persian_digits=False),
        'state': lead.archive_state, 'label': STATES[lead.archive_state],
        'url': reverse('supervisory_lead', args=[lead.pk]) if request.user.profile.role == 'internal_manager' else reverse('referral_lead_manage', args=[lead.pk]),
    } for lead in rows]}, json_dumps_params={'ensure_ascii': False})
    response['Cache-Control'] = 'private, no-store'
    return response
