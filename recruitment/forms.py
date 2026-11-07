import json
import re
from django import forms
from django.core.exceptions import ValidationError
from .models import Job, Candidate, Application, Advertisement, SOURCES, STAGES, TERMINAL_STAGES

DEFAULT_CRITERIA = [
    {'label':'مهارت عملی مرتبط با شغل','weight':40},
    {'label':'تجربه و شواهد عملکرد','weight':25},
    {'label':'ارتباط و رفتار حرفه‌ای','weight':20},
    {'label':'دقت و انجام تکلیف','weight':15},
]


def normalize_phone(value, country_code='IR'):
    value = str(value or '').translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))
    value = re.sub(r'[\s()\-]', '', value)
    if value.startswith('00'):
        value = '+' + value[2:]
    if country_code == 'IR':
        if value.startswith('09') and len(value) == 11:
            value = '+98' + value[1:]
        elif value.startswith('989') and len(value) == 12:
            value = '+' + value
    if not re.fullmatch(r'\+?[0-9]{8,15}', value):
        raise ValidationError('شماره تماس معتبر وارد کنید.')
    return value


class JobForm(forms.ModelForm):
    criteria = forms.JSONField(required=False)
    salary_min = forms.IntegerField(required=False, min_value=0, max_value=10**12)
    salary_max = forms.IntegerField(required=False, min_value=0, max_value=10**12)

    class Meta:
        model = Job
        fields = ['country','branch','organization','title','headcount','description','requirements',
                  'expected_outcomes','location','shift','benefits','criteria','salary_min','salary_max',
                  'requires_executive_approval','owner','status','target_date']

    def __init__(self, *args, countries, branches, staff, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['country'].queryset = countries
        self.fields['branch'].queryset = branches
        self.fields['owner'].queryset = staff

    def clean_criteria(self):
        value = self.cleaned_data.get('criteria') or DEFAULT_CRITERIA
        if not isinstance(value, list) or not 1 <= len(value) <= 12:
            raise ValidationError('بین یک تا دوازده معیار ارزیابی وارد کنید.')
        clean = []
        for row in value:
            if not isinstance(row, dict):
                raise ValidationError('قالب معیار ارزیابی صحیح نیست.')
            label = str(row.get('label','')).strip()
            weight = row.get('weight')
            if not label or len(label) > 160 or isinstance(weight, bool) or not isinstance(weight, (int,float)) or not 0 < weight <= 100:
                raise ValidationError('هر معیار باید عنوان و وزن عددی مثبت داشته باشد.')
            clean.append({'label':label,'weight':weight})
        if abs(sum(x['weight'] for x in clean)-100) > .001:
            raise ValidationError('مجموع وزن معیارها باید ۱۰۰ باشد.')
        if len({x['label'] for x in clean}) != len(clean):
            raise ValidationError('عنوان معیارها نباید تکراری باشد.')
        return clean

    def clean(self):
        cleaned = super().clean()
        country, branch = cleaned.get('country'), cleaned.get('branch')
        if branch and country and branch.country_id != country.pk:
            self.add_error('branch','شعبه باید متعلق به کشور انتخاب‌شده باشد.')
        low, high = cleaned.get('salary_min'), cleaned.get('salary_max')
        if (low is None) != (high is None):
            self.add_error('salary_max','حداقل و حداکثر حقوق را با هم وارد کنید.')
        elif low is not None and low > high:
            self.add_error('salary_max','حداکثر حقوق نباید کمتر از حداقل باشد.')
        if self.instance.pk:
            old = Job.objects.get(pk=self.instance.pk)
            if country and country.pk != old.country_id:
                self.add_error('country','کشور موقعیت ثبت‌شده قابل تغییر نیست.')
            if cleaned.get('criteria') != old.criteria and old.applications.filter(evaluations__isnull=False).exists():
                self.add_error('criteria','پس از ثبت ارزیابی، معیارهای این موقعیت قابل تغییر نیست.')
        return cleaned


class CandidateApplicationForm(forms.Form):
    name = forms.CharField(max_length=160)
    phone = forms.CharField(max_length=40)
    job = forms.ModelChoiceField(queryset=Job.objects.none())
    owner = forms.ModelChoiceField(queryset=Job.objects.none())
    email = forms.EmailField(required=False)
    city = forms.CharField(max_length=120, required=False)
    resume_text = forms.CharField(max_length=20000, required=False)
    resume = forms.FileField(required=False)
    source = forms.ChoiceField(choices=SOURCES, required=False)
    source_detail = forms.CharField(max_length=300, required=False)
    requested_salary = forms.IntegerField(required=False, min_value=0, max_value=10**12)
    next_action = forms.CharField(max_length=300)
    next_action_at = forms.DateTimeField()
    notes = forms.CharField(max_length=5000, required=False)

    def __init__(self,*args,jobs,staff,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['job'].queryset = jobs
        self.fields['owner'].queryset = staff

    def clean_resume(self):
        upload = self.cleaned_data.get('resume')
        if upload:
            if upload.size > 5*1024*1024:
                raise ValidationError('حداکثر حجم رزومه ۵ مگابایت است.')
            if not upload.name.lower().endswith('.pdf') or upload.read(5) != b'%PDF-':
                raise ValidationError('رزومه باید فایل PDF معتبر باشد.')
            upload.seek(0)
        return upload

    def clean(self):
        data = super().clean()
        job = data.get('job')
        if job and data.get('phone'):
            try:
                data['phone'] = normalize_phone(data['phone'], job.country.code)
            except ValidationError as exc:
                self.add_error('phone',exc)
        if job and job.status == 'closed':
            self.add_error('job','این موقعیت بسته شده است؛ ابتدا آن را باز کنید.')
        return data


class ApplicationForm(forms.ModelForm):
    requested_salary = forms.IntegerField(required=False,min_value=0,max_value=10**12)
    offered_salary = forms.IntegerField(required=False,min_value=0,max_value=10**12)

    class Meta:
        model = Application
        fields = ['stage','owner','next_action','next_action_at','interview_at','interview_location',
                  'requested_salary','offered_salary','decision_reason','start_date','probation_review_at',
                  'source','source_detail']

    def __init__(self,*args,staff,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['owner'].queryset = staff
        self.fields['next_action'].required = False

    def clean(self):
        data = super().clean()
        stage = data.get('stage')
        if stage in {'rejected','withdrawn','talent','salary_declined'} and not data.get('decision_reason','').strip():
            self.add_error('decision_reason','دلیل این تصمیم را ثبت کنید.')
        if stage not in TERMINAL_STAGES or stage == 'talent':
            if not data.get('next_action','').strip():
                self.add_error('next_action','اقدام بعدی را مشخص کنید.')
            if not data.get('next_action_at'):
                self.add_error('next_action_at','زمان اقدام بعدی را مشخص کنید.')
        if stage == 'interview' and not data.get('interview_at'):
            self.add_error('interview_at','زمان مصاحبه را مشخص کنید.')
        if stage in {'offer','accepted','started','probation','hired'} and data.get('offered_salary') is None:
            self.add_error('offered_salary','مبلغ پیشنهادی همکاری را ثبت کنید.')
        if stage in {'started','probation','hired'} and not data.get('start_date'):
            self.add_error('start_date','تاریخ شروع کار را ثبت کنید.')
        if stage == 'hired' and not self.instance.probation_outcome.strip():
            self.add_error('stage','پیش از تثبیت همکاری، نتیجه دوره آزمایشی را ثبت کنید.')
        return data


class AdvertisementForm(forms.ModelForm):
    cost = forms.IntegerField(required=False,min_value=0,max_value=10**12)

    class Meta:
        model = Advertisement
        fields = ['job','source','title','body','status','url','cost','external_id','expires_at']

    def __init__(self,*args,jobs,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['job'].queryset = jobs

    def clean(self):
        data = super().clean()
        url = data.get('url','')
        if url and not url.startswith(('https://','http://')):
            self.add_error('url','لینک باید با https یا http شروع شود.')
        if data.get('status') == 'active' and not url:
            self.add_error('url','برای آگهی فعال، لینک واقعی انتشار را وارد کنید.')
        return data


class CandidateForm(forms.ModelForm):
    resume = forms.FileField(required=False)

    class Meta:
        model = Candidate
        fields = ['name','email','city','resume_text']

    def clean_resume(self):
        return CandidateApplicationForm.clean_resume(self)
