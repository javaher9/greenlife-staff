from django import forms
from django.contrib.auth import authenticate
from django.contrib.auth.models import User

from .models import PublicNetworkMember


def _normalize_phone(value):
    value = (value or '').strip()
    cleaned = ''.join(ch for ch in value if ch.isdigit() or ch == '+')
    if cleaned.startswith('0098'):
        cleaned = '+98' + cleaned[4:]
    if cleaned.startswith('98') and not cleaned.startswith('+98'):
        cleaned = '+' + cleaned
    if cleaned.startswith('09'):
        cleaned = '+98' + cleaned[1:]
    return cleaned


class PublicNetworkSignupForm(forms.Form):
    first_name = forms.CharField(label='نام', max_length=80)
    last_name = forms.CharField(label='نام خانوادگی', max_length=100)
    phone = forms.CharField(label='شماره موبایل', max_length=30)
    username = forms.CharField(label='نام کاربری', max_length=80, help_text='برای ورود بعدی به شبکه')
    password = forms.CharField(
        label='رمز عبور (حداقل ۶ کاراکتر)',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
        min_length=6,
        help_text='حداقل ۶ کاراکتر؛ رمزی انتخاب کنید که یادتان بماند.',
    )
    password_confirm = forms.CharField(
        label='تکرار رمز عبور',
        widget=forms.PasswordInput(attrs={'autocomplete': 'new-password'}),
    )
    photo = forms.ImageField(
        label='عکس پروفایل',
        required=True,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
    )
    accept_terms = forms.BooleanField(
        label='قوانین عضویت و استفاده مسئولانه از شبکه فروش گرین لایف را می‌پذیرم.'
    )
    website = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_username(self):
        value = self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError('این نام کاربری قبلاً استفاده شده است.')
        return value

    def clean_phone(self):
        value = _normalize_phone(self.cleaned_data['phone'])
        digits = ''.join(ch for ch in value if ch.isdigit())
        if len(digits) < 10 or len(digits) > 15:
            raise forms.ValidationError('شماره موبایل معتبر وارد کنید.')
        if PublicNetworkMember.objects.filter(phone=value, is_active=True).exists():
            raise forms.ValidationError('با این شماره موبایل قبلاً عضویت فعال ثبت شده است.')
        return value

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo and getattr(photo, 'size', 0) > 8 * 1024 * 1024:
            raise forms.ValidationError('حجم عکس باید کمتر از ۸ مگابایت باشد.')
        return photo

    def clean(self):
        data = super().clean()
        if data.get('website'):
            raise forms.ValidationError('درخواست نامعتبر است.')
        if data.get('password') and data.get('password_confirm') and data['password'] != data['password_confirm']:
            self.add_error('password_confirm', 'تکرار رمز عبور با رمز اصلی یکسان نیست.')
        return data


class PublicNetworkLoginForm(forms.Form):
    username = forms.CharField(label='نام کاربری')
    password = forms.CharField(label='رمز عبور', widget=forms.PasswordInput)

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.request = request
        self.user = None

    def clean(self):
        data = super().clean()
        if data.get('username') and data.get('password'):
            self.user = authenticate(self.request, username=data['username'], password=data['password'])
            if not self.user or not self.user.is_active:
                raise forms.ValidationError('نام کاربری یا رمز عبور صحیح نیست.')
            if not hasattr(self.user, 'public_network_member'):
                raise forms.ValidationError('این حساب عضو شبکه عمومی گرین لایف نیست.')
        return data

    def get_user(self):
        return self.user


class TurkeyNetworkSignupForm(PublicNetworkSignupForm):
    """Turkish/English copy over the existing public-network signup rules."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        labels = {
            'first_name': 'Ad / First name',
            'last_name': 'Soyad / Last name',
            'phone': 'Telefon / Mobile number',
            'username': 'Kullanıcı adı / Username',
            'password': 'Şifre / Password (min. 6 characters)',
            'password_confirm': 'Şifre tekrar / Confirm password',
            'photo': 'Profil fotoğrafı / Profile photo',
            'accept_terms': 'Üyelik koşullarını kabul ediyorum / I accept the membership terms',
        }
        for name, label in labels.items():
            if name in self.fields:
                self.fields[name].label = label
        self.fields['phone'].widget.attrs.update({
            'placeholder': '+90 5XX XXX XX XX',
            'inputmode': 'tel',
            'autocomplete': 'tel',
        })
        self.fields['username'].help_text = 'Sonraki girişler için / For future sign-ins'
        self.fields['password'].help_text = 'En az 6 karakter / At least 6 characters'

    def clean_phone(self):
        value = (self.cleaned_data.get('phone') or '').strip()
        cleaned = ''.join(ch for ch in value if ch.isdigit() or ch == '+')
        if cleaned.startswith('0090'):
            cleaned = '+90' + cleaned[4:]
        elif cleaned.startswith('90') and not cleaned.startswith('+90'):
            cleaned = '+' + cleaned
        elif cleaned.startswith('05'):
            cleaned = '+90' + cleaned[1:]
        digits = ''.join(ch for ch in cleaned if ch.isdigit())
        if len(digits) < 10 or len(digits) > 15:
            raise forms.ValidationError('Geçerli bir telefon numarası girin / Enter a valid mobile number.')
        if PublicNetworkMember.objects.filter(phone=cleaned, is_active=True).exists():
            raise forms.ValidationError('Bu telefonla aktif üyelik mevcut / An active account already exists for this number.')
        return cleaned


class TurkeyNetworkLoginForm(PublicNetworkLoginForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['username'].label = 'Kullanıcı adı / Username'
        self.fields['password'].label = 'Şifre / Password'

    def clean(self):
        try:
            return super().clean()
        except forms.ValidationError:
            raise forms.ValidationError('Kullanıcı adı veya şifre hatalı / Incorrect username or password.')
