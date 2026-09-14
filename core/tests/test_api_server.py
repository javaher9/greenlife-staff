import json
from datetime import timedelta
from io import BytesIO
from unittest.mock import patch
from urllib.error import HTTPError

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.credential_security import decrypt_secret, encrypt_secret
from core.finance import sync_crm
from core.integration_api import ApiServerError, call_api
from core.jalali import format_jalali
from core.models import (
    ApiServerSettings, Branch, FinancialTransaction, SmsMessageLog, VisitAppointment,
)
from core.sms import SmsGatewayError, send_appointment_confirmation, send_sms


class _Response:
    def __init__(self,payload,status=200):
        self.payload=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        self.status=status

    def __enter__(self):
        return self

    def __exit__(self,*args):
        return False

    def getcode(self):
        return self.status

    def read(self):
        return self.payload


@override_settings(ROOT_URLCONF='greenlife.urls')
class ApiServerClientTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('api-user',password='SafePass123')
        self.config=ApiServerSettings.load()
        self.config.base_url='http://192.168.40.33:81/gl-api'
        self.config.api_key_cipher=encrypt_secret('private-api-key')
        self.config.is_enabled=True
        self.config.timeout_seconds=17
        self.config.save()

    @patch('core.integration_api.urlopen')
    def test_client_posts_json_to_ip_port_with_x_api_key(self,mocked_open):
        mocked_open.return_value=_Response({'ids':[812183911]})
        status,payload=call_api('/sms/send',{'body':'پیام','number':'09123456789'})

        request=mocked_open.call_args.args[0]
        headers={key.lower():value for key,value in request.header_items()}
        self.assertEqual(request.full_url,'http://192.168.40.33:81/gl-api/sms/send')
        self.assertEqual(request.method,'POST')
        self.assertEqual(headers['x-api-key'],'private-api-key')
        self.assertEqual(headers['content-type'],'application/json')
        self.assertEqual(mocked_open.call_args.kwargs['timeout'],17)
        self.assertEqual(json.loads(request.data.decode('utf-8'))['number'],'09123456789')
        self.assertEqual(status,200)
        self.assertEqual(payload['ids'],[812183911])

    @patch('core.integration_api.urlopen')
    def test_sms_records_gateway_acceptance(self,mocked_open):
        mocked_open.return_value=_Response({'ids':[42]})
        log,_payload=send_sms('09123456789','پیام تست',created_by=self.user)
        self.assertEqual(log.status,'accepted')
        self.assertEqual(log.provider_ids,[42])
        self.assertEqual(log.http_status,200)

    @patch('core.integration_api.urlopen')
    def test_sms_records_unauthorized_error(self,mocked_open):
        mocked_open.side_effect=HTTPError(
            'http://example.test',401,'Unauthorized',{},
            BytesIO(b'{"success":false,"error":"unauthorized"}'),
        )
        with self.assertRaises(SmsGatewayError) as raised:
            send_sms('09123456789','پیام تست')
        self.assertEqual(raised.exception.code,'unauthorized')
        log=SmsMessageLog.objects.get()
        self.assertEqual(log.status,'failed')
        self.assertEqual(log.http_status,401)
        self.assertEqual(log.error_code,'unauthorized')

    def test_disabled_server_blocks_operational_calls(self):
        self.config.is_enabled=False
        self.config.save(update_fields=['is_enabled'])
        with self.assertRaises(ApiServerError) as raised:
            call_api('/crm/finance_month',{})
        self.assertEqual(raised.exception.code,'disabled')

    @patch('core.sms.call_api')
    def test_appointment_confirmation_uses_jalali_date(self,mocked_call):
        mocked_call.return_value=(200,{'ids':[10]})
        self.config.appointment_confirmation_enabled=True
        self.config.save(update_fields=['appointment_confirmation_enabled'])
        branch=Branch.objects.create(name='نیاوران')
        appointment=VisitAppointment.objects.create(
            branch=branch,full_name='علی رضایی',phone='09123456789',
            appointment_date=timezone.localdate(),appointment_time='10:30',created_by=self.user,
        )
        send_appointment_confirmation(appointment.pk)
        body=mocked_call.call_args.args[1]['body']
        self.assertIn('علی رضایی',body)
        self.assertIn('نیاوران',body)
        self.assertIn(format_jalali(timezone.localdate()),body)
        self.assertEqual(SmsMessageLog.objects.filter(purpose='appointment').count(),1)


@override_settings(ROOT_URLCONF='greenlife.urls',EXECUTIVE_USERNAMES=())
class ApiServerSettingsViewTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('api-admin','admin@example.com','SafePass123')
        self.client.force_login(self.admin)

    def test_admin_saves_encrypted_key_and_editable_ip_port(self):
        response=self.client.post(reverse('api_server_settings'),{
            'action':'save',
            'base_url':'http://10.20.30.40:8181/gl-api/',
            'api_key':'new-private-key',
            'timeout_seconds':'25',
            'is_enabled':'on',
            'appointment_message_template':ApiServerSettings.DEFAULT_APPOINTMENT_TEMPLATE,
        })
        self.assertRedirects(response,reverse('api_server_settings'))
        config=ApiServerSettings.load()
        self.assertEqual(config.base_url,'http://10.20.30.40:8181/gl-api')
        self.assertEqual(config.timeout_seconds,25)
        self.assertNotIn('new-private-key',config.api_key_cipher)
        self.assertEqual(decrypt_secret(config.api_key_cipher),'new-private-key')

    def test_blank_key_keeps_existing_encrypted_value(self):
        config=ApiServerSettings.load()
        config.api_key_cipher=encrypt_secret('existing-key')
        config.save()
        response=self.client.post(reverse('api_server_settings'),{
            'action':'save','base_url':config.base_url,'api_key':'',
            'timeout_seconds':'30','appointment_message_template':config.appointment_message_template,
        })
        self.assertRedirects(response,reverse('api_server_settings'))
        config.refresh_from_db()
        self.assertEqual(decrypt_secret(config.api_key_cipher),'existing-key')

    def test_non_admin_is_forbidden(self):
        user=User.objects.create_user('ordinary',password='SafePass123')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('api_server_settings')).status_code,403)

    def test_key_and_full_phone_are_not_rendered(self):
        config=ApiServerSettings.load()
        config.api_key_cipher=encrypt_secret('do-not-render-this-key')
        config.save()
        SmsMessageLog.objects.create(
            number='09123456789',body='test',purpose='test',status='accepted',
        )
        response=self.client.get(reverse('api_server_settings'))
        self.assertContains(response,'0912***6789')
        self.assertNotContains(response,'09123456789')
        self.assertNotContains(response,'do-not-render-this-key')


@override_settings(ROOT_URLCONF='greenlife.urls')
class CrmFinanceApiSyncTests(TestCase):
    def setUp(self):
        config=ApiServerSettings.load()
        config.api_key_cipher=encrypt_secret('crm-key')
        config.is_enabled=True
        config.save()

    def _row(self,*,paid_on=None,amount='1500000',group='3842_117'):
        paid_on=paid_on or timezone.localdate()
        return {
            'FormFillEditDate':f'{paid_on.isoformat()} 12:48:02.807',
            'کلینیک':'اصفهان',
            'CustomerId':'462920',
            'group':group,
            'formValueId':'867826',
            'تاریخ فیش پرداختی':paid_on.strftime('%m/%d/%Y'),
            'مبلغ فیش پرداختی':amount,
            'نحوه پرداخت فیش':'کارتخوان',
            'پرداخت خدمات مرتبط':'ویزیت، اسکن و آنالیز، دایا',
            'مشتری':'زهره حسن پور',
        }

    @patch('core.finance.call_api')
    def test_sync_filters_current_jalali_month_and_upserts(self,mocked_call):
        old_row=self._row(paid_on=timezone.localdate()-timedelta(days=70),group='old')
        rows=[self._row(),old_row]
        mocked_call.return_value=(200,{'success':True,'count':2,'rows':rows})

        first=sync_crm()
        second=sync_crm()

        self.assertEqual(first['imported'],1)
        self.assertEqual(second['imported'],0)
        self.assertEqual(second['updated'],1)
        self.assertEqual(FinancialTransaction.objects.filter(source='crm').count(),1)
        item=FinancialTransaction.objects.get(source='crm')
        self.assertEqual(item.external_id,'glapi:867826:3842_117')
        self.assertEqual(item.amount,1500000)
        self.assertEqual(item.branch.name,'اصفهان')
        self.assertEqual(item.person_name,'زهره حسن پور')
        self.assertEqual(item.payment_method,'کارتخوان')

    @patch('core.finance.call_api')
    def test_sync_uses_primary_receipt_fields_only(self,mocked_call):
        row=self._row()
        row['تاریخ فیش پرداختی']=None
        row['مبلغ فیش پرداختی']=None
        row['تاریخ پرداخت']=timezone.localdate().strftime('%m/%d/%Y')
        row['مبلغ پرداختی']='9900000'
        mocked_call.return_value=(200,{'success':True,'count':1,'rows':[row]})
        result=sync_crm()
        self.assertEqual(result['skipped'],1)
        self.assertFalse(FinancialTransaction.objects.exists())
