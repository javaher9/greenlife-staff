import json
from datetime import time, timedelta
from django.test import TestCase, Client
from django.utils import timezone
from core.models import CustomerPortalMember, Branch, VisitAppointment
from core.me_nutrition_models import MeNutritionProgress
from core.me_nutrition_views import LESSONS
from core.me_sync_models import MeDailyAward
from core.me_diet_views import today


class NutritionLearningTests(TestCase):
    url = '/customer/me/nutrition/'

    def setUp(self):
        self.member = CustomerPortalMember.objects.create(phone='09123456789', referral_code='learn1')
        s = self.client.session
        s['gl_customer_member_id'] = self.member.pk
        s['gl_customer_auth_at'] = timezone.now().timestamp()
        s.save()

    def answer(self, id=1, **extra):
        return self.client.post(self.url, json.dumps({'version': LESSONS['version'], 'id': id, 'choice': 'change', **extra}), content_type='application/json')

    def test_guest_free_preview_and_no_write(self):
        guest = Client(); data = guest.get(self.url).json()
        self.assertEqual(len(data['catalog']), 85)
        self.assertEqual(len(data['items']), 20)
        self.assertFalse(data['clinic'])
        self.assertEqual(guest.post(self.url, '{}', content_type='application/json').status_code, 401)

    def test_unique_catalog_and_no_missing_situations(self):
        self.assertEqual(sorted(i for g in LESSONS['groups'] for i in g['ids']), list(range(1,86)))
        self.assertEqual([i['id'] for i in LESSONS['items']], list(range(1,86)))

    def test_locked_content_and_no_client_entitlement(self):
        self.assertEqual(self.answer(10).status_code, 403)
        self.assertEqual(self.answer(10, hearts=999).status_code, 400)
        self.assertEqual(self.answer(True).status_code, 400)
        for n in range(3): MeDailyAward.objects.create(member=self.member, day=today()-timedelta(days=n))
        self.assertEqual(self.answer(10).status_code, 200)
        self.assertEqual(self.answer(14).status_code, 403)

    def test_progress_cross_session_isolated_idempotent_no_reward(self):
        self.assertEqual(self.answer().status_code, 200); self.answer()
        second = Client(); s=second.session; s.update(self.client.session); s.save()
        self.assertEqual(second.get(self.url).json()['choices'], {'1': 'change'})
        self.assertEqual(MeDailyAward.objects.count(), 0)
        other = CustomerPortalMember.objects.create(phone='09123456780', referral_code='learn2')
        s=second.session; s['gl_customer_member_id']=other.pk; s.save()
        self.assertEqual(second.get(self.url).json()['choices'], {})
        self.assertEqual(MeNutritionProgress.objects.count(), 1)

    def test_clinic_requires_own_completed_past_visit(self):
        b=Branch.objects.create(name='آزمون')
        a=VisitAppointment.objects.create(branch=b,full_name='آزمون',phone=self.member.phone,appointment_date=today(),appointment_time=time(9),status='booked')
        self.assertFalse(self.client.get(self.url).json()['clinic'])
        a.status='completed';a.appointment_date=today()+timedelta(days=1);a.save()
        self.assertFalse(self.client.get(self.url).json()['clinic'])
        a.appointment_date=today();a.phone='09120000000';a.save()
        self.assertEqual(self.answer(11).status_code,403)
        a.phone=self.member.phone;a.save()
        self.assertTrue(self.client.get(self.url).json()['clinic'])
        self.assertEqual(self.answer(11).status_code,200)

    def test_csrf_required(self):
        secure=Client(enforce_csrf_checks=True);s=secure.session;s.update(self.client.session);s.save()
        self.assertEqual(secure.post(self.url,'{}',content_type='application/json').status_code,403)
