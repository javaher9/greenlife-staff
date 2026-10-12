"""Regression checks for shared CRM treatment labels and doctor selectors."""
from datetime import time
from importlib import import_module

from django.apps import apps
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Branch, PatientDietProgram, PatientLipolyticProgram,
    TreatmentCatalogItem, VisitAppointment,
)

seed = import_module("core.migrations.0084_seed_treatment_service_master_data")


class TreatmentMasterDataTests(TestCase):
    def test_every_provided_label_is_active_and_shared(self):
        for category, titles in seed.CATALOG_ITEMS.items():
            with self.subTest(category=category):
                rows = TreatmentCatalogItem.objects.filter(
                    category=category,
                    branch__isnull=True,
                    name__in=titles,
                )
                self.assertEqual(rows.count(), len(titles))
                self.assertEqual(set(rows.values_list("name", flat=True)), set(titles))
                self.assertFalse(rows.filter(is_active=False).exists())

    def test_seed_can_run_again_without_creating_duplicates(self):
        counts = {
            category: TreatmentCatalogItem.objects.filter(
                category=category, branch__isnull=True, name__in=titles,
            ).count()
            for category, titles in seed.CATALOG_ITEMS.items()
        }

        class SchemaEditor:
            connection = connection

        seed.seed_catalog_titles(apps, SchemaEditor())
        for category, titles in seed.CATALOG_ITEMS.items():
            self.assertEqual(
                TreatmentCatalogItem.objects.filter(
                    category=category, branch__isnull=True, name__in=titles,
                ).count(), counts[category],
            )

    def test_doctor_selectors_and_saved_titles_use_existing_workflow(self):
        branch = Branch.objects.create(name="شعبه آزمایشی کاتالوگ")
        user = User.objects.create_user(
            username="doctor-master-catalog", password="StrongPass123",
        )
        profile = user.profile
        profile.role = "doctor"
        profile.branch = branch
        profile.is_active = True
        profile.save(update_fields=["role", "branch", "is_active"])
        appointment = VisitAppointment.objects.create(
            branch=branch,
            full_name="بیمار آزمایشی",
            phone="09128887766",
            service="ویزیت",
            appointment_date=timezone.localdate(),
            appointment_time=time(11, 0),
            status="arrived",
            care_stage="doctor",
        )
        self.client.force_login(user)
        response = self.client.get(reverse("doctor_dashboard"))
        self.assertEqual(response.status_code, 200)
        expected = (
            ("diet_options", "Keto-Fast"),
            ("recommendation_options", "40 نکته مهم  لاغری"),
            ("print_template_options", "Fluoxetin 30"),
            ("lipolytic_options", "مزو متا پیور A پلاس"),
        )
        for key, title in expected:
            with self.subTest(key=key):
                self.assertIn(title, [item["name"] for item in response.context[key]])
                self.assertContains(response, 'value="' + title + '"')

        saved = self.client.post(reverse("doctor_dashboard"), {
            "appointment_id": str(appointment.pk),
            "action": "diet",
            "diet_name": "Keto-Fast",
            "recommendation_pack": "40 نکته مهم  لاغری",
            "print_template": "Fluoxetin 30",
        })
        self.assertEqual(saved.status_code, 302)
        diet = PatientDietProgram.objects.get(appointment=appointment)
        self.assertEqual(diet.diet_name, "Keto-Fast")
        self.assertEqual(diet.recommendation_pack, "40 نکته مهم  لاغری")
        self.assertEqual(diet.print_template, "Fluoxetin 30")

        lipolytic = self.client.post(reverse("doctor_dashboard"), {
            "appointment_id": str(appointment.pk),
            "action": "lipolytic",
            "protocol_name": "مزو متا پیور A پلاس",
            "sessions": "1",
        })
        self.assertEqual(lipolytic.status_code, 302)
        self.assertEqual(
            PatientLipolyticProgram.objects.get(appointment=appointment).protocol_name,
            "مزو متا پیور A پلاس",
        )
