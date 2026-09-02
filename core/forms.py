from io import BytesIO
from uuid import uuid4

from django import forms
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.utils import timezone
from PIL import Image, ImageOps
from .models import DailyReport, Task, LeaveRequest, Announcement, BlackboardMessage, EmployeeProfile, Attendance, KPIRecord, ScoreEvent, Branch, JobDutyTemplate, Guideline, DeviceIssue, ReferralProfile, ReferralLead, ReferralSale, FinancialTransaction
from .jalali import parse_jalali, format_jalali

class JalaliDateInput(forms.TextInput):
    input_type='text'
    def __init__(self,*args,**kwargs):
        attrs=kwargs.setdefault('attrs',{}); attrs.setdefault('placeholder','۱۴۰۵/۰۵/۲۴'); attrs.setdefault('dir','ltr')
        super().__init__(*args,**kwargs)
    def format_value(self,value):
        if not value: return ''
        try:
            if isinstance(value,str) and '-' in value:
                from datetime import date
                value=date.fromisoformat(value)
            return format_jalali(value)
        except Exception: return value

class JalaliDateField(forms.DateField):
    widget=JalaliDateInput
    def to_python(self,value):
        if value in self.empty_values: return None
        try: return parse_jalali(value)
        except Exception as e: raise forms.ValidationError(str(e))

class ReportForm(forms.ModelForm):
    class Meta:
        model=DailyReport; fields=['text','audio']
        widgets={'text':forms.Textarea(attrs={'rows':5,'placeholder':'امروز چه کاری انجام دادی و چه چیزی لازم است مدیریت بداند؟'}),'audio':forms.ClearableFileInput(attrs={'accept':'audio/*,.webm,.m4a,.mp3,.wav,.ogg'})}

class TaskStatusForm(forms.ModelForm):
    class Meta: model=Task; fields=['status']

class TaskForm(forms.ModelForm):
    due_date=JalaliDateField(label='مهلت',required=False)
    class Meta:
        model=Task; fields=['title','description','assigned_to','due_date','priority']
        labels={'title':'عنوان وظیفه','description':'شرح وظیفه','assigned_to':'مسئول انجام','priority':'اولویت'}
        widgets={'description':forms.Textarea(attrs={'rows':4,'placeholder':'انتظار مدیریت، جزئیات اجرا و نتیجه موردنظر را بنویسید.'})}

class LeaveRequestForm(forms.ModelForm):
    start_date=JalaliDateField(label='از تاریخ')
    end_date=JalaliDateField(label='تا تاریخ')
    class Meta:
        model=LeaveRequest; fields=['request_type','start_date','end_date','reason']; widgets={'reason':forms.Textarea(attrs={'rows':4})}

class LeaveReviewForm(forms.ModelForm):
    class Meta: model=LeaveRequest; fields=['status','manager_note']; widgets={'manager_note':forms.Textarea(attrs={'rows':3})}

class AnnouncementForm(forms.ModelForm):
    class Meta: model=Announcement; fields=['title','body','branch','is_active']; widgets={'body':forms.Textarea(attrs={'rows':5})}

class BlackboardMessageForm(forms.ModelForm):
    class Meta:
        model=BlackboardMessage
        fields=['title','message','branch','is_active']
        labels={'title':'عنوان کوتاه','message':'متن روی تخته','branch':'شعبه','is_active':'نمایش داده شود'}
        widgets={
            'title':forms.TextInput(attrs={'placeholder':'مثلاً پیام امروز'}),
            'message':forms.Textarea(attrs={'rows':4,'maxlength':320,'placeholder':'مثلاً امروز می‌ترکونیم! شبکه فروشت یادت نره.'}),
        }

class EmployeeCreateForm(forms.Form):
    username=forms.CharField(label='نام کاربری'); first_name=forms.CharField(label='نام'); last_name=forms.CharField(label='نام خانوادگی')
    password=forms.CharField(label='رمز عبور',widget=forms.PasswordInput); employee_code=forms.CharField(label='کد پرسنلی',required=False)
    job_title=forms.CharField(label='سمت',required=False); phone=forms.CharField(label='تلفن',required=False); birth_date=JalaliDateField(label='تاریخ تولد',required=False)
    branch=forms.ModelChoiceField(label='شعبه',queryset=Branch.objects.filter(is_active=True),required=False); role=forms.ChoiceField(label='نقش',choices=EmployeeProfile.ROLE_CHOICES)
    def clean_username(self):
        value=self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=value).exists(): raise forms.ValidationError('این نام کاربری قبلاً ثبت شده است.')
        return value


class ReferralMemberForm(forms.Form):
    first_name=forms.CharField(label='نام')
    last_name=forms.CharField(label='نام خانوادگی')
    phone=forms.CharField(label='شماره موبایل')
    username=forms.CharField(label='نام کاربری',help_text='برای ورود معرف به پنل')
    password=forms.CharField(label='رمز ورود',widget=forms.PasswordInput)
    photo=forms.ImageField(label='عکس فرد',required=False,widget=forms.ClearableFileInput(attrs={'accept':'image/jpeg,image/png,image/webp'}))

    def clean_username(self):
        value=self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=value).exists():
            raise forms.ValidationError('این نام کاربری قبلاً ثبت شده است.')
        return value

    def clean_photo(self):
        photo=self.cleaned_data.get('photo')
        if photo and getattr(photo,'size',0)>10*1024*1024:
            raise forms.ValidationError('حجم عکس باید کمتر از ۱۰ مگابایت باشد.')
        return photo


class ReferralLeadForm(forms.ModelForm):
    class Meta:
        model=ReferralLead
        fields=['full_name','phone','alternate_phone','interested_service','notes']
        labels={
            'full_name':'نام و نام خانوادگی مشتری','phone':'شماره موبایل',
            'alternate_phone':'شماره جایگزین','interested_service':'خدمت موردنظر','notes':'توضیحات',
        }
        widgets={'notes':forms.Textarea(attrs={'rows':4,'placeholder':'نیاز مشتری یا بهترین زمان تماس را بنویسید.'})}

    def clean_phone(self):
        value=''.join(ch for ch in self.cleaned_data['phone'] if ch.isdigit() or ch=='+')
        if len(value)<10: raise forms.ValidationError('شماره موبایل معتبر وارد کنید.')
        return value


class PublicReferralLeadForm(ReferralLeadForm):
    consent=forms.BooleanField(label='اجازه می‌دهم کارشناسان گرین‌لایف برای راهنمایی با من تماس بگیرند.')


class ReferralLeadManageForm(forms.ModelForm):
    next_follow_up=JalaliDateField(label='پیگیری بعدی',required=False)
    class Meta:
        model=ReferralLead
        fields=['status','assigned_to','next_follow_up','interested_service','notes']
        labels={'status':'وضعیت','assigned_to':'مسئول پیگیری','interested_service':'خدمت موردنظر','notes':'یادداشت پیگیری'}
        widgets={'notes':forms.Textarea(attrs={'rows':5})}

    def __init__(self,*args,branch=None,**kwargs):
        super().__init__(*args,**kwargs)
        qs=EmployeeProfile.objects.filter(is_active=True,role='call_center').select_related('user','branch')
        self.fields['assigned_to'].queryset=qs.order_by('branch__name','user__last_name')


class CallCenterLeadForm(forms.ModelForm):
    next_follow_up=JalaliDateField(label='پیگیری بعدی',required=False)
    class Meta:
        model=ReferralLead
        fields=['status','next_follow_up','interested_service','notes']
        labels={
            'status':'نتیجه تماس','interested_service':'خدمت موردنظر',
            'notes':'گزارش تماس و توضیحات مشتری',
        }
        widgets={'notes':forms.Textarea(attrs={
            'rows':6,
            'placeholder':'نتیجه تماس، درخواست مشتری و زمان مناسب پیگیری بعدی را ثبت کنید.',
        })}


class ReferralSaleForm(forms.ModelForm):
    sale_date=JalaliDateField(label='تاریخ فروش')
    class Meta:
        model=ReferralSale
        fields=['sale_date','amount','direct_commission','level_two_commission','status','note']
        labels={
            'amount':'مبلغ فروش (تومان)','direct_commission':'پورسانت معرف مستقیم (تومان)',
            'level_two_commission':'پورسانت معرف بالادستی (تومان)','status':'وضعیت','note':'توضیحات',
        }
        widgets={'note':forms.Textarea(attrs={'rows':4})}

    def clean(self):
        data=super().clean()
        amount=data.get('amount') or 0
        direct=data.get('direct_commission') or 0
        level_two=data.get('level_two_commission') or 0
        if amount<0 or direct<0 or level_two<0:
            raise forms.ValidationError('مبلغ فروش و پورسانت نمی‌تواند منفی باشد.')
        if direct+level_two>amount:
            raise forms.ValidationError('جمع پورسانت‌ها نمی‌تواند از مبلغ فروش بیشتر باشد.')
        return data

class EmployeeEditForm(forms.Form):
    first_name=forms.CharField(label='نام')
    last_name=forms.CharField(label='نام خانوادگی')
    username=forms.CharField(label='نام کاربری')
    email=forms.EmailField(label='ایمیل',required=False)
    employee_code=forms.CharField(label='کد پرسنلی',required=False)
    job_title=forms.CharField(label='سمت',required=False)
    phone=forms.CharField(label='تلفن',required=False)
    birth_date=JalaliDateField(label='تاریخ تولد',required=False)
    start_date=JalaliDateField(label='شروع همکاری',required=False)
    branch=forms.ModelChoiceField(label='شعبه',queryset=Branch.objects.filter(is_active=True),required=False)
    role=forms.ChoiceField(label='نقش',choices=EmployeeProfile.ROLE_CHOICES)
    shift_group=forms.ModelChoiceField(label='گروه شیفت',queryset=None,required=False)
    address=forms.CharField(label='آدرس',required=False,widget=forms.Textarea(attrs={'rows':3}))
    education=forms.CharField(label='تحصیلات',required=False)
    is_insured=forms.TypedChoiceField(
        label='وضعیت بیمه',required=False,coerce=lambda value: {'True':True,'False':False}.get(value),
        empty_value=None,choices=(('', 'نامشخص'),('True', 'بیمه شده'),('False', 'بیمه نشده')),
    )
    is_active=forms.BooleanField(label='فعال',required=False)
    new_password=forms.CharField(label='رمز عبور جدید',required=False,widget=forms.PasswordInput,help_text='اگر نمی‌خواهید رمز تغییر کند، خالی بگذارید.')

    def __init__(self,*args,employee,**kwargs):
        super().__init__(*args,**kwargs)
        from .models import ShiftGroup
        self.employee=employee
        self.fields['shift_group'].queryset=ShiftGroup.objects.filter(is_active=True).select_related('branch').order_by('branch__name','name')
        if not self.is_bound:
            self.initial.update({
                'first_name':employee.user.first_name,'last_name':employee.user.last_name,
                'username':employee.user.username,'email':employee.user.email,
                'employee_code':employee.employee_code or '','job_title':employee.job_title,
                'phone':employee.phone,'birth_date':employee.birth_date,'start_date':employee.start_date,
                'branch':employee.branch,'role':employee.role,'shift_group':employee.shift_group,
                'address':employee.address,'education':employee.education,
                'is_insured':employee.is_insured,'is_active':employee.is_active,
            })

    def clean_username(self):
        value=self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=value).exclude(pk=self.employee.user_id).exists():
            raise forms.ValidationError('این نام کاربری قبلاً ثبت شده است.')
        return value

    def clean_employee_code(self):
        value=(self.cleaned_data.get('employee_code') or '').strip()
        if value and EmployeeProfile.objects.filter(employee_code=value).exclude(pk=self.employee.pk).exists():
            raise forms.ValidationError('این کد پرسنلی قبلاً ثبت شده است.')
        return value

    def save(self):
        d=self.cleaned_data; employee=self.employee; user=employee.user
        user.first_name=d['first_name']; user.last_name=d['last_name']; user.username=d['username']; user.email=d['email']; user.is_active=d['is_active']
        if d.get('new_password'): user.set_password(d['new_password'])
        user.save()
        for field in ('branch','role','shift_group','job_title','phone','birth_date','start_date','address','education','is_insured','is_active'):
            setattr(employee,field,d.get(field))
        if employee.role=='call_center' and not employee.job_title:
            employee.job_title='کارشناس کال‌سنتر'
        if employee.role=='consultant' and not employee.job_title:
            employee.job_title='مشاور'
        employee.employee_code=d['employee_code'] or None
        employee.save()
        return employee


class ConsultantFinanceEntryForm(forms.ModelForm):
    PAYMENT_METHODS=[
        ('Pos S','Pos S'),
        ('Pos H','Pos H'),
        ('CC P','CC P'),
        ('CC D','CC D'),
        ('CC S','CC S'),
    ]
    date=JalaliDateField(label='تاریخ تراکنش',initial=timezone.localdate)
    payment_method=forms.ChoiceField(label='مقصد واریز',choices=PAYMENT_METHODS)
    receipt_image=forms.ImageField(
        label='تصویر تراکنش',required=True,
        widget=forms.ClearableFileInput(attrs={'accept':'image/jpeg,image/png,image/webp'}),
    )

    class Meta:
        model=FinancialTransaction
        fields=[
            'entry_type','person_name','amount','payment_method','service',
            'account_heading','terminal_or_payee','tracking_number',
            'destination_card','description','receipt_image',
        ]
        labels={
            'entry_type':'نوع ثبت','person_name':'نام فرد','amount':'مبلغ (ریال)',
            'service':'خدمت یا پکیج','account_heading':'سرفصل دستگاه یا حساب',
            'terminal_or_payee':'نام پایانه یا شخص دریافت‌کننده','tracking_number':'شماره پیگیری',
            'destination_card':'کارت مقصد','description':'توضیحات',
        }
        widgets={
            'amount':forms.NumberInput(attrs={'min':'1','step':'1','inputmode':'numeric','placeholder':'مبلغ را دقیق و عددی وارد کنید'}),
            'person_name':forms.TextInput(attrs={'placeholder':'نام و نام خانوادگی فرد'}),
            'description':forms.Textarea(attrs={'rows':3}),
        }

    def clean_amount(self):
        amount=self.cleaned_data['amount']
        if amount<=0:
            raise forms.ValidationError('مبلغ باید بیشتر از صفر باشد.')
        return amount

    def clean_date(self):
        value=self.cleaned_data['date']
        if value>timezone.localdate():
            raise forms.ValidationError('تاریخ تراکنش نمی‌تواند در آینده باشد.')
        return value

    def clean_person_name(self):
        value=(self.cleaned_data.get('person_name') or '').strip()
        if len(value)<2:
            raise forms.ValidationError('نام فرد را کامل وارد کنید.')
        return value

    def clean_receipt_image(self):
        image=self.cleaned_data['receipt_image']
        original_size=getattr(image,'size',0)
        if original_size>10*1024*1024:
            raise forms.ValidationError('حجم تصویر تراکنش باید کمتر از ۱۰ مگابایت باشد.')
        try:
            image.seek(0)
            source=Image.open(image)
            source=ImageOps.exif_transpose(source)
            source.load()
            source.thumbnail((2000,2000),Image.Resampling.LANCZOS)

            # Receipts need a light background so text remains legible after
            # converting transparent PNG screenshots to compact WebP.
            if source.mode in ('RGBA','LA'):
                rgba=source.convert('RGBA')
                background=Image.new('RGBA',rgba.size,'white')
                background.alpha_composite(rgba)
                source=background.convert('RGB')
            elif source.mode!='RGB':
                source=source.convert('RGB')

            output=BytesIO()
            target_bytes=1500*1024
            for quality in (84,78,72,66):
                output.seek(0); output.truncate(0)
                source.save(output,format='WEBP',quality=quality,method=6)
                if output.tell()<=target_bytes:
                    break
            data=output.getvalue()
            compressed=ContentFile(data,name=f'receipt-{uuid4().hex[:16]}.webp')
            compressed.content_type='image/webp'
            self.receipt_original_size=original_size
            self.receipt_compressed_size=len(data)
            return compressed
        except Exception as exc:
            raise forms.ValidationError('فشرده‌سازی تصویر انجام نشد؛ یک عکس JPG، PNG یا WEBP معتبر ارسال کنید.') from exc

    def clean(self):
        data=super().clean()
        if data.get('payment_method')=='CC P' and not (data.get('terminal_or_payee') or '').strip():
            self.add_error('terminal_or_payee','برای CC P نام شخص دریافت‌کننده الزامی است.')
        return data

class AttendanceManualForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta:
        model=Attendance; fields=['user','date','check_in','check_out','status','note']
        widgets={'check_in':forms.DateTimeInput(attrs={'type':'datetime-local'}),'check_out':forms.DateTimeInput(attrs={'type':'datetime-local'})}

class KPIRecordForm(forms.ModelForm):
    period_start=JalaliDateField(label='شروع دوره'); period_end=JalaliDateField(label='پایان دوره')
    class Meta: model=KPIRecord; fields=['user','title','value','target','score','period_start','period_end','note']; widgets={'note':forms.Textarea(attrs={'rows':3})}
    def clean_score(self):
        x=self.cleaned_data['score']
        if x>100: raise forms.ValidationError('امتیاز KPI باید بین ۰ تا ۱۰۰ باشد.')
        return x

class ScoreEventForm(forms.ModelForm):
    event_date=JalaliDateField(label='تاریخ')
    class Meta: model=ScoreEvent; fields=['user','points','reason','description','event_date']

from .models import WorkShift, ShiftAssignment, AttendanceCorrectionRequest

class WorkShiftForm(forms.ModelForm):
    class Meta:
        model=WorkShift; fields=['name','branch','start_time','end_time','grace_minutes','report_required','is_active']
        widgets={'start_time':forms.TimeInput(attrs={'type':'time'}),'end_time':forms.TimeInput(attrs={'type':'time'})}

class ShiftAssignmentForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta: model=ShiftAssignment; fields=['user','shift','date','note']

class AttendanceCorrectionForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta:
        model=AttendanceCorrectionRequest; fields=['date','requested_check_in','requested_check_out','reason']
        widgets={'requested_check_in':forms.DateTimeInput(attrs={'type':'datetime-local'}),'requested_check_out':forms.DateTimeInput(attrs={'type':'datetime-local'}),'reason':forms.Textarea(attrs={'rows':4})}

class AttendanceCorrectionReviewForm(forms.ModelForm):
    class Meta:
        model=AttendanceCorrectionRequest; fields=['status','manager_note']
        widgets={'manager_note':forms.Textarea(attrs={'rows':3})}


class EmployeeAvatarForm(forms.ModelForm):
    class Meta:
        model=EmployeeProfile
        fields=['avatar']
        widgets={'avatar': forms.ClearableFileInput(attrs={'accept':'image/jpeg,image/png,image/webp,.jpg,.jpeg,.png,.webp'})}

    def clean_avatar(self):
        avatar=self.cleaned_data.get('avatar')
        if avatar:
            # Nginx accepts up to 30 MB. Keep a lower app-level guard while
            # allowing normal modern phone photos, which are often >5 MB.
            if getattr(avatar,'size',0) > 15*1024*1024:
                raise forms.ValidationError('حجم عکس باید کمتر از ۱۵ مگابایت باشد.')
            content_type=(getattr(avatar,'content_type','') or '').lower()
            allowed=('image/jpeg','image/jpg','image/pjpeg','image/png','image/webp')
            if content_type and content_type not in allowed:
                raise forms.ValidationError('فرمت عکس باید JPG، PNG یا WEBP باشد. عکس‌های HEIC/HEIF را ابتدا به JPG تبدیل کنید.')
        return avatar


from .models import EmployeeDocument, ChecklistTemplate, ChecklistItem

class EmployeeDocumentForm(forms.ModelForm):
    issue_date=JalaliDateField(label='تاریخ صدور',required=False)
    expiry_date=JalaliDateField(label='تاریخ انقضا',required=False)
    class Meta:
        model=EmployeeDocument
        fields=['document_type','title','file','issue_date','expiry_date','note']
        widgets={'file':forms.ClearableFileInput(attrs={'accept':'.pdf,.jpg,.jpeg,.png,.webp,.doc,.docx'}),
                 'note':forms.Textarea(attrs={'rows':3})}
    def clean_file(self):
        f=self.cleaned_data.get('file')
        if f and getattr(f,'size',0)>12*1024*1024:
            raise forms.ValidationError('حجم فایل باید کمتر از ۱۲ مگابایت باشد.')
        return f

class ChecklistTemplateForm(forms.ModelForm):
    class Meta:
        model=ChecklistTemplate
        fields=['name','branch','role','job_title','is_active']

class ChecklistItemForm(forms.ModelForm):
    class Meta:
        model=ChecklistItem
        fields=['title','description','sort_order','is_required']
        widgets={'description':forms.Textarea(attrs={'rows':3})}

from .models import PersonnelAction, PerformanceGoal, InternalRequest

class PersonnelActionForm(forms.ModelForm):
    event_date=JalaliDateField(label='تاریخ',required=True)
    class Meta:
        model=PersonnelAction
        fields=['action_type','title','description','event_date']
        labels={'action_type':'نوع اقدام','title':'عنوان','description':'شرح کامل'}
        widgets={
            'title':forms.TextInput(attrs={'placeholder':'عنوان کوتاه و روشن اقدام'}),
            'description':forms.Textarea(attrs={'rows':4,'placeholder':'دلیل اقدام، انتظار مدیریت و توضیحات لازم را ثبت کنید.'}),
        }

class PerformanceGoalForm(forms.ModelForm):
    start_date=JalaliDateField(label='از تاریخ',required=True)
    end_date=JalaliDateField(label='تا تاریخ',required=True)
    class Meta:
        model=PerformanceGoal
        fields=['title','scope','metric','employee','branch','target','start_date','end_date','is_active']

class InternalRequestForm(forms.ModelForm):
    due_date=JalaliDateField(label='مهلت',required=False)
    class Meta:
        model=InternalRequest
        fields=['category','title','description','priority','due_date']
        widgets={'description':forms.Textarea(attrs={'rows':4})}

from .models import ManagementEvent

class ManagementEventForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta:
        model=ManagementEvent
        fields=['title','event_type','date','time','branch','description']
        widgets={'time':forms.TimeInput(attrs={'type':'time'}),'description':forms.Textarea(attrs={'rows':3})}


from .models import (
    CampPurchaseRequest, CampInvoice, CampInventoryItem, CampInventoryMovement,
    CampWorker, CampWorkerAttendance, CampProject, CampDailyTask, CampFoodPlan,
    CampDailyPhoto
)

class CampPurchaseRequestForm(forms.ModelForm):
    request_date=JalaliDateField(label='تاریخ درخواست')
    class Meta:
        model=CampPurchaseRequest
        fields=['item_name','category','quantity','unit','estimated_amount','reason','request_date','urgency','attachment']
        widgets={'reason':forms.Textarea(attrs={'rows':3}),'attachment':forms.ClearableFileInput(attrs={'accept':'image/*,.pdf'})}

class CampInvoiceForm(forms.ModelForm):
    class Meta:
        model=CampInvoice
        fields=['final_amount','vendor','payment_method','invoice_image','description','is_paid']
        widgets={'description':forms.Textarea(attrs={'rows':3}),'invoice_image':forms.ClearableFileInput(attrs={'accept':'image/*'})}

class CampInventoryItemForm(forms.ModelForm):
    last_purchase_date=JalaliDateField(label='آخرین تاریخ خرید',required=False)
    class Meta:
        model=CampInventoryItem
        fields=['name','category','current_stock','unit','minimum_stock','last_purchase_date','weekly_average_consumption','is_active']

class CampInventoryMovementForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta:
        model=CampInventoryMovement
        fields=['movement_type','quantity','date','reason','reference_purchase']

class CampWorkerForm(forms.ModelForm):
    class Meta:
        model=CampWorker
        fields=['full_name','role','phone','referral','status','daily_wage','notes','photo']
        widgets={'notes':forms.Textarea(attrs={'rows':3}),'photo':forms.ClearableFileInput(attrs={'accept':'image/*'})}

class CampWorkerAttendanceForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta:
        model=CampWorkerAttendance
        fields=['worker','date','is_present','start_time','end_time','work_done','wage_for_day','notes']
        widgets={'start_time':forms.TimeInput(attrs={'type':'time'}),'end_time':forms.TimeInput(attrs={'type':'time'}),'work_done':forms.Textarea(attrs={'rows':2}),'notes':forms.Textarea(attrs={'rows':2})}

class CampProjectForm(forms.ModelForm):
    start_date=JalaliDateField(label='تاریخ شروع')
    last_progress_date=JalaliDateField(label='آخرین پیشرفت',required=False)
    def clean_progress(self):
        value=self.cleaned_data.get('progress',0)
        if value>100: raise forms.ValidationError('درصد پیشرفت نمی‌تواند بیشتر از ۱۰۰ باشد.')
        return value
    class Meta:
        model=CampProject
        fields=['name','manager','start_date','status','progress','estimated_cost','actual_cost','description','blockers','last_progress_date','before_photo','during_photo','after_photo']
        widgets={'description':forms.Textarea(attrs={'rows':3}),'blockers':forms.Textarea(attrs={'rows':3})}

class CampDailyTaskForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta:
        model=CampDailyTask
        fields=['date','title','responsible','priority','project','status','description','before_photo','after_photo']
        widgets={'description':forms.Textarea(attrs={'rows':3})}

class CampFoodPlanForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta:
        model=CampFoodPlan
        fields=['date','meal','people_count','ingredients','estimated_cost','actual_cost','responsible','notes']
        widgets={'ingredients':forms.Textarea(attrs={'rows':3}),'notes':forms.Textarea(attrs={'rows':2})}

class CampDailyPhotoForm(forms.ModelForm):
    date=JalaliDateField(label='تاریخ')
    class Meta:
        model=CampDailyPhoto
        fields=['date','photo_type','image','project','caption','location']
        widgets={'image':forms.ClearableFileInput(attrs={'accept':'image/*'})}


class ManagerReportCommentForm(forms.ModelForm):
    class Meta:
        model=DailyReport
        fields=['manager_comment']
        widgets={'manager_comment':forms.TextInput(attrs={'maxlength':300,'placeholder':'مثلاً: لطفاً با صدای بلندتر ضبط کنید.'})}

class JobDutyTemplateForm(forms.ModelForm):
    class Meta:
        model=JobDutyTemplate
        fields=['title','branch','job_title','description','is_active']
        widgets={'description':forms.Textarea(attrs={'rows':6})}

class GuidelineForm(forms.ModelForm):
    class Meta:
        model=Guideline
        fields=['title','body','audience','branch','job_title','is_required','is_active']
        widgets={'body':forms.Textarea(attrs={'rows':8})}


class DeviceIssueForm(forms.ModelForm):
    class Meta:
        model=DeviceIssue
        fields=['device_name','description']
        labels={'device_name':'نام دستگاه','description':'شرح خرابی'}
        widgets={
            'device_name':forms.TextInput(attrs={'placeholder':'مثلاً دستگاه لیزر، اتوکلاو، کامپیوتر پذیرش...'}),
            'description':forms.Textarea(attrs={'rows':6,'placeholder':'مشکل دستگاه را کوتاه و دقیق توضیح دهید؛ چه اتفاقی افتاده و از چه زمانی.'}),
        }

class DeviceIssueReviewForm(forms.ModelForm):
    class Meta:
        model=DeviceIssue
        fields=['status','manager_note']
        labels={'status':'وضعیت','manager_note':'یادداشت مدیر / مسئول فنی'}
        widgets={'manager_note':forms.Textarea(attrs={'rows':4,'placeholder':'اقدام انجام‌شده یا توضیح پیگیری...'})}
