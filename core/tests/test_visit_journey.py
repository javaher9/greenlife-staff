"""Full request -> private intake -> desk -> follow-up integration checks."""
from datetime import timedelta
from io import BytesIO

from PIL import Image
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.utils import timezone

from core.models import (
    Branch, CustomerPortalMember, CustomerServiceRequest, CustomerIntakePhoto,
    CustomerRequestEvent, StaffNotification,
)


class VisitJourneyTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Journey test branch')
        self.member = CustomerPortalMember.objects.create(
            phone='09120001000', full_name='عضو آزمون مسیر', referral_code='journey-test')
        self.operator = User.objects.create_user(username='journey-operator')
        profile = self.operator.profile
        profile.role = 'call_center'
        profile.branch = self.branch
        profile.save()
        self.staff = Client(enforce_csrf_checks=True)
        self.staff.force_login(self.operator)
        self.customer = self.member_client(self.member)
        self.intake = '/customer/request/visit/'
        self.desk = '/call-center/greenlife-me/'

    def member_client(self, member):
        client = Client(enforce_csrf_checks=True)
        session = client.session
        session['gl_customer_member_id'] = member.pk
        session['gl_customer_auth_at'] = timezone.now().timestamp()
        session.save()
        return client

    def post(self, client, form_page, action, fields):
        self.assertEqual(client.get(form_page).status_code, 200)
        return client.post(action, {
            **fields, 'csrfmiddlewaretoken': client.cookies['csrftoken'].value,
        })

    def submit(self):
        image = BytesIO()
        Image.new('RGB', (320, 240), '#649373').save(image, 'PNG')
        result = self.post(self.customer, self.intake, self.intake, {
            'full_name': self.member.full_name, 'age': '38',
            'city': 'شهر آزمایشی', 'address': 'آدرس ساختگی جهت آزمون',
            'goal': 'بررسی اتصال کامل پرونده', 'branch': str(self.branch.pk),
            'preferred_date': (timezone.localdate() + timedelta(days=2)).isoformat(),
            'daypart': 'afternoon', 'note': 'آزمایش؛ نیاز به تماس واقعی ندارد',
            'photo_consent': 'yes',
            'photos': SimpleUploadedFile('synthetic.png', image.getvalue(), 'image/png'),
        })
        self.assertRedirects(result, self.intake)
        row = CustomerServiceRequest.objects.get(member=self.member)
        return row, f'{self.desk}{row.pk}/'

    def test_complete_journey_persists_across_sessions(self):
        row, detail = self.submit()
        self.assertEqual(row.intake.age, 38)
        self.assertIsNotNone(row.intake.consent_at)
        self.assertEqual(row.daypart, 'afternoon')
        self.assertEqual(row.intake.photos.count(), 1)
        self.assertTrue(StaffNotification.objects.filter(user=self.operator,
                                                       title='درخواست جدید ویزیت').exists())
        self.assertContains(self.staff.get(self.desk + '?view=new'), self.member.full_name)
        self.assertContains(self.staff.get(self.desk + '?q=' + self.member.phone), self.member.full_name)
        page = self.staff.get(detail)
        for value in ('شهر آزمایشی', 'آدرس ساختگی جهت آزمون',
                      'بررسی اتصال کامل پرونده', 'آزمایش؛ نیاز به تماس واقعی ندارد'):
            self.assertContains(page, value)
        photo = CustomerIntakePhoto.objects.get(intake=row.intake)
        photo_url = f'/customer/intake/photo/{photo.public_id}/'
        self.assertContains(page, photo_url)
        operator_image = self.staff.get(photo_url)
        self.assertEqual(operator_image.status_code, 200)
        self.assertEqual(operator_image['Content-Type'], 'image/jpeg')
        self.assertEqual(operator_image['Cache-Control'], 'private, no-store')
        self.assertEqual(operator_image.content, bytes(photo.content))
        self.assertEqual(self.customer.get(photo_url).content, operator_image.content)
        Image.open(BytesIO(operator_image.content)).verify()

        action = f'/staff/customer-requests/{row.pk}/action/'
        self.assertRedirects(self.post(self.staff, detail, action, {
            'action': 'claim', 'return_to': 'me_desk'}), detail)
        due = (timezone.localtime() + timedelta(days=1)).replace(second=0, microsecond=0)
        internal_note = 'یادداشت خصوصی آزمون؛ تماس واقعی انجام نشده'
        self.assertRedirects(self.post(self.staff, detail, detail + 'followup/', {
            'outcome': 'callback', 'note': internal_note,
            'next_contact': due.strftime('%Y-%m-%dT%H:%M')}), detail)
        row.refresh_from_db()
        self.assertEqual(row.status, 'contacted')
        self.assertEqual(row.assigned_to_id, self.operator.profile.pk)
        self.assertEqual(row.next_followup_at, due)
        self.assertEqual(CustomerRequestEvent.objects.filter(request=row).count(), 2)
        self.assertEqual(row.followup_events.first().actor_id, self.operator.pk)

        fresh_staff = Client()
        fresh_staff.force_login(self.operator)
        self.assertContains(fresh_staff.get(detail), internal_note)
        self.assertContains(fresh_staff.get(self.desk + '?view=mine'), self.member.full_name)
        fresh_customer = self.member_client(self.member)
        member_page = fresh_customer.get(self.intake)
        self.assertContains(member_page, 'در حال پیگیری')
        self.assertContains(member_page, photo_url)
        self.assertNotContains(member_page, internal_note)
        self.assertEqual(fresh_customer.get(photo_url).content, operator_image.content)

        # Resubmitting the original form cannot create a second active case.
        self.post(self.customer, self.intake, self.intake, {
            'full_name': self.member.full_name, 'branch': str(self.branch.pk)})
        self.assertEqual(CustomerServiceRequest.objects.filter(member=self.member).count(), 1)
        self.assertEqual(CustomerIntakePhoto.objects.count(), 1)

        self.assertRedirects(self.post(self.staff, detail, action, {
            'action': 'decline', 'staff_note': 'آزمون کامل شد؛ بدون نوبت و تماس واقعی',
            'return_to': 'me_desk'}), detail)
        row.refresh_from_db()
        self.assertEqual(row.status, 'declined')
        self.assertIsNone(row.next_followup_at)
        self.assertIsNone(row.visit_appointment_id)
        self.assertEqual(row.followup_events.count(), 3)
        self.assertNotContains(self.staff.get(self.desk), self.member.full_name)
        self.assertContains(self.staff.get(self.desk + '?view=closed'), self.member.full_name)
        self.assertContains(fresh_staff.get(detail), 'آزمون کامل شد؛ بدون نوبت و تماس واقعی')

    def test_private_photo_and_case_cannot_be_read_by_other_member(self):
        row, detail = self.submit()
        photo = row.intake.photos.get()
        photo_url = f'/customer/intake/photo/{photo.public_id}/'
        stranger = CustomerPortalMember.objects.create(phone='09120001001', referral_code='stranger')
        for client in (Client(), self.member_client(stranger)):
            self.assertEqual(client.get(photo_url).status_code, 404)
            self.assertEqual(client.get(detail).status_code, 403)

    def test_csrf_and_invalid_followup_do_not_mutate_case(self):
        row, detail = self.submit()
        # Staff CSRF failures intentionally redirect to refresh the page;
        # the important invariant is that the unsafe request never writes.
        self.assertEqual(self.staff.post(detail + 'followup/', {
            'outcome': 'note', 'note': 'بدون توکن'}).status_code, 302)
        self.assertFalse(row.followup_events.exists())
        row.refresh_from_db()
        self.assertEqual(row.status, 'pending')
        self.assertRedirects(self.post(self.staff, detail, detail + 'followup/', {
            'outcome': 'no_answer', 'note': 'بدون موعد تماس'}), detail)
        row.refresh_from_db()
        self.assertEqual(row.status, 'pending')
        self.assertIsNone(row.assigned_to_id)
        self.assertIsNone(row.next_followup_at)
        self.assertFalse(row.followup_events.exists())
