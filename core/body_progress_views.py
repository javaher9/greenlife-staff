"""Private scan-linked progress photos and OTP-authenticated body summary."""
from io import BytesIO
from decimal import Decimal
from PIL import Image, ImageOps, UnidentifiedImageError

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.db import transaction
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from .customer_portal_models import CustomerPortalMember
from .customer_portal_views import _require_member
from .models import BodyAnalysisRecord, BodyProgressPhoto, PatientProfile, VisitAppointment
from .scan_analysis_display import SCAN_FIELDS, scan_summary, scan_value

STAFF_PHOTO_ROLES = {'scan_station', 'receptionist', 'admin', 'internal_manager', 'manager'}
MAX_UPLOAD_BYTES = 8 * 1024 * 1024
ANGLES = dict(BodyProgressPhoto.ANGLE_CHOICES)
PHASES = dict(BodyProgressPhoto.PHASE_CHOICES)


def _staff_scan_access(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or (profile.role not in STAFF_PHOTO_ROLES and not request.user.is_superuser):
        raise PermissionDenied('ثبت تصاویر فقط برای پرسنل مجاز اسکن فعال است.')
    return profile


def _normalized_jpeg(uploaded):
    if uploaded.size > MAX_UPLOAD_BYTES:
        raise ValueError('حجم هر تصویر نباید بیش از ۸ مگابایت باشد.')
    try:
        with Image.open(uploaded) as source:
            if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                raise ValueError('فقط تصویر JPG، PNG یا WebP پذیرفته می‌شود.')
            if source.width * source.height > 30_000_000 or min(source.size) < 200:
                raise ValueError('ابعاد تصویر مناسب نیست.')
            source.load()
            image = ImageOps.exif_transpose(source)
            image.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
            if image.mode not in ('RGB', 'L'):
                background = Image.new('RGB', image.size, 'white')
                if image.mode == 'RGBA':
                    background.paste(image, mask=image.getchannel('A'))
                else:
                    background.paste(image.convert('RGB'))
                image = background
            if image.mode == 'L':
                image = image.convert('RGB')
            output = BytesIO()
            image.save(output, format='JPEG', quality=85, optimize=True)
            return output.getvalue()
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError):
        raise ValueError('فایل تصویری معتبر نیست.') from None


@login_required
@require_POST
def upload_progress_photos(request):
    profile = _staff_scan_access(request)
    if not getattr(settings, 'BODY_PROGRESS_UPLOAD_ENABLED', False):
        messages.error(request, 'ثبت تصاویر تا تأیید حفاظت فضای ذخیره‌سازی سرور غیرفعال است.')
        return redirect('scan_station')
    if request.POST.get('consent') != 'yes':
        messages.error(request, 'رضایت بیمار برای ثبت و نمایش خصوصی تصاویر الزامی است.')
        return redirect('scan_station')
    phase = request.POST.get('phase')
    if phase not in PHASES:
        messages.error(request, 'نوع تصویر اولیه یا پیگیری را انتخاب کنید.')
        return redirect('scan_station')

    appointment_qs = VisitAppointment.objects.filter(
        status='arrived', appointment_date=timezone.localdate(),
    )
    if not request.user.is_superuser and profile.role not in ('admin', 'internal_manager'):
        if not profile.branch_id:
            raise PermissionDenied('شعبه ثبت‌کننده مشخص نیست.')
        appointment_qs = appointment_qs.filter(branch_id=profile.branch_id)
    appointment = get_object_or_404(appointment_qs, pk=request.POST.get('appointment_id'))
    patient = get_object_or_404(PatientProfile, phone=appointment.phone)

    selected = [(angle, request.FILES.get(angle)) for angle in ANGLES if request.FILES.get(angle)]
    if not selected:
        messages.error(request, 'حداقل یک تصویر از روبه‌رو، نیم‌رخ یا پشت انتخاب کنید.')
        return redirect('scan_station')

    try:
        normalized = [(angle, _normalized_jpeg(uploaded)) for angle, uploaded in selected]
    except ValueError as error:
        messages.error(request, str(error))
        return redirect('scan_station')

    scan = BodyAnalysisRecord.objects.filter(
        patient=patient, measurements__scan_appointment_id=appointment.pk,
    ).order_by('-recorded_at').first()
    now = timezone.now()
    with transaction.atomic():
        for angle, content in normalized:
            photo = BodyProgressPhoto(
                patient=patient, scan=scan, phase=phase, angle=angle,
                taken_at=now, consent_recorded_at=now, recorded_by=request.user,
            )
            photo.image.save('progress.jpg', ContentFile(content), save=False)
            photo.save()
    messages.success(request, f'{len(normalized)} تصویر به پرونده {patient.full_name} اضافه شد.')
    return redirect('scan_station')


def _verified_patient(request):
    member = _require_member(request)
    if not isinstance(member, CustomerPortalMember):
        return None, member
    return PatientProfile.objects.filter(phone=member.phone).first(), None


@require_GET
def customer_body(request):
    patient, denied = _verified_patient(request)
    if denied is not None:
        return denied
    records = list(BodyAnalysisRecord.objects.filter(patient=patient).order_by('recorded_at', 'id')) if patient else []
    latest = records[-1] if records else None
    baseline = records[0] if records else None
    weight_change = None
    if baseline and latest and baseline.pk != latest.pk:
        start, end = scan_value(baseline, 'weight_kg'), scan_value(latest, 'weight_kg')
        if start is not None and end is not None:
            weight_change = end - start

    photos = list(BodyProgressPhoto.objects.filter(patient=patient, is_visible=True).order_by('taken_at', 'id')) if patient else []
    pairs = []
    for angle, label in BodyProgressPhoto.ANGLE_CHOICES:
        before = next((photo for photo in photos if photo.angle == angle and photo.phase == 'baseline'), None)
        after = next((photo for photo in reversed(photos) if photo.angle == angle and photo.phase == 'followup'), None)
        if before or after:
            pairs.append({'angle': label, 'before': before, 'after': after})
    history = [
        {'date': rec.recorded_at, 'metrics': scan_summary(rec)}
        for rec in reversed(records)
    ]
    series = [
        {'day': rec.recorded_at.strftime('%Y-%m-%d'), 'weight': float(scan_value(rec, 'weight_kg'))}
        for rec in records if scan_value(rec, 'weight_kg') is not None
    ]
    response = render(request, 'core/customer_portal/body.html', {
        'patient': patient, 'latest': latest, 'metrics': scan_summary(latest),
        'weight_change': weight_change, 'history': history[:30],
        'pairs': pairs, 'weight_series': series,
    })
    response['Cache-Control'] = 'private, no-store'
    return response


@require_GET
def customer_body_photo(request, public_id):
    patient, denied = _verified_patient(request)
    if denied is not None:
        return denied
    photo = get_object_or_404(
        BodyProgressPhoto, public_id=public_id, patient=patient, is_visible=True,
    )
    if not photo.image:
        raise Http404
    response = FileResponse(photo.image.open('rb'), content_type='image/jpeg')
    response['Cache-Control'] = 'private, no-store'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
