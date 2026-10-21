import json
import uuid
from django.test import TestCase,Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from core.models import PatientProfile,PatientDietProgram,TreatmentCatalogItem,TreatmentRichContent,TreatmentRichSection,CustomerPortalMember,DietMealCheckin,DietFoodChange
from core.diet_companion_views import plan_data

class DietCompanionTests(TestCase):
    def setUp(self):
        self.patient=PatientProfile.objects.create(full_name='مراجع آزمایشی',phone='09123456789')
        self.other=PatientProfile.objects.create(full_name='دیگر',phone='09123456780')
        self.member=CustomerPortalMember.objects.create(phone=self.patient.phone,referral_code='diet-test')
        self.item=TreatmentCatalogItem.objects.create(name='Test-13',category='diet')
        self.content=TreatmentRichContent.objects.create(master_item=self.item,presentation_template='thirteen',is_active=True)
        TreatmentRichSection.objects.create(content=self.content,title='برنامه غذایی',body='روز ۱\nصبحانه\nمتن پزشک بدون تغییر\nروز ۵\nناهار\nعدسی\nروز ۱۳\nشام\nسالاد',meal_slot='other')
        self.program=PatientDietProgram.objects.create(patient=self.patient,diet_name=self.item.name,catalog_item=self.item)
        self.other_program=PatientDietProgram.objects.create(patient=self.other,diet_name=self.item.name,catalog_item=self.item)
        self.url=reverse('customer_diet',args=[self.program.pk]);self.log=reverse('customer_diet_log',args=[self.program.pk])
        self.login_customer()
    def login_customer(self):
        session=self.client.session;session['gl_customer_member_id']=self.member.pk;session['gl_customer_auth_at']=timezone.now().timestamp();session.save()
    def post(self,data,url=None):return self.client.post(url or self.log,json.dumps(data),content_type='application/json')
    def meal(self,day=5,status='planned'):
        days,_=plan_data(self.content)
        return {'action':'meal','day':day,'key':days[day-1]['cards'][0]['key'],'status':status,'note':'ثبت آزمایشی'}
    def test_patient_only_own_prescription_and_session_required(self):
        self.assertEqual(self.client.get(self.url).status_code,200)
        self.assertEqual(self.client.get(reverse('customer_diet',args=[self.other_program.pk])).status_code,404)
        self.assertEqual(self.post(self.meal(),reverse('customer_diet_log',args=[self.other_program.pk])).status_code,404)
        self.client=Client();self.assertEqual(self.client.get(self.url).status_code,302)
        self.assertEqual(self.post(self.meal()).status_code,302)
    def test_out_of_order_persists_idempotent_and_new_course_is_separate(self):
        for day in [5,1,13]:self.assertEqual(self.post(self.meal(day)).status_code,200)
        for _ in range(3):self.post(self.meal(5))
        self.assertEqual(DietMealCheckin.objects.count(),3)
        data=self.post(self.meal(5,'replacement')).json();self.assertEqual(sorted(data['completed_days']),[1,5,13])
        self.assertEqual(len(data['badges']),2)
        response=self.client.get(self.url);self.assertContains(response,'متن پزشک بدون تغییر');self.assertContains(response,'replacement')
        new=PatientDietProgram.objects.create(patient=self.patient,diet_name=self.item.name,catalog_item=self.item)
        self.assertNotContains(self.client.get(reverse('customer_diet',args=[new.pk])),'ثبت آزمایشی')
    def test_undo_and_invalid_meal_cannot_write(self):
        self.post(self.meal());self.post(self.meal(status=''));self.assertEqual(DietMealCheckin.objects.count(),0)
        bad=self.meal();bad['key']='foreign-key';self.assertEqual(self.post(bad).status_code,400)
        self.assertEqual(self.post({'action':'meal','day':99}).status_code,400)
        self.assertEqual(self.client.post(self.log,'[]',content_type='application/json').status_code,400)
    def test_change_once_not_rewarded_as_adherence_and_escaped(self):
        entry={'action':'change','day':5,'food':'<script>alert(1)</script>','amount':'یک عدد','reason':'party','request_id':str(uuid.uuid4())}
        self.post(entry);result=self.post(entry).json()
        self.assertEqual(DietFoodChange.objects.count(),1);self.assertEqual(result['completed_days'],[]);self.assertEqual(result['badges'],[])
        self.assertNotContains(self.client.get(self.url),'<script>alert(1)</script>',html=False)
    def test_paused_draft_and_csrf_protected(self):
        secure=Client(enforce_csrf_checks=True);session=secure.session;session.update(self.client.session);session.save()
        self.assertEqual(secure.post(self.log,json.dumps(self.meal()),content_type='application/json').status_code,403)
        self.program.status='paused';self.program.save();self.assertEqual(self.post(self.meal()).status_code,409)
        self.content.is_active=False;self.content.save();self.assertEqual(self.client.get(self.url).status_code,404)
    def test_demo_does_not_write_and_staff_authorization(self):
        url=reverse('diet_companion_preview',args=[self.item.pk]);self.assertEqual(self.client.get(url).status_code,302)
        admin=User.objects.create_superuser('diet-admin','diet@example.com','test');self.client.force_login(admin)
        self.assertContains(self.client.get(url),'پیش‌نمایش آزمایشی');self.assertEqual(DietMealCheckin.objects.count(),0)
    def test_four_templates_and_legacy_name_resolution(self):
        self.program.catalog_item=None;self.program.save();self.assertEqual(self.client.get(self.url).status_code,200)
        for kind in ['weekly','ramadan','text']:
            self.content.presentation_template=kind;self.content.save();response=self.client.get(self.url)
            self.assertEqual(response.status_code,200)
    def test_ambiguous_code_fails_closed(self):
        self.program.catalog_item=None;self.program.save()
        duplicate=TreatmentCatalogItem.objects.create(name=self.item.name,category='diet')
        TreatmentRichContent.objects.create(master_item=duplicate,is_active=True)
        self.assertEqual(self.client.get(self.url).status_code,404)
