from django import forms
from django.contrib.auth.models import User
from django.utils import timezone
from .models import DailyReport, Task, LeaveRequest, Announcement, EmployeeProfile, Attendance, KPIRecord, ScoreEvent, Branch, JobDutyTemplate, Guideline, DeviceIssue
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
        model=Task; fields=['title','description','assigned_to','due_date','priority']; widgets={'description':forms.Textarea(attrs={'rows':4})}

class LeaveRequestForm(forms.ModelForm):
    start_date=JalaliDateField(label='از تاریخ')
    end_date=JalaliDateField(label='تا تاریخ')
    class Meta:
        model=LeaveRequest; fields=['request_type','start_date','end_date','reason']; widgets={'reason':forms.Textarea(attrs={'rows':4})}

class LeaveReviewForm(forms.ModelForm):
    class Meta: model=LeaveRequest; fields=['status','manager_note']; widgets={'manager_note':forms.Textarea(attrs={'rows':3})}

class AnnouncementForm(forms.ModelForm):
    class Meta: model=Announcement; fields=['title','body','branch','is_active']; widgets={'body':forms.Textarea(attrs={'rows':5})}

class EmployeeCreateForm(forms.Form):
    username=forms.CharField(label='نام کاربری'); first_name=forms.CharField(label='نام'); last_name=forms.CharField(label='نام خانوادگی')
    password=forms.CharField(label='رمز عبور',widget=forms.PasswordInput); employee_code=forms.CharField(label='کد پرسنلی',required=False)
    job_title=forms.CharField(label='سمت',required=False); phone=forms.CharField(label='تلفن',required=False); birth_date=JalaliDateField(label='تاریخ تولد',required=False)
    branch=forms.ModelChoiceField(label='شعبه',queryset=Branch.objects.filter(is_active=True),required=False); role=forms.ChoiceField(label='نقش',choices=EmployeeProfile.ROLE_CHOICES)
    def clean_username(self):
        value=self.cleaned_data['username'].strip()
        if User.objects.filter(username__iexact=value).exists(): raise forms.ValidationError('این نام کاربری قبلاً ثبت شده است.')
        return value

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
        widgets={'avatar': forms.ClearableFileInput(attrs={'accept':'image/jpeg,image/png,image/webp'})}

    def clean_avatar(self):
        avatar=self.cleaned_data.get('avatar')
        if avatar:
            if getattr(avatar,'size',0) > 5*1024*1024:
                raise forms.ValidationError('حجم عکس باید کمتر از ۵ مگابایت باشد.')
            content_type=getattr(avatar,'content_type','')
            if content_type and content_type not in ('image/jpeg','image/png','image/webp'):
                raise forms.ValidationError('فرمت عکس باید JPG، PNG یا WEBP باشد.')
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
        widgets={'description':forms.Textarea(attrs={'rows':4})}

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
