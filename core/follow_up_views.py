"""Date-driven callback agendas for call center and internal management."""
from datetime import date
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .call_center_identity import call_center_display_name
from .follow_up_agenda import due_follow_up_scope
from .models import EmployeeProfile, LeadFollowUpLog, ReferralLead


MANAGEMENT_TABS = {
    'today': 'تماس‌های مقرر امروز',
    'overdue': 'عقب‌افتاده',
    'future': 'آینده',
    'done': 'اقدام ثبت‌شده برای موعد امروز',
    'unscheduled': 'بدون موعد',
    'all': 'همه پیگیری‌های باز',
}
MANAGEMENT_DATE_TABS = {'today', 'overdue', 'future', 'all'}
CONTACT_RESULTS = dict(ReferralLead.CONTACT_RESULT)


def _completed_logs(today):
    # Only a recorded action on a callback already due today belongs to this history.
    return LeadFollowUpLog.objects.filter(
        created_at__date=today,
        previous_date=today,
        action__in=('attempt', 'scheduled', 'closed'),
    ).order_by()


def _active_due_leads():
    return due_follow_up_scope(ReferralLead.objects.all())


def _completed_ids(today, *, actor_id=None):
    # Only callbacks whose prior promise was due today count as completed.
    # Scheduling a brand-new lead for the future is not today's completed call.
    logs=LeadFollowUpLog.objects.filter(
        created_at__date=today,previous_date=today,
        action__in=('attempt','scheduled','closed'),
    )
    if actor_id is not None:
        logs=logs.filter(actor_id=actor_id)
    return logs.values_list('lead_id',flat=True).distinct()


def _scope(request, role):
    if role=='call_center':
        return _active_due_leads().filter(assigned_to=request.user.profile)
    return _active_due_leads().select_related('assigned_to__user')


def _category_counts(scope, today, user_id=None):
    complete=LeadFollowUpLog.objects.filter(
        created_at__date=today,previous_date=today,
        action__in=('attempt','scheduled','closed'),
    )
    if user_id:
        complete=complete.filter(actor_id=user_id)
    return {
        'today':scope.filter(next_follow_up=today).count(),
        'overdue':scope.filter(next_follow_up__lt=today).count(),
        'future':scope.filter(next_follow_up__gt=today).count(),
        'done':complete.values('lead_id').distinct().count(),
        'unscheduled':scope.filter(contact_result='follow_up',next_follow_up__isnull=True).count(),
    }


def _date_from(request):
    try:
        return date.fromisoformat(request.GET.get('date', '').strip())
    except ValueError:
        return None


def _query_string(tab, query, due_date, operator=''):
    params = {'tab': tab}
    if query:
        params['q'] = query
    if due_date and tab in MANAGEMENT_DATE_TABS:
        params['date'] = due_date.isoformat()
    if operator:
        params['operator'] = operator
    return urlencode(params)


@login_required
@require_GET
def call_center_follow_up_agenda(request):
    profile=getattr(request.user,'profile',None)
    if not profile or not profile.is_active or not request.user.is_active or profile.role!='call_center':
        return HttpResponseForbidden('دسترسی مجاز نیست.')
    today=timezone.localdate()
    scope=_scope(request,'call_center')
    counts=_category_counts(scope,today,request.user.id)
    tab=(request.GET.get('tab') or 'today').strip()
    if tab not in ('today','overdue','future','done','unscheduled'):
        tab='today'
    if tab=='today':
        rows=scope.filter(next_follow_up=today)
    elif tab=='overdue':
        rows=scope.filter(next_follow_up__lt=today)
    elif tab=='future':
        rows=scope.filter(next_follow_up__gt=today)
    elif tab=='unscheduled':
        rows=scope.filter(contact_result='follow_up',next_follow_up__isnull=True)
    else:
        ids=_completed_ids(today,actor_id=request.user.pk)
        # Show even a now-closed lead in today's completed history.
        rows=ReferralLead.objects.filter(pk__in=ids,assigned_to=profile)

    query=(request.GET.get('q') or '').strip()[:100]
    if query:
        rows=rows.filter(
            Q(full_name__icontains=query)|Q(phone__icontains=query)|
            Q(alternate_phone__icontains=query)
        )
    exact=(request.GET.get('date') or '').strip()
    try:
        exact_date=date.fromisoformat(exact) if exact else None
    except ValueError:
        exact_date=None
    if exact_date and tab=='future':
        rows=rows.filter(next_follow_up=exact_date)

    rows=rows.select_related('group','assigned_to__user').order_by(
        'next_follow_up','next_follow_up_time','pk',
    )
    page=Paginator(rows,40).get_page(request.GET.get('page'))
    # Prefetch limited history for currently visible leads only.
    history={
        lead.pk:list(LeadFollowUpLog.objects.filter(lead_id=lead.pk)
                     .select_related('actor').order_by('-created_at','-pk')[:3])
        for lead in page.object_list
    }
    cards=[{'lead':lead,'history':history[lead.pk]} for lead in page.object_list]
    params=request.GET.copy()
    params.pop('page',None)
    return render(request,'core/call_center/follow_up_agenda.html',{
        'tab':tab,'counts':counts,'today':today,'cards':cards,'page':page,
        'query':query,'exact_date':exact,'page_query':params.urlencode(),
    })


def can_access_management_follow_ups(user):
    profile = getattr(user, 'profile', None)
    return bool(user.is_active and profile and profile.is_active and
                profile.role in ('admin', 'manager', 'internal_manager'))


@login_required
@require_GET
def management_follow_up_agenda(request):
    if not can_access_management_follow_ups(request.user):
        return HttpResponseForbidden('دسترسی مجاز نیست.')

    today = timezone.localdate()
    operators = {
        str(operator.pk): call_center_display_name(operator)
        for operator in EmployeeProfile.objects.filter(
            role='call_center', is_active=True, user__is_active=True,
        ).select_related('user').order_by('pk')
    }
    tab = request.GET.get('tab', '').strip()
    if tab not in MANAGEMENT_TABS:
        tab = 'today'
    query = request.GET.get('q', '').strip()[:100]
    exact_date = _date_from(request) if tab in MANAGEMENT_DATE_TABS else None
    operator_filter = request.GET.get('operator', '').strip()
    if operator_filter != 'unassigned' and operator_filter not in operators:
        operator_filter = ''

    due = {
        'today': Q(next_follow_up=today),
        'overdue': Q(next_follow_up__lt=today),
        'future': Q(next_follow_up__gt=today),
        'unscheduled': Q(contact_result='follow_up', next_follow_up__isnull=True),
    }
    active = due_follow_up_scope(ReferralLead.objects.all()).filter(
        Q(next_follow_up__isnull=False) | due['unscheduled'],
    )
    aggregates = {key: Count('pk', filter=condition) for key, condition in due.items()}
    active_per_operator = {
        row['assigned_to_id']: row
        for row in active.order_by().values('assigned_to_id').annotate(**aggregates)
    }
    counts = {key: sum(row[key] for row in active_per_operator.values()) for key in due}
    counts['all'] = sum(counts.values())

    completed = _completed_logs(today).filter(actor__profile__role='call_center')
    counts['done'] = completed.values('lead_id').distinct().count()
    handled_per_operator = {
        str(row['actor__profile__pk']): row['total']
        for row in completed.values('actor__profile__pk').annotate(total=Count('lead_id', distinct=True))
    }
    unassigned = sum(active_per_operator.get(None, {}).get(key, 0) for key in due)
    totals = [
        {
            'operator_id': key, 'name': name,
            **{category: active_per_operator.get(int(key), {}).get(category, 0) for category in due},
            'done': handled_per_operator.get(key, 0),
            'url': '?' + _query_string(tab, query, exact_date, key) + '#follow-up-list',
        }
        for key, name in operators.items()
    ]

    if tab == 'done':
        # Past actions belong to the actor even when the lead has since been reassigned.
        if operator_filter == 'unassigned':
            completed = completed.none()
        elif operator_filter:
            completed = completed.filter(actor__profile__pk=operator_filter)
        latest = completed.filter(lead_id=OuterRef('pk')).order_by('-created_at', '-pk')
        rows = ReferralLead.objects.filter(pk__in=completed.values('lead_id')).annotate(
            handled_log_id=Subquery(latest.values('pk')[:1]),
            handled_at=Subquery(latest.values('created_at')[:1]),
        ).order_by('-handled_at', 'pk')
    else:
        rows = active.filter(due.get(tab, Q())).order_by(
            F('next_follow_up').asc(nulls_last=True),
            F('next_follow_up_time').asc(nulls_last=True),
            'pk',
        )
        if operator_filter:
            rows = rows.filter(assigned_to_id=None if operator_filter == 'unassigned' else operator_filter)
        if exact_date:
            rows = rows.filter(next_follow_up=exact_date)
    if query:
        rows = rows.filter(full_name__icontains=query)

    page = Paginator(rows.select_related('assigned_to__user').only(
        'full_name', 'contact_result', 'next_follow_up', 'next_follow_up_time',
        'assigned_to__user__first_name', 'assigned_to__user__last_name', 'assigned_to__user__username',
    ), 50).get_page(request.GET.get('page'))
    page.object_list = list(page.object_list)
    handled = {}
    if tab == 'done':
        handled = LeadFollowUpLog.objects.select_related('actor').in_bulk(
            lead.handled_log_id for lead in page.object_list
        )
    # The lead management form renders a phone number in its subtitle.
    can_open_lead = request.user.profile.role in ('admin', 'manager')
    cards = []
    for lead in page.object_list:
        event = handled.get(getattr(lead, 'handled_log_id', None))
        cards.append({
            'id': lead.pk, 'full_name': lead.full_name,
            'assigned_name': call_center_display_name(lead.assigned_to),
            'next_follow_up': event.previous_date if event else lead.next_follow_up,
            'next_follow_up_time': event.previous_time if event else lead.next_follow_up_time,
            'result_label': (
                CONTACT_RESULTS.get(event.result, event.get_action_display())
                if event else lead.get_contact_result_display()
            ),
            'handled_at': event.created_at if event else None,
            'handled_by': call_center_display_name(event.actor) if event else '',
            'detail_url': reverse('management_lead_follow_up', args=[lead.pk]) if can_open_lead else '',
        })
    page.object_list = cards
    tabs = [
        {
            'key': key, 'label': label, 'count': counts[key],
            'url': '?' + _query_string(key, query, exact_date, operator_filter),
        }
        for key, label in MANAGEMENT_TABS.items()
    ]
    return render(request, 'core/call_center/follow_up_management.html', {
        'today': today, 'tab': tab, 'counts': counts, 'totals': totals, 'page': page,
        'q': query, 'operator_filter': operator_filter,
        'operator_options': [{'id': key, 'name': name} for key, name in operators.items()],
        'exact_date_input': exact_date.isoformat() if exact_date else '',
        'date_filter_allowed': tab in MANAGEMENT_DATE_TABS,
        'has_filters': bool(query or operator_filter or exact_date),
        'unassigned': unassigned,
        'unassigned_url': '?' + _query_string('all', query, exact_date, 'unassigned') + '#follow-up-list',
        'tabs': tabs,
        'page_query': _query_string(tab, query, exact_date, operator_filter),
    })
