import uuid
from datetime import timedelta
from django.test import TestCase,Client
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import CustomerPortalMember
from core.me_diet_models import MeMealReport
from core.me_members_models import MeMemberAction,MeMemberCare
class MemberTests(TestCase):
 def setUp(self):
  self.u=User.objects.create_superuser('member-owner','x@example.com','test');self.client.force_login(self.u)
  self.m=CustomerPortalMember.objects.create(phone='09123456789',full_name='عضو آزمایش',referral_code='one')
  self.other=CustomerPortalMember.objects.create(phone='09123456780',full_name='عضو دوم',referral_code='two')
  self.url=f'/greenlife-me/members/{self.m.pk}/'
 def data(self,kind='note',**kw):
  d=dict(kind=kind,body='متن نمونه',token=str(uuid.uuid4()),revision=0,reviewed_through=timezone.now().isoformat());d.update(kw);return d
 def test_dashboard_all_members_and_detail(self):
  r=self.client.get('/greenlife-me/members/');self.assertEqual(r.status_code,200);self.assertEqual(r.context['counts']['total'],2);self.assertContains(r,'عضو دوم')
  self.assertContains(self.client.get(self.url),'ثبت پاسخ به عضو');self.assertFalse(MeMemberCare.objects.exists())
 def test_permissions(self):
  u=User.objects.create_user('ordinary');self.client.force_login(u);self.assertEqual(self.client.get(self.url).status_code,403)
  u.profile.role='internal_manager';u.profile.save();r=self.client.get(self.url);self.assertEqual(r.status_code,200);self.assertNotContains(r,self.m.phone)
  self.assertNotContains(self.client.get('/greenlife-me/members/?q='+self.m.phone),'عضو آزمایش')
  u.profile.is_active=False;u.profile.save();self.assertEqual(self.client.get(self.url).status_code,403)
 def test_points_idempotency_and_conflict(self):
  d=self.data('points',points=7);self.assertEqual(self.client.post(self.url,d).status_code,200);self.assertEqual(self.client.post(self.url,d).status_code,200);self.assertEqual(MeMemberAction.objects.count(),1)
  self.assertEqual(self.client.post(self.url,self.data()).status_code,400)
  self.assertEqual(self.client.post(self.url,self.data('points',points=101,revision=1)).status_code,400)
 def test_inbox_isolation(self):
  self.client.post(self.url,self.data('note',body='سرّ داخلی'))
  self.client.post(self.url,self.data('reply',revision=1,body='پاسخ عمومی'))
  c=Client();s=c.session;s['gl_customer_member_id']=self.m.pk;s['gl_customer_auth_at']=timezone.now().timestamp();s.save();r=c.get('/customer/me/messages/');self.assertContains(r,'پاسخ عمومی');self.assertNotContains(r,'سرّ داخلی')
  s=c.session;s['gl_customer_member_id']=self.other.pk;s.save();self.assertNotContains(c.get('/customer/me/messages/'),'پاسخ عمومی')
 def test_review_then_new_report(self):
  meal=MeMealReport.objects.create(member=self.m,day=timezone.localdate(),meal_key='lunch',label='ناهار',status='reported',note='کمک')
  self.assertEqual(self.client.get('/greenlife-me/members/').context['counts']['notes'],1)
  self.assertEqual(self.client.post(self.url,self.data('review')).status_code,200)
  self.assertEqual(self.client.get('/greenlife-me/members/').context['counts']['notes'],0)
  meal.note='دوباره';meal.save();self.assertEqual(self.client.get('/greenlife-me/members/').context['counts']['notes'],1)
 def test_followup_validation(self):
  self.assertEqual(self.client.post(self.url,self.data('followup',followup_at=(timezone.now()-timedelta(days=1)).isoformat())).status_code,400)
  self.assertFalse(MeMemberAction.objects.exists())
 def test_counts_and_real_attendance(self):
  from datetime import time
  from core.models import Branch,VisitAppointment
  b=Branch.objects.create(name='آزمون')
  a=VisitAppointment.objects.create(branch=b,full_name='آزمون',phone='+989123456789',appointment_date=timezone.localdate(),appointment_time=time(10),status='booked')
  for key in ('a','b'):
   MeMealReport.objects.create(member=self.m,day=timezone.localdate(),meal_key=key,label=key,status='reported')
  r=self.client.get('/greenlife-me/members/');self.assertEqual(r.context['counts']['total'],2);self.assertEqual(r.context['counts']['visited'],0)
  a.status='arrived';a.save();r=self.client.get('/greenlife-me/members/');self.assertEqual(r.context['counts']['visited'],1);self.assertEqual(r.context['counts']['unvisited'],1)
