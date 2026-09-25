from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Branch, TreatmentCatalogItem


class TreatmentCatalogSettingsTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser(
            username='catalog-admin',
            email='admin@example.com',
            password='StrongPass123',
        )
        self.branch=Branch.objects.create(name='نیاوران کاتالوگ')
        self.client.login(username='catalog-admin',password='StrongPass123')

    def test_admin_can_add_catalog_item_with_price(self):
        response=self.client.post(reverse('treatment_catalog_settings'),{
            'action':'save',
            'category':'lipolytic',
            'name':'لیپولیتیک گرید ۳',
            'price_toman':'3500000',
            'unit_label':'جلسه',
            'branch':str(self.branch.pk),
            'sort_order':'10',
            'is_active':'1',
            'notes':'پروتکل داخلی تست',
        },follow=True)
        self.assertEqual(response.status_code,200)
        item=TreatmentCatalogItem.objects.get(name='لیپولیتیک گرید ۳')
        self.assertEqual(item.category,'lipolytic')
        self.assertEqual(int(item.price_toman),3500000)
        self.assertEqual(item.branch,self.branch)
        self.assertTrue(item.is_active)

    def test_settings_page_lists_catalog_sections(self):
        TreatmentCatalogItem.objects.create(
            category='device',
            name='Double Define',
            price_toman=2500000,
            unit_label='ناحیه',
            created_by=self.admin,
        )
        response=self.client.get(reverse('treatment_catalog_settings'))
        body=response.content.decode('utf-8')
        self.assertIn('تنظیمات خدمات و درمان‌ها',body)
        self.assertIn('Double Define',body)
        self.assertIn('دستگاه',body)
