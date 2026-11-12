import json
import uuid
from datetime import timedelta
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from core.models import CustomerPortalMember, Branch, EmployeeProfile, CustomerServiceRequest, StaffNotification, PatientProfile, PatientDietProgram, TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection
from core.me_diet_models import MeMealReport
from core.me_sync_models import MeDailyAward
from core.me_diet_views import today


class MeDietTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='شعبه آزمون')
        self.member=CustomerPortalMember.objects.create(phone='09123456789',referral_code='diet-member',full_name='عضو آزمایشی')
        self.user=User.objects.create_user('diet-agent',password='test')
        self.staff=self.user.profile;self.staff.role='call_center';self.staff.branch=self.branch;self.staff.save()
        s=self.client.session;s['gl_customer_member_id']=self.member.pk;s['gl_customer_auth_at']=timezone.now().timestamp();s.save()
        self.url=reverse('me_diet')

    def post(self,**data):return self.client.post(self.url,json.dumps(data),content_type='application/json')
    def help_data(self):return dict(action='help',name='عضو آزمایشی',reason='contact',note='آزمون درخواست',consent=True,branch=self.branch.pk,token=str(uuid.uuid4()))

    def test_auth_csrf_and_member_isolation(self):
        self.assertEqual(Client().get(self.url).status_code,401)
        secure=Client(enforce_csrf_checks=True);s=secure.session;s.update(self.client.session);s.save()
        self.assertEqual(secure.post(self.url,'{}',content_type='application/json').status_code,403)
        other=CustomerPortalMember.objects.create(phone='09123456780',referral_code='other')
        MeMealReport.objects.create(member=other,day=today(),meal_key='breakfast',label='خصوصی',status='planned')
        self.assertEqual(self.client.get(self.url).json()['reported'],0)

    def test_every_honest_status_counts_once_and_no_fake_adherence(self):
        keys=['breakfast','lunch','dinner','snacks']
        for k,s in zip(keys,['partial','replacement','skipped','help']):
            r=self.post(action='meal',key=k,status=s,revision=0);self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['percent'],100);self.assertEqual(r.json()['hearts'],1)
        self.assertEqual(MeDailyAward.objects.count(),1)
        self.assertEqual(self.post(action='meal',key='snacks',status='planned',revision=1).status_code,200)
        self.assertEqual(MeDailyAward.objects.count(),1)
        self.assertEqual(self.post(action='meal',key='snacks',status='partial',revision=1).status_code,409)
        self.assertEqual(self.member.me_state.values['greenlife-heart-v1']['days'],{})

    def test_existing_daily_award_never_doubles(self):
        MeDailyAward.objects.create(member=self.member,day=today())
        for k in ['breakfast','lunch','dinner','snacks']:self.post(action='meal',key=k,status='planned',revision=0)
        self.assertEqual(MeDailyAward.objects.count(),1)

    def test_invalid_and_future_fail_closed(self):
        for data in [dict(action='meal',key='foreign',status='planned',revision=0),dict(action='meal',key='breakfast',status='planned',revision=0,day=str(today()+timedelta(days=1))),dict(action='meal',key='breakfast',status='invalid',revision=0)]:self.assertEqual(self.post(**data).status_code,400)
        self.assertEqual(MeMealReport.objects.count(),0)

    def test_help_reaches_queue_notification_response_and_idempotency(self):
        data=self.help_data();r=self.post(**data);self.assertEqual(r.status_code,200)
        pk=r.json()['sent']['id'];self.post(**data);self.post(**self.help_data())
        self.assertEqual(CustomerServiceRequest.objects.count(),1)
        self.assertTrue(StaffNotification.objects.filter(user=self.user,title__contains='رژیم').exists())
        staff=Client();staff.force_login(self.user)
        self.assertContains(staff.get(reverse('staff_customer_requests')),'آزمون درخواست')
        self.assertEqual(staff.post(reverse('staff_customer_request_action',args=[pk]),{'action':'claim'}).status_code,302)
        self.assertEqual(self.client.get(self.url).json()['requests'][0]['status'],'contacted')
        self.assertEqual(staff.post(reverse('staff_customer_request_action',args=[pk]),{'action':'resolve','staff_note':'درخواست شما برای بررسی دریافت شد.'}).status_code,302)
        r=self.client.get(self.url).json()['requests'][0];self.assertEqual(r['status'],'resolved');self.assertIn('بررسی',r['reply'])
        self.post(**data);self.assertEqual(CustomerServiceRequest.objects.count(),1)
        self.assertEqual(MeDailyAward.objects.count(),0)

    def test_help_requires_consent_and_staff_permissions(self):
        data=self.help_data();data['consent']=False;self.assertEqual(self.post(**data).status_code,400)
        data['consent']=True;r=self.post(**data);pk=r.json()['sent']['id']
        other=User.objects.create_user('other-agent',password='test');other.profile.role='employee';other.profile.save()
        c=Client();c.force_login(other);self.assertIn(c.post(reverse('staff_customer_request_action',args=[pk]),{'action':'resolve','staff_note':'no'}).status_code,[403,404])

    def test_actual_prescription_text_and_meal_keys(self):
        patient=PatientProfile.objects.create(full_name='آزمون',phone=self.member.phone)
        item=TreatmentCatalogItem.objects.create(name='Test-Diet',category='diet')
        content=TreatmentRichContent.objects.create(master_item=item,presentation_template='text',is_active=True)
        TreatmentRichSection.objects.create(content=content,title='وعده پزشک',body='متن نسخه بدون تغییر',meal_slot='other')
        p=PatientDietProgram.objects.create(patient=patient,diet_name=item.name,catalog_item=item)
        r=self.client.get(self.url).json();self.assertEqual(r['program']['id'],p.pk);self.assertEqual(r['meals'][0]['body'],'متن نسخه بدون تغییر')
        self.assertEqual(self.post(action='meal',key='breakfast',status='planned',revision=0).status_code,400)
        self.assertEqual(self.post(action='meal',key=r['meals'][0]['key'],status='replacement',revision=0).status_code,200)
