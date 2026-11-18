from io import BytesIO
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
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

    def test_owner_is_sixth_named_assignee_without_staff_permission(self):
        from .views import six_payment_assignees, five_payment_assignees
        self.client.force_login(self.executive)
        staff_members=five_payment_assignees()
        slots=six_payment_assignees(self.executive)
        self.assertEqual(len(slots),len(staff_members)+1)
        self.assertEqual(slots[-1][0],'executive')
        self.assertEqual(slots[-1][1],'دکتر جواهریان')
        self.assertEqual(slots[-1][2].pk,self.executive.pk)
        form_page=self.client.get(reverse('payments_executive_quick'))
        self.assertEqual(form_page.status_code,200)
        self.assertContains(form_page,'دکتر جواهریان')
        self.assertContains(form_page,'person--executive')
        self.assertContains(form_page,f'value="{self.executive.pk}"')
        self.assertFalse(self.executive.has_perm('payments.execute_official_payment'))

    def test_owner_direct_order_can_be_paid_using_smartpay_from_personal_account(self):
        self.client.force_login(self.executive)
        response=self.client.post(reverse('payments_executive_quick'),{
            'amount_million':'35',
            'priority':'normal',
            'description':'خرید قطعات گرین لایف',
            'assigned_to':self.executive.pk,
            'recipient_name':'تأمین‌کننده',
            'recipient_card':'6037991234567890',
        })
        self.assertEqual(response.status_code,302)
        self.assertIn('#assignedPayments',response.url)
        order=PaymentRequest.objects.get(description='خرید قطعات گرین لایف')
        self.assertEqual(order.amount_toman,35000000)
        self.assertEqual(order.state,'approved')
        self.assertEqual(order.assigned_to_id,self.executive.pk)
        self.assertEqual(order.approved_by_id,self.executive.pk)
        queue=self.client.get(reverse('payments_workspace'))
        self.assertContains(queue,'SmartPay')
        self.assertContains(queue,'حساب شخصی مدیر')
        paid=self.client.post(reverse('payments_complete',args=[order.pk]),{
            'payment_method':'smartpay',
            'funding_source':'personal',
            'reference':'SMARTPAY-TEST-001',
            'receipt':SimpleUploadedFile('proof.pdf',b'%PDF-1.4\\nproof',content_type='application/pdf'),
        })
        self.assertEqual(paid.status_code,302)
        order.refresh_from_db()
        self.assertEqual(order.state,'paid')
        self.assertEqual(order.payment_method,'smartpay')
        self.assertEqual(order.funding_source,'personal')
        self.assertEqual(order.payment_reference,'SMARTPAY-TEST-001')
        self.assertTrue(order.payment_receipt)
        self.assertEqual(PaymentEvent.objects.filter(payment=order,action='paid',actor=self.executive).count(),1)
        self.assertIn('SmartPay',PaymentEvent.objects.get(payment=order,action='paid').notes)
        self.assertEqual(PaymentRequest.objects.filter(pk=order.pk).count(),1)
        history=self.client.get(reverse('payments_workspace'))
        self.assertContains(history,'SMARTPAY-TEST-001')
        self.assertContains(history,'SmartPay')
        self.assertEqual(self.client.post(reverse('payments_complete',args=[order.pk]),{
            'payment_method':'smartpay','funding_source':'company','reference':'DUP',
            'receipt':SimpleUploadedFile('proof.pdf',b'%PDF-1.4\\nproof',content_type='application/pdf'),
        }).status_code,400)
        self.assertEqual(PaymentEvent.objects.filter(payment=order,action='paid').count(),1)

    def test_owner_cannot_mark_paid_without_method_funding_account_or_receipt(self):
        order=self._request()
        order.state='approved'
        order.channel='staff'
        order.assigned_to=self.executive
        order.save(update_fields=['state','channel','assigned_to'])
        self.client.force_login(self.executive)
        url=reverse('payments_complete',args=[order.pk])
        for method,funding in (('', 'company'),('smartpay',''),('invalid','company'),('smartpay','invalid')):
            response=self.client.post(url,{
                'reference':'PENDING-TEST',
                'payment_method':method,'funding_source':funding,
                'receipt':SimpleUploadedFile('proof.pdf',b'%PDF-1.4\\nproof',content_type='application/pdf'),
            })
            self.assertEqual(response.status_code,400)
        order.refresh_from_db()
        self.assertEqual(order.state,'approved')
        self.assertEqual(order.payment_method,'')
        self.assertFalse(PaymentEvent.objects.filter(payment=order,action='paid').exists())

    def test_pending_request_can_be_approved_for_executive_self(self):
        order=self._request()
        self.client.force_login(self.executive)
        result=self.client.post(reverse('payments_review',args=[order.pk]),{
            'action':'approve','channel':'staff','assigned_to':self.executive.pk,
        })
        self.assertEqual(result.status_code,302)
        order.refresh_from_db()
        self.assertEqual(order.state,'approved')
        self.assertEqual(order.assigned_to_id,self.executive.pk)
        admin_page=self.client.get(reverse('payments_admin'))
        self.assertContains(admin_page,'دکتر جواهریان')

    def test_unauthorized_user_cannot_complete_executive_order(self):
        order=self._request()
        order.state='approved'
        order.channel='staff'
        order.assigned_to=self.executive
        order.save(update_fields=['state','channel','assigned_to'])
        self.client.force_login(self.worker)
        response=self.client.post(reverse('payments_complete',args=[order.pk]),{
            'payment_method':'smartpay','funding_source':'personal','reference':'SPOOF',
            'receipt':SimpleUploadedFile('proof.pdf',b'%PDF-1.4\\nproof',content_type='application/pdf'),
        })
        self.assertEqual(response.status_code,404)
        order.refresh_from_db()
        self.assertEqual(order.state,'approved')

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

    def test_employee_home_alert_appears_and_clears_when_paid(self):
        payment=self._request()
        payment.state='approved'
        payment.channel='staff'
        payment.assigned_to=self.worker
        payment.save(update_fields=['state','channel','assigned_to'])
        self.worker.profile.role='employee'
        self.worker.profile.can_execute_payments=True
        self.worker.profile.save(update_fields=['role','can_execute_payments'])
        self.client.force_login(self.worker)
        response=self.client.get('/',HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 14) Mobile')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'gl-home-payment-alert')
        self.assertContains(response,'دستور پرداخت نیازمند اقدام شماست')
        payment.state='paid'
        payment.save(update_fields=['state'])
        response=self.client.get('/',HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 14) Mobile')
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'class="gl-home-payment-alert"')

    def test_executive_can_edit_approved_unpaid_amount(self):
        p=self._request()
        p.state='approved'; p.assigned_to=self.worker; p.channel='staff'; p.save()
        self.client.force_login(self.executive)
        r=self.client.post(reverse('payments_executive_change',args=[p.pk]),
                           {'action':'edit','amount_million':'12','description':'Updated training fee'})
        self.assertEqual(r.status_code,302)
        p.refresh_from_db()
        self.assertEqual(p.amount_toman,12000000)
        self.assertEqual(p.state,'approved')
        self.assertEqual(p.assigned_to,self.worker)
        self.assertTrue(PaymentEvent.objects.filter(payment=p,action='executive_edit').exists())

    def test_executive_can_cancel_duplicate_without_deleting_history(self):
        p=self._request()
        p.state='approved';p.assigned_to=self.worker;p.channel='staff';p.save()
        self.client.force_login(self.executive)
        r=self.client.post(reverse('payments_executive_change',args=[p.pk]),
                           {'action':'cancel','reason':'Duplicate entry'})
        self.assertEqual(r.status_code,302)
        p.refresh_from_db()
        self.assertEqual(p.state,'rejected')
        self.assertIsNone(p.assigned_to)
        self.assertTrue(PaymentEvent.objects.filter(payment=p,action='executive_cancel').exists())

    def test_staff_cannot_change_payment(self):
        p=self._request()
        self.client.force_login(self.worker)
        r=self.client.post(reverse('payments_executive_change',args=[p.pk]),
                           {'action':'edit','amount_million':'12','description':'Unauthorized'})
        self.assertEqual(r.status_code,403)
        p.refresh_from_db()
        self.assertEqual(p.amount_toman,3000000)

    def test_paid_payment_cannot_be_edited_or_cancelled(self):
        p=self._request()
        p.state='paid';p.payment_reference='BANK123';p.save()
        self.client.force_login(self.executive)
        for action in ('edit','cancel'):
            r=self.client.post(reverse('payments_executive_change',args=[p.pk]),
                               {'action':action,'amount_million':'12','description':'Change',
                                'reason':'Duplicate entry'})
            self.assertEqual(r.status_code,400)
        p.refresh_from_db()
        self.assertEqual(p.amount_toman,3000000)
        self.assertEqual(p.state,'paid')

    def test_invalid_amount_does_not_change_approved_payment(self):
        p=self._request()
        p.state='approved';p.save()
        self.client.force_login(self.executive)
        r=self.client.post(reverse('payments_executive_change',args=[p.pk]),
                           {'action':'edit','amount_million':'-1','description':'Bad value'})
        self.assertEqual(r.status_code,400)
        p.refresh_from_db()
        self.assertEqual(p.amount_toman,3000000)


class SavedPaymentRecipientTests(TestCase):
    def setUp(self):
        self.executive=User.objects.create_user(username=next(iter(settings.EXECUTIVE_USERNAMES)),password='pw')
        self.other=User.objects.create_user(username='other-recipient-user',password='pw')

    def test_executive_can_save_and_find_recipient(self):
        from .models import SavedPaymentRecipient
        self.client.force_login(self.executive)
        response=self.client.post(reverse('payments_executive_recipient_save'),{'name':'سنا','iban':'IR123456789012345678901234','card':''})
        self.assertEqual(response.status_code,302)
        self.assertTrue(SavedPaymentRecipient.objects.filter(owner=self.executive,name='سنا').exists())
        page=self.client.get(reverse('payments_executive_quick'))
        self.assertContains(page,'سنا')

    def test_other_user_cannot_save_or_read_executive_book(self):
        from .models import SavedPaymentRecipient
        SavedPaymentRecipient.objects.create(owner=self.executive,name='Private',card='1234567890123456')
        self.client.force_login(self.other)
        self.assertEqual(self.client.post(reverse('payments_executive_recipient_save'),{'name':'Test','card':'1234567890123456'}).status_code,403)
        self.assertEqual(self.client.get(reverse('payments_executive_quick')).status_code,403)

    def test_invalid_bank_details_not_saved(self):
        from .models import SavedPaymentRecipient
        self.client.force_login(self.executive)
        response=self.client.post(reverse('payments_executive_recipient_save'),{'name':'سنا','iban':'IR123'})
        self.assertEqual(response.status_code,400)
        self.assertEqual(SavedPaymentRecipient.objects.count(),0)


class PaymentHistoryTests(TestCase):
    """History discovery must not widen receipt or financial-record access."""

    @classmethod
    def setUpTestData(cls):
        cls.executive = User.objects.create_user(
            username=next(iter(settings.EXECUTIVE_USERNAMES)),
            first_name='علی', last_name='جواهریان', password='history-test-password',
        )
        cls.requester = User.objects.create_user(
            username='history-requester', first_name='رضا', last_name='صادقی',
            password='history-test-password',
        )
        cls.operator = User.objects.create_user(
            username='history-operator', first_name='نادر', last_name='نادری',
            password='history-test-password',
        )
        cls.outsider = User.objects.create_user(
            username='history-outsider', password='history-test-password',
        )
        cls.branch = Branch.objects.create(name='History test branch')
        for user in (cls.requester, cls.operator, cls.outsider):
            EmployeeProfile.objects.update_or_create(user=user, defaults={
                'branch': cls.branch, 'role': 'consultant', 'is_active': True,
                'can_request_payments': True, 'can_execute_payments': True,
            })

    def setUp(self):
        media = TemporaryDirectory(prefix='greenlife-history-tests-')
        self.addCleanup(media.cleanup)
        media_settings = override_settings(MEDIA_ROOT=media.name)
        media_settings.enable()
        self.addCleanup(media_settings.disable)

    def payment(self, **overrides):
        fields = {
            'kind': 'payment', 'amount_toman': 3500000,
            'description': 'هزینه تجهیزات آزمایشی مرکز',
            'recipient_name': 'گیرنده آزمایشی',
            'requester': self.requester, 'branch': self.branch,
        }
        fields.update(overrides)
        return PaymentRequest.objects.create(**fields)

    def history(self, **query):
        response = self.client.get(reverse('payments_workspace'), query)
        self.assertEqual(response.status_code, 200)
        return response

    def history_ids(self, response):
        return [p.pk for p in response.context['history_page'].object_list]

    def image_receipt(self):
        from PIL import Image
        buffer = BytesIO()
        Image.new('RGB', (1200, 800), color='#186452').save(buffer, format='PNG')
        return SimpleUploadedFile('receipt.png', buffer.getvalue(), content_type='image/png')

    def test_executive_history_identifies_requester_separately_from_operator(self):
        team_payment = self.payment(state='approved', assigned_to=self.operator)
        own_payment = self.payment(requester=self.executive)
        self.client.force_login(self.executive)
        response = self.history()
        self.assertEqual(set(self.history_ids(response)), {team_payment.pk, own_payment.pk})
        record = next(p for p in response.context['history_page'] if p.pk == team_payment.pk)
        self.assertEqual(record.requester_name, 'رضا صادقی')
        self.assertEqual(record.assignee_name, 'نادر نادری')
        self.assertEqual(response.context['history_stats']['total'], 2)
        self.assertEqual(response.context['history_stats']['approved'], 1)

    def test_staff_queries_cannot_expand_history_or_requester_directory(self):
        own = self.payment(requester=self.operator)
        assigned = self.payment(state='approved', assigned_to=self.operator)
        hidden = self.payment(requester=self.outsider, description='Hidden financial request')
        self.client.force_login(self.operator)
        response = self.history(scope='all', requester=str(self.outsider.pk))
        self.assertEqual(set(self.history_ids(response)), {own.pk, assigned.pk})
        self.assertNotContains(response, hidden.description)
        self.assertEqual(response.context['history_stats']['total'], 2)
        self.assertFalse(response.context['history_requesters'])
        self.assertEqual(response.context['history_filters']['requester'], '')

    def test_mine_and_assigned_scopes_have_distinct_meanings(self):
        own = self.payment(requester=self.executive, assigned_to=self.operator)
        assigned = self.payment(state='approved', assigned_to=self.executive)
        self.payment()
        self.client.force_login(self.executive)
        self.assertEqual(self.history_ids(self.history(scope='mine')), [own.pk])
        self.assertEqual(self.history_ids(self.history(scope='assigned')), [assigned.pk])

    def test_pagination_includes_older_records_and_filters_before_slicing(self):
        oldest = self.payment(description='Unique older archived request', state='paid')
        for index in range(27):
            self.payment(description=f'Recent request {index}')
        self.client.force_login(self.executive)
        first = self.history()
        second = self.history(page=2)
        self.assertEqual(first.context['history_page'].paginator.count, 28)
        self.assertEqual(len(self.history_ids(first)), 25)
        self.assertEqual(len(self.history_ids(second)), 3)
        self.assertNotIn(oldest.pk, self.history_ids(first))
        self.assertIn(oldest.pk, self.history_ids(second))
        self.assertFalse(set(self.history_ids(first)) & set(self.history_ids(second)))
        self.assertEqual(self.history_ids(self.history(status='paid')), [oldest.pk])
        self.assertEqual(self.history_ids(self.history(q='Unique older archived')), [oldest.pk])

    def test_search_finds_requester_recipient_reference_and_persian_request_id(self):
        payment = self.payment(
            recipient_name='فروشنده آزمایشی ویژه', payment_reference='HISTORY-REF-445',
        )
        self.payment(requester=self.outsider, recipient_name='Someone else')
        self.client.force_login(self.executive)
        persian_id = str(payment.pk).translate(str.maketrans('0123456789', '۰۱۲۳۴۵۶۷۸۹'))
        for query in ('رضا صادقی', 'فروشنده آزمایشی ویژه', 'HISTORY-REF-445', persian_id):
            with self.subTest(query=query):
                self.assertEqual(self.history_ids(self.history(q=query)), [payment.pk])

    def test_filters_compose_and_pagination_query_preserves_the_selection(self):
        target = self.payment(state='paid', description='Target transfer',
                              payment_receipt='payment_receipts/target.png')
        self.payment(state='approved', description='Target transfer')
        self.payment(requester=self.outsider, state='paid', description='Target transfer',
                     payment_receipt='payment_receipts/other.png')
        self.client.force_login(self.executive)
        response = self.history(q='Target', status='paid', scope='all',
                                requester=str(self.requester.pk), receipt='yes', page=1)
        self.assertEqual(self.history_ids(response), [target.pk])
        query = parse_qs(response.context['history_query'])
        self.assertNotIn('page', query)
        for name, value in (('q', 'Target'), ('status', 'paid'),
                            ('requester', str(self.requester.pk)), ('receipt', 'yes')):
            self.assertEqual(query[name], [value])

    def test_original_expense_invoice_does_not_count_as_payment_receipt(self):
        claim = self.payment(kind='personal_expense', personal_expense_receipt='claims/invoice.pdf')
        paid = self.payment(state='paid', payment_receipt='payment_receipts/settled.pdf')
        self.client.force_login(self.executive)
        self.assertEqual(self.history_ids(self.history(receipt='yes')), [paid.pk])
        response = self.history(receipt='no')
        self.assertEqual(self.history_ids(response), [claim.pk])
        record = response.context['history_page'][0]
        self.assertEqual(record.receipt_kind, 'none')
        self.assertEqual(record.personal_receipt_kind, 'pdf')

    def test_invalid_filters_and_page_do_not_error_or_hide_the_default_history(self):
        payment = self.payment()
        self.client.force_login(self.executive)
        response = self.history(status='unknown', scope='foreign', requester='not-an-id',
                                receipt='unsafe', page='not-a-page')
        self.assertEqual(self.history_ids(response), [payment.pk])
        self.assertEqual(response.context['history_filters']['status'], '')
        self.assertEqual(response.context['history_filters']['scope'], 'all')
        self.assertEqual(response.context['history_filters']['receipt'], '')

    def test_full_detail_and_panel_use_the_same_record_permissions(self):
        payment = self.payment(state='approved', assigned_to=self.operator)
        detail_url = reverse('payments_detail', args=[payment.pk])
        for user in (self.executive, self.requester, self.operator):
            self.client.force_login(user)
            for query in ({}, {'panel': '1'}):
                with self.subTest(user=user.username, query=query):
                    response = self.client.get(detail_url, query)
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.context['payment'].pk, payment.pk)
        self.client.force_login(self.outsider)
        for query in ({}, {'panel': '1'}):
            self.assertEqual(self.client.get(detail_url, query).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(detail_url).status_code, 302)

    def test_timeline_reports_only_recorded_events_with_actor_and_order(self):
        from .models import PaymentClarification
        payment = self.payment(state='approved', assigned_to=self.operator)
        created = PaymentEvent.objects.create(payment=payment, actor=self.requester, action='created')
        approved = PaymentEvent.objects.create(payment=payment, actor=self.executive,
                                               action='approve', notes='Approved after review')
        note = PaymentClarification.objects.create(payment=payment, author=self.requester,
                                                   message='Original explanatory note')
        self.client.force_login(self.executive)
        response = self.client.get(reverse('payments_detail', args=[payment.pk]))
        self.assertEqual(response.status_code, 200)
        timeline = list(response.context['timeline'])
        self.assertEqual([event.pk for event in timeline], [created.pk, approved.pk])
        self.assertEqual([event.actor_id for event in timeline], [self.requester.pk, self.executive.pk])
        self.assertTrue(all(event.action_label and event.action_label != event.action for event in timeline))
        self.assertEqual(timeline[1].notes, approved.notes)
        self.assertEqual(list(response.context['clarification_messages']), [note])
        self.assertEqual(payment.events.count(), 2)

    def test_cancelled_detail_preserves_audit_and_edit_returns_to_the_detail(self):
        payment = self.payment(state='approved', assigned_to=self.operator, channel='staff')
        self.client.force_login(self.executive)
        detail_url = reverse('payments_detail', args=[payment.pk])
        result = self.client.post(reverse('payments_executive_change', args=[payment.pk]), {
            'action': 'cancel', 'reason': 'Duplicate test request', 'return_to': 'detail',
        })
        self.assertRedirects(result, detail_url)
        payment.refresh_from_db()
        self.assertEqual(payment.state, 'rejected')
        response = self.client.get(detail_url)
        self.assertTrue(response.context['payment'].history_cancelled)
        self.assertIn('لغو', response.context['payment'].history_state_label)
        self.assertFalse(response.context['can_edit'])
        self.assertEqual(payment.events.filter(action='executive_cancel').count(), 1)

    def test_detail_never_offers_edits_for_a_payment_with_execution_evidence(self):
        payment = self.payment(state='approved', payment_reference='ALREADY-RECORDED')
        self.client.force_login(self.executive)
        detail_url = reverse('payments_detail', args=[payment.pk])
        response = self.client.get(detail_url)
        self.assertFalse(response.context['can_edit'])
        self.assertEqual(self.client.post(detail_url).status_code, 405)
        self.assertEqual(payment.events.count(), 0)

    def test_edit_return_target_cannot_be_used_as_external_redirect(self):
        payment = self.payment()
        self.client.force_login(self.executive)
        result = self.client.post(reverse('payments_executive_change', args=[payment.pk]), {
            'action': 'edit', 'description': 'Updated test description', 'amount_million': '4',
            'return_to': 'https://untrusted.invalid/',
        })
        self.assertRedirects(result, reverse('payments_workspace'))

    def test_thumbnail_is_a_small_private_image_and_does_not_modify_payment(self):
        from PIL import Image
        payment = self.payment(state='paid', assigned_to=self.operator,
                               payment_receipt=self.image_receipt(), payment_reference='BANK-IMAGE')
        before = PaymentRequest.objects.filter(pk=payment.pk).values().get()
        url = reverse('payments_receipt_thumbnail', args=[payment.pk])
        for user in (self.executive, self.requester, self.operator):
            self.client.force_login(user)
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Content-Type'], 'image/jpeg')
            self.assertIn('no-store', response['Cache-Control'])
            self.assertIn('private', response['Cache-Control'])
            self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
            content = b''.join(response.streaming_content) if response.streaming else response.content
            with Image.open(BytesIO(content)) as image:
                self.assertLessEqual(max(image.size), 160)
                self.assertGreater(min(image.size), 0)
        self.assertEqual(PaymentRequest.objects.filter(pk=payment.pk).values().get(), before)
        self.assertEqual(payment.events.count(), 0)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    def test_thumbnail_rejects_pdf_corrupt_missing_and_unpaid_receipts(self):
        cases = [
            ('paid', SimpleUploadedFile('proof.pdf', b'%PDF-1.4 test', content_type='application/pdf')),
            ('paid', SimpleUploadedFile('corrupt.png', b'not an image', content_type='image/png')),
            ('paid', 'payment_receipts/missing.png'),
            ('approved', self.image_receipt()),
        ]
        self.client.force_login(self.executive)
        for state, receipt in cases:
            with self.subTest(state=state, receipt=str(receipt)):
                payment = self.payment(state=state, payment_receipt=receipt)
                response = self.client.get(reverse('payments_receipt_thumbnail', args=[payment.pk]))
                self.assertEqual(response.status_code, 404)

    def test_personal_invoice_thumbnail_remains_private_and_distinct_from_payment(self):
        payment = self.payment(kind='personal_expense', personal_expense_receipt=self.image_receipt())
        url = reverse('payments_personal_receipt_thumbnail', args=[payment.pk])
        self.client.force_login(self.requester)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.get(reverse('payments_receipt_thumbnail', args=[payment.pk])).status_code, 404)
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)
