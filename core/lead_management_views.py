from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from django.contrib import messages
from django.views.decorators.http import require_POST

from .call_center_identity import (
    FlowerLeadProxy, FlowerProfileProxy, call_center_display_name,
)
from .models import EmployeeProfile, ReferralLead, ReferralSale
from .instagram_views import INSTAGRAM_PAGE_SOURCES
from .jalali import gregorian_to_jalali


ALLOWED_ROLES = ('admin', 'manager', 'internal_manager')
OPEN_STATUSES = ('new', 'contacted', 'appointment')
STATUS_FILTER_CHOICES = (
    ('new', 'جدید'),
    ('contacted', 'تماس گرفته شد'),
    ('follow_up', 'نیاز به پیگیری مجدد'),
    ('appointment', 'نوبت داده شد'),
    ('visited', 'مراجعه کرد'),
    ('won', 'فروش موفق'),
    ('lost', 'تمایل به پیگیری ندارد'),
)


def _person_name(user):
    if not user:
        return '—'
    return user.get_full_name() or user.username or '—'


def _network_root(profile):
    if not profile:
        return None
    root = profile
    seen = set()
    while getattr(root, 'sponsor_id', None) and root.pk not in seen:
        seen.add(root.pk)
        root = root.sponsor
    return root


def _enrich_referral_group_label(lead):
    group = getattr(lead, 'group', None)
    if not group or group.name != 'شبکه فروش پرسنل':
        return
    referrer = getattr(lead, 'referrer', None)
    if not referrer:
        return
    root = _network_root(referrer)
    referrer_name = _person_name(getattr(referrer, 'user', None))
    root_name = _person_name(getattr(root, 'user', None)) if root else '—'
    label = f'معرف: {referrer_name} · شبکه: {root_name}'
    creator = getattr(lead, 'created_by', None)
    if creator and getattr(creator, 'id', None) != getattr(referrer, 'user_id', None):
        label += f' · ثبت: {_person_name(creator)}'
    group.name = label


def _attention_reason(lead, now, today):
    if not lead.assigned_to_id:
        return 'بدون مسئول؛ باید به یک اپراتور تخصیص داده شود'
    if lead.status == 'new' and lead.created_at < now - timedelta(hours=2):
        return 'بیش از ۲ ساعت از ورود گذشته و هنوز تماس ثبت نشده'
    if lead.status in OPEN_STATUSES and lead.next_follow_up and lead.next_follow_up < today:
        return 'موعد پیگیری گذشته و باید دوباره پیگیری شود'
    return 'نیاز به بررسی مدیر'


class AttentionLeadProxy(FlowerLeadProxy):
    """Lead Hub proxy that explains why a lead is urgent and gives managers actions."""

    def __init__(self, lead, now, today):
        super().__init__(lead)
        self._attention_now = now
        self._attention_today = today

    @property
    def full_name(self):
        lead = self._flower_lead
        reason = _attention_reason(lead, self._attention_now, self._attention_today)
        manage_url = reverse('referral_lead_manage', args=[lead.pk])
        phone = ''.join(ch for ch in (lead.phone or '') if ch.isdigit() or ch == '+')
        manage_label = 'تخصیص مسئول' if not lead.assigned_to_id else 'باز کردن و پیگیری'
        return format_html(
            '<span style="display:block;font-weight:900;color:#fff;margin-bottom:4px">{}</span>'
            '<span style="display:block;color:#ffd27d;font-size:9px;margin-bottom:6px;white-space:normal;line-height:1.7">علت: {}</span>'
            '<span style="display:flex;gap:5px;flex-wrap:wrap">'
            '<a href="tel:{}" style="display:inline-flex;align-items:center;padding:5px 8px;border-radius:8px;background:#153b32;color:#86f0c0;text-decoration:none;font-size:9px;font-weight:900">☎ تماس</a>'
            '<a href="{}" style="display:inline-flex;align-items:center;padding:5px 8px;border-radius:8px;background:#302753;color:#d8ccff;text-decoration:none;font-size:9px;font-weight:900">{}</a>'
            '</span>',
            lead.full_name,
            reason,
            phone,
            manage_url,
            manage_label,
        )


def _channel_q(channel):
    marker = f'[channel:{channel}]'
    if channel == 'instagram':
        return Q(group__name__in=('اینستاگرام جدید', 'اینستاگرام - لینک')) | Q(notes__icontains='[channel:instagram]') | Q(source_url__icontains='/instagram/')
    if channel == 'telegram':
        return Q(group__name='تلگرام - لینک') | Q(notes__icontains='[channel:telegram]') | Q(notes__icontains='ورودی مستقیم فرم تلگرام') | Q(source_url__icontains='/telegram/')
    if channel == 'bale':
        return Q(group__name='بله - لینک') | Q(notes__icontains='[channel:bale]') | Q(notes__icontains='ورودی مستقیم فرم بله') | Q(source_url__icontains='/bale/')
    if channel == 'website':
        return Q(notes__icontains=marker) | (Q(source_url__icontains='greenlifeclinics.com') & ~Q(source_url__icontains='/instagram/') & ~Q(source_url__icontains='/telegram/') & ~Q(source_url__icontains='/bale/'))
    if channel == 'crm':
        return Q(notes__icontains=marker) | Q(source_url__icontains='crm')
    if channel == 'whatsapp':
        return Q(notes__icontains=marker) | Q(source_url__icontains='whatsapp') | Q(source_url__icontains='wa.me')
    if channel == 'campaign':
        return Q(notes__icontains=marker) | Q(source_url__icontains='utm_campaign=')
    return Q()


def _channel_counts(leads):
    channels = [('instagram','اینستاگرام','#ec4899'),('website','وب‌سایت','#3b82f6'),('crm','CRM','#8b5cf6'),('whatsapp','واتس‌اپ','#22c55e'),('campaign','کمپین / UTM','#f59e0b'),('telegram','تلگرام','#38bdf8'),('bale','بله','#10b981')]
    claimed = Q(pk__in=[])
    rows = []
    for key, label, color in channels:
        q = _channel_q(key); count = leads.filter(q).count(); rows.append({'key':key,'label':label,'count':count,'color':color}); claimed |= q
    rows.extend([{'key':'panel','label':'ثبت در پنل','count':leads.filter(source='panel').count(),'color':'#06b6d4'},{'key':'qr','label':'QR','count':leads.filter(source='qr').count(),'color':'#14b8a6'},{'key':'other','label':'سایر / قدیمی','count':leads.exclude(claimed).filter(source='link').count(),'color':'#94a3b8'}])
    max_count = max([row['count'] for row in rows] or [1]) or 1
    for row in rows: row['bar'] = round(row['count'] * 100 / max_count, 1)
    return rows


def _instagram_page_rows(leads):
    instagram = leads.filter(_channel_q('instagram'))
    rows = []
    claimed = Q(pk__in=[])
    for slug, label in INSTAGRAM_PAGE_SOURCES.items():
        q = Q(notes__icontains=f'[instagram_page:{slug}]')
        page_qs = instagram.filter(q)
        rows.append({
            'slug': slug,
            'label': label,
            'total': page_qs.count(),
            'link': page_qs.filter(source='link').count(),
            'manual': page_qs.filter(source='panel').count(),
        })
        claimed |= q
    legacy = instagram.exclude(claimed).count()
    if legacy:
        rows.append({
            'slug': 'legacy',
            'label': 'قدیمی / نامشخص',
            'total': legacy,
            'link': instagram.exclude(claimed).filter(source='link').count(),
            'manual': instagram.exclude(claimed).filter(source='panel').count(),
        })
    return rows


def _successful_lead_ids(leads):
    """A successful lead is either explicitly won or has a real approved/paid sale."""
    paid_ids = ReferralSale.objects.filter(
        lead__in=leads, status__in=('approved', 'paid')
    ).values_list('lead_id', flat=True)
    return leads.filter(Q(status='won') | Q(pk__in=paid_ids)).values_list('pk', flat=True).distinct()


def _operational_status_rows(leads, total):
    successful_ids = _successful_lead_ids(leads)
    successful_count = leads.filter(pk__in=successful_ids).count()
    rows = [
        ('new','جدید',leads.filter(status='new').count()),
        ('contacted','تماس گرفته شد',leads.filter(status__in=('contacted','appointment','visited','won','lost')).count()),
        ('appointment','نوبت داده شد',leads.filter(status__in=('appointment','visited','won')).count()),
        ('follow_up','نیاز به پیگیری مجدد',leads.filter(status='contacted',next_follow_up__isnull=False).count()),
        ('lost','تمایل به پیگیری ندارد',leads.filter(status='lost').count()),
        ('visited','مراجعه کرد',leads.filter(status__in=('visited','won')).count()),
        ('won','فروش موفق',successful_count),
    ]
    return [{'key':key,'label':label,'count':count,'percent':round(count*100/total,1) if total else 0} for key,label,count in rows]



def _filtered_leads_for_trend(request):
    """Apply only source/operator dimensions to the live 30-day trend."""
    leads=ReferralLead.objects.all()
    source_filter=(request.GET.get('source') or '').strip()
    operator_filter=(request.GET.get('operator') or '').strip()
    if source_filter in ('instagram','website','crm','whatsapp','campaign','telegram','bale'):
        leads=leads.filter(_channel_q(source_filter))
    elif source_filter in ('panel','qr','link'):
        leads=leads.filter(source=source_filter)
    if operator_filter.isdigit():
        leads=leads.filter(assigned_to_id=int(operator_filter))
    return leads


@login_required
def lead_management_trend_data(request):
    """Live 30-day Lead Hub series, refreshed by the dashboard every 10 seconds."""
    profile=getattr(request.user,'profile',None)
    if not profile or profile.role not in ALLOWED_ROLES:
        return JsonResponse({'detail':'forbidden'},status=403)

    today=timezone.localdate()
    start=today-timedelta(days=29)
    leads=_filtered_leads_for_trend(request).filter(created_at__date__gte=start,created_at__date__lte=today)

    rows={
        row['day']:row
        for row in leads.annotate(day=TruncDate('created_at')).values('day').annotate(
            leads=Count('id',distinct=True),
            contacted=Count(
                'id',
                filter=Q(status__in=('contacted','appointment','visited','won','lost'))|~Q(contact_result=''),
                distinct=True,
            ),
            appointments=Count(
                'id',
                filter=Q(status__in=('appointment','visited','won'))|Q(appointments__isnull=False),
                distinct=True,
            ),
            won=Count(
                'id',
                filter=Q(status='won')|Q(sale__status__in=('approved','paid')),
                distinct=True,
            ),
        )
    }

    series=[]
    for offset in range(29,-1,-1):
        day=today-timedelta(days=offset)
        row=rows.get(day,{})
        jy,jm,jd=gregorian_to_jalali(day.year,day.month,day.day)
        series.append({
            'date':day.isoformat(),
            'label':f'{jm:02d}/{jd:02d}',
            'leads':int(row.get('leads') or 0),
            'contacted':int(row.get('contacted') or 0),
            'appointments':int(row.get('appointments') or 0),
            'won':int(row.get('won') or 0),
        })
    return JsonResponse({
        'series':series,
        'generated_at':timezone.localtime().strftime('%H:%M:%S'),
        'refresh_seconds':10,
    })


@require_POST
@login_required
def lead_attention_bulk_action(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in ALLOWED_ROLES:
        return render(request, 'core/lead_management_forbidden.html', status=403)
    ids = [int(x) for x in request.POST.getlist('lead_ids') if str(x).isdigit()]
    if not ids:
        messages.warning(request, 'حداقل یک لید را انتخاب کنید.')
        return redirect('lead_management_dashboard')
    operator_id = (request.POST.get('operator_id') or '').strip()
    if not operator_id.isdigit():
        messages.warning(request, 'مسئول پیگیری را انتخاب کنید.')
        return redirect('lead_management_dashboard')
    operator = EmployeeProfile.objects.filter(
        pk=int(operator_id), role='call_center', is_active=True, user__is_active=True,
    ).first()
    if not operator:
        messages.error(request, 'اپراتور انتخاب‌شده فعال نیست.')
        return redirect('lead_management_dashboard')
    leads = ReferralLead.objects.filter(pk__in=ids).exclude(status__in=('won','lost'))
    changed = 0
    from .referral_views import _default_call_center_group, _notify_call_center_assignment
    for lead in leads:
        was = lead.assigned_to_id
        lead.assigned_to = operator
        lead.group = _default_call_center_group(operator)
        lead.save(update_fields=['assigned_to','group','updated_at'])
        if was != operator.id:
            _notify_call_center_assignment(lead)
        changed += 1
    messages.success(request, f'{changed} لید به {call_center_display_name(operator)} ارجاع شد.')
    return redirect('lead_management_dashboard')


@login_required
def lead_management_dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in ALLOWED_ROLES:
        return render(request, 'core/lead_management_forbidden.html', status=403)

    now = timezone.now(); today = timezone.localdate(); start_week = today - timedelta(days=today.weekday()); start_month = today.replace(day=1)
    leads = ReferralLead.objects.select_related('assigned_to__user','group','referrer__user','referrer__sponsor__user','referrer__sponsor__sponsor__user','created_by').prefetch_related('appointments')
    source_filter=(request.GET.get('source') or '').strip(); status_filter=(request.GET.get('status') or '').strip(); operator_filter=(request.GET.get('operator') or '').strip()
    filtered=leads
    if source_filter in ('instagram','website','crm','whatsapp','campaign','telegram','bale'): filtered=filtered.filter(_channel_q(source_filter))
    elif source_filter in ('panel','qr','link'): filtered=filtered.filter(source=source_filter)
    if status_filter=='follow_up': filtered=filtered.filter(status='contacted',next_follow_up__isnull=False)
    elif status_filter: filtered=filtered.filter(status=status_filter)
    if operator_filter.isdigit(): filtered=filtered.filter(assigned_to_id=int(operator_filter))

    total=leads.count(); today_count=leads.filter(created_at__date=today).count(); week_count=leads.filter(created_at__date__gte=start_week).count(); month_count=leads.filter(created_at__date__gte=start_month).count()
    contacted_count=leads.filter(status__in=('contacted','appointment','visited','won','lost')).count(); appointment_count=leads.filter(status__in=('appointment','visited','won')).count()
    successful_ids=_successful_lead_ids(leads); won_count=leads.filter(pk__in=successful_ids).count()
    conversion=round((won_count*100/total),1) if total else 0; contact_rate=round((contacted_count*100/total),1) if total else 0
    unassigned_count=leads.filter(assigned_to__isnull=True,status__in=OPEN_STATUSES).count(); overdue_count=leads.filter(status__in=OPEN_STATUSES,next_follow_up__lt=today).count(); untouched_count=leads.filter(status='new',created_at__lt=now-timedelta(hours=2)).count()
    duplicate_phones=leads.exclude(phone='').values('phone').annotate(c=Count('id')).filter(c__gt=1).count()
    status_rows=_operational_status_rows(leads,total); source_rows=_channel_counts(leads); instagram_page_rows=_instagram_page_rows(leads)

    operator_rows=[]
    operators=EmployeeProfile.objects.filter(role='call_center',is_active=True,user__is_active=True).select_related('user')
    for op in operators:
        qs=leads.filter(assigned_to=op); op_total=qs.count(); op_success_ids=_successful_lead_ids(qs); op_won=qs.filter(pk__in=op_success_ids).count(); op_contacted=qs.filter(status__in=('contacted','appointment','visited','won','lost')).count()
        operator_rows.append({'id':op.id,'name':call_center_display_name(op),'total':op_total,'new':qs.filter(status='new').count(),'contacted':op_contacted,'open':qs.filter(status__in=OPEN_STATUSES).count(),'overdue':qs.filter(status__in=OPEN_STATUSES,next_follow_up__lt=today).count(),'appointments':qs.filter(status__in=('appointment','visited','won')).count(),'won':op_won,'contact_rate':round(op_contacted*100/op_total,1) if op_total else 0,'conversion':round(op_won*100/op_total,1) if op_total else 0})
    operator_rows.sort(key=lambda x:(x['won'],x['appointments'],x['total']),reverse=True)
    group_rows=list(leads.exclude(group__isnull=True).values('group__name').annotate(count=Count('id')).order_by('-count')[:12])

    sales=ReferralSale.objects.filter(status__in=('approved','paid')); sales_amount=sales.aggregate(v=Sum('amount'))['v'] or 0
    instagram_sales_amount=sales.filter(lead__in=leads.filter(_channel_q('instagram'))).aggregate(v=Sum('amount'))['v'] or 0; website_sales_amount=sales.filter(lead__in=leads.filter(_channel_q('website'))).aggregate(v=Sum('amount'))['v'] or 0
    recent=list(filtered.order_by('-created_at')[:150]); attention=list(leads.filter(Q(assigned_to__isnull=True)|Q(status='new',created_at__lt=now-timedelta(hours=2))|Q(status__in=OPEN_STATUSES,next_follow_up__lt=today)).distinct().order_by('created_at')[:20])
    for lead in recent: _enrich_referral_group_label(lead)
    integration_rows=[{'name':'Instagram Form','state':'connected','detail':'فرم فعلی مستقیماً وارد ReferralLead می‌شود.'},{'name':'Website','state':'ready','detail':'برای اتصال فرم سایت به ورودی یکپارچه آماده است.'},{'name':'CRM','state':'ready','detail':'وب‌هوک/API ورودی برای اتصال CRM طراحی شده است.'},{'name':'WhatsApp / Campaigns','state':'ready','detail':'قابل اتصال با source و UTM مستقل.'}]
    return render(request,'core/lead_management_dashboard.html',{'lead_kpis':{'total':total,'today':today_count,'week':week_count,'month':month_count,'contacted':contacted_count,'appointments':appointment_count,'won':won_count,'conversion':conversion,'contact_rate':contact_rate,'unassigned':unassigned_count,'overdue':overdue_count,'untouched':untouched_count,'duplicates':duplicate_phones,'sales_amount':sales_amount,'instagram_sales_amount':instagram_sales_amount,'website_sales_amount':website_sales_amount},'status_rows':status_rows,'source_rows':source_rows,'instagram_page_rows':instagram_page_rows,'group_rows':group_rows,'operator_rows':operator_rows,'recent_leads':[FlowerLeadProxy(lead) for lead in recent],'attention_leads':[AttentionLeadProxy(lead, now, today) for lead in attention],'integration_rows':integration_rows,'operators':[FlowerProfileProxy(op) for op in operators],'source_filter':source_filter,'status_filter':status_filter,'operator_filter':operator_filter,'status_choices':STATUS_FILTER_CHOICES})
