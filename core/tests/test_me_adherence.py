from django.test import TestCase, Client
from django.urls import reverse
from django.db import IntegrityError, transaction
from core.tests.test_me_diet import MeDietTests
from core.models import PatientProfile, PatientDietProgram, TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection, Branch
from core.me_diet_models import MeMealReport
from core.me_diet_views import today

class MealAdherenceTests(TestCase):
    setUp=MeDietTests.setUp
    post=MeDietTests.post

    def programme(self):
        self.patient=PatientProfile.objects.create(full_name='آزمون رعایت',phone=self.member.phone,home_branch=self.branch)
        item=TreatmentCatalogItem.objects.create(name='Adherence test',category='diet')
        content=TreatmentRichContent.objects.create(master_item=item,presentation_template='text',is_active=True)
        TreatmentRichSection.objects.create(content=content,title='صبحانه',body='نسخه',meal_slot='other')
        self.program=PatientDietProgram.objects.create(patient=self.patient,diet_name=item.name,catalog_item=item)
        return self.client.get(self.url).json()['meals'][0]['key']

    def test_zero_hundred_unreported_and_revision(self):
        key=self.programme()
        self.assertIsNone(self.client.get(self.url).json()['meals'][0]['report'])
        for revision,percent in enumerate([0,100]):
            response=self.post(action='meal',key=key,adherence_percent=percent,note='توضیح اختصاصی',revision=revision)
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['meals'][0]['report']['adherence_percent'],percent)
        row=MeMealReport.objects.get();self.assertEqual(row.patient,self.patient);self.assertEqual(row.program,self.program)
        self.assertEqual(self.post(action='meal',key=key,adherence_percent=40,revision=0).status_code,409)

    def test_invalid_percent_and_no_implicit_default(self):
        key=self.programme()
        for value in [None,True,False,'50',50.5,-1,101]:
            self.assertEqual(self.post(action='meal',key=key,adherence_percent=value).status_code,400)
        self.assertEqual(self.post(action='meal',key=key,status='reported').status_code,400)
        self.assertEqual(MeMealReport.objects.count(),0)
        self.assertEqual(self.post(action='meal',key=key,status='planned').status_code,200)
        self.assertIsNone(MeMealReport.objects.get().adherence_percent)
        with self.assertRaises(IntegrityError), transaction.atomic():
            MeMealReport.objects.update(adherence_percent=101)

    def test_no_program_note_only(self):
        self.assertEqual(self.post(action='meal',key='breakfast',adherence_percent=50,note='شرح').status_code,400)
        self.assertEqual(self.post(action='meal',key='breakfast',adherence_percent=None,note='شرح').status_code,200)
        self.assertIsNone(MeMealReport.objects.get().adherence_percent)

    def test_staff_record_monitor_and_branch_isolation(self):
        key=self.programme();self.post(action='meal',key=key,adherence_percent=0,note='<script>private-note</script>')
        self.client.force_login(self.user)
        monitor=reverse('me_meal_monitor');record=reverse('patient_360',args=[self.patient.pk])
        self.assertEqual(self.client.get(monitor).status_code,403)
        self.staff.role='doctor';self.staff.save()
        for url in [monitor,record]:
            r=self.client.get(url);self.assertContains(r,'&lt;script&gt;private-note&lt;/script&gt;');self.assertContains(r,'0٪');self.assertIn('no-store',r['Cache-Control'])
        self.staff.branch=Branch.objects.create(name='شعبه دیگر');self.staff.save()
        self.assertNotContains(self.client.get(monitor),'private-note')
        self.assertEqual(self.client.get(record).status_code,403)
        self.staff.branch=None;self.staff.save()
        self.assertNotContains(self.client.get(monitor),'private-note')
        self.staff.role='admin';self.staff.save()
        self.assertContains(self.client.get(monitor),'private-note')
        self.assertEqual(Client().get(monitor).status_code,302)
        MeMealReport.objects.update(patient=None,program=None)
        self.assertContains(self.client.get(record),'private-note')
        self.staff.role='doctor';self.staff.branch=self.branch;self.staff.save()
        self.assertContains(self.client.get(monitor),'private-note')
