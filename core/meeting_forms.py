from django import forms
from django.contrib.auth.models import User
from django.forms import BaseModelFormSet, modelformset_factory
from django.utils import timezone

from .forms import JalaliDateField
from .models import MeetingActionItem, MeetingMinute


def active_staff():
    return User.objects.filter(profile__is_active=True).exclude(profile__role='referrer').select_related('profile').order_by(
        'first_name','last_name','username'
    )


class StaffPhotoSelect(forms.Select):
    def create_option(self,name,value,label,selected,index,subindex=None,attrs=None):
        option=super().create_option(name,value,label,selected,index,subindex=subindex,attrs=attrs)
        instance=getattr(value,'instance',None)
        profile=getattr(instance,'profile',None) if instance else None
        avatar=getattr(profile,'avatar',None)
        try:
            photo=avatar.url if avatar else ''
        except Exception:
            photo=''
        if photo:
            option['attrs']['data-photo']=photo
        return option


class PersianStaffChoiceField(forms.ModelChoiceField):
    widget=StaffPhotoSelect
    def label_from_instance(self,obj):
        name=(obj.get_full_name() or '').strip()
        return name or 'نام فارسی ثبت نشده'


class MeetingMinuteForm(forms.ModelForm):
    meeting_date=JalaliDateField(label='تاریخ جلسه')
    attendees=forms.ModelMultipleChoiceField(
        label='افراد حاضر',queryset=User.objects.none(),required=False,
        widget=forms.SelectMultiple(attrs={'size':8}),
    )
    class Meta:
        model=MeetingMinute
        fields=['title','meeting_date','start_time','location','attendees','summary']
        labels={
            'title':'عنوان جلسه','start_time':'ساعت شروع','location':'محل جلسه',
            'summary':'خلاصه و توضیحات جلسه',
        }
        widgets={
            'start_time':forms.TimeInput(attrs={'type':'time'}),
            'summary':forms.Textarea(attrs={'rows':6,'placeholder':'موضوعات مطرح‌شده و جمع‌بندی کلی جلسه را بنویسید.'}),
        }
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['attendees'].queryset=active_staff()
        self.fields['attendees'].label_from_instance=lambda obj: (obj.get_full_name() or '').strip() or 'نام فارسی ثبت نشده'
        if not self.is_bound and not self.instance.pk:
            self.fields['meeting_date'].initial=timezone.localdate()
            self.fields['start_time'].initial=timezone.localtime().strftime('%H:%M')


class MeetingActionForm(forms.ModelForm):
    assigned_to=PersianStaffChoiceField(label='مسئول انجام',queryset=User.objects.none())
    due_date=JalaliDateField(label='مهلت انجام',required=False)
    class Meta:
        model=MeetingActionItem
        fields=['title','assigned_to','due_date','priority','description']
        labels={
            'title':'شرح مصوبه','assigned_to':'مسئول انجام','priority':'اولویت',
            'description':'توضیحات اجرایی',
        }
        widgets={'description':forms.Textarea(attrs={'rows':2,'placeholder':'جزئیات، نتیجه مورد انتظار یا توضیح تکمیلی'})}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['assigned_to'].queryset=active_staff()


class RequiredActionFormSet(BaseModelFormSet):
    def clean(self):
        super().clean()
        if any(self.errors): return
        if not any(form.cleaned_data and form.cleaned_data.get('title') for form in self.forms):
            raise forms.ValidationError('حداقل یک مصوبه برای جلسه ثبت کنید.')


MeetingActionFormSet=modelformset_factory(
    MeetingActionItem,form=MeetingActionForm,formset=RequiredActionFormSet,
    extra=1,max_num=12,validate_max=True,
)


class MeetingActionProgressForm(forms.Form):
    status=forms.ChoiceField(label='وضعیت جدید')
    note=forms.CharField(
        label='گزارش پیشرفت یا توضیح',required=False,
        widget=forms.Textarea(attrs={'rows':4,'placeholder':'چه کاری انجام شد، چه مانعی وجود دارد یا نتیجه چه بود؟'}),
    )
    def __init__(self,*args,manager=False,**kwargs):
        super().__init__(*args,**kwargs)
        allowed=MeetingActionItem.STATUS if manager else [
            choice for choice in MeetingActionItem.STATUS if choice[0] in ('todo','doing','awaiting_approval','blocked')
        ]
        self.fields['status'].choices=allowed


class MeetingActionManageForm(forms.ModelForm):
    assigned_to=PersianStaffChoiceField(label='مسئول انجام',queryset=User.objects.none())
    due_date=JalaliDateField(label='مهلت انجام',required=False)
    class Meta:
        model=MeetingActionItem
        fields=['assigned_to','due_date','priority']
        labels={'assigned_to':'مسئول انجام','priority':'اولویت'}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['assigned_to'].queryset=active_staff()


class MeetingStepForm(forms.Form):
    title=forms.CharField(label='مرحله یا زیرکار',max_length=180)
