from io import BytesIO
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from core.models import Branch, EmployeeProfile
from .models import PaymentRequest, PaymentEvent

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
