from django import forms
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction, models
from django.db.models import Sum, Q
from django.core.paginator import Paginator
from django.utils.dateparse import parse_date
from django.http import HttpResponse, HttpResponseBadRequest, FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_safe
from django.contrib.auth.models import User
from django.contrib import messages
from django.urls import reverse
from .models import PaymentRequest, PaymentEvent, PettyCashExpense, PaymentClarification, SavedPaymentRecipient
from .history import (
    EVENT_LABELS, decorate_payment, display_name, history_context,
    presentation_queryset, visible_payments,
)

def executive(user):
    return user.is_authenticated and user.username.lower() in settings.EXECUTIVE_USERNAMES

def staff(user):
    p=getattr(user,'profile',None)
    return bool(user.is_active and p and p.is_active and p.can_request_payments)

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

class PersonalExpenseForm(forms.Form):
    amount_million=forms.DecimalField(label='مبلغ (میلیون تومان)',min_value=0.000001,decimal_places=6,max_digits=15)
    description=forms.CharField(label='شرح هزینه شخصی',min_length=10,widget=forms.Textarea(attrs={'rows':2}))
    category=forms.ChoiceField(label='موضوع هزینه',choices=__import__('payments.models',fromlist=['EXPENSE_CATEGORIES']).EXPENSE_CATEGORIES)
    receipt=forms.FileField(label='فاکتور یا رسید پرداخت')
    def clean_receipt(self):
        file=self.cleaned_data['receipt']
        if file.size > 10*1024*1024 or file.content_type not in ('image/jpeg','image/png','image/webp','application/pdf'):
            raise ValidationError('رسید باید PDF یا تصویر، حداکثر ۱۰ مگابایت باشد.')
        return file


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
    candidates=User.objects.filter(is_active=True,profile__is_active=True,profile__can_execute_payments=True).select_related('profile')
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

def six_payment_assignees(executive_user):
    """Append exactly the authenticated owner as sixth recipient of orders.

    Match by executive permission/username, never by shared surname.
    Do not grant general payment-operator permissions to other users.
    """
    people=five_payment_assignees()
    if executive_user and executive_user.is_active and executive(executive_user):
        if not any(user.pk==executive_user.pk for _,_,user in people):
            people.append(('executive','دکتر جواهریان',executive_user))
    return people


class ExecutiveQuickPaymentForm(forms.Form):
    amount_million=forms.DecimalField(label='مبلغ (میلیون تومان)',min_value=0.001,max_digits=14,decimal_places=3,widget=forms.NumberInput(attrs={'step':'0.001','placeholder':'مثلاً ۳۲'}))
    description=forms.CharField(label='شرح پرداخت',max_length=500,widget=forms.Textarea(attrs={'rows':2,'placeholder':'بابت چه کاری؟'}))
    assigned_to=forms.ModelChoiceField(label='مسئول پرداخت',queryset=User.objects.none(),widget=forms.RadioSelect)
    priority=forms.ChoiceField(label='اولویت',choices=PaymentRequest.PRIORITIES,initial='normal')
    recipient_name=forms.CharField(label='نام گیرنده',max_length=160)
    recipient_iban=forms.CharField(label='شماره شبا',max_length=34,required=False)
    recipient_card=forms.CharField(label='شماره کارت',max_length=24,required=False)
    def __init__(self,*args,executive_user=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.assignees=six_payment_assignees(executive_user)
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
        role__in=['referrer','referral_supervisor','scan_station']
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
        permission=request.POST.get('permission','can_request_payments')
        allowed=('can_request_payments','can_execute_payments','can_manage_petty_cash','can_claim_personal_expense')
        if permission not in allowed:
            return HttpResponseBadRequest('نوع مجوز مالی نامعتبر است.')
        setattr(profile,permission,request.POST.get('enabled')=='1')
        profile.save(update_fields=[permission])
        from django.urls import reverse
        return redirect(f'{reverse("payments_admin")}#finance-person-{profile.pk}')
    return redirect('payments_admin')

@login_required
@login_required
def executive_quick_payment(request):
    if not executive(request.user):
        raise PermissionDenied()
    form=ExecutiveQuickPaymentForm(request.POST or None,executive_user=request.user)
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
        if item.assigned_to_id == request.user.pk:
            from django.urls import reverse
            return redirect(reverse('payments_workspace') + '#assignedPayments')
        return redirect('payments_expenses')
    saved_recipients = SavedPaymentRecipient.objects.filter(owner=request.user)
    named_staff_count=sum(1 for slug,_,_ in form.assignees if slug!='executive')
    return render(request,'payments/executive_quick_payment.html',{
        'form':form,'assignees':form.assignees,
        'missing_count':5-named_staff_count,'saved_recipients':saved_recipients,
    })

@login_required
@require_POST
def executive_save_recipient(request):
    if not executive(request.user):
        raise PermissionDenied()
    name=request.POST.get('name','').strip()
    iban=request.POST.get('iban','').strip().replace(' ','').upper()
    card=request.POST.get('card','').strip().replace(' ','').replace('-','')
    if not name or len(name)>160 or not (iban or card):
        return HttpResponseBadRequest('نام و شماره شبا یا کارت الزامی است.')
    if iban and (len(iban)!=26 or not iban.startswith('IR') or not iban[2:].isdigit()):
        return HttpResponseBadRequest('شماره شبا باید IR و ۲۴ رقم باشد.')
    if card and (len(card)!=16 or not card.isdigit()):
        return HttpResponseBadRequest('شماره کارت باید ۱۶ رقم باشد.')
    if SavedPaymentRecipient.objects.filter(owner=request.user,name=name,iban=iban,card=card).exists():
        return redirect('payments_executive_quick')
    SavedPaymentRecipient.objects.create(owner=request.user,name=name,iban=iban,card=card)
    return redirect('payments_executive_quick')

@login_required
def workspace(request):
    if not request.user.is_active:
        raise PermissionDenied()
    if not staff(request.user) and not executive(request.user) and not assigned_operator(request.user) and not getattr(getattr(request.user,'profile',None),'can_manage_petty_cash',False) and not getattr(getattr(request.user,'profile',None),'can_claim_personal_expense',False):
        raise PermissionDenied()
    operation=request.POST.get('operation') if request.method=='POST' else None
    form=RequestForm(request.POST if operation=='request' else None,prefix='req')
    expense_form=ExpenseForm(request.POST if operation=='expense' else None,request.FILES if operation=='expense' else None,prefix='exp')
    personal_form=PersonalExpenseForm(request.POST if operation=='personal_expense' else None,request.FILES if operation=='personal_expense' else None,prefix='personal')
    previous_recipient=(PaymentRequest.objects.filter(requester=request.user)
        .exclude(recipient_name='').order_by('-created_at').first())
    if previous_recipient and not form.is_bound:
        form.initial.update({
            'recipient_name':previous_recipient.recipient_name,
            'recipient_card':previous_recipient.recipient_card,
            'recipient_iban':previous_recipient.recipient_iban,
        })
    if request.method=='POST':
        if operation=='personal_expense' and not (executive(request.user) or getattr(getattr(request.user,'profile',None),'can_claim_personal_expense',False)):
            raise PermissionDenied()
        if operation=='expense' and not (executive(request.user) or getattr(getattr(request.user,'profile',None),'can_manage_petty_cash',False)):
            raise PermissionDenied()
        if operation not in ('request','expense','personal_expense'):
            return HttpResponseBadRequest('عملیات مالی نامعتبر است.')
    if request.method=='POST':
        if operation=='request' and request.POST.get('req-kind') not in ('payment','petty_cash'):
            return HttpResponseBadRequest('نوع درخواست نامعتبر است.')
        if operation=='personal_expense' and personal_form.is_valid():
            data=personal_form.cleaned_data
            amount=int(data['amount_million']*1000000)
            if amount<=0:
                return HttpResponseBadRequest('مبلغ نامعتبر است.')
            claim=PaymentRequest.objects.create(kind='personal_expense',amount_toman=amount,description=data['description'],category=data['category'],requester=request.user,beneficiary=request.user,branch=getattr(request.user.profile,'branch',None),recipient_name=request.user.get_full_name() or request.user.username,personal_expense_receipt=data['receipt'])
            PaymentEvent.objects.create(payment=claim,actor=request.user,action='created',notes='هزینه شخصی؛ نیازمند بررسی و تأیید مدیریت')
            return redirect('payments_workspace')
        if operation=='request' and request.POST.get('req-kind')=='petty_cash' and not executive(request.user) and not getattr(request.user.profile,'can_manage_petty_cash',False):
            raise PermissionDenied()
        if operation=='request' and request.POST.get('req-kind')!='petty_cash' and not (staff(request.user) or executive(request.user)):
            raise PermissionDenied()
        if operation=='request' and form.is_valid():
            obj=form.save(commit=False)
            obj.requester=request.user
            obj.branch=getattr(getattr(request.user,'profile',None),'branch',None)
            if obj.kind=='petty_cash':
                obj.beneficiary=request.user
            obj.save()
            PaymentEvent.objects.create(payment=obj,actor=request.user,action='created')
            return redirect('payments_workspace')
        if operation=='expense' and not (executive(request.user) or getattr(request.user.profile,'can_manage_petty_cash',False)):
            raise PermissionDenied()
        if operation=='expense' and expense_form.is_valid():
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
    response = render(request,'payments/workspace.html',dict(personal_form=personal_form,can_request=staff(request.user) or executive(request.user),can_petty=executive(request.user) or getattr(getattr(request.user,'profile',None),'can_manage_petty_cash',False), can_personal=executive(request.user) or getattr(getattr(request.user,'profile',None),'can_claim_personal_expense',False),submit_operation=operation,posted_million=request.POST.get('req-amount_million','') if operation=='request' else '',posted_exp_million=request.POST.get('exp-amount_million','') if operation=='expense' else '',form=form,expense_form=expense_form,queue=queue,completed=completed,clarifications=clarifications,mine=mine,expenses=expenses[:20],balance=received-spent,has_petty_cash=(received>0 or spent>0),is_executive=executive(request.user),payment_methods=PaymentRequest.PAYMENT_METHODS,funding_sources=PaymentRequest.FUNDING_SOURCES, can_submit=staff(request.user) or executive(request.user),**history_context(request,executive(request.user))))
    response['Cache-Control'] = 'no-store, private'
    return response


@login_required
@require_safe
def payment_detail(request, pk):
    """Read a payment and its recorded audit trail inside the viewer's scope."""
    if not request.user.is_active:
        raise PermissionDenied()
    is_executive = executive(request.user)
    payment = get_object_or_404(
        presentation_queryset(visible_payments(request.user, is_executive)), pk=pk,
    )
    decorate_payment(payment, is_executive)
    timeline = list(payment.events.select_related('actor').order_by('created_at', 'pk'))
    for event in timeline:
        event.action_label = EVENT_LABELS.get(event.action, 'رویداد ثبت‌شده')
        event.actor_name = display_name(event.actor)
    clarification_messages = payment.clarifications.select_related('author').order_by('created_at', 'pk')
    in_dialog = request.GET.get('panel') == '1'
    template = 'payments/partials/payment_detail.html' if in_dialog else 'payments/history_detail.html'
    response = render(request, template, {
        'payment': payment, 'timeline': timeline,
        'clarification_messages': clarification_messages,
        'can_edit': payment.history_can_edit, 'is_executive': is_executive,
        'can_delete': payment.history_can_delete,
        'deletion_reasons': PaymentRequest.DELETION_REASONS, 'in_dialog': in_dialog,
        'delete_return_to': request.GET.get('return_to', '') if request.GET.get('return_to') in ('admin', 'expenses') else '',
        'open_delete': request.GET.get('focus') == 'delete',
        'can_complete': (
            payment.state == 'approved' and payment.assigned_to_id == request.user.pk
            and payment.channel in ('consultant', 'staff')
            and (is_executive or getattr(getattr(request.user, 'profile', None), 'can_execute_payments', False))
        ),
    })
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    return response


def _receipt_thumbnail(request, pk, *, personal=False):
    """Decode a small protected preview without publishing or modifying originals."""
    from io import BytesIO
    import warnings
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not request.user.is_active:
        raise PermissionDenied()
    payments = visible_payments(request.user, executive(request.user))
    payments = payments.filter(kind='personal_expense') if personal else payments.filter(state='paid')
    payment = get_object_or_404(payments, pk=pk)
    receipt_file = payment.personal_expense_receipt if personal else payment.payment_receipt
    if not receipt_file:
        raise Http404()
    try:
        if receipt_file.size > 10 * 1024 * 1024:
            raise Http404()
        with receipt_file.open('rb') as source, warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(source) as original:
                if original.format not in ('JPEG', 'PNG', 'WEBP') or original.width * original.height > 40000000:
                    raise Http404()
                original.thumbnail((160, 160), Image.Resampling.LANCZOS)
                preview = ImageOps.exif_transpose(original).convert('RGBA')
                flattened = Image.new('RGB', preview.size, 'white')
                flattened.paste(preview, mask=preview.getchannel('A'))
                output = BytesIO()
                flattened.save(output, format='JPEG', quality=82, optimize=True)
    except (OSError, ValueError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise Http404()
    response = HttpResponse(output.getvalue(), content_type='image/jpeg')
    response['Cache-Control'] = 'no-store, private'
    response['X-Content-Type-Options'] = 'nosniff'
    response['Content-Disposition'] = 'inline; filename="payment-thumbnail.jpg"'
    return response


@login_required
@require_safe
def receipt_thumbnail(request, pk):
    return _receipt_thumbnail(request, pk)


@login_required
@require_safe
def personal_receipt_thumbnail(request, pk):
    return _receipt_thumbnail(request, pk, personal=True)

def payment_approved_assignees():
    """Only explicitly designated Green Life payment operators, never the whole workforce."""
    names=('حسینی','نادری','مرادی','معماری','صادقی','hosseini','hossaini','naderi','moradi','memari','sadeghi')
    match=Q(pk__in=[])
    for name in names:
        match |= Q(last_name__icontains=name) | Q(first_name__icontains=name)
    authorized_operator=(
        Q(profile__is_active=True,profile__can_execute_payments=True)
        & match
        & ~Q(profile__role__in=('referrer','referral_supervisor','scan_station'))
    )
    return User.objects.filter(is_active=True).filter(
        authorized_operator | Q(username__in=settings.EXECUTIVE_USERNAMES),
    ).select_related('profile','profile__branch').distinct().order_by('last_name','first_name')


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
            if not assignee.is_active:
                raise PermissionDenied()
            p.state='needs_info'
            p.clarification_assignee=assignee
            PaymentClarification.objects.create(payment=p,author=request.user,message=note)
        elif action=='approve':
            assignee=get_object_or_404(payment_approved_assignees(),pk=request.POST.get('assigned_to'))
            channel=request.POST.get('channel')
            if channel not in ('consultant', 'staff'):
                return HttpResponseBadRequest('مسیر پرداخت نامعتبر است.')
            if channel=='consultant' and (assignee.profile.role != 'consultant' or not assignee.profile.can_execute_payments):
                return HttpResponseBadRequest('پرداخت‌کننده باید مشاور یا منشی فعال باشد.')
            if channel=='staff' and not (executive(assignee) or getattr(getattr(assignee,'profile',None),'can_execute_payments',False)):
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
def executive_change_unpaid(request, pk):
    """Executive-only correction/cancellation; paid payments are immutable."""
    if not executive(request.user):
        raise PermissionDenied()
    from decimal import Decimal, InvalidOperation
    action = request.POST.get('action')
    if action not in ('edit', 'cancel'):
        return HttpResponseBadRequest('عملیات نامعتبر است.')
    with transaction.atomic():
        p = get_object_or_404(PaymentRequest.objects.select_for_update(), pk=pk)
        if p.state not in ('pending', 'approved'):
            return HttpResponseBadRequest('فقط درخواست‌های پرداخت‌نشده قابل اصلاح یا لغو هستند.')
        if p.has_payment_evidence:
            return HttpResponseBadRequest('این درخواست دارای سابقه پرداخت است.')
        if action == 'cancel':
            reason = request.POST.get('reason', '').strip()
            if len(reason) < 5:
                return HttpResponseBadRequest('علت لغو باید حداقل ۵ حرف باشد.')
            previous = p.state
            p.state = 'rejected'
            p.assigned_to = None
            p.channel = ''
            p.save(update_fields=['state', 'assigned_to', 'channel'])
            PaymentEvent.objects.create(payment=p, actor=request.user, action='executive_cancel',
                                        notes=f'{previous}: {reason}'[:250])
        else:
            raw = request.POST.get('amount_million', '').strip().replace(',', '')
            try:
                million = Decimal(raw)
                toman = million * Decimal(1000000)
            except (InvalidOperation, ValueError):
                return HttpResponseBadRequest('مبلغ نامعتبر است.')
            if not million.is_finite() or toman != toman.to_integral_value() or not (0 < toman < 9223372036854775808):
                return HttpResponseBadRequest('مبلغ باید مثبت و به میلیون تومان باشد.')
            description = request.POST.get('description', '').strip()
            if not description or len(description) > 2000:
                return HttpResponseBadRequest('شرح معتبر وارد کنید.')
            before_amount = p.amount_toman
            before_description = p.description
            p.amount_toman = int(toman)
            p.description = description
            p.save(update_fields=['amount_toman', 'description'])
            PaymentEvent.objects.create(payment=p, actor=request.user, action='executive_edit',
                                        notes=(f'amount: {before_amount} -> {p.amount_toman}; '
                                               f'description: {before_description[:45]} -> {description[:45]}')[:250])
    if request.POST.get('return_to') == 'detail':
        return redirect('payments_detail', pk=p.pk)
    return redirect('payments_workspace')


@login_required
@require_POST
def executive_delete_unpaid(request, pk):
    """Remove an unpaid request from every operational surface."""
    if not request.user.is_active or not executive(request.user):
        raise PermissionDenied()
    reason = request.POST.get('reason', '')
    deletion_reasons = dict(PaymentRequest.DELETION_REASONS)
    if reason not in deletion_reasons:
        return HttpResponseBadRequest('علت حذف درخواست را انتخاب کنید.')
    if request.POST.get('confirm_delete') != 'yes':
        return HttpResponseBadRequest('حذف این درخواست را تأیید کنید.')
    with transaction.atomic():
        # The same lock is used by payment, review, edit, and reassignment.
        # A stale page cannot revive a deleted request or delete a payment
        # that completed while the confirmation screen was open.
        payment = get_object_or_404(PaymentRequest.objects.select_for_update(), pk=pk)
        if payment.has_payment_evidence:
            return HttpResponseBadRequest('درخواست پرداخت‌شده یا دارای سابقه پرداخت قابل حذف نیست.')
        payment.deleted_at = timezone.now()
        payment.deleted_by = request.user
        payment.deletion_reason = reason
        payment.save(update_fields=['deleted_at', 'deleted_by', 'deletion_reason'])
        PaymentEvent.objects.create(
            payment=payment, actor=request.user, action='executive_delete',
            notes=deletion_reasons[reason],
        )
    messages.success(request, 'درخواست از سوابق و تمام صف‌های تأیید و پرداخت حذف شد.')
    return_to = request.POST.get('return_to', '')
    destinations = {'admin': 'payments_admin', 'expenses': 'payments_expenses'}
    if return_to in destinations:
        return redirect(destinations[return_to])
    return redirect(reverse('payments_workspace') + '#paymentHistory')


@login_required
@require_POST
def reassign_payment(request,pk):
    if not executive(request.user):
        raise PermissionDenied()
    with transaction.atomic():
        payment=get_object_or_404(PaymentRequest.objects.select_for_update(),pk=pk,state='approved')
        assignee=get_object_or_404(payment_approved_assignees(),pk=request.POST.get('assigned_to'))
        previous=payment.assigned_to_id
        payment.assigned_to=assignee
        payment.channel='staff'
        payment.save(update_fields=['assigned_to','channel'])
        PaymentEvent.objects.create(payment=payment,actor=request.user,action='reassigned',notes=f'{previous} → {assignee.pk}')
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
        if not executive(request.user) and not getattr(getattr(request.user,'profile',None),'can_execute_payments',False):
            raise PermissionDenied()
        reference=request.POST.get('reference','').strip()
        receipt=request.FILES.get('receipt')
        payment_method=(request.POST.get('payment_method') or '').strip()
        funding_source=(request.POST.get('funding_source') or '').strip()
        if payment_method and payment_method not in dict(PaymentRequest.PAYMENT_METHODS):
            return HttpResponseBadRequest('روش پرداخت نامعتبر است.')
        if funding_source and funding_source not in dict(PaymentRequest.FUNDING_SOURCES):
            return HttpResponseBadRequest('حساب مبدأ معتبر نیست.')
        # The owner must explicitly identify both how and from which account
        # the money was actually paid. SmartPay alone does not imply personal funds.
        if executive(request.user) and (not payment_method or not funding_source):
            return HttpResponseBadRequest('روش پرداخت و حساب مبدأ را انتخاب کنید.')
        if not reference or not receipt:
            return HttpResponseBadRequest('شماره پیگیری و رسید الزامی است.')
        if receipt.size>10*1024*1024 or receipt.content_type not in ('image/jpeg','image/png','image/webp','application/pdf'):
            return HttpResponseBadRequest('رسید نامعتبر است.')
        p.payment_reference=reference[:120]
        p.payment_method=payment_method
        p.funding_source=funding_source
        p.payment_receipt=receipt
        p.paid_at=timezone.now()
        p.state='paid'
        p.save()
        details=[
            dict(PaymentRequest.PAYMENT_METHODS).get(payment_method,'روش نامشخص'),
            dict(PaymentRequest.FUNDING_SOURCES).get(funding_source,'مبدأ نامشخص'),
            reference[:100],
        ]
        PaymentEvent.objects.create(
            payment=p,actor=request.user,action='paid',notes=' · '.join(details)[:250],
        )
    return redirect('payments_workspace')

@login_required
def admin_dashboard(request):
    if not executive(request.user):
        raise PermissionDenied()
    from django.contrib.auth.models import Permission
    requests=presentation_queryset(PaymentRequest.objects.all())
    consultants=User.objects.filter(is_active=True,profile__is_active=True,profile__role='consultant')
    accountants=User.objects.none()
    operators=payment_approved_assignees()
    executive_ids=list(User.objects.filter(
        is_active=True,username__in=settings.EXECUTIVE_USERNAMES,
    ).values_list('pk',flat=True))
    paid=requests.filter(state='paid')
    return render(request,'payments/admin.html',{'pending':[decorate_payment(p, True) for p in requests.filter(state='pending')],'active':[decorate_payment(p, True) for p in requests.filter(state='approved')],'paid':paid[:200],'consultants':consultants,'accountants':accountants,'operators':operators,'executive_ids':executive_ids,'staff_members':User.objects.filter(is_active=True,profile__is_active=True,profile__role='consultant').order_by('first_name','last_name'),'permission_profiles': __import__('core.models',fromlist=['EmployeeProfile']).EmployeeProfile.objects.filter(is_active=True,user__is_active=True).exclude(role__in=['referrer','scan_station']).filter(~Q(role='employee') | Q(branch__isnull=False) | (Q(employee_code__isnull=False) & ~Q(employee_code='')) | ~Q(job_title='')).select_related('user','branch').order_by('user__first_name','user__last_name'),})

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
def personal_expense_receipt(request,pk):
    p=get_object_or_404(PaymentRequest,pk=pk,kind='personal_expense')
    if not executive(request.user) and request.user.pk not in (p.requester_id,p.assigned_to_id):
        raise PermissionDenied()
    if not p.personal_expense_receipt:
        raise Http404()
    response=FileResponse(p.personal_expense_receipt.open('rb'),as_attachment=True)
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

    requests_page = Paginator(presentation_queryset(base_requests).order_by('-created_at', '-pk'), 50).get_page(request.GET.get('requests_page'))
    requests_page.object_list = [decorate_payment(p, True) for p in requests_page.object_list]
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
