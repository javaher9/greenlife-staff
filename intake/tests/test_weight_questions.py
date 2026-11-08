import hashlib
from datetime import time, timedelta
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Branch, VisitAppointment
from intake.models import IntakeInvitation
from core.intake_summary import compact_medical_summary


@override_settings(ALLOWED_HOSTS=['testserver','app.greenlifeclinics.com'])
class WeightLossIntakeTests(TestCase):
    def setUp(self):
        branch = Branch.objects.create(name='Weight clinic test')
        appointment = VisitAppointment.objects.create(
            branch=branch, full_name='تست کاهش وزن', phone='09120001111',
            service='کاهش وزن', appointment_date=timezone.localdate(),
            appointment_time=time(11, 30), status='arrived',
        )
        token = 'weight-loss-form-token-for-test-only-12345678'
        self.invitation = IntakeInvitation.objects.create(
            appointment=appointment, token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=timezone.now()+timedelta(hours=1))
        self.url = reverse('intake_public_form',args=[token])
        self.client = Client(enforce_csrf_checks=True)

    def test_12_question_form_post_and_physician_summary(self):
        page=self.client.get(self.url,secure=True,HTTP_HOST='app.greenlifeclinics.com')
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'اطلاعات اولیه کاهش وزن')
        data={
            'goal':'کاهش وزن','body_area':'شکم و پهلو',
            'conditions':['کم‌کاری تیروئید'],'medication_status':'بله','medications':'لووتیروکسین',
            'allergy_status':'خیر','allergies':'','safety_none':'yes','safety_flags':[],'screening_confirmed':'on',
            'appetite':'زیاد','eating_habits':['ریزه‌خواری','فست‌فود'],
            'mental_state':'گاهی اضطراب یا غمگینی','hopelessness':'گاهی',
            'activity':'کم','sleep':'۶ تا ۸ ساعت',
            'previous_treatments':'رژیم غذایی','current_weight':'89.2',
            'target_weight':'75','motivation':'سلامتی','consent':'on',
        }
        response=self.client.post(self.url,data,secure=True,
            HTTP_HOST='app.greenlifeclinics.com',
            HTTP_REFERER='https://app.greenlifeclinics.com'+self.url,
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code,200)
        self.invitation.refresh_from_db()
        self.assertIsNotNone(self.invitation.completed_at)
        self.assertEqual(self.invitation.answers['form_version'],'weight-loss-v2')
        self.assertEqual(self.invitation.answers['appetite'],'زیاد')
        self.assertEqual(self.invitation.answers['hopelessness'],'گاهی')
        self.assertEqual(self.invitation.answers['eating_habits'],['ریزه‌خواری','فست‌فود'])
        summary=compact_medical_summary(self.invitation.answers)
        self.assertEqual(summary['sections']['داروها'],['لووتیروکسین'])
        self.assertEqual(summary['sections']['وزن هدف (کیلوگرم)'],['75.0'])

    def test_invalid_form_cannot_complete(self):
        self.client.get(self.url,secure=True,HTTP_HOST='app.greenlifeclinics.com')
        data={'goal':'کاهش وزن','body_area':'شکم و پهلو',
              'screening_confirmed':'on','consent':'on'}
        response=self.client.post(self.url,data,secure=True,
            HTTP_HOST='app.greenlifeclinics.com',
            HTTP_REFERER='https://app.greenlifeclinics.com'+self.url,
            HTTP_X_CSRFTOKEN=self.client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code,200)
        self.invitation.refresh_from_db()
        self.assertIsNone(self.invitation.completed_at)

    def test_unrelated_service_keeps_existing_form(self):
        other=VisitAppointment.objects.create(
            branch=self.invitation.appointment.branch,full_name='پوست تست',
            phone='09120002222', service='بوتاکس',
            appointment_date=timezone.localdate(),appointment_time=time(12,0),status='arrived')
        token='other-service-test-token-long-enough-000123'
        IntakeInvitation.objects.create(appointment=other,
            token_hash=hashlib.sha256(token.encode()).hexdigest(),
            expires_at=timezone.now()+timedelta(hours=1))
        response=self.client.get(reverse('intake_public_form',args=[token]),
            secure=True,HTTP_HOST='app.greenlifeclinics.com')
        self.assertContains(response,'فرم اطلاعات اولیه')
        self.assertNotContains(response,'اطلاعات اولیه کاهش وزن')
