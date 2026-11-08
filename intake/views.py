"""Independent, opt-in patient intake. Arrival NEVER sends a link automatically."""
import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie

from core.models import AuditLog, EmployeeProfile, StaffNotification, VisitAppointment
from core.sms import SmsGatewayError, send_sms
from .models import IntakeInvitation

CONSENT_VERSION = 'intake-2026-10-v1'
REQUIRED_FIELDS = ('reasons', 'conditions', 'medications', 'allergies', 'safety_flags')
LIMITED_CHOICES = {
    'conditions': ['دیابت', 'کم‌کاری تیروئید', 'پرکاری تیروئید', 'فشار خون', 'بیماری قلبی', 'تشنج', 'بیماری کبد یا کلیه', 'زخم معده', 'مشکلات معده و گوارش', 'ریزش موی شدید', 'سابقه لخته خون در پا یا ریه (DVT/PE)', 'جراحی مهم', 'سایر'],
    'safety_flags': ['بارداری', 'شیردهی', 'ضربان‌ساز قلب', 'سابقه واکنش شدید به درمان', 'سایر'],
}
WEIGHT_TERMS = ('لاغری', 'کاهش وزن', 'کاهش سایز', 'تناسب اندام', 'چربی سوز', 'چربی‌سوز', 'فرم دهی بدن', 'فرم‌دهی بدن')
WEIGHT_FIELDS = {
    'goal': ('کاهش وزن', 'کاهش سایز', 'کاهش وزن و سایز'),
    'body_area': ('شکم و پهلو', 'ران و باسن', 'بازو', 'تمام بدن', 'سایر'),
    'appetite': ('کم', 'معمولی', 'زیاد'),
    'eating_habits': ('ریزه‌خواری', 'شیرینی و تنقلات', 'پرخوری', 'هیچ‌کدام'),
    'activity': ('کم', 'متوسط', 'زیاد'),
    'sleep': ('کمتر از ۶ ساعت', '۶ تا ۸ ساعت', 'بیشتر از ۸ ساعت', 'نامنظم'),
    'previous_treatments': ('خیر', 'رژیم غذایی', 'دارو', 'دستگاه لاغری', 'جراحی', 'چند روش'),
    'mental_state': ('حال روحی خوب', 'گاهی اضطراب یا غمگینی', 'غمگینی یا بی‌انگیزگی بیشتر روزها', 'ترجیح می‌دهم با پزشک مطرح کنم'),
    'hopelessness': ('خیر', 'گاهی', 'بیشتر روزها', 'ترجیح می‌دهم پاسخ ندهم'),
    'motivation': ('سلامتی', 'تناسب اندام و زیبایی', 'افزایش انرژی و تحرک', 'سایر'),
}

def _weight_appointment(appointment):
    return any(term in (appointment.service or '') for term in WEIGHT_TERMS)

def _intake_template(invitation):
    return 'intake/weight_form.html' if _weight_appointment(invitation.appointment) else 'intake/form.html'

def _digest(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


@login_required
@csrf_protect
def send_link(request, pk):
    if request.method != 'POST':
        raise PermissionDenied('فقط ثبت توسط منشی مجاز است.')
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'receptionist' or not profile.is_active:
        raise PermissionDenied('دسترسی فقط برای منشی شعبه است.')
    with transaction.atomic():
        appointment = get_object_or_404(
            VisitAppointment.objects.select_for_update(),
            pk=pk, branch_id=profile.branch_id, status='arrived',
        )
        invitation = IntakeInvitation.objects.select_for_update().filter(appointment=appointment).first()
        if invitation and invitation.completed_at:
            messages.info(request, 'فرم اطلاعات اولیه قبلاً تکمیل شده است.')
            return redirect('appointment_schedule')
        if invitation and invitation.sent_at and invitation.sms_status == 'accepted' and not request.POST.get('resend'):
            messages.info(request, 'لینک قبلاً ارسال شده است. برای ارسال دوباره از دکمه مجدد استفاده کنید.')
            return redirect('appointment_schedule')
        token = secrets.token_urlsafe(32)
        expiry = timezone.now() + timedelta(hours=24)
        if invitation is None:
            invitation = IntakeInvitation(appointment=appointment)
        invitation.token_hash = _digest(token)
        invitation.expires_at = expiry
        invitation.sent_by = request.user
        invitation.sms_status = 'pending'
        invitation.save()
        appointment_id = appointment.pk
        phone = appointment.phone
        name = appointment.full_name
        appointment_date = appointment.appointment_date
    # SMS dispatch occurs only AFTER database commit; a failure does not revert reception.
    public_url = settings.PUBLIC_BASE_URL + reverse('intake_public_form', args=[token])
    # Keep the intake invitation within one GSM-7 SMS segment. Long Persian
    # messages containing a URL can be split into multiple segments or filtered
    # by the carrier before reaching the handset.
    text = f'GreenLife form: {public_url}'
    try:
        send_sms(phone, text, purpose='intake_link', created_by=request.user, appointment=appointment)
    except SmsGatewayError:
        IntakeInvitation.objects.filter(appointment_id=appointment_id).update(sms_status='failed')
        messages.error(request, 'ارسال پیامک ناموفق بود؛ وضعیت پذیرش محفوظ است. پس از بررسی می‌توانید دوباره ارسال کنید.')
    else:
        IntakeInvitation.objects.filter(appointment_id=appointment_id).update(sms_status='accepted', sent_at=timezone.now())
        messages.success(request, 'لینک فرم اطلاعات اولیه ارسال شد.')
    AuditLog.objects.create(actor=request.user, action='intake_link_sent', path=request.path,
        method=request.method, object_type='VisitAppointment', object_id=str(appointment_id),
        summary='ارسال لینک توسط منشی؛ وضعیت از طریق پیام سیستم قابل مشاهده است')
    return redirect('appointment_schedule')


@never_cache
@ensure_csrf_cookie
@csrf_protect
def intake_form(request, token):
    if len(token) < 32 or len(token) > 128:
        raise Http404
    invitation = get_object_or_404(IntakeInvitation.objects.select_related('appointment'), token_hash=_digest(token))
    now = timezone.now()
    if invitation.expires_at <= now or invitation.appointment.status in ('cancelled', 'no_show'):
        raise Http404
    if request.method == 'POST':
        if invitation.completed_at:
            return render(request, 'intake/finished.html')
        is_weight = _weight_appointment(invitation.appointment)
        weight_answers = {}
        if is_weight:
            for field, allowed in WEIGHT_FIELDS.items():
                if field == 'eating_habits':
                    items = request.POST.getlist(field)
                    if not items or len(items) > 5 or any(x not in ('ریزه‌خواری', 'شیرینی و کیک و قند', 'فست‌فود', 'غذاهای چرب و سرخ‌کردنی', 'پرخوری', 'هیچ‌کدام') for x in items) or ('هیچ‌کدام' in items and len(items) != 1):
                        return render(request, _intake_template(invitation),
                            {'error': 'عادات غذایی را مشخص کنید.', 'invitation': invitation,
                             'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})
                    weight_answers[field] = items
                    continue
                value = request.POST.get(field, '').strip()
                if value not in allowed:
                    return render(request, _intake_template(invitation),
                        {'error': 'لطفاً تمام پرسش‌های کاهش وزن را پاسخ دهید.', 'invitation': invitation,
                         'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})
                weight_answers[field] = value
            for field, allowed in (
                ('medication_status', ('بله', 'خیر', 'اطلاع ندارم')),
                ('allergy_status', ('بله', 'خیر', 'اطلاع ندارم')),
            ):
                value = request.POST.get(field, '').strip()
                if value not in allowed:
                    return render(request, _intake_template(invitation),
                        {'error': 'وضعیت داروها و حساسیت‌ها را مشخص کنید.', 'invitation': invitation,
                         'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})
                weight_answers[field] = value
            for field in ('body_area_other', 'conditions_other', 'surgery_type', 'surgery_when', 'safety_other', 'motivation_other'):
                weight_answers[field] = request.POST.get(field, '').strip()[:250]
            conditions_selected = request.POST.getlist('conditions')
            safety_selected = request.POST.getlist('safety_flags')
            conditions_none = request.POST.get('conditions_none') == 'yes'
            conditions_unknown = request.POST.get('conditions_unknown') == 'yes'
            safety_none = request.POST.get('safety_none') == 'yes'
            safety_unknown = request.POST.get('safety_unknown') == 'yes'
            if ((not conditions_selected and not conditions_none and not conditions_unknown)
                or (conditions_selected and (conditions_none or conditions_unknown))
                or (conditions_none and conditions_unknown)
                or (not safety_selected and not safety_none and not safety_unknown)
                or (safety_selected and (safety_none or safety_unknown))
                or (safety_none and safety_unknown)
                or any(
                    not weight_answers[field]
                    for field, enabled in (
                        ('surgery_type', 'جراحی مهم' in conditions_selected),
                        ('surgery_when', 'جراحی مهم' in conditions_selected),
                        ('conditions_other', 'سایر' in conditions_selected),
                        ('safety_other', 'سایر' in safety_selected),
                        ('body_area_other', weight_answers['body_area'] == 'سایر'),
                        ('motivation_other', weight_answers['motivation'] == 'سایر'),
                    ) if enabled
                )
                or (weight_answers['medication_status'] == 'بله' and not request.POST.get('medications', '').strip())
                or (weight_answers['allergy_status'] == 'بله' and not request.POST.get('allergies', '').strip())):
                return render(request, _intake_template(invitation),
                    {'error': 'لطفاً سوابق و توضیحات ضروری را کامل کنید.', 'invitation': invitation,
                     'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})
            weight_answers.update({
                'conditions_status': 'نامشخص' if conditions_unknown else ('ندارد' if conditions_none else 'ثبت شده'),
                'safety_status': 'نامشخص' if safety_unknown else ('ندارد' if safety_none else 'ثبت شده'),
            })
            try:
                current_weight = float(request.POST.get('current_weight', ''))
                target_weight = float(request.POST.get('target_weight', ''))
            except (ValueError, TypeError):
                current_weight = target_weight = 0
            if not (20 <= current_weight <= 350 and 20 <= target_weight <= 350):
                return render(request, _intake_template(invitation),
                    {'error': 'وزن فعلی و وزن هدف باید معتبر باشند.', 'invitation': invitation,
                     'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})
            weight_answers.update({'current_weight': current_weight, 'target_weight': target_weight, 'form_version': 'weight-loss-v2'})
        reasons = [weight_answers['goal']] if is_weight else request.POST.getlist('reasons')
        conditions = request.POST.getlist('conditions')
        flags = request.POST.getlist('safety_flags')
        medications = request.POST.get('medications', '').strip()[:1000]
        if is_weight and weight_answers['medication_status'] != 'بله':
            medications = weight_answers['medication_status']
        allergies = request.POST.get('allergies', '').strip()[:1000]
        if is_weight and weight_answers['allergy_status'] != 'بله':
            allergies = weight_answers['allergy_status']
        comments = request.POST.get('comments', '').strip()[:1000]
        if not reasons or request.POST.get('consent') != 'on' or request.POST.get('screening_confirmed') != 'on':
            return render(request, _intake_template(invitation), {'error': 'علت مراجعه، تأیید بررسی سوابق بیماری و آگاهی از ثبت اطلاعات الزامی است.', 'invitation': invitation, 'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})
        if any(len(x) > 100 for x in reasons) or any(x not in LIMITED_CHOICES['conditions'] for x in conditions) or any(x not in LIMITED_CHOICES['safety_flags'] for x in flags):
            raise PermissionDenied('مقادیر فرم نامعتبر است.')
        with transaction.atomic():
            locked = IntakeInvitation.objects.select_for_update().get(pk=invitation.pk)
            if locked.completed_at or locked.expires_at <= timezone.now():
                raise Http404
            locked.answers = {
                'reasons': reasons, 'conditions': conditions, 'safety_flags': flags,
                'medications': medications, 'allergies': allergies, 'comments': comments,
                'required_screening_complete': True,
                **weight_answers,
            }
            locked.consent_version = CONSENT_VERSION
            locked.consent_at = timezone.now()
            locked.completed_at = timezone.now()
            locked.save(update_fields=['answers', 'consent_version', 'consent_at', 'completed_at'])
            staff = EmployeeProfile.objects.filter(role='receptionist', branch_id=locked.appointment.branch_id, is_active=True, user__is_active=True).select_related('user')
            StaffNotification.objects.bulk_create([
                StaffNotification(user=p.user, title='فرم اطلاعات اولیه تکمیل شد',
                    message=f'{locked.appointment.full_name} فرم را تکمیل کرد؛ آماده ارجاع به آنالیز.',
                    notification_type='appointment', related_date=locked.appointment.appointment_date)
                for p in staff
            ])
        return render(request, 'intake/finished.html')
    if not invitation.started_at and not invitation.completed_at:
        IntakeInvitation.objects.filter(pk=invitation.pk, started_at__isnull=True).update(started_at=now)
    if invitation.completed_at:
        return render(request, 'intake/finished.html')
    return render(request, _intake_template(invitation), {'invitation': invitation, 'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})

