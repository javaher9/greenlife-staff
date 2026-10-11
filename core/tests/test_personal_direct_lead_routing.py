from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import CallCenterLeadGroup, EmployeeProfile, ReferralLead


class PersonalDirectLeadRoutingTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='personal-direct-operator', password='test')
        self.other = User.objects.create_user(username='other-direct-operator', password='test')
        for user in (self.user, self.other):
            profile = user.profile
            profile.role = 'call_center'
            profile.is_active = True
            profile.save(update_fields=['role', 'is_active'])
        self.profile = EmployeeProfile.objects.get(user=self.user)
        self.group = CallCenterLeadGroup.objects.create(name='گروه تست ثبت شخصی', is_default=False)
        self.client.force_login(self.user)

    def test_inline_direct_lead_stays_with_registrar_and_selected_group(self):
        response = self.client.post(reverse('call_center_lead_create'), {
            'full_name': 'مراجعه کننده مستقیم اول',
            'phone': '09129991001',
            'group': self.group.pk,
            'interested_service': 'لاغری',
            'notes': 'ثبت مستقیم در گروه',
        })
        self.assertEqual(response.status_code, 302)
        lead = ReferralLead.objects.get(phone='09129991001')
        self.assertEqual(lead.assigned_to_id, self.profile.pk)
        self.assertEqual(lead.group_id, self.group.pk)
        self.assertEqual(lead.created_by_id, self.user.pk)
        self.assertIsNotNone(lead.assigned_at)

    def test_full_direct_form_stays_with_registrar_and_selected_group(self):
        response = self.client.post(reverse('call_center_direct_lead_create'), {
            'full_name': 'مراجعه کننده مستقیم دوم',
            'phone': '09129991002',
            'group': self.group.pk,
            'interested_service': 'پیگیری',
            'notes': 'ثبت شخصی',
        })
        self.assertEqual(response.status_code, 302)
        lead = ReferralLead.objects.get(phone='09129991002')
        self.assertEqual(lead.assigned_to_id, self.profile.pk)
        self.assertEqual(lead.group_id, self.group.pk)
        self.assertEqual(lead.created_by_id, self.user.pk)
        self.assertIn('[entry:direct]', lead.notes)
