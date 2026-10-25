from io import BytesIO
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from core.models import Branch, EmployeeProfile
from .models import PaymentRequest, PaymentEvent, PettyCashExpense

class PaymentWorkflowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.executive=User.objects.create_user(username=next(iter(settings.EXECUTIVE_USERNAMES)),password='test-password')
        cls.worker=User.objects.create_user(username='payments-worker',password='test-password',last_name='نادری')
        cls.other=User.objects.create_user(username='payments-other',password='test-password')
        branch=Branch.objects.create(name='Payment Test Branch')
        EmployeeProfile.objects.update_or_create(user=cls.worker,defaults={'branch':branch,'role':'consultant','is_active':True,'can_request_payments':True,'can_execute_payments':True,'can_manage_petty_cash':True})
        EmployeeProfile.objects.update_or_create(user=cls.other,defaults={'branch':branch,'role':'consultant','is_active':True,'can_request_payments':True,'can_execute_payments':True,'can_manage_petty_cash':True})
        cls.branch=branch

    def _request(self):
        return PaymentRequest.objects.create(kind='payment',amount_toman=3000000,
            description='Approved supplier payout',recipient_name='Supplier',
            recipient_card='1234567890123456',requester=self.worker,branch=self.branch)

    def test_non_executive_cannot_approve(self):
        p=self._request()
        self.client.force_login(self.worker)
        response=self.client.post(reverse('payments_review',args=[p.pk]),{
            'action':'approve','channel':'consultant','assigned_to':self.worker.pk})
        self.assertEqual(response.status_code,403)
        p.refresh_from_db()
        self.assertEqual(p.state,'pending')

    def test_approved_payment_is_assigned_to_one_queue(self):
        p=self._request()
        self.client.force_login(self.executive)
        result=self.client.post(reverse('payments_review',args=[p.pk]),{
            'action':'approve','channel':'consultant','assigned_to':self.worker.pk})
        self.assertEqual(result.status_code,302)
        p.refresh_from_db()
        self.assertEqual(p.state,'approved')
        self.assertEqual(p.assigned_to,self.worker)
        self.assertEqual(PaymentEvent.objects.filter(payment=p,action='approve').count(),1)

    def test_other_consultant_cannot_mark_paid(self):
        p=self._request()
        p.state='approved';p.channel='consultant';p.assigned_to=self.worker;p.save()
        self.client.force_login(self.other)
        r=self.client.post(reverse('payments_complete',args=[p.pk]),{
            'reference':'ABC','receipt':SimpleUploadedFile('proof.pdf',b'%PDF-1.4\nabc',content_type='application/pdf')})
        self.assertEqual(r.status_code,404)
        p.refresh_from_db()
        self.assertEqual(p.state,'approved')

    def test_payment_vanishes_from_queue_after_receipt(self):
        p=self._request()
        p.state='approved';p.channel='consultant';p.assigned_to=self.worker;p.save()
        self.client.force_login(self.worker)
        r=self.client.post(reverse('payments_complete',args=[p.pk]),{
            'reference':'BANK-0001','receipt':SimpleUploadedFile('proof.pdf',b'%PDF-1.4\nabc',content_type='application/pdf')})
        self.assertEqual(r.status_code,302)
        p.refresh_from_db()
        self.assertEqual(p.state,'paid')
        self.assertFalse(PaymentRequest.objects.filter(pk=p.pk,state='approved',assigned_to=self.worker).exists())
        self.assertTrue(PaymentRequest.objects.filter(pk=p.pk,state='paid').exists())

    def test_cannot_complete_twice(self):
        p=self._request()
        p.state='paid';p.channel='consultant';p.assigned_to=self.worker;p.save()
        self.client.force_login(self.worker)
        r=self.client.post(reverse('payments_complete',args=[p.pk]),{
            'reference':'DUPLICATE','receipt':SimpleUploadedFile('proof.pdf',b'%PDF-1.4\nabc',content_type='application/pdf')})
        self.assertEqual(r.status_code,400)
        self.assertEqual(PaymentEvent.objects.filter(payment=p,action='paid').count(),0)

    def test_other_staff_role_cannot_open_payment_workspace(self):
        self.other.profile.role='receptionist'
        self.other.profile.can_request_payments=False
        self.other.profile.can_execute_payments=False
        self.other.profile.can_manage_petty_cash=False
        self.other.profile.save(update_fields=['role','can_request_payments','can_execute_payments','can_manage_petty_cash'])
        self.client.force_login(self.other)
        response=self.client.get(reverse('payments_workspace'))
        self.assertEqual(response.status_code,403)

    def test_consultant_can_open_payment_workspace(self):
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse('payments_workspace')).status_code,200)

    def test_accountant_channel_disabled_during_pilot(self):
        p=self._request()
        self.client.force_login(self.executive)
        r=self.client.post(reverse('payments_review',args=[p.pk]),{
            'action':'approve','channel':'accountant','assigned_to':self.worker.pk})
        self.assertEqual(r.status_code,400)
        p.refresh_from_db()
        self.assertEqual(p.state,'pending')

    def test_expense_ledger_is_executive_only(self):
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse('payments_expenses')).status_code, 403)
        self.client.force_login(self.executive)
        self.assertEqual(self.client.get(reverse('payments_expenses')).status_code, 200)

    def test_personal_legal_request_is_classified(self):
        self.client.force_login(self.executive)
        result = self.client.post(reverse('payments_workspace'), {
            'operation': 'request',
            'req-kind': 'payment',
            'req-amount_toman': 12000000,
            'req-description': 'حق الزحمه وکیل برای پرونده شخصی',
            'req-category': 'legal',
            'req-cost_owner': 'personal',
            'req-cost_center': 'پرونده شخصی',
            'req-recipient_name': 'وکیل',
            'req-recipient_card': '1234567890123456',
        })
        self.assertEqual(result.status_code, 302)
        obj = PaymentRequest.objects.get(requester=self.executive)
        self.assertEqual(obj.category, 'legal')
        self.assertEqual(obj.cost_owner, 'personal')
        self.assertEqual(obj.state, 'pending')

    def test_petty_funding_not_double_counted_as_expense(self):
        PaymentRequest.objects.create(
            kind='payment',amount_toman=10000000,description='Office expense',
            requester=self.worker,branch=self.branch,state='paid',
            category='supplies',cost_owner='company')
        PaymentRequest.objects.create(
            kind='petty_cash',amount_toman=5000000,description='Petty cash funding',
            requester=self.worker,beneficiary=self.worker,branch=self.branch,
            state='paid',cost_owner='company')
        PettyCashExpense.objects.create(
            holder=self.worker,created_by=self.worker,amount_toman=2000000,
            description='Actual petty purchase',category='supplies',
            cost_owner='company',receipt='petty_expenses/test-proof.pdf')
        self.client.force_login(self.executive)
        resp=self.client.get(reverse('payments_expenses'))
        self.assertEqual(resp.status_code,200)
        self.assertEqual(resp.context['summary']['paid_transfers'],15000000)
        self.assertEqual(resp.context['summary']['paid_costs'],12000000)
        self.assertEqual(resp.context['summary']['petty_spent'],2000000)

    def test_ledger_can_filter_by_ownership(self):
        personal=PaymentRequest.objects.create(
            kind='payment',amount_toman=3000000,description='Legal personal',
            category='legal',cost_owner='personal',requester=self.worker)
        company=PaymentRequest.objects.create(
            kind='payment',amount_toman=5000000,description='Company supplies',
            category='supplies',cost_owner='company',requester=self.worker)
        self.client.force_login(self.executive)
        result=self.client.get(reverse('payments_expenses')+'?owner=personal')
        self.assertEqual(result.status_code,200)
        self.assertContains(result,'Legal personal')
        self.assertNotContains(result,'Company supplies')

    def test_invalid_date_filters_do_not_crash(self):
        self.client.force_login(self.executive)
        result=self.client.get(reverse('payments_expenses')+'?from=2026-02-31')
        self.assertEqual(result.status_code,200)

    def test_other_user_cannot_read_petty_receipt(self):
        item=PettyCashExpense.objects.create(
            holder=self.worker,created_by=self.worker,amount_toman=100000,
            description='Sample expense',receipt='petty_expenses/private.pdf')
        self.client.force_login(self.other)
        result=self.client.get(reverse('payments_petty_receipt',args=[item.pk]))
        self.assertEqual(result.status_code,403)

    def test_named_staff_can_only_complete_own_assigned_payment(self):
        self.other.last_name='مرادی'
        self.other.save(update_fields=['last_name'])
        self.other.profile.role='quality_control'
        self.other.profile.can_request_payments=False
        self.other.profile.can_manage_petty_cash=False
        self.other.profile.save(update_fields=['role','can_request_payments','can_manage_petty_cash'])
        p=self._request()
        self.client.force_login(self.executive)
        approved=self.client.post(reverse('payments_review',args=[p.pk]),{
            'action':'approve','channel':'staff','assigned_to':self.other.pk})
        self.assertEqual(approved.status_code,302)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('payments_workspace')).status_code,200)
        denied=self.client.post(reverse('payments_workspace'),{
            'operation':'request','req-kind':'payment','req-amount_toman':'1000000',
            'req-description':'Should be disallowed'})
        self.assertEqual(denied.status_code,403)
        self.assertEqual(PaymentRequest.objects.filter(requester=self.other).count(),0)
        other_request=self._request()
        other_request.state='approved'
        other_request.assigned_to=self.worker
        other_request.channel='staff'
        other_request.save()
        forbidden=self.client.post(reverse('payments_complete',args=[other_request.pk]),{
            'reference':'NO','receipt':SimpleUploadedFile('other.pdf',b'%PDF-1.4 test',content_type='application/pdf')})
        self.assertEqual(forbidden.status_code,404)

    def test_paid_only_delegate_keeps_private_history_access(self):
        payment=PaymentRequest.objects.create(
            kind='payment',amount_toman=3000000,description='Completed task',
            requester=self.executive,assigned_to=self.other,
            state='paid',channel='staff',payment_reference='OK-33')
        self.client.force_login(self.other)
        response=self.client.get(reverse('payments_workspace'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Completed task')
        self.assertEqual(list(response.context['queue']),[])
        self.assertEqual(response.context['completed'][0].pk,payment.pk)

    def test_delegate_cannot_see_another_persons_paid_history(self):
        PaymentRequest.objects.create(
            kind='payment',amount_toman=3000000,description='Private completed payment',
            requester=self.executive,assigned_to=self.worker,
            state='paid',channel='staff',payment_reference='PRIVATE')
        PaymentRequest.objects.create(
            kind='payment',amount_toman=2000000,description='Own completed payment',
            requester=self.executive,assigned_to=self.other,
            state='paid',channel='staff',payment_reference='PUBLIC')
        self.client.force_login(self.other)
        response=self.client.get(reverse('payments_workspace'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Own completed payment')
        self.assertNotContains(response,'Private completed payment')

    def test_executive_quick_instruction_directly_assigns_approved_payment(self):
        self.client.force_login(self.executive)
        self.worker.first_name='خانم'
        self.worker.last_name='مرادی'
        self.worker.save()
        res=self.client.post(reverse('payments_executive_quick'),{
            'amount_million':'32',
            'priority':'urgent',
            'description':'Device maintenance',
            'assigned_to':self.worker.pk,
            'recipient_name':'Example Recipient',
            'recipient_iban':'IR123456789012345678901234',
        })
        self.assertEqual(res.status_code,302)
        order=PaymentRequest.objects.get(description='Device maintenance')
        self.assertEqual(order.amount_toman,32000000)
        self.assertEqual(order.state,'approved')
        self.assertEqual(order.priority,'urgent')
        self.assertEqual(order.assigned_to,self.worker)
        self.assertEqual(order.approved_by,self.executive)

    def test_nonexecutive_cannot_create_direct_payment(self):
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse('payments_executive_quick')).status_code,403)

    def test_only_five_named_active_staff_can_receive_direct_orders(self):
        from .views import ExecutiveQuickPaymentForm
        self.worker.first_name='خانم'
        self.worker.last_name='مرادی'
        self.worker.save()
        form=ExecutiveQuickPaymentForm()
        self.assertEqual(list(form.fields['assigned_to'].queryset.values_list('pk',flat=True)),[self.worker.pk])
        self.assertFalse(form.fields['assigned_to'].queryset.filter(pk=self.other.pk).exists())

    def test_selected_employee_can_request_after_executive_grant(self):
        from django.urls import reverse
        self.other.profile.role='employee'
        self.other.profile.employee_code='EMP-PAY-TEST'
        self.other.profile.can_request_payments=False
        self.other.profile.can_manage_petty_cash=False
        self.other.profile.can_execute_payments=False
        self.other.profile.save(update_fields=['role','employee_code','can_request_payments','can_manage_petty_cash','can_execute_payments'])
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('payments_workspace')).status_code,403)
        self.client.force_login(self.executive)
        response=self.client.post(reverse('payments_request_permissions'),{'profile_id':self.other.profile.pk,'enabled':'1'})
        self.assertEqual(response.status_code,302)
        self.other.profile.refresh_from_db()
        self.assertTrue(self.other.profile.can_request_payments)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('payments_workspace')).status_code,200)

    def test_worker_cannot_grant_payment_request_permission(self):
        from django.urls import reverse
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse('payments_request_permissions')).status_code,403)
        self.assertEqual(self.client.post(reverse('payments_request_permissions'),{'profile_id':self.other.profile.pk,'enabled':'1'}).status_code,403)

    def test_worker_submits_million_toman_ui_amount(self):
        self.client.force_login(self.worker)
        response=self.client.post(reverse('payments_workspace'),{
            'operation':'request','req-kind':'payment','req-amount_million':'32.5',
            'req-description':'خرید ملزومات ضروری برای شعبه',
            'req-category':'supplies','req-cost_owner':'company',
            'req-recipient_name':'Supplier','req-recipient_card':'1234567890123456',
        })
        self.assertEqual(response.status_code,302)
        req=PaymentRequest.objects.filter(requester=self.worker).latest('pk')
        self.assertEqual(req.amount_toman,32500000)
        self.assertEqual(req.state,'pending')

    def test_malformed_million_amount_is_rejected(self):
        self.client.force_login(self.worker)
        response=self.client.post(reverse('payments_workspace'),{
            'operation':'request','req-kind':'payment','req-amount_million':'abc',
            'req-description':'خرید ملزومات ضروری برای شعبه',
            'req-category':'supplies','req-cost_owner':'company',
            'req-recipient_card':'1234567890123456',
        })
        self.assertEqual(response.status_code,200)
        self.assertFalse(PaymentRequest.objects.filter(requester=self.worker).exists())

    def test_staff_payment_requires_recipient_name(self):
        self.client.force_login(self.worker)
        response=self.client.post(reverse('payments_workspace'),{
            'operation':'request','req-kind':'payment','req-amount_million':'3',
            'req-description':'خرید ملزومات ضروری برای شعبه',
            'req-category':'supplies','req-cost_owner':'company',
            'req-recipient_card':'1234567890123456',
        })
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'نام دریافت‌کننده برای درخواست پرداخت الزامی است')
        self.assertFalse(PaymentRequest.objects.filter(requester=self.worker).exists())

    def test_petty_cash_request_does_not_require_recipient_bank_details(self):
        self.client.force_login(self.worker)
        response=self.client.post(reverse('payments_workspace'),{
            'operation':'request','req-kind':'petty_cash','req-amount_million':'4',
            'req-description':'درخواست تنخواه برای تهیه اقلام مصرفی شعبه',
            'req-category':'supplies','req-cost_owner':'company',
        })
        self.assertEqual(response.status_code,302)
        req=PaymentRequest.objects.filter(requester=self.worker).latest('pk')
        self.assertEqual(req.kind,'petty_cash')
        self.assertEqual(req.amount_toman,4000000)
        self.assertEqual(req.state,'pending')

    def test_invalid_request_keeps_million_amount_and_shows_errors(self):
        self.client.force_login(self.worker)
        response=self.client.post(reverse('payments_workspace'),{
            'operation':'request','req-kind':'payment','req-amount_million':'5.5',
            'req-description':'خرید ملزومات ضروری شعبه با هماهنگی مدیر',
            'req-category':'supplies','req-cost_owner':'company',
        })
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'درخواست ثبت نشد')
        self.assertContains(response,'value="5.5"')
        self.assertFalse(PaymentRequest.objects.filter(requester=self.worker).exists())

    def test_recipient_details_prefilled_from_own_previous_request(self):
        PaymentRequest.objects.create(kind='payment',amount_toman=2500000,
            description='Prior vendor payment',requester=self.worker,branch=self.branch,
            recipient_name='Previous Vendor',recipient_card='1234567890123456')
        self.client.force_login(self.worker)
        response=self.client.get(reverse('payments_workspace'))
        self.assertContains(response,'Previous Vendor')
        self.assertContains(response,'1234567890123456')

    def test_reject_requires_reason_and_records_it(self):
        p=self._request()
        self.client.force_login(self.executive)
        bad=self.client.post(reverse('payments_review',args=[p.pk]),{'action':'reject'})
        self.assertEqual(bad.status_code,400)
        p.refresh_from_db()
        self.assertEqual(p.state,'pending')
        ok=self.client.post(reverse('payments_review',args=[p.pk]),{'action':'reject','reason':'مدرک پرداخت ناقص است'})
        self.assertEqual(ok.status_code,302)
        p.refresh_from_db()
        self.assertEqual(p.state,'rejected')
        self.assertEqual(p.events.filter(action='reject').latest('pk').notes,'مدرک پرداخت ناقص است')

    def test_needs_info_always_goes_to_original_requester(self):
        p=self._request()
        self.client.force_login(self.executive)
        res=self.client.post(reverse('payments_review',args=[p.pk]),{
            'action':'needs_info','question':'فاکتور خرید را ارسال کنید',
            'clarification_assignee':self.other.pk})
        self.assertEqual(res.status_code,302)
        p.refresh_from_db()
        self.assertEqual(p.state,'needs_info')
        self.assertEqual(p.clarification_assignee,self.worker)

    def test_cannot_assign_payment_to_nonapproved_worker(self):
        p=self._request()
        self.client.force_login(self.executive)
        res=self.client.post(reverse('payments_review',args=[p.pk]),{
            'action':'approve','channel':'staff','assigned_to':self.other.pk})
        self.assertEqual(res.status_code,404)
        p.refresh_from_db()
        self.assertEqual(p.state,'pending')

    def test_executive_can_toggle_each_financial_permission(self):
        self.client.force_login(self.executive)
        for permission in ('can_request_payments','can_execute_payments','can_manage_petty_cash','can_claim_personal_expense'):
            res=self.client.post(reverse('payments_request_permissions'),{
                'profile_id':self.other.profile.pk,'permission':permission,'enabled':'1'})
            self.assertEqual(res.status_code,302)
            self.other.profile.refresh_from_db()
            self.assertTrue(getattr(self.other.profile,permission))
            off=self.client.post(reverse('payments_request_permissions'),{
                'profile_id':self.other.profile.pk,'permission':permission,'enabled':'0'})
            self.assertEqual(off.status_code,302)
            self.other.profile.refresh_from_db()
            self.assertFalse(getattr(self.other.profile,permission))

    def test_personal_expense_claim_requires_permission_and_receipt(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.other.profile.can_claim_personal_expense=False
        self.other.profile.save(update_fields=['can_claim_personal_expense'])
        data={'operation':'personal_expense','personal-amount_million':'12',
              'personal-description':'خرید ملزومات با حساب شخصی برای مرکز',
              'personal-category':'supplies'}
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('payments_workspace'),data).status_code,403)
        self.other.profile.can_claim_personal_expense=True
        self.other.profile.save(update_fields=['can_claim_personal_expense'])
        no_receipt=self.client.post(reverse('payments_workspace'),data)
        self.assertEqual(no_receipt.status_code,200)
        self.assertFalse(PaymentRequest.objects.filter(requester=self.other,kind='personal_expense').exists())
        data['personal-receipt']=SimpleUploadedFile('purchase.pdf',b'%PDF-1.4 test',content_type='application/pdf')
        ok=self.client.post(reverse('payments_workspace'),data)
        self.assertEqual(ok.status_code,302)
        claim=PaymentRequest.objects.get(requester=self.other,kind='personal_expense')
        self.assertEqual(claim.amount_toman,12000000)
        self.assertEqual(claim.state,'pending')
        self.assertTrue(claim.personal_expense_receipt)

    def test_generic_request_cannot_bypass_personal_expense_permission(self):
        self.client.force_login(self.worker)
        self.worker.profile.can_claim_personal_expense=False
        self.worker.profile.save(update_fields=['can_claim_personal_expense'])
        response=self.client.post(reverse('payments_workspace'),{
            'operation':'request','req-kind':'personal_expense',
            'req-amount_million':'12','req-description':'خرید ملزومات از جیب خودم برای مرکز',
            'req-category':'supplies','req-cost_owner':'company'})
        self.assertEqual(response.status_code,400)
        self.assertFalse(PaymentRequest.objects.filter(kind='personal_expense',requester=self.worker).exists())

    def test_disabled_delegate_cannot_be_approved_or_see_quick_payment(self):
        p=self._request()
        self.worker.profile.can_execute_payments=False
        self.worker.profile.save(update_fields=['can_execute_payments'])
        self.client.force_login(self.executive)
        res=self.client.post(reverse('payments_review',args=[p.pk]),{
            'action':'approve','channel':'staff','assigned_to':self.worker.pk})
        self.assertEqual(res.status_code,404)
        p.refresh_from_db()
        self.assertEqual(p.state,'pending')

    def test_executive_can_reassign_outstanding_payment_to_enabled_delegate(self):
        p=self._request()
        p.state='approved'
        p.assigned_to=self.worker
        p.channel='staff'
        p.save(update_fields=['state','assigned_to','channel'])
        self.other.first_name='خانم'
        self.other.last_name='مرادی'
        self.other.save(update_fields=['first_name','last_name'])
        self.other.profile.can_execute_payments=True
        self.other.profile.save(update_fields=['can_execute_payments'])
        self.client.force_login(self.executive)
        result=self.client.post(reverse('payments_reassign',args=[p.pk]),{'assigned_to':self.other.pk})
        self.assertEqual(result.status_code,302)
        p.refresh_from_db()
        self.assertEqual(p.assigned_to_id,self.other.pk)
        self.assertEqual(p.state,'approved')
        self.assertTrue(p.events.filter(action='reassigned').exists())
        p.state='paid'
        p.save(update_fields=['state'])
        denied=self.client.post(reverse('payments_reassign',args=[p.pk]),{'assigned_to':self.worker.pk})
        self.assertEqual(denied.status_code,404)

    def test_approved_queue_has_prominent_payment_amount_and_count(self):
        p=self._request()
        p.state='approved'
        p.channel='staff'
        p.assigned_to=self.worker
        p.save(update_fields=['state','channel','assigned_to'])
        self.client.force_login(self.worker)
        response=self.client.get(reverse('payments_workspace'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'دستورهای پرداخت من')
        self.assertContains(response,'payment-inbox-count')
        self.assertContains(response,'payment-amount')

    def test_payment_indicator_counts_only_own_open_assignments(self):
        from django.template import Context, Template
        p=self._request()
        p.state='approved'
        p.channel='staff'
        p.assigned_to=self.worker
        p.save(update_fields=['state','channel','assigned_to'])
        self.worker.profile.can_execute_payments=True
        self.worker.profile.save(update_fields=['can_execute_payments'])
        result=Template('{% load finance_alerts %}{% open_payment_count employee %}').render(Context({'employee':self.worker}))
        self.assertEqual(result,'1')
        p.state='paid'
        p.save(update_fields=['state'])
        result=Template('{% load finance_alerts %}{% open_payment_count employee %}').render(Context({'employee':self.worker}))
        self.assertEqual(result,'0')

    def test_staff_home_shows_pending_payment_alert_only_while_unpaid(self):
        payment=self._request()
        payment.state='approved'
        payment.channel='staff'
        payment.assigned_to=self.worker
        payment.save(update_fields=['state','channel','assigned_to'])
        self.worker.profile.can_execute_payments=True
        self.worker.profile.save(update_fields=['can_execute_payments'])
        self.client.force_login(self.worker)
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'gl-home-payment-alert')
        self.assertContains(response,'دستور پرداخت نیازمند اقدام شماست')
        payment.state='paid'
        payment.save(update_fields=['state'])
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'gl-home-payment-alert" href')
