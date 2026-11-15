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
 def test_payments_units_status_and_no_double_count(self):
  from decimal import Decimal
  from datetime import time
  from core.models import Branch,VisitAppointment,FinancialTransaction,PatientProfile
  b=Branch.objects.create(name='پرداخت آزمون')
  a=VisitAppointment.objects.create(branch=b,full_name='آزمون',phone=self.m.phone,appointment_date=timezone.localdate(),appointment_time=time(10))
  def receipt(amount,**kw):
   return FinancialTransaction.objects.create(amount=amount,occurred_at=timezone.now(),source='manual',patient_ref=self.m.phone,**kw)
  receipt(100000000,appointment=a)
  receipt(100000000) # equal-sized separate receipts must both count
  receipt(100000000,review_status='pending')
  receipt(100000000,review_status='cancelled')
  receipt(100000000,entry_type='exp')
  PatientProfile.objects.create(full_name='آزمون',phone=self.m.phone,crm_id='MEMBER-CRM')
  FinancialTransaction.objects.create(amount=100000000,occurred_at=timezone.now(),patient_ref='MEMBER-CRM')
  r=self.client.get('/greenlife-me/members/');row=next(x for x in r.context['rows'] if x.pk==self.m.pk)
  self.assertEqual(row.paid_total,Decimal('300000000'));self.assertContains(r,'>30</strong>');self.assertContains(r,'میلیون تومان')
  self.assertEqual(next(x for x in r.context['rows'] if x.pk==self.other.pk).paid_total,0)
  self.assertContains(self.client.get(self.url),'>30</strong>')
 def test_payment_privacy_and_authoritative_appointment(self):
  from datetime import time
  from core.models import Branch,VisitAppointment,FinancialTransaction
  b=Branch.objects.create(name='آزمون مالی')
  a=VisitAppointment.objects.create(branch=b,full_name='آزمون',phone=self.other.phone,appointment_date=timezone.localdate(),appointment_time=time(10))
  FinancialTransaction.objects.create(amount=300000000,occurred_at=timezone.now(),patient_ref=self.m.phone,appointment=a)
  r=self.client.get('/greenlife-me/members/');paid={x.pk:x.paid_total for x in r.context['rows']}
  self.assertEqual(paid[self.m.pk],0);self.assertEqual(paid[self.other.pk],300000000)
  u=User.objects.create_user('limited-finance');u.profile.role='internal_manager';u.profile.save();self.client.force_login(u)
  r=self.client.get('/greenlife-me/members/');self.assertFalse(any(hasattr(x,'paid_total') for x in r.context['rows']));self.assertNotContains(r,'>30</strong>');self.assertNotContains(self.client.get(self.url),'کل پرداختی تأییدشده')
 def test_visit_modes_and_name(self):
  from datetime import time
  from core.models import Branch,VisitAppointment,PatientProfile
  b=Branch.objects.create(name='mode');self.m.full_name='';self.m.save();PatientProfile.objects.create(full_name='نام پرونده',phone=self.m.phone)
  a=VisitAppointment.objects.create(branch=b,full_name='name',phone=self.m.phone,appointment_date=timezone.localdate(),appointment_time=time(10),visit_mode='online',status='booked')
  r=self.client.get('/greenlife-me/members/');m=next(x for x in r.context['rows'] if x.pk==self.m.pk);self.assertIsNone(m.last_mode);self.assertEqual(m.display_name,'نام پرونده')
  a.status='completed';a.save();r=self.client.get('/greenlife-me/members/');m=next(x for x in r.context['rows'] if x.pk==self.m.pk);self.assertEqual(m.last_mode,'online')
  VisitAppointment.objects.create(branch=b,full_name='name',phone=self.m.phone,appointment_date=timezone.localdate(),appointment_time=time(11),visit_mode='in_person',status='arrived')
  r=self.client.get('/greenlife-me/members/');m=next(x for x in r.context['rows'] if x.pk==self.m.pk);self.assertEqual(m.last_mode,'in_person');self.assertTrue(m.has_online and m.has_in_person)
