from datetime import timedelta
from decimal import Decimal
from hashlib import sha256
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import FinancialTransaction
from payments.models import PaymentEvent, PaymentRequest


TOKEN = 'test-only-accounting-export'
TOKEN_DIGEST = sha256(TOKEN.encode()).hexdigest()


@override_settings(ACCOUNTING_EXPORT_TOKEN_SHA256=TOKEN_DIGEST)
class AccountingExportTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser('test-accounting-manager')
        self.now = timezone.now()
        day = timezone.localdate(self.now)
        self.window = {'from': day.isoformat(), 'until': (day + timedelta(days=1)).isoformat()}
        self.auth = {'HTTP_AUTHORIZATION': f'Bearer {TOKEN}'}
        self.client = Client(enforce_csrf_checks=True)
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        settings = override_settings(MEDIA_ROOT=directory.name)
        settings.enable()
        self.addCleanup(settings.disable)

    def receipt(self, code, **kwargs):
        fields = dict(
            review_status='approved', entry_type='inc', amount=Decimal('27000'),
            person_name='private patient', tracking_number='private tracking',
            destination_card='private destination', description='private note',
        )
        fields.update(kwargs)
        return FinancialTransaction.objects.create(
            payment_method=code, occurred_at=self.now, **fields,
        )

    def expense(self, *, documents=True, audit=True, **kwargs):
        fields = dict(
            kind='personal_expense', state='paid', cost_owner='company',
            amount_toman=27, description='Company expense', payment_reference='private reference',
            recipient_iban='private IBAN', recipient_card='private card',
            approved_at=self.now, paid_at=self.now, approved_by=self.user, requester=self.user,
        )
        fields.update(kwargs)
        row = PaymentRequest.objects.create(**fields)
        if documents:
            row.personal_expense_receipt.save('invoice.pdf', ContentFile(b'original invoice'))
            row.payment_receipt.save('receipt.pdf', ContentFile(b'payment receipt'))
        if audit:
            PaymentEvent.objects.create(payment=row, actor=self.user, action='approve')
        return row

    def fetch(self, feed, **query):
        url = reverse(f'accounting_{feed}_export')
        return self.client.get(url, {**self.window, **query}, secure=True, **self.auth)

    def test_feed_requires_service_token_and_https_and_is_read_only(self):
        url = reverse('accounting_receipt_export')
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(url, self.window, secure=True).status_code, 403)
        wrong = {'HTTP_AUTHORIZATION': 'Bearer unrelated-service'}
        self.assertEqual(self.client.get(url, self.window, secure=True, **wrong).status_code, 403)
        self.assertEqual(self.client.get(url, self.window, **self.auth).status_code, 403)
        with override_settings(ACCOUNTING_EXPORT_TOKEN_SHA256=''):
            self.assertEqual(self.fetch('receipt').status_code, 404)
        self.assertEqual(
            Client(enforce_csrf_checks=True).post(url, secure=True, **self.auth).status_code, 403,
        )
        self.assertRedirects(
            self.client.post(url, secure=True, **self.auth), url, fetch_redirect_response=False,
        )
        self.assertEqual(Client().post(url, secure=True, **self.auth).status_code, 405)
        self.assertEqual(self.fetch('receipt', until=self.window['from']).status_code, 400)
        self.assertEqual(self.fetch('receipt', after='-1').status_code, 400)

    def test_receipts_return_only_canonical_company_codes_and_minimum_fields(self):
        first = self.receipt('Pos S')
        second = self.receipt('CC G')
        third = self.receipt('CCG')
        self.receipt('POS-H')
        self.receipt('CC S')
        self.receipt('CC G extra')
        self.receipt('CC G', review_status='pending')
        self.receipt('CC G', review_status='cancelled')
        self.receipt('CC G', cash_currency='USD')
        self.receipt('CC G', amount=Decimal('0.25'))
        self.receipt('Pos S', entry_type='exp')
        response = self.fetch('receipt')
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        result = response.json()
        self.assertEqual(result['incomplete_count'], 1)
        self.assertEqual(result['items'], [
            {'source_id': f'staff:receipt:{row.pk}', 'code': code,
             'amount_rial': '27000', 'date': self.window['from'], 'branch_id': None}
            for row, code in [(first, 'POS-S'), (second, 'CC-G'), (third, 'CC-G')]
        ])

    def test_receipt_pagination_can_replay_without_skipping_valid_rows(self):
        first = self.receipt('Pos S', amount=Decimal('1.25'))
        second = self.receipt('CC-G')
        with patch('core.accounting_export._PAGE_SIZE', 1):
            page = self.fetch('receipt').json()
            self.assertEqual(page, self.fetch('receipt').json())
            self.assertEqual(page['items'], [])
            self.assertEqual(page['next_after'], first.pk)
            last = self.fetch('receipt', after=first.pk).json()
            self.assertEqual(last['items'][0]['source_id'], f'staff:receipt:{second.pk}')
            self.assertIsNone(last['next_after'])
        self.assertEqual(FinancialTransaction.objects.count(), 2)

    def test_expense_feed_and_documents_require_complete_company_approval(self):
        complete = self.expense()
        pending = self.expense(state='pending')
        rejected = self.expense(state='rejected')
        missing_invoice = self.expense(documents=False)
        self.expense(cost_owner='personal')
        self.expense(audit=False)
        self.expense(deleted_at=self.now)
        self.expense(kind='petty_cash')
        unavailable = self.expense()
        unavailable.payment_receipt.storage.delete(unavailable.payment_receipt.name)

        response = self.fetch('expense')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['incomplete_count'], 2)
        items = response.json()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['source_id'], f'staff:expense:{complete.pk}')
        self.assertEqual(items[0]['amount_rial'], '270')
        self.assertNotIn('private', response.content.decode())
        self.assertEqual(self.fetch('receipt').json()['items'], [])

        for kind, expected in [('invoice', b'original invoice'), ('receipt', b'payment receipt')]:
            url = items[0]['documents'][kind]
            self.assertEqual(self.client.get(url, secure=True).status_code, 403)
            document = self.client.get(url, secure=True, **self.auth)
            self.assertEqual(document.status_code, 200)
            self.assertEqual(b''.join(document.streaming_content), expected)
            self.assertIn('no-store', document['Cache-Control'])
        for item in (pending, rejected, missing_invoice, unavailable):
            url = reverse('accounting_expense_invoice', args=[item.pk])
            self.assertEqual(self.client.get(url, secure=True, **self.auth).status_code, 404)
