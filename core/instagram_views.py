from django import forms
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.shortcuts import render
from django.utils import timezone

from .models import CallCenterLeadGroup, EmployeeProfile, ReferralLead, ReferralProfile, StaffNotification


INSTAGRAM_GROUP_NAME = 'اینستاگرام - لینک'
INSTAGRAM_MANUAL_GROUP_NAME = 'اینستاگرام - دستی'


class InstagramLeadForm(forms.Form):
    full_name = forms.CharField(
        label='نام و نام خانوادگی',
        max_length=140,
        widget=forms.TextInput(attrs={
            'placeholder': 'نام و نام خانوادگی',
            'autocomplete': 'name',
        }),
    )
    phone = forms.CharField(
        label='شماره موبایل',
        max_length=30,
        widget=forms.TextInput(attrs={
            'placeholder': 'مثلاً 09121234567',
            'inputmode': 'tel',
            'autocomplete': 'tel',
            'dir': 'ltr',
        }),
    )
    interested_service = forms.CharField(
        label='خدمت موردنظر',
        max_length=160,
        required=False,
        widget=forms.TextInput(attrs={'placeholder': 'اختیاری؛ مثلاً لاغری موضعی'}),
    )
    consent = forms.BooleanField(
        label='اجازه می‌دهم کارشناسان گرین‌لایف برای راهنمایی با من تماس بگیرند.'
    )

    def clean_phone(self):
        value = ''.join(ch for ch in self.cleaned_data['phone'] if ch.isdigit() or ch == '+')
        if len(value) < 10:
            raise forms.ValidationError('شماره موبایل معتبر وارد کنید.')
        return value


def _instagram_source_profile():
    user, _ = User.objects.get_or_create(
        username='instagram-lead-source',
        defaults={
            'first_name': 'اینستاگرام',
            'last_name': 'گرین‌لایف',
            'is_active': False,
        },
    )
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
    profile, _ = ReferralProfile.objects.get_or_create(
        user=user,
        defaults={
            'referral_code': 'GLINSTAGRAM',
            'is_active': False,
            'created_by': None,
        },
    )
    return profile


def _assign_instagram_lead(lead, group_name=INSTAGRAM_GROUP_NAME, notification_title='لید جدید اینستاگرام'):
    operator = (
        EmployeeProfile.objects
        .filter(role='call_center', is_active=True, user__is_active=True)
        .annotate(open_leads=Count(
            'assigned_referral_leads',
            filter=Q(assigned_referral_leads__status__in=('new', 'contacted', 'appointment')),
        ))
        .order_by('open_leads', 'id')
        .first()
    )
    if not operator:
        return None

    group, _ = CallCenterLeadGroup.objects.get_or_create(
        owner=operator,
        name=group_name,
        defaults={'is_default': False},
    )
    lead.assigned_to = operator
    lead.group = group
    lead.save(update_fields=['assigned_to', 'group', 'updated_at'])
    StaffNotification.objects.create(
        user=operator.user,
        title=notification_title,
        message=f'{lead.full_name} با شماره {lead.phone} به گروه «{group_name}» اضافه شد.',
        notification_type='call_center_lead',
        related_date=timezone.localdate(),
    )
    return operator


def instagram_lead(request):
    form = InstagramLeadForm(request.POST or None)
    completed = False
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        lead = ReferralLead.objects.create(
            referrer=_instagram_source_profile(),
            full_name=data['full_name'].strip(),
            phone=data['phone'],
            interested_service=(data.get('interested_service') or '').strip(),
            status='new',
            source='link',
            source_url=request.build_absolute_uri()[:500],
            notes='ورودی مستقیم فرم اینستاگرام Green Life',
        )
        _assign_instagram_lead(lead)
        completed = True
        form = InstagramLeadForm()

    return render(request, 'core/instagram_lead.html', {
        'form': form,
        'completed': completed,
    })


@login_required(login_url='/login/')
def instagram_manual_lead(request):
    post_data = None
    if request.method == 'POST':
        post_data = request.POST.copy()
        # The customer has already supplied their phone number in Instagram DM;
        # keep the public consent field out of the internal staff workflow.
        post_data['consent'] = 'on'

    form = InstagramLeadForm(post_data)
    completed = False
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        staff_name = request.user.get_full_name() or request.user.username
        lead = ReferralLead.objects.create(
            referrer=_instagram_source_profile(),
            full_name=data['full_name'].strip(),
            phone=data['phone'],
            interested_service=(data.get('interested_service') or '').strip(),
            status='new',
            source='panel',
            source_url=request.build_absolute_uri()[:500],
            notes=f'اینستاگرام - دستی | ثبت از دایرکت توسط {staff_name}',
            created_by=request.user,
        )
        _assign_instagram_lead(
            lead,
            group_name=INSTAGRAM_MANUAL_GROUP_NAME,
            notification_title='لید جدید اینستاگرام - دستی',
        )
        completed = True
        form = InstagramLeadForm()

    return render(request, 'core/instagram_manual_lead.html', {
        'form': form,
        'completed': completed,
    })
