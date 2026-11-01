from django.contrib.auth.models import User
from django.test import TestCase
from core.models import EmployeeProfile
from core.lead_management_views import _management_flower_candidates, _management_flower_target
from core.lead_routing import _operators_for_channel


class ManualGandomTests(TestCase):
    def test_gandom_is_manual_target_but_not_in_auto_rotation(self):
        user=User.objects.create_user(username='gandom-worker',first_name='گندم')
        profile=EmployeeProfile.objects.create(user=user,role='employee',is_active=True)
        self.assertIn(profile.pk,list(_management_flower_candidates().values_list('pk',flat=True)))
        self.assertEqual(_management_flower_target(profile.pk).pk,profile.pk)
        self.assertNotIn(profile.pk,[p.pk for p in _operators_for_channel([profile],None)])

    def test_inactive_gandom_not_assignable(self):
        user=User.objects.create_user(username='gandom-inactive',first_name='گندم')
        profile=EmployeeProfile.objects.create(user=user,role='employee',is_active=False)
        self.assertIsNone(_management_flower_target(profile.pk))
