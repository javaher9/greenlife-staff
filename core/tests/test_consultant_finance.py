import tempfile
from io import BytesIO
from unittest.mock import Mock, patch
from datetime import datetime, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone
from PIL import Image, ImageDraw

from core.finance import finance_summary
from core.jalali import format_jalali
from core.models import AuditLog, Branch, EmployeeProfile, FinancialTransaction


@override_settings(ROOT_URLCONF='greenlife.urls')
class ConsultantFinanceEntryTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.media_dir=tempfile.TemporaryDirectory(prefix='greenlife-finance-test-')
        cls.media_override=override_settings(MEDIA_ROOT=cls.media_dir.name)
        cls.media_override.enable()

    @classmethod
    def tearDownClass(cls):
        cls.media_override.disable()
        cls.media_dir.cleanup()
        super().tearDownClass()

    def setUp(self):
        self.env_patcher=patch.dict('os.environ',{'OPENAI_API_KEY':''},clear=False)
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        self.branch=Branch.objects.create(name='نیاوران')
        self.other_branch=Branch.objects.create(name='پونک')
        self.consultant=self.make_user('consultant', 'consultant', self.branch, 'نازنین', 'مرادی')
        self.employee=self.make_user('employee', 'employee', self.branch, 'کارمند', 'نمونه')
        self.admin=self.make_user('admin', 'admin', self.branch, 'مدیر', 'سیستم')
        self.manager=self.make_user('manager', 'manager', self.other_branch, 'مدیر', 'پونک')

    @staticmethod
    def make_user(username, role, branch, first_name, last_name):
        user=User.objects.create_user(
            username=username,password='test-password',first_name=first_name,last_name=last_name,
        )
        EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={'role':role,'branch':branch,'job_title':'مشاور' if role=='consultant' else '', 'is_active':True},
        )
        return User.objects.get(pk=user.pk)

    @staticmethod
    def receipt(name='receipt.gif'):
        # A valid 1x1 GIF. The form validates image content, not only its extension.
        content=(
            b'GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,'
            b'\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;'
        )
        return SimpleUploadedFile(name, content, content_type='image/gif')

    @staticmethod
    def large_receipt():
        image=Image.new('RGB',(2600,1900),'white')
        draw=ImageDraw.Draw(image)
        for y in range(50,1850,45):
            draw.line((80,y,2520,y),fill=(80+(y%120),90,100),width=3)
        output=BytesIO()
        image.save(output,format='JPEG',quality=96)
        return SimpleUploadedFile('large-receipt.jpg',output.getvalue(),content_type='image/jpeg')

    def valid_payload(self, **overrides):
        data={
            'date':format_jalali(timezone.localdate()),
            'entry_type':'inc',
            'person_name':'مشتری نمونه',
            'amount':'1234567',
            'payment_method':'Pos S',
            'service':'پکیج مشاوره',
            'account_heading':'فروش پکیج',
            'terminal_or_payee':'کارتخوان نیاوران',
            'tracking_number':'998877',
            'destination_card':'',
            'description':'ثبت آزمایشی',
            'receipt_image':self.receipt(),
        }
        data.update(overrides)
        return data

    def test_consultant_role_and_default_today_are_available(self):
        self.assertIn(('consultant','مشاور'), EmployeeProfile.ROLE_CHOICES)
        self.client.force_login(self.consultant)
        response=self.client.get('/finance/entry/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ثبت تراکنش مالی')
        self.assertContains(response, format_jalali(timezone.localdate()))

    def test_consultant_dashboard_has_prominent_finance_entry_and_stats(self):
        occurred=timezone.make_aware(datetime.combine(timezone.localdate(),time(10,0)))
        FinancialTransaction.objects.create(
            source='manual',branch=self.branch,occurred_at=occurred,amount=500,
            person_name='مشتری',review_status='pending',recorded_by=self.consultant,
        )
        FinancialTransaction.objects.create(
            source='manual',branch=self.branch,occurred_at=occurred,amount=700,
            person_name='مشتری دوم',review_status='needs_correction',recorded_by=self.consultant,
        )
        self.client.force_login(self.consultant)
        response=self.client.get('/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'ثبت مالی جدید')
        self.assertContains(response,'class="gl-finance-launch-main"')
        self.assertContains(response,'در انتظار تأیید')
        self.assertContains(response,'نیازمند اصلاح')
        self.assertContains(response,'consultant-finance-nav')

    def test_consultant_sees_only_destination_codes_not_internal_meanings(self):
        self.client.force_login(self.consultant)
        response=self.client.get('/finance/entry/')
        for code in ('Pos S','Pos H','CC P','CC D','CC S'):
            self.assertContains(response,code)
        for internal_label in ('پوز اصلی','فیلم و هنر','دکتر جواهریان','ساره'):
            self.assertNotContains(response,internal_label)

    def test_consultant_submits_exact_manual_amount_name_and_receipt(self):
        self.client.force_login(self.consultant)
        response=self.client.post('/finance/entry/', data=self.valid_payload())
        self.assertRedirects(response, '/finance/entry/', fetch_redirect_response=False)
        entry=FinancialTransaction.objects.get(source='manual')
        self.assertEqual(entry.amount, Decimal('1234567'))
        self.assertEqual(entry.person_name, 'مشتری نمونه')
        self.assertEqual(entry.patient_ref, 'مشتری نمونه')
        self.assertEqual(entry.branch, self.branch)
        self.assertEqual(entry.recorded_by, self.consultant)
        self.assertEqual(entry.review_status, 'pending')
        self.assertEqual(entry.analysis_status, 'skipped')
        self.assertTrue(entry.receipt_image.name)
        self.assertTrue(entry.receipt_image.name.endswith('.webp'))
        self.assertGreater(entry.receipt_original_size,0)
        self.assertGreater(entry.receipt_compressed_size,0)
        self.assertEqual(entry.raw_data['entry_channel'], 'staff_consultant')
        self.assertTrue(AuditLog.objects.filter(action='finance_entry',object_id=str(entry.pk)).exists())

    def test_receipt_and_positive_manual_amount_are_required(self):
        self.client.force_login(self.consultant)
        missing_receipt=self.valid_payload()
        missing_receipt.pop('receipt_image')
        response=self.client.post('/finance/entry/', data=missing_receipt)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'این فیلد لازم است')
        self.assertFalse(FinancialTransaction.objects.exists())

        response=self.client.post('/finance/entry/', data=self.valid_payload(amount='0'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مبلغ باید بیشتر از صفر باشد')
        self.assertFalse(FinancialTransaction.objects.exists())

    def test_large_receipt_is_resized_and_compressed(self):
        self.client.force_login(self.consultant)
        response=self.client.post(
            '/finance/entry/',data=self.valid_payload(receipt_image=self.large_receipt()),
        )
        self.assertRedirects(response,'/finance/entry/',fetch_redirect_response=False)
        entry=FinancialTransaction.objects.get(source='manual')
        self.assertLess(entry.receipt_compressed_size,entry.receipt_original_size)
        entry.receipt_image.open('rb')
        try:
            stored=Image.open(entry.receipt_image)
            self.assertLessEqual(max(stored.size),2000)
            self.assertEqual(stored.format,'WEBP')
        finally:
            entry.receipt_image.close()


    def test_cc_p_requires_other_recipient_name(self):
        self.client.force_login(self.consultant)
        response=self.client.post('/finance/entry/',data=self.valid_payload(
            payment_method='CC P',terminal_or_payee='',
        ))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'برای CC P نام شخص دریافت‌کننده الزامی است')
        self.assertFalse(FinancialTransaction.objects.exists())

    def test_employee_cannot_open_or_submit_consultant_finance(self):
        self.client.force_login(self.employee)
        response=self.client.get('/finance/entry/')
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        response=self.client.post('/finance/entry/', data=self.valid_payload())
        self.assertRedirects(response, '/', fetch_redirect_response=False)
        self.assertFalse(FinancialTransaction.objects.exists())

    def test_pending_entry_is_excluded_until_admin_approves(self):
        self.client.force_login(self.consultant)
        self.client.post('/finance/entry/', data=self.valid_payload())
        entry=FinancialTransaction.objects.get(source='manual')
        summary=finance_summary(timezone.localdate())
        self.assertEqual(summary['total'], Decimal('0'))

        self.client.force_login(self.admin)
        response=self.client.post(f'/finance/entries/{entry.pk}/approve/')
        self.assertRedirects(response, '/finance/', fetch_redirect_response=False)
        entry.refresh_from_db()
        self.assertEqual(entry.review_status, 'approved')
        self.assertEqual(entry.reviewed_by, self.admin)
        summary=finance_summary(timezone.localdate())
        self.assertEqual(summary['total'], Decimal('1234567'))

    def test_manager_cannot_review_another_branch_entry(self):
        occurred=timezone.make_aware(datetime.combine(timezone.localdate(),time(10,0)))
        entry=FinancialTransaction.objects.create(
            source='manual',branch=self.branch,occurred_at=occurred,amount=500,
            person_name='مشتری',review_status='pending',recorded_by=self.consultant,
        )
        self.client.force_login(self.manager)
        response=self.client.post(f'/finance/entries/{entry.pk}/approve/')
        self.assertRedirects(response, '/finance/', fetch_redirect_response=False)
        entry.refresh_from_db()
        self.assertEqual(entry.review_status, 'pending')

    def test_expense_is_separate_from_income_and_net(self):
        occurred=timezone.make_aware(datetime.combine(timezone.localdate(),time(10,0)))
        FinancialTransaction.objects.create(
            source='manual',branch=self.branch,occurred_at=occurred,amount=1000,
            entry_type='inc',review_status='approved',person_name='مشتری',
        )
        FinancialTransaction.objects.create(
            source='manual',branch=self.branch,occurred_at=occurred,amount=250,
            entry_type='exp',review_status='approved',person_name='فروشنده',
        )
        summary=finance_summary(timezone.localdate())
        self.assertEqual(summary['total'], Decimal('1000'))
        self.assertEqual(summary['expense_total'], Decimal('250'))
        self.assertEqual(summary['net_total'], Decimal('750'))

    def test_ai_analysis_flags_mismatch_without_changing_manual_amount(self):
        client=Mock()
        client.responses.create.return_value.output_text='''{
          "readable": true,
          "document_type": "pos_receipt",
          "detected_amount": "999000",
          "currency_unit": "rial",
          "detected_date": "1405/06/10",
          "tracking_number": "12345",
          "destination_card_last4": null,
          "payer_or_payee": null,
          "confidence": "high",
          "warnings": []
        }'''
        self.client.force_login(self.consultant)
        with patch.dict('os.environ',{'OPENAI_API_KEY':'test-key'},clear=False), \
             patch('core.ai.OpenAI',return_value=client):
            response=self.client.post('/finance/entry/',data=self.valid_payload())
        self.assertRedirects(response,'/finance/entry/',fetch_redirect_response=False)
        entry=FinancialTransaction.objects.get(source='manual')
        self.assertEqual(entry.amount,Decimal('1234567'))
        self.assertEqual(entry.analysis_status,'processed')
        self.assertFalse(entry.receipt_analysis['manual_amount_match'])
        self.assertEqual(entry.receipt_analysis['tracking_number'],'12345')
        self.assertIn('اختلاف',entry.receipt_analysis['warnings'][0])
        client.responses.create.assert_called_once()
