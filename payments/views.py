from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum, Q
from django.http import HttpResponseBadRequest, FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.contrib.auth.models import User
from .models import PaymentRequest, PaymentEvent, PettyCashExpense, PaymentClarification

def executive(user):
    return user.is_authenticated and user.username.lower() in settings.EXECUTIVE_USERNAMES

def staff(user):
    p=getattr(user,'profile',None)
    return bool(p and p.is_active and user.is_active)

class RequestForm(forms.ModelForm):
    class Meta:
        model=PaymentRequest
        fields=['kind','amount_toman','description','recipient_name','recipient_iban','recipient_card']
        widgets={'description':forms.Textarea(attrs={'rows':2})}
    def clean_description(self):
        value=self.cleaned_data['description'].strip()
        if len(value)<10:
            raise ValidationError('شرح درخواست باید حداقل ده نویسه باشد.')
        return value
    def clean(self):
        d=super().clean()
        if d.get('kind')=='payment' and not (d.get('recipient_iban') or d.get('recipient_card')):
            raise ValidationError('شماره کارت یا شبا الزامی است.')
        return d

class ExpenseForm(forms.ModelForm):
    class Meta:
        model=PettyCashExpense
        fields=['amount_toman','description','receipt']
    def clean_receipt(self):
        f=self.cleaned_data['receipt']
        if f.size > 10*1024*1024 or f.content_type not in ('image/jpeg','image/png','image/webp','application/pdf'):
            raise ValidationError('فرمت یا حجم رسید مجاز نیست.')
        return f

@login_required
def workspace(request):
    if not staff(request.user) and not executive(request.user):
        raise PermissionDenied()
    form=RequestForm(request.POST or None,prefix='req')
    expense_form=ExpenseForm(request.POST or None,request.FILES or None,prefix='exp')
    if request.method=='POST':
        if request.POST.get('operation')=='request' and form.is_valid():
            obj=form.save(commit=False)
            obj.requester=request.user
            obj.branch=getattr(getattr(request.user,'profile',None),'branch',None)
            if obj.kind=='petty_cash':
                obj.beneficiary=request.user
            obj.save()
            PaymentEvent.objects.create(payment=obj,actor=request.user,action='created')
            return redirect('payments_workspace')
        if request.POST.get('operation')=='expense' and expense_form.is_valid():
            entry=expense_form.save(commit=False)
            entry.holder=request.user
            entry.created_by=request.user
            entry.save()
            return redirect('payments_workspace')
    clarifications=PaymentRequest.objects.filter(state='needs_info',clarification_assignee=request.user).prefetch_related('clarifications')
    queue=PaymentRequest.objects.filter(state='approved',assigned_to=request.user).select_related('requester')
    mine=PaymentRequest.objects.filter(requester=request.user)[:30]
    expenses=PettyCashExpense.objects.filter(holder=request.user)
    received=PaymentRequest.objects.filter(kind='petty_cash',beneficiary=request.user,state='paid').aggregate(x=Sum('amount_toman'))['x'] or 0
    spent=expenses.aggregate(x=Sum('amount_toman'))['x'] or 0
    return render(request,'payments/workspace.html',dict(form=form,expense_form=expense_form,queue=queue,clarifications=clarifications,mine=mine,expenses=expenses[:20],balance=received-spent,is_executive=executive(request.user)))

@login_required
@require_POST
def review(request,pk):
    if not executive(request.user):
        raise PermissionDenied()
    with transaction.atomic():
        p=get_object_or_404(PaymentRequest.objects.select_for_update(),pk=pk)
        if p.state!='pending':
            return HttpResponseBadRequest('این درخواست قبلاً بررسی شده است.')
        action=request.POST.get('action')
        if action=='reject':
            p.state='rejected'
        elif action=='needs_info':
            note=request.POST.get('question','').strip()
            assignee=get_object_or_404(User,pk=request.POST.get('clarification_assignee') or p.requester_id,is_active=True)
            if len(note)<5:
                return HttpResponseBadRequest('سؤال توضیحی الزامی است.')
            if not staff(assignee) and not executive(assignee):
                raise PermissionDenied()
            p.state='needs_info'
            p.clarification_assignee=assignee
            PaymentClarification.objects.create(payment=p,author=request.user,message=note)
        elif action=='approve':
            assignee=get_object_or_404(User,pk=request.POST.get('assigned_to'),is_active=True)
            channel=request.POST.get('channel')
            if channel not in ('consultant','accountant'):
                return HttpResponseBadRequest('مسیر پرداخت نامعتبر است.')
            if channel=='consultant' and (not staff(assignee) or assignee.profile.role not in ('consultant','receptionist')):
                return HttpResponseBadRequest('پرداخت‌کننده باید مشاور یا منشی فعال باشد.')
            if channel=='accountant' and not assignee.has_perm('payments.execute_official_payment'):
                return HttpResponseBadRequest('مجوز پرداخت رسمی وجود ندارد.')
            p.state='approved'
            p.channel=channel
            p.assigned_to=assignee
            p.approved_by=request.user
            p.approved_at=timezone.now()
        else:
            return HttpResponseBadRequest('عملیات نامعتبر است.')
        p.save()
        PaymentEvent.objects.create(payment=p,actor=request.user,action=action)
    return redirect('payments_admin')

@login_required
@require_POST
def mark_paid(request,pk):
    if not staff(request.user) and not executive(request.user):
        raise PermissionDenied()
    with transaction.atomic():
        p=get_object_or_404(PaymentRequest.objects.select_for_update(),pk=pk,assigned_to=request.user)
        if p.state!='approved':
            return HttpResponseBadRequest('این درخواست در صف شما نیست.')
        if p.channel=='accountant' and not request.user.has_perm('payments.execute_official_payment'):
            raise PermissionDenied()
        reference=request.POST.get('reference','').strip()
        receipt=request.FILES.get('receipt')
        if not reference or not receipt:
            return HttpResponseBadRequest('شماره پیگیری و رسید الزامی است.')
        if receipt.size>10*1024*1024 or receipt.content_type not in ('image/jpeg','image/png','image/webp','application/pdf'):
            return HttpResponseBadRequest('رسید نامعتبر است.')
        p.payment_reference=reference[:120]
        p.payment_receipt=receipt
        p.paid_at=timezone.now()
        p.state='paid'
        p.save()
        PaymentEvent.objects.create(payment=p,actor=request.user,action='paid',notes=reference[:120])
    return redirect('payments_workspace')

@login_required
def admin_dashboard(request):
    if not executive(request.user):
        raise PermissionDenied()
    from django.contrib.auth.models import Permission
    requests=PaymentRequest.objects.select_related('requester','assigned_to','approved_by','beneficiary','branch')
    consultants=User.objects.filter(is_active=True,profile__is_active=True,profile__role__in=['consultant','receptionist'])
    accountants=User.objects.filter(is_active=True,user_permissions__codename='execute_official_payment').distinct()
    paid=requests.filter(state='paid')
    return render(request,'payments/admin.html',{'pending':requests.filter(state='pending'),'active':requests.filter(state='approved'),'paid':paid[:200],'consultants':consultants,'accountants':accountants,'staff_members':User.objects.filter(is_active=True,profile__is_active=True).order_by('first_name','last_name')})

@login_required
@require_POST
def answer_clarification(request,pk):
    with transaction.atomic():
        p=get_object_or_404(PaymentRequest.objects.select_for_update(),pk=pk)
        if p.state!='needs_info' or p.clarification_assignee_id!=request.user.id:
            raise PermissionDenied()
        response=request.POST.get('answer','').strip()
        if len(response)<5:
            return HttpResponseBadRequest('پاسخ توضیحی الزامی است.')
        PaymentClarification.objects.create(payment=p,author=request.user,message=response)
        p.state='pending'
        p.clarification_assignee=None
        p.save(update_fields=['state','clarification_assignee'])
        PaymentEvent.objects.create(payment=p,actor=request.user,action='clarification_answered')
    return redirect('payments_workspace')

@login_required
def receipt(request,pk):
    p=get_object_or_404(PaymentRequest,pk=pk,state='paid')
    if not executive(request.user) and request.user.pk not in (p.requester_id,p.assigned_to_id):
        raise PermissionDenied()
    if not p.payment_receipt:
        raise Http404()
    response=FileResponse(p.payment_receipt.open('rb'),as_attachment=True)
    response['Cache-Control']='no-store, private'
    response['X-Content-Type-Options']='nosniff'
    return response
