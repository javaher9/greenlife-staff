"""Skin Care 50/50 settlement must not double-count unapproved receipts."""
from datetime import timedelta
from decimal import Decimal
from tempfile import TemporaryDirectory

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.finance import finance_summary
from core.jalali import format_jalali
from core.models import Branch, EmployeeProfile, FinancialTransaction, SkinCareSettlement


GIF=(b'GIF89a\x01\x00\x01\x00\x80\x00\x00\xff\xff\xff\x00\x00\x00'
     b'!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00'
     b'\x01\x00\x00\x02\x02D\x01\x00;')


class SkinCareSettlementTests(TestCase):
    def setUp(self):
        self.media=TemporaryDirectory()
        self.media_settings=override_settings(MEDIA_ROOT=self.media.name)
        self.media_settings.enable()
        self.addCleanup(self.media_settings.disable)
        self.addCleanup(self.media.cleanup)
        self.branch=Branch.objects.create(name='Skin Care test center')
        self.second=Branch.objects.create(name='Other Skin Care branch')
        self.haddad=User.objects.create_user(username='staff-haddad-test',first_name='لیلا',last_name='حداد',password='test')
        self.performer,_=EmployeeProfile.objects.update_or_create(
            user=self.haddad,defaults={'branch':self.branch,'role':'employee','is_active':True,'can_record_skin_care':True}
        )
        self.receptionist=User.objects.create_user(username='skin-reception',password='test')
        self.recprofile,_=EmployeeProfile.objects.update_or_create(
            user=self.receptionist,defaults={'branch':self.branch,'role':'receptionist','is_active':True}
        )
        self.other=User.objects.create_user(username='skin-outsider',password='test')
        self.other_profile,_=EmployeeProfile.objects.update_or_create(
            user=self.other,defaults={'branch':self.second,'role':'employee','is_active':True}
        )
        self.url=reverse('skin_care_home')
        self.client.force_login(self.haddad)

    def payload(self, **values):
        data={
            'performer':str(self.performer.pk),
            'service_date':format_jalali(timezone.localdate(),persian_digits=False),
            'company_share_toman':'30000000',
            'payment_method':'Pos S',
            'tracking_number':'SC-REMIT-1',
            'submission_token':'219b5fe2c72e42dc9f2edab32518df13',
        }
        data.update(values)
        return data

    def receipt(self):
        return SimpleUploadedFile('receipt.gif',GIF,content_type='image/gif')

    def test_share_of_sixty_million_is_thirty_million_only_after_approval(self):
        response=self.client.post(self.url,{
            **self.payload(),'receipt_image':self.receipt()
        })
        self.assertEqual(response.status_code,302)
        settlement=SkinCareSettlement.objects.get()
        tx=settlement.finance_transaction
        self.assertEqual(settlement.company_share_toman,Decimal('30000000'))
        self.assertEqual(settlement.gross_equivalent_toman,Decimal('60000000'))
        self.assertEqual(tx.amount,Decimal('300000000'))  # stored in rial
        self.assertEqual(tx.sale_reason,'skin_care')
        self.assertEqual(tx.review_status,'pending')
        self.assertEqual(finance_summary()['income_total'],0)

        tx.review_status='approved'
        tx.save(update_fields=['review_status'])
        self.assertEqual(finance_summary()['income_total'],Decimal('300000000'))

    def test_duplicate_submission_cannot_double_count(self):
        payload={**self.payload(),'receipt_image':self.receipt()}
        self.assertEqual(self.client.post(self.url,payload).status_code,302)
        payload['receipt_image']=self.receipt()
        self.assertEqual(self.client.post(self.url,payload).status_code,302)
        self.assertEqual(SkinCareSettlement.objects.count(),1)
        self.assertEqual(FinancialTransaction.objects.filter(sale_reason='skin_care').count(),1)

    def test_bank_receipt_is_required(self):
        res=self.client.post(self.url,self.payload())
        self.assertEqual(res.status_code,200)
        self.assertContains(res,'تصویر واریز سهم گرین‌لایف الزامی است')
        self.assertFalse(SkinCareSettlement.objects.exists())

    def test_receptionist_can_record_for_same_branch_worker(self):
        self.client.force_login(self.receptionist)
        response=self.client.post(self.url,{**self.payload(),'receipt_image':self.receipt()})
        self.assertEqual(response.status_code,302)
        settlement=SkinCareSettlement.objects.get()
        self.assertEqual(settlement.created_by,self.receptionist)
        self.assertEqual(settlement.performer,self.performer)

    def test_unrelated_employee_cannot_open_skin_care(self):
        self.client.force_login(self.other)
        response=self.client.get(self.url)
        self.assertEqual(response.status_code,403)
        self.assertFalse(SkinCareSettlement.objects.exists())

    def test_authorized_skin_care_staff_cannot_record_for_other_person(self):
        outside=User.objects.create_user('other-authorized-skin-care',password='test')
        other_profile,_=EmployeeProfile.objects.update_or_create(
            user=outside,
            defaults={'role':'employee','branch':self.second,'is_active':True,'can_record_skin_care':True},
        )
        response=self.client.post(self.url,{
            **self.payload(performer=str(other_profile.pk)),
            'receipt_image':self.receipt(),
        })
        self.assertEqual(response.status_code,200)
        self.assertFalse(SkinCareSettlement.objects.exists())

    def test_duplicate_bank_reference_is_rejected_even_with_a_new_token(self):
        self.client.post(self.url,{**self.payload(),'receipt_image':self.receipt()})
        response=self.client.post(self.url,{
            **self.payload(
                submission_token='7d590f64a4ee4eff95c177355628811e',
            ),
            'receipt_image':self.receipt(),
        })
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'شماره پیگیری این واریز اسکین‌کر قبلاً ثبت شده است')
        self.assertEqual(SkinCareSettlement.objects.count(),1)
