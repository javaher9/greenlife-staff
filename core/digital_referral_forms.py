from django import forms
from django.contrib.auth.models import User


class DigitalReferralSignupForm(forms.Form):
    first_name = forms.CharField(label='نام')
    last_name = forms.CharField(label='نام خانوادگی')
    phone = forms.CharField(label='شماره موبایل')
    username = forms.CharField(label='نام کاربری')
    password = forms.CharField(label='رمز عبور', widget=forms.PasswordInput)
    password_confirm = forms.CharField(label='تکرار رمز عبور', widget=forms.PasswordInput)
    photo = forms.ImageField(
        label='عکس پروفایل',
        required=True,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
        help_text='برای نمایش حرفه‌ای شبکه، عکس چهره الزامی است.',
    )
    consent = forms.BooleanField(label='قوانین همکاری و ثبت اطلاعات در شبکه فروش گرین‌لایف را می‌پذیرم.')

    def clean_username(self):
        value = self.cleaned_data['username'].strip()
        if len(value) < 4:
            raise forms.ValidationError('نام کاربری حداقل ۴ کاراکتر باشد.')
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError('این نام کاربری قبلاً ثبت شده است.')
        return value

    def clean_phone(self):
        value = ''.join(ch for ch in self.cleaned_data['phone'] if ch.isdigit() or ch == '+')
        if len(value) < 10:
            raise forms.ValidationError('شماره موبایل معتبر وارد کنید.')
        return value

    def clean_photo(self):
        photo = self.cleaned_data.get('photo')
        if photo and getattr(photo, 'size', 0) > 8 * 1024 * 1024:
            raise forms.ValidationError('حجم عکس باید کمتر از ۸ مگابایت باشد.')
        return photo

    def clean(self):
        data = super().clean()
        if data.get('password') and data.get('password_confirm') and data['password'] != data['password_confirm']:
            self.add_error('password_confirm', 'تکرار رمز عبور با رمز عبور یکسان نیست.')
        return data


class DigitalLeadForm(forms.Form):
    full_name = forms.CharField(label='نام و نام خانوادگی مشتری')
    phone = forms.CharField(label='شماره موبایل')
    interested_service = forms.CharField(label='خدمت موردنظر', required=False)
    notes = forms.CharField(label='توضیحات', required=False, widget=forms.Textarea(attrs={'rows': 4}))

    def clean_phone(self):
        value = ''.join(ch for ch in self.cleaned_data['phone'] if ch.isdigit() or ch == '+')
        if len(value) < 10:
            raise forms.ValidationError('شماره موبایل معتبر وارد کنید.')
        return value
