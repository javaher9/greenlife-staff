from django.contrib.auth.models import User
from django.test import TestCase

from core.models import Branch, EmployeeProfile
from core.reporting import answer_query


class InternalManagerRoleTests(TestCase):
    def setUp(self):
        self.niavaran = Branch.objects.create(name='نیاوران')
        self.other_branch = Branch.objects.create(name='آزادی')
        self.internal = self.make_user(
            'hashemi', 'internal_manager', self.niavaran,
            first_name='فاطیما', last_name='هاشمی', job_title='مدیر داخلی',
        )
        self.admin = self.make_user('admin-user', 'admin', self.niavaran)
        self.manager = self.make_user('branch-manager', 'manager', self.other_branch)
        self.employee_one = self.make_user('employee-one', 'employee', self.niavaran)
        self.employee_two = self.make_user('employee-two', 'employee', self.other_branch)
        self.client.force_login(self.internal)

    @staticmethod
    def make_user(username, role, branch, **profile_fields):
        user = User.objects.create_user(
            username=username,
            password='test-password',
            first_name=profile_fields.pop('first_name', ''),
            last_name=profile_fields.pop('last_name', ''),
        )
        EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={'role': role, 'branch': branch, 'is_active': True, **profile_fields},
        )
        return user

    def test_role_has_distinct_persian_label(self):
        self.assertIn(('internal_manager', 'مدیر داخلی'), EmployeeProfile.ROLE_CHOICES)
        self.assertEqual(self.internal.profile.get_role_display(), 'مدیر داخلی')

    def test_dashboard_opens_internal_management_and_hides_sensitive_navigation(self):
        response = self.client.get('/')
        self.assertRedirects(response, '/live/', fetch_redirect_response=False)
        response = self.client.get('/employees/')
        self.assertContains(response, 'مدیریت داخلی')
        self.assertNotContains(response, 'مالی و درآمد')
        self.assertNotContains(response, 'معرفی مشتری')

    def test_employee_list_covers_all_branches_but_only_regular_employees(self):
        response = self.client.get('/employees/')
        self.assertEqual(response.status_code, 200)
        employees = list(response.context['employees'])
        self.assertIn(self.employee_one.profile, employees)
        self.assertIn(self.employee_two.profile, employees)
        self.assertNotIn(self.admin.profile, employees)
        self.assertNotIn(self.manager.profile, employees)

    def test_can_edit_employee_but_not_manager_or_admin_accounts(self):
        allowed = self.client.get(f'/employees/{self.employee_two.profile.pk}/edit/')
        self.assertEqual(allowed.status_code, 200)
        denied_manager = self.client.get(f'/employees/{self.manager.profile.pk}/edit/')
        denied_admin = self.client.get(f'/employees/{self.admin.profile.pk}/edit/')
        self.assertRedirects(denied_manager, '/employees/', fetch_redirect_response=False)
        self.assertRedirects(denied_admin, '/employees/', fetch_redirect_response=False)

    def test_finance_routes_and_queries_are_denied(self):
        dashboard = self.client.get('/finance/')
        self.assertRedirects(dashboard, '/', fetch_redirect_response=False)
        api = self.client.get('/api/management/finance/summary/')
        self.assertEqual(api.status_code, 403)
        result = answer_query(self.internal, 'درآمد امروز چقدر است؟')
        self.assertEqual(result['data'], {})
        self.assertIn('فعال نیست', result['answer'])

    def test_live_api_is_operational_but_has_no_revenue_field(self):
        response = self.client.get('/api/live/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('revenue_today', response.json())

    def test_referral_panel_is_denied(self):
        response = self.client.get('/referrals/')
        self.assertEqual(response.status_code, 403)
