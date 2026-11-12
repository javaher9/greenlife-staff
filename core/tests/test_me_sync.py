import json
from django.test import TestCase, Client
from django.utils import timezone
from zoneinfo import ZoneInfo
from core.models import CustomerPortalMember, MeAccountState, MeDailyAward


class MeSyncTests(TestCase):
    def setUp(self):
        self.member = CustomerPortalMember.objects.create(phone='09123456789', referral_code='ME_TEST')
        self.url = '/customer/me/state/'
        self.login(self.client)

    def login(self, client):
        session = client.session
        session['gl_customer_member_id'] = self.member.pk
        session['gl_customer_auth_at'] = timezone.now().timestamp()
        session.save()

    def send(self, values, version=0, **extra):
        return self.client.post(self.url, json.dumps({'values': values, 'version': version, 'consent': True, **extra}), content_type='application/json')

    def test_guest_denied_and_existing_identity_reused(self):
        self.assertEqual(Client().get(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url).json()['member'], str(self.member.pk))
        self.assertIn('no-store', self.client.get(self.url)['Cache-Control'])

    def test_two_devices_and_revision_conflict(self):
        self.assertEqual(self.send({'greenlife-interactive-preview-v1': {'focus': 'mind'}}).status_code, 200)
        second = Client(); self.login(second)
        self.assertEqual(second.get(self.url).json()['values']['greenlife-interactive-preview-v1']['focus'], 'mind')
        self.assertEqual(self.send({}, version=0).status_code, 409)
        self.assertEqual(MeAccountState.objects.get(member=self.member).version, 1)

    def test_client_awards_ignored_daily_grants_unique_and_correction_preserves_history(self):
        day = str(timezone.now().astimezone(ZoneInfo('Asia/Tehran')).date())
        key = 'greenlife-heart-v1'
        values = {key: {'awards': {'2000-01-01': 'fake'}, 'days': {day: {'food': 100, 'move': 100}}}}
        self.assertEqual(self.send(values).status_code, 200)
        self.assertEqual(MeDailyAward.objects.filter(member=self.member).count(), 1)
        self.assertNotIn('2000-01-01', self.client.get(self.url).json()['values'][key]['awards'])
        self.send(values, version=1)
        values[key]['days'][day]['food'] = 0
        self.send(values, version=2)
        self.assertEqual(MeDailyAward.objects.filter(member=self.member).count(), 1)

    def test_unknown_partial_and_rest_do_not_earn_awards(self):
        day = str(timezone.now().astimezone(ZoneInfo('Asia/Tehran')).date())
        for version, pair in enumerate([(100, None), ('skip', 'skip'), (0, 0)]):
            self.send({'greenlife-heart-v1': {'days': {day: dict(zip(['food','move'], pair))}}}, version=version)
        self.assertEqual(MeDailyAward.objects.count(), 0)

    def test_isolation_does_not_accept_client_member_id(self):
        other = CustomerPortalMember.objects.create(phone='09999999999', referral_code='OTHER')
        self.send({}, member=str(other.pk))
        self.assertFalse(MeAccountState.objects.filter(member=other).exists())

    def test_csrf_and_consent_required_and_invalid_shape_rejected(self):
        strict = Client(enforce_csrf_checks=True); self.login(strict)
        self.assertEqual(strict.post(self.url, '{}', content_type='application/json').status_code, 403)
        self.assertEqual(self.send({}, consent=False).status_code, 400)
        self.assertEqual(self.send({'unexpected': {}}).status_code, 400)
        self.assertEqual(self.send({'greenlife-heart-v1': {'days': {'bad': {}}}}).status_code, 400)
        self.assertEqual(MeAccountState.objects.count(), 0)

    def test_events_excluded_and_logout_revokes_identity(self):
        self.send({'greenlife-me-member-v1': {'events': [{'text': 'private'}]}})
        self.assertEqual(self.client.get(self.url).json()['values']['greenlife-me-member-v1']['events'], [])
        self.client.post('/customer/me/logout/')
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_valid_csrf_from_canonical_app_and_untrusted_origin_denied(self):
        strict = Client(enforce_csrf_checks=True); self.login(strict)
        token = strict.get(self.url, secure=True).json()['csrf']
        body = json.dumps({'values': {}, 'version': 0, 'consent': True})
        self.assertEqual(strict.post(self.url, body, content_type='application/json', secure=True,
                         HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN='https://attacker.test').status_code, 403)
        self.assertEqual(strict.post(self.url, body, content_type='application/json', secure=True,
                         HTTP_X_CSRFTOKEN=token, HTTP_ORIGIN='https://greenlife-me-preview.vercel.app').status_code, 200)
