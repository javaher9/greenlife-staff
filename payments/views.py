from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, models
from django.db.models import Sum, Q
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
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
    return bool(user.is_active and p and p.is_active and (p.role == 'consultant' or p.can_request_payments))

def assigned_operator(user):
    return bool(user.is_authenticated and user.is_active and PaymentRequest.objects.filter(assigned_to=user, state__in=('approved','paid')).exists())

class RequestForm(forms.ModelForm):
    class Meta:
        model=PaymentRequest
        fields=['kind','amount_toman','description','category','cost_owner','cost_center','due_date','recipient_name','recipient_iban','recipient_card']
        labels={'kind':'نوع درخواست','amount_toman':'مبلغ (تومان)','description':'شرح و علت پرداخت','category':'موضوع هزینه','cost_owner':'متعلق به','cost_center':'مرکز هزینه / پروژه (اختیاری)','due_date':'مهلت پرداخت','recipient_name':'نام گیرنده','recipient_iban':'شماره شبا','recipient_card':'شماره کارت'}
        widgets={'description':forms.Textarea(attrs={'rows':2}),'due_date':forms.DateInput(attrs={'type':'date'})}
    def __init__(self, *args, **kwargs):
        # The staff UI submits amounts in millions; existing API/test clients can still use toman.
        if args and args[0] is not None and 'req-amount_million' in args[0]:
            data=args[0].copy()
            try:
                from decimal import Decimal
                million=Decimal(str(data.get('req-amount_million','')).replace(',','').strip())
                if not million.is_finite() or million <= 0 or million * 1000000 != int(million * 1000000):
                    raise ValueError()
                data['req-amount_toman']=str(int(million*1000000))
            except (ValueError,ArithmeticError):
                data['req-amount_toman']=''
            args=(data,)+args[1:]
        super().__init__(*args,**kwargs)

    def clean_description(self):
        value=self.cleaned_data['description'].strip()
        if len(value)<10:
            raise ValidationError('شرح درخواست باید حداقل ده نویسه باشد.')
        return value
    def clean(self):
        d=super().clean()
        if d.get('kind')=='payment' and not d.get('recipient_name'):
            raise ValidationError('نام دریافت‌کننده برای درخواست پرداخت الزامی است.')
        if d.get('kind')=='payment' and not (d.get('recipient_iban') or d.get('recipient_card')):
            raise ValidationError('شماره کارت یا شبا الزامی است.')
        return d

class ExpenseForm(forms.ModelForm):
    class Meta:
        model=PettyCashExpense
        fields=['amount_toman','description','category','cost_owner','cost_center','receipt']
        labels={'amount_toman':'مبلغ خرج‌شده (تومان)','description':'شرح هزینه','category':'موضوع هزینه','cost_owner':'متعلق به','cost_center':'مرکز هزینه / پروژه (اختیاری)','receipt':'فاکتور یا رسید'}
        widgets={'description':forms.Textarea(attrs={'rows':2})}
    def __init__(self, *args, **kwargs):
        # The staff UI submits amounts in millions; existing API/test clients can still use toman.
        if args and args[0] is not None and 'exp-amount_million' in args[0]:
            data=args[0].copy()
            try:
                from decimal import Decimal
                million=Decimal(str(data.get('exp-amount_million','')).replace(',','').strip())
                if not million.is_finite() or million <= 0 or million * 1000000 != int(million * 1000000):
                    raise ValueError()
                data['exp-amount_toman']=str(int(million*1000000))
            except (ValueError,ArithmeticError):
                data['exp-amount_toman']=''
            args=(data,)+args[1:]
        super().__init__(*args,**kwargs)

    def clean_receipt(self):
        f=self.cleaned_data['receipt']
        if f.size > 10*1024*1024 or f.content_type not in ('image/jpeg','image/png','image/webp','application/pdf'):
            raise ValidationError('فرمت یا حجم رسید مجاز نیست.')
        return f


PAYMENT_ASSIGNEES = (
    ('sadeghi', 'آقای صادقی', ('صادقی', 'sadeghi')),
    ('naderi', 'آقای نادری', ('نادری', 'naderi')),
    ('moradi', 'خانم مرادی', ('مرادی', 'moradi')),
    ('hosseini', 'خانم حسینی · حسابدار', ('حسینی', 'hosseini')),
    ('memari', 'خانم مرجان معماری · مشاور پونک', ('معماری', 'memari', 'memary')),
)

def five_payment_assignees():
    """Only uniquely identified active employee accounts, never sales-network members."""
    candidates=User.objects.filter(is_active=True,profile__is_active=True).select_related('profile')
    results=[]
    for slug,title,aliases in PAYMENT_ASSIGNEES:
        matched=[]
        for user in candidates:
            full=' '.join([user.first_name or '',user.last_name or '',user.username or '']).replace('ي','ی').replace('ك','ک').lower()
            if any(alias.lower() in full for alias in aliases):
                if slug=='memari' and not ('مرجان' in full or 'marjan' in full):
                    continue
                if slug=='hosseini' and not ('زینب' in full or 'zeinab' in full or 'zeynab' in full or 'حسابدار' in (user.profile.job_title or '')):
                    continue
                matched.append(user)
        if len(matched)==1:
            results.append((slug,title,matched[0]))
    return results

class ExecutiveQuickPaymentForm(forms.Form):
    amount_million=forms.DecimalField(label='مبلغ (میلیون تومان)',min_value=0.001,max_digits=14,decimal_places=3,widget=forms.NumberInput(attrs={'step':'0.001','placeholder':'مثلاً ۳۲'}))
    description=forms.CharField(label='شرح پرداخت',max_length=500,widget=forms.Textarea(attrs={'rows':2,'placeholder':'بابت چه کاری؟'}))
    assigned_to=forms.ModelChoiceField(label='مسئول پرداخت',queryset=User.objects.none(),widget=forms.RadioSelect)
    priority=forms.ChoiceField(label='اولویت',choices=PaymentRequest.PRIORITIES,initial='normal')
    recipient_name=forms.CharField(label='نام گیرنده',max_length=160)
    recipient_iban=forms.CharField(label='شماره شبا',max_length=34,required=False)
    recipient_card=forms.CharField(label='شماره کارت',max_length=24,required=False)
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.assignees=five_payment_assignees()
        self.fields['assigned_to'].queryset=User.objects.filter(pk__in=[user.pk for _,_,user in self.assignees])
    def clean(self):
        cleaned=super().clean()
        if not cleaned.get('recipient_iban') and not cleaned.get('recipient_card'):
            raise ValidationError('شماره کارت یا شبا را وارد کنید.')
        return cleaned

@login_required
def request_permission_settings(request):
    if not executive(request.user):
        raise PermissionDenied()
    from core.models import EmployeeProfile
    # Restrict grants to real employed staff, never referral/sales-network members.
    workforce=EmployeeProfile.objects.filter(is_active=True,user__is_active=True).exclude(
        role__in=['referrer','scan_station']
    ).filter(
        ~Q(role='employee') | Q(branch__isnull=False) |
        (Q(employee_code__isnull=False) & ~Q(employee_code='')) |
        ~Q(job_title='')
    ).select_related('user','branch').order_by('user__first_name','user__last_name')
    if request.method=='POST':
        try:
            profile_id=int(request.POST.get('profile_id',''))
        except (ValueError,TypeError):
            return HttpResponseBadRequest('شناسه نامعتبر است')
        profile=get_object_or_404(workforce,pk=profile_id)
        profile.can_request_payments=request.POST.get('enabled')=='1'
        profile.save(update_fields=['can_request_payments'])
        return redirect('payments_admin')
    return redirect('payments_admin')

@login_required
@login_required
def executive_quick_payment(request):
    if not executive(request.user):
        raise PermissionDenied()
    form=ExecutiveQuickPaymentForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            item=PaymentRequest.objects.create(
                kind='payment',
                amount_toman=int(form.cleaned_data['amount_million'] * 1000000),
                description=form.cleaned_data['description'],
                requester=request.user,
                state='approved',
                approved_by=request.user,
                approved_at=timezone.now(),
                assigned_to=form.cleaned_data['assigned_to'],
                channel='staff',
                priority=form.cleaned_data['priority'],
                recipient_name=form.cleaned_data['recipient_name'],
                recipient_iban=form.cleaned_data['recipient_iban'],
                recipient_card=form.cleaned_data['recipient_card'],
            )
            PaymentEvent.objects.create(payment=item,actor=request.user,action='created',notes='دستور مستقیم مدیریت')
            PaymentEvent.objects.create(payment=item,actor=request.user,action='approve',notes='تأیید مستقیم مدیریت')
        return redirect('payments_expenses')
    return render(request,'payments/executive_quick_payment.html',{'form':form,'assignees':form.assignees,'missing_count':5-len(form.assignees)})

@login_required
def workspace(request):
    if not staff(request.user) and not executive(request.user) and not assigned_operator(request.user):
        raise PermissionDenied()
    operation=request.POST.get('operation') if request.method=='POST' else None
    form=RequestForm(request.POST if operation=='request' else None,prefix='req')
    expense_form=ExpenseForm(request.POST if operation=='expense' else None,request.FILES if operation=='expense' else None,prefix='exp')
    previous_recipient=(PaymentRequest.objects.filter(requester=request.user)
        .exclude(recipient_name='').order_by('-created_at').first())
    if previous_recipient and not form.is_bound:
        form.initial.update({
            'recipient_name':previous_recipient.recipient_name,
            'recipient_card':previous_recipient.recipient_card,
            'recipient_iban':previous_recipient.recipient_iban,
        })
    if request.method=='POST' and not (staff(request.user) or executive(request.user)):
        raise PermissionDenied()
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
    queue=PaymentRequest.objects.filter(state='approved',assigned_to=request.user).select_related('requester').order_by(models.Case(models.When(priority='urgent',then=0),models.When(priority='today',then=1),models.When(priority='normal',then=2),default=3,output_field=models.IntegerField()),'due_date','-created_at')
    completed=PaymentRequest.objects.filter(state='paid',assigned_to=request.user).select_related('requester').order_by('-paid_at')[:40]
    mine=PaymentRequest.objects.filter(requester=request.user).prefetch_related('events')[:30]
    expenses=PettyCashExpense.objects.filter(holder=request.user)
    received=PaymentRequest.objects.filter(kind='petty_cash',beneficiary=request.user,state='paid').aggregate(x=Sum('amount_toman'))['x'] or 0
    spent=expenses.aggregate(x=Sum('amount_toman'))['x'] or 0
    return render(request,'payments/workspace.html',dict(submit_operation=operation,posted_million=request.POST.get('req-amount_million','') if operation=='request' else '',posted_exp_million=request.POST.get('exp-amount_million','') if operation=='expense' else '',form=form,expense_form=expense_form,queue=queue,completed=completed,clarifications=clarifications,mine=mine,expenses=expenses[:20],balance=received-spent,has_petty_cash=(received>0 or spent>0),is_executive=executive(request.user), can_submit=staff(request.user) or executive(request.user)))

def payment_approved_assignees():
    """Only explicitly designated Green Life payment operators, never the whole workforce."""
    names=('حسینی','نادری','مرادی','معماری','صادقی','hosseini','hossaini','naderi','moradi','memari','sadeghi')
    match=Q(pk__in=[])
    for name in names:
        match |= Q(last_name__icontains=name) | Q(first_name__icontains=name)
    return User.objects.filter(is_active=True,profile__is_active=True).filter(match).exclude(profile__role__in=('referrer','referral_supervisor','scan_station')).select_related('profile','profile__branch').distinct().order_by('last_name','first_name')


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
            note=request.POST.get('reason','').strip()
            if len(note)<5:
                return HttpResponseBadRequest('علت رد درخواست الزامی است (حداقل ۵ حرف).')
            p.state='rejected'
        elif action=='needs_info':
            note=request.POST.get('question','').strip()
            assignee=p.requester
            if len(note)<5:
                return HttpResponseBadRequest('سؤال توضیحی الزامی است.')
            if not staff(assignee) and not executive(assignee):
                raise PermissionDenied()
            p.state='needs_info'
            p.clarification_assignee=assignee
            PaymentClarification.objects.create(payment=p,author=request.user,message=note)
        elif action=='approve':
            assignee=get_object_or_404(payment_approved_assignees(),pk=request.POST.get('assigned_to'))
            channel=request.POST.get('channel')
            if channel not in ('consultant', 'staff'):
                return HttpResponseBadRequest('مسیر پرداخت نامعتبر است.')
            if channel=='consultant' and (not staff(assignee) or assignee.profile.role != 'consultant'):
                return HttpResponseBadRequest('پرداخت‌کننده باید مشاور یا منشی فعال باشد.')
            if channel=='staff' and not assignee.is_active:
                return HttpResponseBadRequest('مسئول پرداخت فعال نیست.')
            p.state='approved'
            p.channel=channel
            p.assigned_to=assignee
            p.approved_by=request.user
            p.approved_at=timezone.now()
        else:
            return HttpResponseBadRequest('عملیات نامعتبر است.')
        p.save()
        PaymentEvent.objects.create(payment=p,actor=request.user,action=action,notes=(note[:250] if action in ('reject','needs_info') else ''))
    return redirect('payments_admin')

@login_required
@require_POST
def mark_paid(request,pk):
    if not request.user.is_authenticated or not request.user.is_active:
        raise PermissionDenied()
    with transaction.atomic():
        p=get_object_or_404(PaymentRequest.objects.select_for_update(),pk=pk,assigned_to=request.user)
        if p.state!='approved':
            return HttpResponseBadRequest('این درخواست در صف شما نیست.')
        if p.channel not in ('consultant','staff'):
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
    consultants=User.objects.filter(is_active=True,profile__is_active=True,profile__role='consultant')
    accountants=User.objects.none()
    operators=payment_approved_assignees()
    paid=requests.filter(state='paid')
    return render(request,'payments/admin.html',{'pending':requests.filter(state='pending'),'active':requests.filter(state='approved'),'paid':paid[:200],'consultants':consultants,'accountants':accountants,'operators':operators,'staff_members':User.objects.filter(is_active=True,profile__is_active=True,profile__role='consultant').order_by('first_name','last_name'),'permission_profiles': __import__('core.models',fromlist=['EmployeeProfile']).EmployeeProfile.objects.filter(is_active=True,user__is_active=True).exclude(role__in=['referrer','scan_station']).filter(~Q(role='employee') | Q(branch__isnull=False) | (Q(employee_code__isnull=False) & ~Q(employee_code='')) | ~Q(job_title='')).select_related('user','branch').order_by('user__first_name','user__last_name'),})

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


@login_required
def expenses_dashboard(request):
    """Executive-only expense ledger, independent from the existing income dashboard.

    A petty-cash disbursement transfers funds to a holder; the actual
    PettyCashExpense is the expense. Do not count both as operating costs.
    """
    if not executive(request.user):
        raise PermissionDenied()

    base_requests = PaymentRequest.objects.select_related('requester', 'assigned_to', 'branch')
    base_expenses = PettyCashExpense.objects.select_related('holder', 'created_by')
    def amount(qs):
        return qs.aggregate(total=Sum('amount_toman'))['total'] or 0

    summary = {
        'pending': amount(base_requests.filter(state__in=['pending', 'needs_info'])),
        'approved': amount(base_requests.filter(state='approved')),
        'paid_transfers': amount(base_requests.filter(state='paid')),
        'paid_costs': amount(base_requests.filter(state='paid', kind='payment')) + amount(base_expenses),
        'petty_disbursed': amount(base_requests.filter(state='paid', kind='petty_cash')),
        'petty_spent': amount(base_expenses),
        'personal_costs': amount(base_requests.filter(state='paid', kind='payment', cost_owner='personal')) +
                          amount(base_expenses.filter(cost_owner='personal')),
    }

    selected_category = request.GET.get('category', '')
    selected_owner = request.GET.get('owner', '')
    selected_status = request.GET.get('state', '')
    query = request.GET.get('q', '').strip()[:150]
    def safe_date(key):
        try:
            return parse_date(request.GET.get(key, ''))
        except ValueError:
            return None
    from_date = safe_date('from')
    to_date = safe_date('to')
    if selected_category:
        base_requests = base_requests.filter(category=selected_category)
        base_expenses = base_expenses.filter(category=selected_category)
    if selected_owner:
        base_requests = base_requests.filter(cost_owner=selected_owner)
        base_expenses = base_expenses.filter(cost_owner=selected_owner)
    if selected_status in ('pending','approved','needs_info','rejected','paid'):
        base_requests = base_requests.filter(state=selected_status)
        if selected_status != 'paid':
            base_expenses = base_expenses.none()
    if query:
        base_requests = base_requests.filter(
            Q(description__icontains=query) | Q(recipient_name__icontains=query) |
            Q(cost_center__icontains=query) | Q(requester__username__icontains=query))
        base_expenses = base_expenses.filter(
            Q(description__icontains=query) | Q(cost_center__icontains=query) |
            Q(holder__username__icontains=query))
    if from_date:
        base_requests = base_requests.filter(created_at__date__gte=from_date)
        base_expenses = base_expenses.filter(created_at__date__gte=from_date)
    if to_date:
        base_requests = base_requests.filter(created_at__date__lte=to_date)
        base_expenses = base_expenses.filter(created_at__date__lte=to_date)

    requests_page = Paginator(base_requests.order_by('-created_at'), 50).get_page(request.GET.get('requests_page'))
    petty_page = Paginator(base_expenses.order_by('-created_at'), 30).get_page(request.GET.get('petty_page'))
    from .models import EXPENSE_CATEGORIES, COST_OWNERS
    return render(request, 'payments/expenses_dashboard.html', {
        'summary': summary, 'requests_page': requests_page, 'petty_page': petty_page,
        'categories': EXPENSE_CATEGORIES, 'owners': COST_OWNERS,
        'selected_category': selected_category, 'selected_owner': selected_owner,
        'selected_status': selected_status, 'query': query,
        'from_date': request.GET.get('from',''), 'to_date': request.GET.get('to','')
    })


@login_required
def petty_receipt(request, pk):
    item = get_object_or_404(PettyCashExpense, pk=pk)
    if not executive(request.user) and item.holder_id != request.user.pk:
        raise PermissionDenied()
    if not item.receipt:
        raise Http404()
    response = FileResponse(item.receipt.open('rb'), as_attachment=True)
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


@login_required
def accounting_hub(request):
    """Executive-only management accounting entry, not an accounting ledger."""
    if not executive(request.user):
        raise PermissionDenied()
    return render(request, 'payments/accounting_hub.html')
