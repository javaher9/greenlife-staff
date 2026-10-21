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
from django.views.decorators.csrf import csrf_protect

from core.models import AuditLog, EmployeeProfile, StaffNotification, VisitAppointment
from core.sms import SmsGatewayError, send_sms
from .models import IntakeInvitation

CONSENT_VERSION = 'intake-2026-10-v1'
REQUIRED_FIELDS = ('reasons', 'conditions', 'medications', 'allergies', 'safety_flags')
LIMITED_CHOICES = {
    'conditions': ['دیابت', 'کم‌کاری تیروئید', 'پرکاری تیروئید', 'فشار خون', 'بیماری قلبی', 'تشنج', 'بیماری کبد یا کلیه', 'جراحی مهم', 'سایر'],
    'safety_flags': ['بارداری', 'شیردهی', 'ضربان‌ساز قلب', 'سابقه واکنش شدید به درمان', 'سایر'],
}
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
    public_url = 'https://app.greenlifeclinics.com' + reverse('intake_public_form', args=[token])
    text = f'{name} عزیز، به گرین‌لایف خوش آمدید. لطفاً فرم اطلاعات اولیه را تکمیل کنید: {public_url}'
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
        reasons = request.POST.getlist('reasons')
        conditions = request.POST.getlist('conditions')
        flags = request.POST.getlist('safety_flags')
        medications = request.POST.get('medications', '').strip()[:1000]
        allergies = request.POST.get('allergies', '').strip()[:1000]
        comments = request.POST.get('comments', '').strip()[:1000]
        if not reasons or request.POST.get('consent') != 'on':
            return render(request, 'intake/form.html', {'error': 'علت مراجعه و تأیید آگاهی از ثبت اطلاعات الزامی است.', 'invitation': invitation, 'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})
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
    return render(request, 'intake/form.html', {'invitation': invitation, 'conditions': LIMITED_CHOICES['conditions'], 'safety_flags': LIMITED_CHOICES['safety_flags']})
