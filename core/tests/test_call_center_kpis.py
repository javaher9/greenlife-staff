from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Branch, EmployeeProfile, ReferralLead, ReferralProfile


class CallCenterKpiPanelTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='کال‌سنتر KPI')
        self.operator = self._user('kpi-operator', 'نرگس')
        self.other_operator = self._user('kpi-other', 'خورشیدی')
        referrer_user = User.objects.create_user('kpi-referrer', password='pass', first_name='معرف')
        EmployeeProfile.objects.update_or_create(
            user=referrer_user,
            defaults={'role':'employee','branch':self.branch,'is_active':True},
        )
        self.referrer = ReferralProfile.objects.create(
            user=referrer_user, referral_code='GLKPITEST', created_by=referrer_user,
        )
        ReferralLead.objects.create(
            referrer=self.referrer,
            full_name='لید KPI من',
            phone='09120001111',
            assigned_to=self.operator.profile,
            status='new',
        )
        ReferralLead.objects.create(
            referrer=self.referrer,
            full_name='لید KPI همکار',
            phone='09120002222',
            assigned_to=self.other_operator.profile,
            status='new',
        )
        self.client.force_login(self.operator)

    def _user(self, username, first_name):
        user = User.objects.create_user(username, password='pass', first_name=first_name)
        EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={
                'role':'call_center',
                'branch':self.branch,
                'job_title':'کارشناس کال‌سنتر',
                'is_active':True,
            },
        )
        return User.objects.get(pk=user.pk)

    def test_kpi_panel_is_additive_and_uses_real_operator_data(self):
        response = self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code, 200)

        # Existing cards and navigation must remain so operators are not disoriented.
        for old_label in (
            'لیدهای امروز', 'کل مراجعین من', 'پیگیری باز',
            'نوبت امروز', 'نوبت‌های آینده', 'مراجعین و لیدهای من',
        ):
            self.assertContains(response, old_label)

        for new_label in (
            'عملکرد من', 'بدون تماس امروز', 'سهم لید امروز', 'نرخ رسیدگی ماه',
            'نوبت‌سازی ماه', 'مراجعه از نوبت', 'تبدیل ماه', 'فروش ماه',
            'پیگیری عقب‌افتاده',
        ):
            self.assertContains(response, new_label)

        performance = response.context['performance']
        self.assertEqual(performance['today_uncontacted'], 1)
        self.assertEqual(performance['month_total'], 1)
        self.assertEqual(performance['team_today'], 2)
        self.assertEqual(performance['lead_share_today'], 50)
