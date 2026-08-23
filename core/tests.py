from django.contrib.auth import authenticate
from django.contrib.auth.models import User
from django.test import TestCase

from .forms import EmployeeCreateForm


class CaseInsensitiveAuthenticationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='Manager1', password='safe-test-password')

    def test_authenticates_with_lowercase_username(self):
        self.assertEqual(
            authenticate(username='manager1', password='safe-test-password'),
            self.user,
        )

    def test_authenticates_with_uppercase_username(self):
        self.assertEqual(
            authenticate(username='MANAGER1', password='safe-test-password'),
            self.user,
        )

    def test_rejects_wrong_password(self):
        self.assertIsNone(authenticate(username='manager1', password='wrong-password'))

    def test_employee_form_rejects_case_only_duplicate(self):
        form = EmployeeCreateForm(
            data={
                'username': 'manager1',
                'first_name': 'Test',
                'last_name': 'User',
                'password': 'safe-test-password',
                'role': 'employee',
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn('username', form.errors)
