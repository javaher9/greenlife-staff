from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase

from core.call_center_identity import (
    FlowerProfileProxy,
    FlowerUserProxy,
    call_center_display_name,
)
from core.context_processors import call_center_flower_user
from core.models import EmployeeProfile


class CallCenterFlowerNameTests(TestCase):
    def _operator(self, first_name, last_name, username):
        user = User.objects.create_user(
            username=username,
            first_name=first_name,
            last_name=last_name,
            password='test-pass',
        )
        profile = EmployeeProfile.objects.create(
            user=user,
            role='call_center',
            is_active=True,
        )
        return user, profile

    def test_confirmed_flower_aliases(self):
        cases = (
            ('محمد', 'صالحی', 'salehi-test', 'خورشیدی'),
            ('فاطمه', 'بابایی', 'babayi-test', 'نرگس'),
            ('حدیث', 'توانا', 'tavana-test', 'بنفشه'),
            ('پریسا', 'کلکلی', 'kolkoli-test', 'کاملیا'),
            ('شیما', 'عباسی', 'abbasi-test', 'لاله'),
            ('زهرا', 'آزادی', 'zahra-azadi', 'یاسمن'),
        )
        for first_name, last_name, username, expected in cases:
            user, profile = self._operator(first_name, last_name, username)
            self.assertEqual(call_center_display_name(user), expected)
            self.assertEqual(call_center_display_name(profile), expected)

    def test_unknown_operator_falls_back_to_real_name(self):
        user, profile = self._operator('مریم', 'احمدی', 'maryam-ahmadi')
        self.assertEqual(call_center_display_name(profile), 'مریم احمدی')

    def test_ui_proxies_keep_identity_data_but_show_flower_name(self):
        user, profile = self._operator('شیما', 'عباسی', 'shima-abbasi')
        user_proxy = FlowerUserProxy(user)
        profile_proxy = FlowerProfileProxy(profile)
        self.assertEqual(user_proxy.first_name, 'لاله')
        self.assertEqual(user_proxy.get_full_name(), 'لاله')
        self.assertEqual(user_proxy.username, 'shima-abbasi')
        self.assertEqual(profile_proxy.user.get_full_name(), 'لاله')
        self.assertEqual(profile_proxy.id, profile.id)

    def test_context_processor_only_relabels_call_center_pages(self):
        user, _ = self._operator('محمد', 'صالحی', 'm-salehi')
        factory = RequestFactory()

        call_center_request = factory.get('/call-center/')
        call_center_request.user = user
        context = call_center_flower_user(call_center_request)
        self.assertEqual(context['user'].get_full_name(), 'خورشیدی')

        other_request = factory.get('/attendance/')
        other_request.user = user
        self.assertEqual(call_center_flower_user(other_request), {})
        self.assertEqual(user.get_full_name(), 'محمد صالحی')
