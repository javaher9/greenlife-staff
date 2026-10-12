"""Single-source global device pricing and treatment-catalog editing regression."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse

from core.consultant_sales_views import _catalog_price
from core.device_pricing import (
    device_unit_price, from_toman_to_million, to_toman_from_million,
)
from core.doctor_views import _catalog_options
from core.models import (
    Branch, DeviceTypeSchedule, PhysicalDevice, TreatmentCatalogItem,
)


class UnifiedDevicePricingTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name="نیاوران آزمایشی قیمت")
        self.other_branch=Branch.objects.create(name="پونک آزمایشی قیمت")
        self.superuser=User.objects.create_superuser(
            username="catalog-unit-admin",email="unit-admin@example.com",
            password="StrongPass123",
        )
        self.role_admin=User.objects.create_user(
            username="catalog-role-admin",password="StrongPass123",
        )
        self.role_admin.profile.role="admin"
        self.role_admin.profile.branch=self.branch
        self.role_admin.profile.save(update_fields=["role","branch"])
        self.manager=User.objects.create_user(username="catalog-unit-manager",password="StrongPass123")
        self.manager.profile.role="manager"
        self.manager.profile.branch=self.branch
        self.manager.profile.save(update_fields=["role","branch"])
        self.em=DeviceTypeSchedule.objects.create(
            code="EM30",name="EM تست قیمت",treatment_minutes=30,preparation_minutes=10,
        )
        self.cryo=DeviceTypeSchedule.objects.create(
            code="CRYO60",name="کرایو تست قیمت",treatment_minutes=60,preparation_minutes=20,
            price_unit="cup",
        )
        self.physical=PhysicalDevice.objects.create(
            branch=self.branch,device_type=self.em,name="EM-1",
        )

    def test_money_value_is_million_toman_and_is_lossless(self):
        self.assertEqual(to_toman_from_million("5"),Decimal("5000000"))
        self.assertEqual(to_toman_from_million("2.5"),Decimal("2500000"))
        self.assertEqual(from_toman_to_million(10000000),"10")
        self.assertIsNone(to_toman_from_million(""))
        with self.assertRaises(ValueError):
            to_toman_from_million("-1")
        with self.assertRaises(ValueError):
            to_toman_from_million("1.0001")

    def test_old_unconfigured_tariff_is_preserved_and_global_bank_price_overrides(self):
        TreatmentCatalogItem.objects.create(
            category="device",name=self.em.name,price_toman=Decimal("4200000"),
            branch=self.branch,
        )
        self.assertEqual(device_unit_price(self.em.name,self.branch),Decimal("4200000"))
        self.client.force_login(self.superuser)
        result=self.client.post(reverse("treatment_catalog_settings"),{
            "action":"device_price","type_id":str(self.em.pk),
            "unit_price_million":"5","price_unit":"session",
        },follow=True)
        self.assertEqual(result.status_code,200)
        self.em.refresh_from_db()
        self.assertEqual(self.em.unit_price_toman,Decimal("5000000"))
        self.assertEqual(device_unit_price(self.em.name,self.branch),Decimal("5000000"))
        self.assertEqual(device_unit_price(self.em.name,self.other_branch),Decimal("5000000"))
        self.assertEqual(_catalog_price(self.branch,"device",self.em.name),Decimal("5000000"))
        self.assertIn(self.em.name,[x["name"] for x in _catalog_options("device",self.branch,())])
        self.assertEqual(TreatmentCatalogItem.objects.filter(category="device",name=self.em.name).count(),1)
        self.assertContains(result,"EM تست قیمت")

    def test_bank_not_legacy_catalog_drives_doctor_and_services_listing(self):
        TreatmentCatalogItem.objects.create(
            category="device",name="نام قدیمی خارج از بانک",price_toman=Decimal("1000000")
        )
        self.client.force_login(self.superuser)
        response=self.client.get(reverse("treatment_catalog_settings")+"?category=device")
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"EM تست قیمت")
        self.assertContains(response,"کرایو تست قیمت")
        self.assertNotContains(response,"نام قدیمی خارج از بانک")
        choices=[row["name"] for row in _catalog_options("device",self.branch,())]
        self.assertIn(self.em.name,choices)
        self.assertIn(self.cryo.name,choices)
        self.assertNotIn("نام قدیمی خارج از بانک",choices)
        self.em.is_active=False
        self.em.save(update_fields=["is_active"])
        self.assertNotIn(self.em.name,[x["name"] for x in _catalog_options("device",self.branch,())])

    def test_price_saved_in_bank_via_device_capacity_page(self):
        self.client.force_login(self.role_admin)
        response=self.client.post(reverse("device_capacity_settings"),{
            "branch":str(self.branch.pk),"action":"device_price",
            "type_id":str(self.cryo.pk),"unit_price_million":"3.5",
            "price_unit":"cup",
        },follow=True)
        self.assertEqual(response.status_code,200)
        self.cryo.refresh_from_db()
        self.assertEqual(self.cryo.unit_price_toman,Decimal("3500000"))
        self.assertEqual(self.cryo.price_unit,"cup")
        self.assertEqual(self.cryo.treatment_minutes,60)
        response=self.client.get(reverse("device_capacity_settings")+"?branch="+str(self.branch.pk))
        self.assertContains(response,'value="3.5"')
        self.assertContains(response,"هر کاپ")

    def test_manager_cannot_change_any_device_price(self):
        self.client.force_login(self.manager)
        response=self.client.post(reverse("device_capacity_settings"),{
            "branch":str(self.branch.pk),"action":"device_price",
            "type_id":str(self.em.pk),"unit_price_million":"9","price_unit":"cup",
        })
        self.assertEqual(response.status_code,403)
        self.em.refresh_from_db()
        self.assertIsNone(self.em.unit_price_toman)
        self.assertEqual(self.em.price_unit,"session")
        self.assertEqual(self.client.get(reverse("treatment_catalog_settings")).status_code,403)

    def test_existing_treatment_can_be_edited_and_persists(self):
        item=TreatmentCatalogItem.objects.create(
            category="diet",name="رژیم قبل",branch=None,notes="قدیمی",
        )
        self.client.force_login(self.role_admin)
        response=self.client.post(reverse("treatment_catalog_settings"),{
            "action":"save","item_id":str(item.pk),
            "category":"diet","name":"رژیم اصلاح شده",
            "price_toman":"2.5","unit_label":"نسخه",
            "notes":"توضیح جدید","sort_order":"15","is_active":"1","branch":"",
        },follow=True)
        self.assertEqual(response.status_code,200)
        item.refresh_from_db()
        self.assertEqual(item.name,"رژیم اصلاح شده")
        self.assertEqual(item.notes,"توضیح جدید")
        self.assertEqual(item.price_toman,Decimal("2500000"))
        self.assertEqual(TreatmentCatalogItem.objects.filter(pk=item.pk).count(),1)
        self.assertContains(response,"رژیم اصلاح شده")
        self.assertContains(response,"ویرایش اطلاعات")

    def test_base_tariff_input_is_in_million_toman(self):
        self.client.force_login(self.role_admin)
        response=self.client.post(reverse("treatment_catalog_settings"),{
            "action":"base_device_tariff","base_price_toman":"10",
        },follow=True)
        self.assertEqual(response.status_code,200)
        from core.models import DeviceBaseTariff
        self.assertEqual(DeviceBaseTariff.current(),Decimal("10000000"))
        self.assertContains(response,'value="10"')
