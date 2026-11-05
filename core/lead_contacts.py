"""Contact numbers belonging to one lead, with compatible primary/alternate fields."""
import hashlib
import json
import re

from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import Q

from .models import DuplicateLeadError, LeadContactPhone, ReferralLead, lead_phone_variants, normalize_lead_phone


def description_text(service, notes):
    parts=[]
    for value in (service, notes):
        value=re.sub(r'\[(?:entry|instagram_page|channel|source|market|followup_time):[^\]]*\]', '', value or '')
        lines=[line.strip(' |') for line in value.splitlines()
               if not line.startswith(('اینستاگرام - دستی |', 'ورودی مستقیم فرم اینستاگرام |'))]
        value='\n'.join(line for line in lines if line).strip()
        if value and value not in parts:
            parts.append(value)
    return '\n'.join(parts)


def valid_phone(raw):
    raw=str(raw or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')).strip()
    if not re.fullmatch(r'\+?[0-9 ()\-]+',raw):
        raise ValidationError('شماره تلفن معتبر وارد کنید؛ فقط ارقام و پیش‌شماره مجاز است.')
    number=normalize_lead_phone(raw)
    if not (re.fullmatch(r'09[0-9]{9}',number) or re.fullmatch(r'0[1-8][0-9]{9}',number) or re.fullmatch(r'\+[1-9][0-9]{9,14}',number)):
        raise ValidationError('شماره با پیش‌شماره معتبر وارد شود؛ مثلاً 09121234567 یا +905321234567.')
    return number


def clean_numbers(primary, additional):
    if not isinstance(additional,list) or len(additional)>10:
        raise ValidationError('حداکثر 10 شمارهٔ دیگر می‌توانید ثبت کنید.')
    numbers=[valid_phone(primary)]+[valid_phone(value) for value in additional if str(value).strip()]
    if len(numbers)!=len(set(numbers)):
        raise ValidationError('یک شماره را دوبار در همین پرونده وارد نکنید.')
    return numbers


def contacts_version(lead):
    return hashlib.sha256(json.dumps([lead.phone,lead.alternate_phone,lead.contact_numbers],ensure_ascii=True).encode()).hexdigest()


def whatsapp_url(number):
    number=normalize_lead_phone(number)
    if number.startswith('09'):
        number='98'+number[1:]
    return 'https://wa.me/'+number.lstrip('+')


def contact_payload(lead):
    return {'phone':lead.phone,'numbers':lead.contact_numbers,'version':contacts_version(lead),
            'contacts':[{'phone':n,'wa_url':whatsapp_url(n)} for n in lead.contact_numbers]}


def lock_numbers(numbers):
    if connection.vendor=='postgresql':
        with connection.cursor() as cursor:
            for number in sorted(set(numbers)):
                cursor.execute('SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)',[f'greenlife-lead:{number}'])


def conflicting_lead(number, exclude_pk):
    variants=lead_phone_variants(number)
    qs=ReferralLead.objects.exclude(pk=exclude_pk)
    match=qs.filter(Q(phone__in=variants)|Q(alternate_phone__in=variants)|Q(extra_phones__phone__in=variants)).first()
    if match:
        return match
    # Retain detection for legacy numbers containing spaces/Persian digits.
    for item in qs.only('id','phone','alternate_phone').iterator():
        if number in (normalize_lead_phone(item.phone),normalize_lead_phone(item.alternate_phone)):
            return item
    return None


def store_additional(lead, numbers):
    lead.extra_phones.exclude(phone__in=numbers).delete()
    existing=set(lead.extra_phones.values_list('phone',flat=True))
    LeadContactPhone.objects.bulk_create([LeadContactPhone(lead=lead,phone=n) for n in numbers if n not in existing])
    if hasattr(lead,'_prefetched_objects_cache'):
        lead._prefetched_objects_cache.pop('extra_phones',None)


@transaction.atomic
def create_with_contacts(lead, additional):
    numbers=clean_numbers(lead.phone,additional)
    lock_numbers(numbers)
    for number in numbers:
        duplicate=ReferralLead.recent_duplicate_for_phone(number)
        if duplicate:
            raise DuplicateLeadError(duplicate)
    lead.phone=numbers[0]
    lead.alternate_phone=numbers[1] if len(numbers)>1 else ''
    lead.save()
    store_additional(lead,numbers[1:])
    return lead
