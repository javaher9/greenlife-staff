import json
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .digital_referral_forms import DigitalLeadForm, DigitalReferralSignupForm
from .digital_referral_models import DigitalReferralLead, DigitalReferralProfile
from .models import EmployeeProfile, StaffNotification


SOURCE_MAP = dict(DigitalReferralProfile.SOURCE_CHOICES)


def _source_from_request(request, sponsor=None):
    if sponsor:
        return sponsor.source
    source = (request.GET.get('source') or request.POST.get('source') or 'instagram').strip().lower()
    return source if source in SOURCE_MAP else 'other'


def _manager_allowed(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return getattr(getattr(user, 'profile', None), 'role', '') in ('admin', 'internal_manager', 'manager')


def _auto_assign_call_center(lead):
    operator = (
        EmployeeProfile.objects.filter(role='call_center', is_active=True, user__is_active=True)
        .annotate(
            digital_open=Count(
                'assigned_digital_referral_leads',
                filter=Q(assigned_digital_referral_leads__status__in=('new', 'contacted', 'appointment')),
            )
        )
        .order_by('digital_open', 'id')
        .first()
    )
    if operator:
        lead.assigned_to = operator
        lead.save(update_fields=['assigned_to', 'updated_at'])
        StaffNotification.objects.create(
            user=operator.user,
            title='لید دیجیتال جدید',
            message=f'{lead.full_name} با شماره {lead.phone} از شبکه جذب دیجیتال به صف شما اضافه شد.',
            notification_type='call_center_lead',
            related_date=timezone.localdate(),
        )
    return operator


def digital_signup(request):
    sponsor = None
    sponsor_code = (request.GET.get('ref') or request.POST.get('ref') or '').strip()
    if sponsor_code:
        sponsor = DigitalReferralProfile.objects.filter(referral_code=sponsor_code, is_active=True).select_related('user').first()
        if sponsor and sponsor.sponsor_id:
            messages.error(request, 'این لینک در سطح دوم شبکه است و امکان ساخت سطح سوم وجود ندارد.')
            sponsor = None

    source = _source_from_request(request, sponsor=sponsor)
    form = DigitalReferralSignupForm(request.POST or None, request.FILES or None)

    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            user = User.objects.create_user(
                username=data['username'],
                password=data['password'],
                first_name=data['first_name'],
                last_name=data['last_name'],
            )
            profile = DigitalReferralProfile.objects.create(
                user=user,
                sponsor=sponsor,
                source=source,
                phone=data['phone'],
                photo=data['photo'],
                referral_code=DigitalReferralProfile.new_code(),
            )
        login(request, user)
        messages.success(request, 'عضویت شما در شبکه دیجیتال گرین‌لایف با موفقیت انجام شد.')
        return redirect('digital_referral_portal')

    return render(
        request,
        'core/digital_referrals/signup.html',
        {
            'form': form,
            'source': source,
            'source_title': SOURCE_MAP[source],
            'sponsor': sponsor,
            'ref_code': sponsor_code,
        },
    )


@login_required
def digital_referral_portal(request):
    profile = DigitalReferralProfile.objects.filter(user=request.user, is_active=True).select_related('user').first()
    if not profile:
        if _manager_allowed(request.user):
            return redirect('digital_referral_dashboard')
        raise Http404('پروفایل شبکه دیجیتال یافت نشد.')

    form = DigitalLeadForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        lead = DigitalReferralLead.objects.create(referrer=profile, **form.cleaned_data)
        _auto_assign_call_center(lead)
        messages.success(request, 'مشتری ثبت شد و برای پیگیری به کال‌سنتر ارسال شد.')
        return redirect('digital_referral_portal')

    invite_url = request.build_absolute_uri(reverse('digital_referral_signup'))
    separator = '&' if '?' in invite_url else '?'
    invite_url = f'{invite_url}{separator}source={profile.source}&ref={profile.referral_code}'

    return render(
        request,
        'core/digital_referrals/portal.html',
        {
            'profile': profile,
            'form': form,
            'invite_url': invite_url,
            'member_count': profile.members.filter(is_active=True).count(),
            'lead_count': profile.digital_leads.count(),
            'won_count': profile.digital_leads.filter(status='won').count(),
            'recent_members': profile.members.filter(is_active=True).select_related('user')[:8],
            'recent_leads': profile.digital_leads.all()[:8],
        },
    )


@login_required
def digital_referral_dashboard(request):
    if not _manager_allowed(request.user):
        messages.error(request, 'این بخش فقط برای مدیریت قابل دسترسی است.')
        return redirect('dashboard')

    profiles = DigitalReferralProfile.objects.filter(is_active=True).select_related('user', 'sponsor__user')
    leads = DigitalReferralLead.objects.filter(referrer__is_active=True).select_related('referrer__user', 'assigned_to__user')

    selected_source = (request.GET.get('source') or 'all').strip().lower()
    if selected_source in SOURCE_MAP:
        profiles = profiles.filter(source=selected_source)
        leads = leads.filter(referrer__source=selected_source)
    else:
        selected_source = 'all'

    today = timezone.localdate()
    start = today - timedelta(days=29)
    member_daily_raw = dict(
        profiles.filter(created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Count('id'))
        .values_list('day', 'total')
    )
    lead_daily_raw = dict(
        leads.filter(created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(total=Count('id'))
        .values_list('day', 'total')
    )
    days = [start + timedelta(days=i) for i in range(30)]

    source_rows = []
    for key, label in DigitalReferralProfile.SOURCE_CHOICES:
        p = DigitalReferralProfile.objects.filter(is_active=True, source=key)
        l = DigitalReferralLead.objects.filter(referrer__source=key, referrer__is_active=True)
        source_rows.append(
            {
                'key': key,
                'label': label,
                'members': p.count(),
                'leads': l.count(),
                'won': l.filter(status='won').count(),
                'today_members': p.filter(created_at__date=today).count(),
            }
        )

    signup_base = request.build_absolute_uri(reverse('digital_referral_signup'))
    signup_links = [
        {'key': key, 'label': label, 'url': f'{signup_base}?source={key}'}
        for key, label in DigitalReferralProfile.SOURCE_CHOICES
        if key != 'other'
    ]

    return render(
        request,
        'core/digital_referrals/dashboard.html',
        {
            'profiles': profiles,
            'leads': leads,
            'selected_source': selected_source,
            'sources': DigitalReferralProfile.SOURCE_CHOICES,
            'source_rows': source_rows,
            'signup_links': signup_links,
            'member_count': profiles.count(),
            'lead_count': leads.count(),
            'won_count': leads.filter(status='won').count(),
            'today_members': profiles.filter(created_at__date=today).count(),
            'today_leads': leads.filter(created_at__date=today).count(),
            'conversion_rate': round(leads.filter(status='won').count() * 100 / max(1, leads.count())),
            'recent_members': profiles[:12],
            'recent_leads': leads[:12],
            'chart_labels': json.dumps([day.strftime('%m/%d') for day in days]),
            'chart_members': json.dumps([member_daily_raw.get(day, 0) for day in days]),
            'chart_leads': json.dumps([lead_daily_raw.get(day, 0) for day in days]),
        },
    )
