from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import EmployeeProfile, ReferralLead, ReferralProfile, StaffNotification


class LeadAttentionOneClickAssignmentTests(TestCase):
    def setUp(self):
        self.admin_user=User.objects.create_user(
            'lead-admin',password='pass',first_name='مدیر',
        )
        EmployeeProfile.objects.update_or_create(
            user=self.admin_user,
            defaults={'role':'admin','is_active':True},
        )

        self.operator_user=User.objects.create_user(
            'salehi',password='pass',first_name='محمد',last_name='صالحی',
        )
        self.operator,_=EmployeeProfile.objects.update_or_create(
            user=self.operator_user,
            defaults={'role':'call_center','is_active':True},
        )

        self.source_user=User.objects.create_user(
            'lead-source-test',password='pass',first_name='منبع',
        )
        self.source=ReferralProfile.objects.create(
            user=self.source_user,
            referral_code='LEADSRC01',
            is_active=True,
        )
        self.client.force_login(self.admin_user)

    def make_lead(self, *, phone, status='new', overdue=False):
        lead=ReferralLead.objects.create(
            referrer=self.source,
            full_name='لید تست',
            phone=phone,
            status=status,
            assigned_to=self.operator,
            assigned_at=timezone.now()-timedelta(hours=3),
            next_follow_up=timezone.localdate()-timedelta(days=1) if overdue else None,
            source='panel',
        )
        return lead

    def test_assigned_urgent_row_has_one_click_referral_without_operator_selector(self):
        lead=self.make_lead(phone='09120000001')
        response=self.client.get(reverse('lead_management_dashboard'))

        self.assertEqual(response.status_code,200)
        self.assertContains(response,'خورشیدی')
        self.assertContains(response,f'data-attention-row="{lead.pk}"')
        self.assertContains(response,'name="same_owner_lead_id"')
        self.assertNotContains(response,'name="operator_id"')

    def test_one_click_referral_keeps_current_owner_notifies_and_removes_from_attention(self):
        lead=self.make_lead(phone='09120000002')
        old_assigned_at=lead.assigned_at

        response=self.client.post(
            reverse('lead_attention_bulk_action'),
            {'same_owner_lead_id':str(lead.pk)},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code,200)
        payload=response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['operator'],'خورشیدی')

        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to_id,self.operator.pk)
        self.assertGreater(lead.assigned_at,old_assigned_at)
        self.assertIsNotNone(lead.group_id)
        self.assertEqual(lead.group.owner_id,self.operator.pk)
        self.assertTrue(
            StaffNotification.objects.filter(
                user=self.operator_user,
                notification_type='call_center_lead',
            ).exists()
        )

        dashboard=self.client.get(reverse('lead_management_dashboard'))
        self.assertNotContains(dashboard,f'data-attention-row="{lead.pk}"')

    def test_overdue_followup_is_temporarily_cleared_from_attention_after_rereferral(self):
        lead=self.make_lead(
            phone='09120000003',
            status='contacted',
            overdue=True,
        )
        before=self.client.get(reverse('lead_management_dashboard'))
        self.assertContains(before,f'data-attention-row="{lead.pk}"')

        response=self.client.post(
            reverse('lead_attention_bulk_action'),
            {'same_owner_lead_id':str(lead.pk)},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code,200)

        after=self.client.get(reverse('lead_management_dashboard'))
        self.assertNotContains(after,f'data-attention-row="{lead.pk}"')
