"""Live, read-only audience catalog for Green Life bulk SMS.

This module NEVER sends messages. Segments are calculated from operational
tables on demand so no spreadsheet import, stale snapshot, or duplicate user
lists are needed. Only Iranian mobile numbers are eligible for this version.
"""
import re

from django.db.models import Q

from .models import (
    Branch, CallCenterLeadGroup, PatientProfile, PatientDeviceProgram,
    ReferralLead, ReferralProfile, VisitAppointment,
)

MAX_PREVIEW_CONTACTS = 20000

STATIC_SEGMENTS = [
    ('lead_all', 'لیدها', 'همه لیدها', 'تمام لیدهای ثبت‌شده ایران'),
    ('lead_new', 'لیدها', 'لیدهای جدید', 'هنوز وارد مرحله تماس نشده‌اند'),
    ('lead_followup', 'لیدها', 'نیازمند پیگیری', 'نتیجه تماس: پیگیری'),
    ('lead_no_answer', 'لیدها', 'پاسخ نداده‌اند', 'نتیجه تماس: بی‌پاسخ'),
    ('lead_appointment', 'لیدها', 'نوبت ثبت‌شده', 'وضعیت لید: نوبت'),
    ('lead_visited', 'لیدها', 'لیدهای مراجعه‌کرده', 'ثبت مراجعه در وضعیت لید'),
    ('lead_won', 'لیدها', 'فروش موفق لید', 'وضعیت فروش موفق'),
    ('lead_lost', 'لیدها', 'لیدهای ناموفق', 'وضعیت ناموفق'),
    ('lead_site', 'منابع ورودی', 'لیدهای وب‌سایت', 'فرم سایت و منبع وب‌سایت'),
    ('lead_instagram', 'منابع ورودی', 'لیدهای اینستاگرام', 'تمام ورودی‌های اینستاگرام'),
    ('lead_instagram_manual', 'منابع ورودی', 'اینستاگرام دستی / دایرکت', 'ورود دستی همکاران از DM'),
    ('lead_instagram_other', 'منابع ورودی', 'اینستاگرام غیر دستی', 'فرم و سایر ورودی‌های ثبت‌شده'),
    ('lead_beytoote', 'منابع ورودی', 'بیتوته', 'گزارش و بنر بیتوته'),
    ('lead_telegram', 'منابع ورودی', 'تلگرام', 'ورودی‌های ثبت‌شده تلگرام'),
    ('lead_whatsapp', 'منابع ورودی', 'واتساپ', 'ورودی‌های ثبت‌شده واتساپ'),
    ('lead_sms', 'منابع ورودی', 'لیدهای پیامکی', 'ورودی مرکز پیامک'),
    ('lead_campaign', 'منابع ورودی', 'کمپین‌ها', 'ورودی‌های دارای تگ کمپین'),
    ('visit_all', 'نوبت و مراجعه', 'همه نوبت‌ها', 'تمام شماره‌های نوبت‌های ایرانی'),
    ('visit_booked', 'نوبت و مراجعه', 'نوبت رزرو شده', 'هنوز مراجعه ثبت نشده'),
    ('visit_no_show', 'نوبت و مراجعه', 'نوبت گرفته و نیامده', 'وضعیت عدم مراجعه'),
    ('visit_arrived', 'نوبت و مراجعه', 'مراجعه کرده‌اند', 'پذیرش حضوری ثبت شده'),
    ('visit_completed', 'نوبت و مراجعه', 'نوبت‌های انجام‌شده', 'وضعیت ویزیت تکمیل'),
    ('visit_cancelled', 'نوبت و مراجعه', 'لغو نوبت', 'نوبت لغوشده'),
    ('visit_doctor', 'چرخه درمان', 'در صف پزشک', 'مرحله پزشک'),
    ('visit_consultant', 'چرخه درمان', 'در صف مشاور', 'مرحله مشاوره'),
    ('visit_payment', 'چرخه درمان', 'در انتظار پرداخت', 'مرحله پرداخت'),
    ('visit_closed', 'چرخه درمان', 'چرخه تکمیل‌شده', 'مراحل بسته‌شده'),
    ('visit_unpurchased', 'چرخه درمان', 'مراجعه کرده ولی پرداخت ندارد', 'بدون ثبت درآمد تأییدشده برای همان نوبت'),
    ('patient_all', 'پرونده بیماران', 'تمام پرونده‌ها', 'پرونده طولی بیماران'),
    ('patient_vip', 'پرونده بیماران', 'بیماران VIP', 'دارای پرچم VIP'),
    ('patient_device', 'خدمات و دستگاه', 'دارندگان برنامه دستگاه', 'حداقل یک دستگاه در پرونده'),
    ('patient_diet', 'خدمات و دستگاه', 'برنامه تغذیه', 'حداقل یک برنامه غذایی'),
    ('patient_lipolytic', 'خدمات و دستگاه', 'لیپولیتیک', 'برنامه ثبت‌شده لیپولیتیک'),
    ('patient_analysis', 'خدمات و دستگاه', 'آنالیز بدن', 'دارای رکورد InBody / آنالیز'),
    ('network_all', 'شبکه فروش', 'اعضای شبکه فروش', 'معرف‌های ثبت‌شده و قابل تماس'),
    ('network_active', 'شبکه فروش', 'اعضای فعال شبکه', 'معرف‌های فعال'),
    ('network_level1', 'شبکه فروش', 'اعضای سطح اول', 'اعضای دارای معرف مستقیم'),
    ('network_level2', 'شبکه فروش', 'اعضای سطح دوم', 'اعضای غیرمستقیم'),
    ('network_leads', 'شبکه فروش', 'لیدهای شبکه فروش', 'همه لیدهای ارجاعی'),
]

# Segments intentionally use readable stable keys, rather than arbitrary model
# fields provided by a browser request.
def catalog():
    segments = [
        {'key': key, 'group': group, 'label': label, 'description': description}
        for key, group, label, description in STATIC_SEGMENTS
    ]
    for group in CallCenterLeadGroup.objects.order_by('name','pk').only('id','name')[:150]:
        segments.append({
            'key': f'leadgroup:{group.pk}', 'group': 'گروه‌های کال‌سنتر',
            'label': group.name, 'description': 'گروه ثبت‌شده در کال‌سنتر',
        })
    for branch in Branch.objects.filter(
        Q(country__code='IR') | Q(country__isnull=True),
    ).order_by('name','pk').only('id','name')[:50]:
        segments.extend([
            {'key': f'branch_leads:{branch.pk}', 'group': 'شعبه‌ها',
             'label': f'نوبت‌های {branch.name}', 'description': 'مخاطبان نوبت‌های این شعبه'},
            {'key': f'branch_patients:{branch.pk}', 'group': 'شعبه‌ها',
             'label': f'بیماران {branch.name}', 'description': 'شعبه اصلی پرونده بیمار'},
        ])
    names = PatientDeviceProgram.objects.exclude(
        device_name='',
    ).order_by('device_name').values_list('device_name',flat=True).distinct()[:100]
    for name in names:
        segments.append({
            'key': f'device:{name}', 'group': 'دستگاه‌های ثبت‌شده',
            'label': str(name), 'description': 'بیماران دارای برنامه این دستگاه',
        })
    return segments


def _iran_number(value):
    digits = str(value or '').translate(
        str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'),
    )
    digits = re.sub(r'[^0-9]','',digits)
    if digits.startswith('0098'):
        digits='0'+digits[4:]
    elif digits.startswith('98') and len(digits)==12:
        digits='0'+digits[2:]
    elif digits.startswith('9') and len(digits)==10:
        digits='0'+digits
    return digits if len(digits)==11 and digits.startswith('09') else ''


def _lead_base():
    return ReferralLead.objects.filter(Q(country__code='IR')|Q(country__isnull=True))


def _appointment_base():
    return VisitAppointment.objects.filter(
        Q(branch__country__code='IR')|Q(branch__country__isnull=True),
    )


def _instagram_q():
    return (
        Q(notes__icontains='[channel:instagram]') |
        Q(notes__icontains='[instagram_page:') |
        Q(source_url__icontains='/instagram/') |
        Q(notes__icontains='اینستاگرام')
    )


def segment_numbers(key):
    """Iterable of contact numbers for a whitelisted segment key."""
    leads=_lead_base()
    appts=_appointment_base()
    if key=='lead_all' or key=='network_leads':
        return leads.values_list('phone',flat=True)
    lead_filters={
        'lead_new':Q(status='new'),
        'lead_followup':Q(contact_result='follow_up'),
        'lead_no_answer':Q(contact_result='no_answer'),
        'lead_appointment':Q(status='appointment'),
        'lead_visited':Q(status='visited'),
        'lead_won':Q(status='won'),
        'lead_lost':Q(status='lost'),
        'lead_site':Q(notes__icontains='[channel:website]')|Q(source_url__icontains='greenlifeclinics.com'),
        'lead_instagram':_instagram_q(),
        'lead_instagram_manual':Q(notes__icontains='اینستاگرام - دستی'),
        'lead_instagram_other':_instagram_q() & ~Q(notes__icontains='اینستاگرام - دستی'),
        'lead_beytoote':Q(source_url__icontains='beytoote')|Q(notes__icontains='beytoote'),
        'lead_telegram':Q(notes__icontains='تلگرام')|Q(source_url__icontains='telegram'),
        'lead_whatsapp':Q(notes__icontains='[channel:whatsapp]')|Q(source_url__icontains='whatsapp'),
        'lead_sms':Q(notes__icontains='[channel:sms]'),
        'lead_campaign':Q(notes__icontains='[channel:campaign]')|Q(source_url__icontains='utm_campaign='),
    }
    if key in lead_filters:
        return leads.filter(lead_filters[key]).values_list('phone',flat=True)
    visit_filters={
        'visit_all':Q(),
        'visit_booked':Q(status='booked'),
        'visit_no_show':Q(status='no_show'),
        'visit_arrived':Q(status='arrived'),
        'visit_completed':Q(status='completed'),
        'visit_cancelled':Q(status='cancelled'),
        'visit_doctor':Q(care_stage='doctor'),
        'visit_consultant':Q(care_stage='consultant'),
        'visit_payment':Q(care_stage='payment'),
        'visit_closed':Q(care_stage='closed'),
        'visit_unpurchased':Q(status__in=('arrived','completed')),
    }
    if key in visit_filters:
        qs=appts.filter(visit_filters[key])
        if key=='visit_unpurchased':
            qs=qs.exclude(
                financial_transactions__entry_type='inc',
                financial_transactions__review_status='approved',
            )
        return qs.values_list('phone',flat=True)
    patients=PatientProfile.objects.all()
    patient_filters={
        'patient_all':Q(),
        'patient_vip':Q(is_vip=True),
        'patient_device':Q(device_programs__isnull=False),
        'patient_diet':Q(diet_programs__isnull=False),
        'patient_lipolytic':Q(lipolytic_programs__isnull=False),
        'patient_analysis':Q(body_analyses__isnull=False),
    }
    if key in patient_filters:
        return patients.filter(patient_filters[key]).values_list('phone',flat=True).distinct()
    if key.startswith('device:'):
        device_name=key.split(':',1)[1]
        return patients.filter(device_programs__device_name=device_name).values_list('phone',flat=True).distinct()
    if key.startswith('leadgroup:'):
        return leads.filter(group_id=int(key.split(':',1)[1])).values_list('phone',flat=True)
    if key.startswith('branch_leads:'):
        return appts.filter(branch_id=int(key.split(':',1)[1])).values_list('phone',flat=True)
    if key.startswith('branch_patients:'):
        return patients.filter(home_branch_id=int(key.split(':',1)[1])).values_list('phone',flat=True)
    network=ReferralProfile.objects.filter(user__is_active=True)
    if key=='network_active':
        network=network.filter(is_active=True)
    elif key=='network_level1':
        network=network.filter(sponsor__isnull=False,sponsor__sponsor__isnull=True)
    elif key=='network_level2':
        network=network.filter(sponsor__sponsor__isnull=False)
    elif key!='network_all':
        raise ValueError('گروه ناشناخته است.')
    # The registration phone may be in either the referral profile or staff profile.
    return (
        network.values_list('phone',flat=True),
        network.values_list('user__profile__phone',flat=True),
    )


def audience_preview(keys, *, max_contacts=MAX_PREVIEW_CONTACTS):
    available={item['key']:item for item in catalog()}
    if not isinstance(keys,list) or not keys or len(keys)>80 or len(set(keys))!=len(keys):
        raise ValueError('حداقل یک و حداکثر ۸۰ گروه متفاوت را انتخاب کنید.')
    if any(not isinstance(key,str) or key not in available for key in keys):
        raise ValueError('انتخاب گروه نامعتبر است.')
    numbers=set()
    scanned=0
    by_group=[]
    truncated=False
    for key in keys:
        collection=segment_numbers(key)
        iterables=collection if isinstance(collection,tuple) else (collection,)
        group_numbers=set()
        for item in iterables:
            for raw in item.iterator(chunk_size=500):
                scanned+=1
                number=_iran_number(raw)
                if number:
                    group_numbers.add(number)
                    numbers.add(number)
                if scanned>=max_contacts:
                    truncated=True
                    break
            if truncated:
                break
        by_group.append({'key':key,'label':available[key]['label'],'count':len(group_numbers)})
        if truncated:
            break
    return {
        'count':len(numbers),'selected_groups':len(keys),
        'scanned':scanned,'truncated':truncated,
        'per_group':by_group,
        'sample_masked':[n[:4]+'***'+n[-4:] for n in sorted(numbers)[:8]],
        'note':'پیش‌نمایش است؛ هنوز هیچ پیامکی ارسال نشده است.',
    }
