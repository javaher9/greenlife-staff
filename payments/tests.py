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
        cls.worker=User.objects.create_user(username='payments-worker',password='test-password')
        cls.other=User.objects.create_user(username='payments-other',password='test-password')
        branch=Branch.objects.create(name='Payment Test Branch')
        EmployeeProfile.objects.update_or_create(user=cls.worker,defaults={'branch':branch,'role':'consultant','is_active':True})
        EmployeeProfile.objects.update_or_create(user=cls.other,defaults={'branch':branch,'role':'consultant','is_active':True})
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
        self.other.profile.save(update_fields=['role'])
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
        self.other.profile.role='quality_control'
        self.other.profile.save(update_fields=['role'])
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
