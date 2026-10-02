from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import PublicNetworkLoginForm, PublicNetworkSignupForm, TurkeyNetworkLeadForm, TurkeyNetworkLoginForm, TurkeyNetworkSignupForm
from .models import PublicNetworkMember
from core.models import Country


def _source_from_request(request, sponsor):
    raw = (request.GET.get('src') or request.POST.get('src') or '').strip().lower()
    if raw == 'story':
        return 'story'
    if raw == 'qr':
        return 'qr'
    if sponsor:
        return 'referral'
    return 'direct'


def _public_base(request):
    return request.build_absolute_uri('/').rstrip('/')


def _country(code):
    return Country.objects.filter(code=code,is_active=True).first()


def _turkey_language(request):
    raw=(request.GET.get('lang') or request.POST.get('lang') or request.session.get('public_network_locale') or 'tr').strip().lower()
    lang='en' if raw == 'en' else 'tr'
    request.session['public_network_locale']=lang
    return lang


def _turkey_copy(lang, tr, en):
    return en if lang == 'en' else tr


def _member_share_url(request, member):
    return _public_base(request) + reverse('public_network:signup_with_code', args=[member.code]) + '?src=referral'


def _turkey_member_share_url(request, member):
    lang='en' if getattr(member,'preferred_language','tr') == 'en' else 'tr'
    return _public_base(request) + reverse('public_network:turkey_signup_with_code', args=[member.code]) + f'?src=referral&lang={lang}'


def _turkey_member_referral_profile(member):
    """Bridge a public Türkiye network member into the shared ReferralLead attribution model."""
    from core.models import ReferralProfile

    profile, created = ReferralProfile.objects.get_or_create(
        user=member.user,
        defaults={
            'referral_code': member.code,
            'phone': member.phone,
            'is_active': member.is_active,
            'created_by': member.user,
        },
    )
    update_fields=[]
    if profile.phone != member.phone:
        profile.phone = member.phone
        update_fields.append('phone')
    if profile.is_active != member.is_active:
        profile.is_active = member.is_active
        update_fields.append('is_active')
    if update_fields:
        profile.save(update_fields=update_fields+['updated_at'])
    return profile


def _route_turkey_lead_to_call_center(lead):
    """Route Türkiye leads through the existing call-center allocator and Türkiye group."""
    from core.models import CallCenterLeadGroup
    from core.referral_views import _auto_assign_call_center

    operator = _auto_assign_call_center(lead)
    if operator:
        group, _ = CallCenterLeadGroup.objects.get_or_create(
            owner=operator,
            name='Türkiye | Turkey',
            defaults={'is_default': False},
        )
        if lead.group_id != group.id:
            lead.group = group
            lead.save(update_fields=['group', 'updated_at'])
    return operator


def _turkey_lead_source_profile():
    """Technical source used to make Turkey network signups visible in Lead Hub."""
    from core.models import ReferralProfile
    user, _ = User.objects.get_or_create(
        username='turkey-network-source',
        defaults={'first_name': 'Türkiye', 'last_name': 'Network', 'is_active': False},
    )
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
    profile, _ = ReferralProfile.objects.get_or_create(
        user=user,
        defaults={
            'referral_code': 'GLTURKEY',
            'is_active': False,
            'created_by': None,
        },
    )
    return profile


def _sync_turkey_signup_to_call_center(member, request):
    """Create/mark a Lead Hub record and route it to the current Tehran call-center pool."""
    from core.models import CallCenterLeadGroup, DuplicateLeadError, ReferralLead
    from core.referral_views import _auto_assign_call_center

    full_name = member.display_name
    marker = '[market:turkey] | [channel:public_network] | Türkiye Network Marketing'
    try:
        lead = ReferralLead.objects.create(
            referrer=_turkey_lead_source_profile(),
            country=member.country or _country('TR'),
            preferred_language=member.preferred_language if member.preferred_language in ('tr','en') else 'tr',
            full_name=full_name,
            phone=member.phone,
            interested_service='Türkiye Network Marketing',
            status='new',
            source='link',
            source_url=request.build_absolute_uri()[:500],
            notes=marker,
        )
    except DuplicateLeadError as exc:
        lead = getattr(exc, 'existing_lead', None)
        if not lead:
            return None
        update_fields=[]
        if '[market:turkey]' not in (lead.notes or ''):
            lead.notes = ((lead.notes or '').rstrip() + '\n' + marker).strip()
            update_fields.append('notes')
        turkey=member.country or _country('TR')
        if turkey and lead.country_id!=turkey.id:
            lead.country=turkey
            update_fields.append('country')
        member_lang=member.preferred_language if member.preferred_language in ('tr','en') else 'tr'
        if lead.preferred_language!=member_lang:
            lead.preferred_language=member_lang
            update_fields.append('preferred_language')
        if update_fields:
            lead.save(update_fields=update_fields+['updated_at'])

    _route_turkey_lead_to_call_center(lead)
    return lead


def _management_allowed(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return getattr(getattr(user, 'profile', None), 'role', '') in ('admin', 'internal_manager')


def terms(request):
    return render(request, 'public_network/terms.html')


def signup(request, code=None):
    sponsor = None
    if code:
        sponsor = get_object_or_404(
            PublicNetworkMember.objects.select_related('user'), code=code, is_active=True, country__code='IR'
        )
    if request.user.is_authenticated and hasattr(request.user, 'public_network_member'):
        return redirect('public_network:dashboard')

    initial = {'src': _source_from_request(request, sponsor)}
    form = PublicNetworkSignupForm(request.POST or None, request.FILES or None, initial=initial)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        source = _source_from_request(request, sponsor)
        with transaction.atomic():
            user = User.objects.create_user(
                username=data['username'],
                password=data['password'],
                first_name=data['first_name'].strip(),
                last_name=data['last_name'].strip(),
            )
            member = PublicNetworkMember.objects.create(
                user=user,
                country=_country('IR'),
                preferred_language='fa',
                sponsor=sponsor,
                phone=data['phone'],
                photo=data['photo'],
                source=source,
                source_url=request.build_absolute_uri()[:500],
            )
        login(request, user)
        messages.success(request, 'عضویت شما در شبکه اختصاصی Green Life با موفقیت انجام شد.')
        return redirect('public_network:dashboard')

    return render(request, 'public_network/signup.html', {
        'form': form,
        'sponsor': sponsor,
        'source': _source_from_request(request, sponsor),
    })


def member_login(request):
    if request.user.is_authenticated and hasattr(request.user, 'public_network_member'):
        return redirect('public_network:dashboard')
    form = PublicNetworkLoginForm(request.POST or None, request=request)
    if request.method == 'POST' and form.is_valid():
        login(request, form.get_user())
        return redirect('public_network:dashboard')
    return render(request, 'public_network/login.html', {'form': form})


@login_required
def member_logout(request):
    logout(request)
    return redirect('public_network:login')


@login_required
def dashboard(request):
    member = getattr(request.user, 'public_network_member', None)
    if not member or not member.is_active:
        return redirect('public_network:login')
    direct_members = member.members.filter(is_active=True).select_related('user')
    return render(request, 'public_network/dashboard.html', {
        'member': member,
        'direct_members': direct_members[:12],
        'direct_count': direct_members.count(),
        'share_url': _member_share_url(request, member),
        'share_qr_url': reverse('public_network:invite_qr', args=[member.code]),
    })


@login_required
def management(request):
    if not _management_allowed(request.user):
        messages.error(request, 'این بخش فقط برای مدیریت مرکزی شبکه عمومی قابل دسترسی است.')
        return redirect('dashboard')

    members = PublicNetworkMember.objects.filter(is_active=True).select_related('user', 'sponsor__user')
    today = timezone.localdate()
    month_start = today.replace(day=1)
    latest = members.order_by('-created_at')[:30]
    top = members.annotate(direct_count=Count('members')).order_by('-direct_count', '-created_at')[:10]
    source_counts = {key: members.filter(source=key).count() for key, _ in PublicNetworkMember.SOURCE_CHOICES}
    return render(request, 'public_network/management.html', {
        'members': latest,
        'total_count': members.count(),
        'today_count': members.filter(created_at__date=today).count(),
        'month_count': members.filter(created_at__date__gte=month_start).count(),
        'story_count': source_counts.get('story', 0),
        'source_counts': source_counts,
        'top_members': top,
        'story_signup_url': _public_base(request) + reverse('public_network:signup') + '?src=story',
    })


def invite_qr(request, code):
    member = get_object_or_404(PublicNetworkMember, code=code, is_active=True)
    try:
        import qrcode
    except ImportError:
        from django.http import HttpResponse
        return HttpResponse('QR service unavailable', status=503, content_type='text/plain')
    import io
    from django.http import HttpResponse
    target = _member_share_url(request, member).replace('src=referral', 'src=qr')
    qr = qrcode.QRCode(version=None, box_size=10, border=3, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(target)
    qr.make(fit=True)
    image = qr.make_image(fill_color='#6d28d9', back_color='white')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    response = HttpResponse(buffer.getvalue(), content_type='image/png')
    response['Content-Disposition'] = f'inline; filename="greenlife-public-{member.code}.png"'
    response['Cache-Control'] = 'public, max-age=3600'
    return response


def turkey_terms(request):
    lang=_turkey_language(request)
    return render(request, 'public_network/turkey_terms.html', {'turkey_lang':lang})


def turkey_signup(request, code=None):
    lang=_turkey_language(request)
    sponsor = None
    if code:
        sponsor = get_object_or_404(
            PublicNetworkMember.objects.select_related('user'), code=code, is_active=True, country__code='TR'
        )
    if request.user.is_authenticated and hasattr(request.user, 'public_network_member'):
        return redirect(reverse('public_network:turkey_dashboard') + f'?lang={lang}')

    initial = {'src': _source_from_request(request, sponsor)}
    form = TurkeyNetworkSignupForm(request.POST or None, request.FILES or None, initial=initial, language=lang)
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        source = _source_from_request(request, sponsor)
        with transaction.atomic():
            user = User.objects.create_user(
                username=data['username'],
                password=data['password'],
                first_name=data['first_name'].strip(),
                last_name=data['last_name'].strip(),
            )
            member = PublicNetworkMember.objects.create(
                user=user,
                country=_country('TR'),
                preferred_language=lang,
                sponsor=sponsor,
                phone=data['phone'],
                photo=data['photo'],
                source=source,
                source_url=request.build_absolute_uri()[:500],
            )
        _sync_turkey_signup_to_call_center(member, request)
        login(request, user)
        messages.success(request, _turkey_copy(lang, 'Üyeliğiniz oluşturuldu.', 'Your account has been created.'))
        return redirect(reverse('public_network:turkey_dashboard') + f'?lang={lang}')

    return render(request, 'public_network/turkey_signup.html', {
        'form': form,
        'sponsor': sponsor,
        'source': _source_from_request(request, sponsor),
        'turkey_lang': lang,
    })


def turkey_login(request):
    lang=_turkey_language(request)
    if request.user.is_authenticated and hasattr(request.user, 'public_network_member'):
        return redirect(reverse('public_network:turkey_dashboard') + f'?lang={lang}')
    form = TurkeyNetworkLoginForm(request.POST or None, request=request, language=lang)
    if request.method == 'POST' and form.is_valid():
        user=form.get_user()
        login(request, user)
        member=getattr(user,'public_network_member',None)
        if member and member.preferred_language != lang:
            member.preferred_language=lang
            member.save(update_fields=['preferred_language','updated_at'])
        return redirect(reverse('public_network:turkey_dashboard') + f'?lang={lang}')
    return render(request, 'public_network/turkey_login.html', {'form': form, 'turkey_lang':lang})


@login_required
def turkey_logout(request):
    logout(request)
    return redirect('public_network:turkey_login')


@login_required
def turkey_dashboard(request):
    member = getattr(request.user, 'public_network_member', None)
    if not member or not member.is_active:
        return redirect('public_network:turkey_login')
    lang=_turkey_language(request)
    if member.country_id and member.country.code != 'TR':
        return redirect('public_network:dashboard')
    if member.preferred_language != lang:
        member.preferred_language=lang
        member.save(update_fields=['preferred_language','updated_at'])
    direct_members = member.members.filter(is_active=True).select_related('user')
    from core.models import ReferralLead
    member_referral = _turkey_member_referral_profile(member)
    member_leads = ReferralLead.objects.filter(
        referrer=member_referral,
        country__code='TR',
    ).select_related('assigned_to__user').order_by('-created_at')
    source_labels_tr = {
        'story': 'Story',
        'referral': 'Davet linki',
        'qr': 'QR daveti',
        'direct': 'Doğrudan',
    }
    source_labels_en = {
        'story': 'Story',
        'referral': 'Referral link',
        'qr': 'QR invite',
        'direct': 'Direct',
    }
    labels=source_labels_en if lang == 'en' else source_labels_tr
    return render(request, 'public_network/turkey_dashboard.html', {
        'member': member,
        'direct_members': direct_members[:12],
        'direct_count': direct_members.count(),
        'lead_count': member_leads.count(),
        'recent_leads': member_leads[:8],
        'source_label': labels.get(member.source, member.source),
        'share_url': _turkey_member_share_url(request, member),
        'share_qr_url': reverse('public_network:turkey_invite_qr', args=[member.code]),
        'customer_lead_url': _public_base(request) + reverse('public_network:turkey_public_lead', args=[member.code]) + f'?lang={lang}',
        'customer_lead_qr_url': reverse('public_network:turkey_public_lead_qr', args=[member.code]) + f'?lang={lang}',
        'turkey_lang':lang,
    })


def turkey_invite_qr(request, code):
    member = get_object_or_404(PublicNetworkMember, code=code, is_active=True)
    try:
        import qrcode
    except ImportError:
        from django.http import HttpResponse
        return HttpResponse('QR service unavailable', status=503, content_type='text/plain')
    import io
    from django.http import HttpResponse
    target = _turkey_member_share_url(request, member).replace('src=referral', 'src=qr')
    qr = qrcode.QRCode(version=None, box_size=10, border=3, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(target)
    qr.make(fit=True)
    image = qr.make_image(fill_color='#0f766e', back_color='white')
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    response = HttpResponse(buffer.getvalue(), content_type='image/png')
    response['Content-Disposition'] = f'inline; filename="greenlife-turkey-{member.code}.png"'
    response['Cache-Control'] = 'public, max-age=3600'
    return response


def _turkey_member_or_404(code):
    return get_object_or_404(
        PublicNetworkMember.objects.select_related('user','country'),
        code=code,
        is_active=True,
        country__code='TR',
    )


def _create_turkey_customer_lead(member, form, request, *, source):
    from core.models import DuplicateLeadError, ReferralLead

    lang='en' if member.preferred_language == 'en' else 'tr'
    data=form.cleaned_data
    marker=f'[market:turkey] | [channel:network_customer] | [member_code:{member.code}]'
    try:
        lead=ReferralLead.objects.create(
            referrer=_turkey_member_referral_profile(member),
            country=member.country or _country('TR'),
            preferred_language=lang,
            full_name=data['full_name'].strip(),
            phone=data['phone'],
            interested_service=(data.get('interested_service') or '').strip(),
            notes=((data.get('notes') or '').strip() + ('\n' if data.get('notes') else '') + marker).strip(),
            status='new',
            source=source,
            source_url=request.build_absolute_uri()[:500],
            created_by=member.user if getattr(request,'user',None) and request.user.is_authenticated and request.user.pk == member.user_id else None,
        )
    except DuplicateLeadError as exc:
        return None, getattr(exc,'existing_lead',None)

    _route_turkey_lead_to_call_center(lead)
    return lead, None


@login_required
def turkey_lead_create(request):
    member=getattr(request.user,'public_network_member',None)
    if not member or not member.is_active or not member.country_id or member.country.code != 'TR':
        return redirect('public_network:turkey_login')

    lang=_turkey_language(request)
    if member.preferred_language != lang:
        member.preferred_language=lang
        member.save(update_fields=['preferred_language','updated_at'])

    form=TurkeyNetworkLeadForm(request.POST or None, language=lang)
    if request.method == 'POST' and form.is_valid():
        lead, duplicate = _create_turkey_customer_lead(member, form, request, source='panel')
        if duplicate:
            message = (
                'This mobile number was registered during the last 24 hours.'
                if lang == 'en'
                else 'Bu telefon numarası son 24 saat içinde zaten kaydedildi.'
            )
            form.add_error('phone', message)
        else:
            messages.success(
                request,
                'Lead sent to the Green Life call center.' if lang == 'en' else 'Lead Green Life çağrı merkezine gönderildi.'
            )
            return redirect(reverse('public_network:turkey_dashboard') + f'?lang={lang}')

    return render(request,'public_network/turkey_lead_form.html',{
        'form':form,
        'member':member,
        'turkey_lang':lang,
        'public_mode':False,
    })


def turkey_public_lead(request, code):
    member=_turkey_member_or_404(code)
    lang=_turkey_language(request)
    form=TurkeyNetworkLeadForm(request.POST or None, language=lang)
    completed=False
    if request.method == 'POST' and form.is_valid():
        lead, duplicate = _create_turkey_customer_lead(member, form, request, source='link')
        if duplicate:
            message = (
                'This mobile number was registered during the last 24 hours.'
                if lang == 'en'
                else 'Bu telefon numarası son 24 saat içinde zaten kaydedildi.'
            )
            form.add_error('phone', message)
        else:
            completed=True
            form=TurkeyNetworkLeadForm(language=lang)
    return render(request,'public_network/turkey_lead_form.html',{
        'form':form,
        'member':member,
        'turkey_lang':lang,
        'public_mode':True,
        'completed':completed,
    })


def turkey_public_lead_qr(request, code):
    member=_turkey_member_or_404(code)
    lang=_turkey_language(request)
    try:
        import qrcode
    except ImportError:
        from django.http import HttpResponse
        return HttpResponse('QR service unavailable', status=503, content_type='text/plain')
    import io
    from django.http import HttpResponse
    target=_public_base(request) + reverse('public_network:turkey_public_lead', args=[member.code]) + f'?lang={lang}&src=qr'
    qr=qrcode.QRCode(version=None,box_size=10,border=3,error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(target)
    qr.make(fit=True)
    image=qr.make_image(fill_color='#0f766e',back_color='white')
    buffer=io.BytesIO()
    image.save(buffer,format='PNG')
    response=HttpResponse(buffer.getvalue(),content_type='image/png')
    response['Content-Disposition']=f'inline; filename="greenlife-turkey-lead-{member.code}.png"'
    response['Cache-Control']='public, max-age=3600'
    return response
