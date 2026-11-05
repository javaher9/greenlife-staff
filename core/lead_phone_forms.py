import re
from django import forms
from .lead_contacts import clean_numbers
from .models import ReferralLead, LEAD_DUPLICATE_MESSAGE


class LeadPhonesCreateMixin:
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['additional_phones']=forms.CharField(label='شماره‌های دیگر',required=False,max_length=400,
            help_text='هر شماره در یک خط؛ اختیاری',widget=forms.Textarea(attrs={'rows':2,'dir':'ltr','class':'lead-extra-phones-input','inputmode':'tel'}))

    def clean(self):
        data=super().clean()
        if not data.get('phone'):
            return data
        additional=[x.strip() for x in re.split(r'[\n,،;]+',data.get('additional_phones','')) if x.strip()]
        try:
            numbers=clean_numbers(data['phone'],additional)
        except forms.ValidationError as exc:
            self.add_error('additional_phones',exc)
            return data
        data['phone']=numbers[0]
        data['additional_phones']=numbers[1:]
        for number in numbers[1:]:
            if ReferralLead.recent_duplicate_for_phone(number):
                self.add_error('additional_phones',LEAD_DUPLICATE_MESSAGE)
                break
        return data
