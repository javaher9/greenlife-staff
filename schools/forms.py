from django import forms
from django.utils import timezone
from .models import SchoolProgram, Child, GrowthRecord, FamilyEnrollment


class ProgramForm(forms.ModelForm):
    school_name = forms.CharField(label='نام مدرسه', max_length=160)
    branch = forms.ModelChoiceField(label='شعبه', queryset=None)
    class Meta:
        model = SchoolProgram
        fields = ['school_name', 'branch', 'title', 'capacity', 'state', 'starts_on', 'ends_on', 'terms']
        widgets = {'starts_on': forms.DateInput(attrs={'type': 'date'}), 'ends_on': forms.DateInput(attrs={'type': 'date'}), 'terms': forms.Textarea(attrs={'rows': 3})}

    def clean(self):
        data = super().clean()
        if data.get('starts_on') and data.get('ends_on') and data['starts_on'] > data['ends_on']:
            self.add_error('ends_on', 'پایان باید پس از شروع باشد.')
        return data


class ChildForm(forms.ModelForm):
    class Meta:
        model = Child
        fields = ['name', 'birth_date', 'sex']
        widgets = {'birth_date': forms.DateInput(attrs={'type': 'date'})}

    def clean_birth_date(self):
        value = self.cleaned_data['birth_date']
        age = (timezone.localdate() - value).days / 365.2425
        if not 2 <= age < 20:
            raise forms.ValidationError('این طرح ویژهٔ سنین ۲ تا ۱۹ سال است؛ تاریخ تولد را به میلادی وارد کنید.')
        return value


class EnrollmentForm(ChildForm):
    parent_name = forms.CharField(label='نام پدر، مادر یا سرپرست قانونی', max_length=140)
    consent = forms.BooleanField(label='سرپرست قانونی هستم؛ با ارزیابی فرزند، نگهداری محرمانهٔ نتیجه و تماس برای هماهنگی این طرح موافقم.')
    adult_opt_in = forms.BooleanField(label='برای سلامت یا تناسب‌اندام خودم مشاوره می‌خواهم و مایل به تماس هستم.', required=False)


class CoordinationForm(forms.ModelForm):
    class Meta:
        model = FamilyEnrollment
        fields = ['status', 'appointment_at', 'adult_outcome', 'staff_note']
        labels = {'status': 'وضعیت مراجعه', 'appointment_at': 'زمان نوبت؛ تهران (تاریخ میلادی)', 'adult_outcome': 'نتیجهٔ مشاورهٔ والد', 'staff_note': 'یادداشت هماهنگی'}
        widgets = {'appointment_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'), 'staff_note': forms.Textarea(attrs={'rows': 2})}

    def clean(self):
        data = super().clean()
        state = data.get('status')
        if state in FamilyEnrollment.OCCUPIED and not self.instance.app_activated_at:
            self.add_error('status', 'ابتدا والد باید گرین‌لایف من را فعال کند.')
        if state == 'booked' and data.get('appointment_at'):
            at = data['appointment_at']
            if at <= timezone.now():
                self.add_error('appointment_at', 'نوبت جدید باید در آینده باشد.')
            if timezone.localtime(at).weekday() == 4:
                self.add_error('appointment_at', 'فعلاً برای روز جمعه نوبت‌گیری فعال نیست.')
        if state in ('booked', 'attended') and not data.get('appointment_at'):
            self.add_error('appointment_at', 'زمان نوبت را وارد کنید.')
        if state == 'attended' and data.get('appointment_at') and data['appointment_at'] > timezone.now():
            self.add_error('status', 'زمان مراجعه هنوز نرسیده است.')
        if data.get('adult_outcome') not in ('none', 'declined') and not self.instance.adult_opt_in:
            self.add_error('adult_outcome', 'والد درخواست مشاورهٔ شخصی نداده است.')
        return data


class GrowthForm(forms.ModelForm):
    class Meta:
        model = GrowthRecord
        fields = ['measured_on', 'height_cm', 'weight_kg', 'interpretation', 'follow_up_on']
        widgets = {'measured_on': forms.DateInput(attrs={'type': 'date'}), 'follow_up_on': forms.DateInput(attrs={'type': 'date'}), 'interpretation': forms.Textarea(attrs={'rows': 4})}

    def clean(self):
        data = super().clean()
        measured = data.get('measured_on')
        if measured and measured > timezone.localdate():
            self.add_error('measured_on', 'تاریخ ارزیابی نمی‌تواند در آینده باشد.')
        if measured and data.get('follow_up_on') and data['follow_up_on'] < measured:
            self.add_error('follow_up_on', 'پیگیری باید پس از ارزیابی باشد.')
        return data
