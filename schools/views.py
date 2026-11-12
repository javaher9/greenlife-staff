import io
from functools import wraps
import qrcode
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, IntegrityError
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST, require_http_methods
from core.models import Branch, CustomerPortalMember
from core.customer_portal_views import _require_member
from .models import Organization, SchoolProgram, FamilyEnrollment, Child, SchoolAudit
from .services import sync_appointment
from .forms import ProgramForm, EnrollmentForm, ChildForm, CoordinationForm, GrowthForm
from .permissions import can_manage, can_clinical, is_executive, programs_for


def staff_only(view):
    @wraps(view)
    @login_required
    @never_cache
    def wrapped(request, *args, **kwargs):
        if not can_manage(request.user):
            raise PermissionDenied
        return view(request, *args, **kwargs)
    return wrapped


def audit(program, event, request, enrollment=None, details=None):
    SchoolAudit.objects.create(program=program, event=event, actor=request.user if request.user.is_authenticated else None, enrollment=enrollment, details=details or {})


def invitation_url(request, program):
    # Coordinators may work on the private LAN; parents need the canonical public URL.
    return settings.PUBLIC_BASE_URL.rstrip('/') + reverse('schools_join', args=[program.token])


@staff_only
def dashboard(request):
    programs = programs_for(request.user).annotate(
        family_count=Count('enrollments', distinct=True),
        activated=Count('enrollments', filter=Q(enrollments__app_activated_at__isnull=False), distinct=True),
        attended=Count('enrollments', filter=Q(enrollments__status='attended'), distinct=True),
        adult_requests=Count('enrollments', filter=Q(enrollments__adult_opt_in=True), distinct=True),
        treatments=Count('enrollments', filter=Q(enrollments__adult_outcome='treatment'), distinct=True),
    ).order_by('-created_at')
    query = request.GET.get('q', '').strip()[:160]
    if query:
        programs = programs.filter(Q(organization__name__icontains=query) | Q(title__icontains=query))
    return render(request, 'schools/dashboard.html', {'programs': programs, 'query': query, 'executive': is_executive(request.user)})


@staff_only
@require_http_methods(['GET', 'POST'])
def program_edit(request, pk=None):
    program = get_object_or_404(programs_for(request.user), pk=pk) if pk else None
    form = ProgramForm(request.POST or None, instance=program, initial={'school_name': program.organization.name, 'branch': program.organization.branch_id} if program else {'branch': getattr(getattr(request.user, 'profile', None), 'branch_id', None)})
    branches = Branch.objects.filter(is_active=True)
    if not is_executive(request.user):
        branches = branches.filter(pk=request.user.profile.branch_id)
    form.fields['branch'].queryset = branches
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            if program:
                locked = SchoolProgram.objects.select_for_update().get(pk=program.pk)
                if form.cleaned_data['branch'].pk != locked.organization.branch_id:
                    form.add_error('branch', 'شعبهٔ گروه موجود قابل تغییر نیست؛ گروه جدید بسازید.')
                occupied = locked.enrollments.filter(status__in=FamilyEnrollment.OCCUPIED).count()
                if form.cleaned_data['capacity'] < occupied:
                    form.add_error('capacity', f'ظرفیت از {occupied} خانوادهٔ پذیرفته‌شده کمتر نشود.')
            if not form.errors:
                org, _ = Organization.objects.get_or_create(kind='school', name=' '.join(form.cleaned_data['school_name'].split()), branch=form.cleaned_data['branch'], defaults={'created_by': request.user})
                obj = form.save(commit=False)
                obj.organization = org
                if not program:
                    obj.coordinator = request.user
                obj.save()
                audit(obj, 'program_updated' if program else 'program_created', request, details={k: str(form.cleaned_data[k]) for k in form.fields})
                messages.success(request, 'گروه مدرسه ذخیره شد؛ نیازی به تأیید مدیر نیست.')
                return redirect('schools_detail', pk=obj.pk)
    return render(request, 'schools/form.html', {'form': form, 'program': program})


@staff_only
def detail(request, pk):
    program = get_object_or_404(programs_for(request.user), pk=pk)
    families = program.enrollments.select_related('member').prefetch_related('children')
    return render(request, 'schools/detail.html', {'program': program, 'families': families, 'invite_url': invitation_url(request, program), 'audit_entries': program.audit_entries.select_related('actor').order_by('-created_at')[:30]})


@staff_only
def invite_card(request, pk):
    program = get_object_or_404(programs_for(request.user), pk=pk)
    return render(request, 'schools/card.html', {'program': program, 'invite_url': invitation_url(request, program)})


@staff_only
def qr(request, pk):
    program = get_object_or_404(programs_for(request.user), pk=pk)
    stream = io.BytesIO()
    qrcode.make(invitation_url(request, program)).save(stream, format='PNG')
    response = HttpResponse(stream.getvalue(), content_type='image/png')
    if request.GET.get('download'):
        response['Content-Disposition'] = f'attachment; filename="school-{pk}-qr.png"'
    return response


@staff_only
@require_http_methods(['GET', 'POST'])
def coordinate(request, pk):
    enrollment = get_object_or_404(FamilyEnrollment.objects.select_related('program__organization', 'member'), pk=pk, program__in=programs_for(request.user))
    form = CoordinationForm(request.POST or None, instance=enrollment)
    if request.method == 'POST':
        with transaction.atomic():
            # Same lock order as app activation/cancellation: program then enrollment.
            SchoolProgram.objects.select_for_update().get(pk=enrollment.program_id)
            enrollment = FamilyEnrollment.objects.select_for_update().get(pk=pk)
            old_status = enrollment.status
            form = CoordinationForm(request.POST, instance=enrollment)
            if form.is_valid():
                new_status = form.cleaned_data['status']
                occupied = enrollment.program.enrollments.filter(status__in=FamilyEnrollment.OCCUPIED).exclude(pk=pk).count()
                if new_status in FamilyEnrollment.OCCUPIED and occupied >= enrollment.program.capacity:
                    form.add_error('status', 'ظرفیت تکمیل است؛ ابتدا ظرفیت را افزایش دهید یا در انتظار نگه دارید.')
                elif new_status in FamilyEnrollment.OCCUPIED and old_status not in FamilyEnrollment.OCCUPIED and not enrollment.program.is_open:
                    form.add_error('status', 'پذیرش این دوره فعال نیست.')
                else:
                    try:
                        with transaction.atomic():
                            sync_appointment(enrollment, request.user)
                            form.save()
                    except (ValidationError, IntegrityError) as exc:
                        message = 'این زمان قبلاً رزرو شده است؛ زمان دیگری انتخاب کنید.' if isinstance(exc, IntegrityError) else ' / '.join(exc.messages)
                        form.add_error('appointment_at', message)
                    else:
                        audit(enrollment.program, 'family_coordinated', request, enrollment, {k: str(form.cleaned_data[k]) for k in form.fields})
                        messages.success(request, 'پیگیری و نوبت کلینیک ذخیره شد.')
                        return redirect('schools_detail', pk=enrollment.program_id)
    return render(request, 'schools/coordinate.html', {'enrollment': enrollment, 'form': form})


@never_cache
@require_http_methods(['GET', 'POST'])
def join(request, token):
    program = get_object_or_404(SchoolProgram.objects.select_related('organization__branch'), token=token)
    if request.method == 'GET' and not request.GET.get('register'):
        occupied = program.enrollments.filter(status__in=FamilyEnrollment.OCCUPIED).count()
        return render(request, 'schools/join.html', {'program': program, 'remaining': max(0, program.capacity - occupied)})
    member = _require_member(request)
    if not isinstance(member, CustomerPortalMember):
        return member
    existing = program.enrollments.filter(member=member).first()
    if existing:
        return redirect('schools_family')
    if not program.is_open:
        return render(request, 'schools/join.html', {'program': program}, status=409)
    form = EnrollmentForm(request.POST or None, initial={'parent_name': member.full_name})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            program = SchoolProgram.objects.select_for_update().get(pk=program.pk)
            if not program.is_open:
                return render(request, 'schools/join.html', {'program': program}, status=409)
            enrollment, created = FamilyEnrollment.objects.get_or_create(program=program, member=member, defaults={
                'parent_name': form.cleaned_data['parent_name'], 'consent_at': timezone.now(), 'terms_snapshot': program.terms,
                'adult_opt_in': form.cleaned_data['adult_opt_in'], 'adult_opt_in_at': timezone.now() if form.cleaned_data['adult_opt_in'] else None,
                'adult_outcome': 'requested' if form.cleaned_data['adult_opt_in'] else 'none',
            })
            if created:
                Child.objects.create(enrollment=enrollment, **{k: form.cleaned_data[k] for k in ['name', 'birth_date', 'sex']})
                audit(program, 'parent_registered', request, enrollment)
        return redirect('schools_family')
    return render(request, 'schools/register.html', {'program': program, 'form': form})


@never_cache
@require_http_methods(['GET', 'POST'])
def family(request):
    member = _require_member(request)
    if not isinstance(member, CustomerPortalMember):
        return member
    enrollments = member.school_enrollments.select_related('program__organization__branch').prefetch_related('children__growth_records')
    if request.method == 'POST':
        enrollment_id = request.POST.get('enrollment', '')
        if not enrollment_id.isascii() or not enrollment_id.isdecimal():
            return JsonResponse({'error': 'درخواست نامعتبر است.'}, status=400)
        enrollment = get_object_or_404(enrollments, pk=enrollment_id)
        with transaction.atomic():
            program = SchoolProgram.objects.select_for_update().get(pk=enrollment.program_id)
            enrollment = FamilyEnrollment.objects.select_for_update().get(pk=enrollment.pk)
            action = request.POST.get('action')
            if action == 'activate':
                # UX signal only: never used to authorize identity or medical access.
                if request.POST.get('standalone') != '1':
                    return JsonResponse({'error': 'اپ را از صفحهٔ اصلی گوشی باز کنید.'}, status=400)
                if not enrollment.app_activated_at:
                    enrollment.app_activated_at = timezone.now()
                if enrollment.status in ('pending', 'waiting') and program.is_open:
                    occupied = program.enrollments.filter(status__in=FamilyEnrollment.OCCUPIED).count()
                    enrollment.status = 'ready' if occupied < program.capacity else 'waiting'
                enrollment.save(update_fields=['app_activated_at', 'status'])
            elif action == 'cancel':
                if enrollment.status == 'attended':
                    return JsonResponse({'error': 'برای اصلاح سابقهٔ مراجعه با کلینیک تماس بگیرید.'}, status=400)
                enrollment.status = 'cancelled'
                if enrollment.visit_appointment_id:
                    from core.models import VisitAppointment
                    VisitAppointment.objects.filter(pk=enrollment.visit_appointment_id).update(status='cancelled')
                enrollment.save(update_fields=['status'])
            elif action == 'adult_opt_in':
                enrollment.adult_opt_in = request.POST.get('adult_opt_in') == '1'
                enrollment.adult_opt_in_at = timezone.now() if enrollment.adult_opt_in else None
                enrollment.adult_outcome = 'requested' if enrollment.adult_opt_in else 'declined'
                enrollment.save(update_fields=['adult_opt_in', 'adult_opt_in_at', 'adult_outcome'])
            else:
                return JsonResponse({'error': 'درخواست نامعتبر است.'}, status=400)
            audit(program, 'parent_' + action, request, enrollment)
        return redirect('schools_family')
    return render(request, 'schools/family.html', {'enrollments': enrollments, 'member': member})


@never_cache
@require_http_methods(['GET', 'POST'])
def child_add(request, pk):
    member = _require_member(request)
    if not isinstance(member, CustomerPortalMember):
        return member
    enrollment = get_object_or_404(FamilyEnrollment, pk=pk, member=member)
    form = ChildForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            enrollment = FamilyEnrollment.objects.select_for_update().get(pk=pk)
            if enrollment.status == 'cancelled':
                form.add_error(None, 'ثبت‌نام لغو شده است.')
            elif enrollment.children.count() >= 10:
                form.add_error(None, 'برای افزودن فرزند دیگر با کلینیک تماس بگیرید.')
            elif enrollment.children.filter(name=form.cleaned_data['name'], birth_date=form.cleaned_data['birth_date']).exists():
                form.add_error(None, 'این فرزند قبلاً ثبت شده است.')
            else:
                child = form.save(commit=False)
                child.enrollment = enrollment
                child.save()
                audit(enrollment.program, 'child_added', request, enrollment)
                return redirect('schools_family')
    return render(request, 'schools/register.html', {'program': enrollment.program, 'form': form, 'adding_child': True})


@login_required
@never_cache
@require_http_methods(['GET', 'POST'])
def clinical(request, pk=None):
    if not can_clinical(request.user):
        raise PermissionDenied
    children = Child.objects.filter(enrollment__program__in=programs_for(request.user, clinical=True)).select_related('enrollment__program__organization').order_by('name')
    child = get_object_or_404(children, pk=pk) if pk else None
    form = GrowthForm(request.POST or None, initial={'measured_on': timezone.localdate()}) if child else None
    if request.method == 'POST':
        if not child:
            raise PermissionDenied
        if form.is_valid():
            if form.cleaned_data['measured_on'] < child.birth_date:
                form.add_error('measured_on', 'تاریخ ارزیابی قبل از تولد است.')
            else:
                with transaction.atomic():
                    record = form.save(commit=False)
                    record.child = child
                    record.clinician = request.user
                    record.save()
                    audit(child.enrollment.program, 'clinical_record_created', request, child.enrollment, {'record_id': record.pk})
                return redirect('schools_clinical_child', pk=child.pk)
    return render(request, 'schools/clinical.html', {'children': children, 'child': child, 'form': form})


def manifest(request):
    return JsonResponse({'id': '/customer/', 'name': 'گرین‌لایف من', 'short_name': 'گرین‌لایف من', 'lang': 'fa', 'dir': 'rtl', 'start_url': reverse('schools_family'), 'scope': '/customer/', 'display': 'standalone', 'background_color': '#f8f5fc', 'theme_color': '#7044a3', 'icons': [{'src': '/static/core/icon-192.png', 'sizes': '192x192', 'type': 'image/png'}, {'src': '/static/core/icon-512.png', 'sizes': '512x512', 'type': 'image/png'}]}, content_type='application/manifest+json')


def service_worker(request):
    response = HttpResponse("self.addEventListener('install',()=>self.skipWaiting());self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));self.addEventListener('fetch',e=>{if(e.request.method==='GET'&&new URL(e.request.url).origin===self.location.origin){e.respondWith(fetch(e.request));}});", content_type='application/javascript')
    response['Cache-Control'] = 'no-cache'
    return response
