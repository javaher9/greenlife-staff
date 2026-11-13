from datetime import timedelta, time
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import Branch, CustomerPortalMember, CustomerServiceRequest, CustomerIntake, CustomerRequestEvent, VisitAppointment

class MeDeskTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='desk test')
        self.other=Branch.objects.create(name='desk other')
        self.member=CustomerPortalMember.objects.create(phone='09123450000',full_name='عضو نمونه',referral_code='desk-test')
        self.row=CustomerServiceRequest.objects.create(member=self.member,kind='visit',branch=self.branch)
        CustomerIntake.objects.create(request=self.row,city='تهران',goal='هدف نمونه')
        self.u,self.c=self.staff('call_center')
        self.detail=f'/call-center/greenlife-me/{self.row.pk}/'
        self.action=f'/staff/customer-requests/{self.row.pk}/action/'
    def staff(self,role,branch=None):
        u=User.objects.create_user(username='desk-'+str(User.objects.count()));p=u.profile;p.role=role;p.branch=branch or self.branch;p.save();c=Client();c.force_login(u);return u,c
    def test_scope_and_private_detail(self):
        self.assertEqual(Client().get(self.detail).status_code,403)
        _,wrong=self.staff('manager',self.other);self.assertEqual(wrong.get(self.detail).status_code,404)
        _,consultant=self.staff('consultant');self.assertEqual(consultant.get(self.detail).status_code,403)
        response=self.c.get(self.detail);self.assertContains(response,'هدف نمونه');self.assertEqual(response['Cache-Control'],'private, no-store')
        self.assertContains(self.c.get('/call-center/greenlife-me/?q=09123450000'),'عضو نمونه')
        self.assertNotContains(self.c.get('/call-center/greenlife-me/?q=999999'),'عضو نمونه')
    def test_claim_followup_and_other_operator_denial(self):
        response=self.c.post(self.action,{'action':'claim','return_to':'me_desk'});self.assertRedirects(response,self.detail)
        self.assertEqual(CustomerRequestEvent.objects.count(),1)
        future=(timezone.localtime()+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        response=self.c.post(self.detail+'followup/',{'outcome':'callback','note':'یادداشت خصوصی تماس','next_contact':future})
        self.assertRedirects(response,self.detail);self.row.refresh_from_db();self.assertIsNotNone(self.row.next_followup_at);self.assertEqual(self.row.assigned_to_id,self.u.profile.pk)
        _,other=self.staff('call_center');self.assertEqual(other.post(self.detail+'followup/',{'outcome':'note','note':'overwrite'}).status_code,403)
        self.assertEqual(CustomerRequestEvent.objects.count(),2)
        customer=Client();s=customer.session;s['gl_customer_member_id']=self.member.pk;s['gl_customer_auth_at']=timezone.now().timestamp();s.save()
        self.assertNotContains(customer.get('/customer/request/visit/'),'یادداشت خصوصی تماس')
    def test_due_filter_and_close_history(self):
        self.row.next_followup_at=timezone.now()-timedelta(hours=1);self.row.save()
        self.assertContains(self.c.get('/call-center/greenlife-me/?view=overdue'),'عضو نمونه')
        self.c.post(self.action,{'action':'decline','staff_note':'درخواست خود مراجعه‌کننده','return_to':'me_desk'})
        self.row.refresh_from_db();self.assertIsNone(self.row.next_followup_at)
        self.assertContains(self.c.get(self.detail),'درخواست خود مراجعه‌کننده')
        self.assertNotContains(self.c.get('/call-center/greenlife-me/?view=overdue'),'عضو نمونه')
        self.assertEqual(self.c.post(self.detail+'followup/',{'outcome':'note','note':'closed'}).status_code,403)
    def test_invalid_callback_does_not_change_record(self):
        response=self.c.post(self.detail+'followup/',{'outcome':'callback','note':'زمان ندارد'})
        self.assertEqual(response.status_code,302);self.row.refresh_from_db();self.assertEqual(self.row.status,'pending');self.assertFalse(CustomerRequestEvent.objects.exists())
    def test_real_booking_match_and_timeline(self):
        booking=VisitAppointment.objects.create(branch=self.branch,full_name='عضو نمونه',phone='09129999999',appointment_date=timezone.localdate(),appointment_time=time(10),status='booked')
        self.assertEqual(self.c.post(self.action,{'action':'book','booking_id':booking.pk}).status_code,403)
        booking.phone=self.member.phone;booking.save()
        self.assertContains(self.c.get(self.detail),'#'+str(booking.pk))
        self.assertEqual(self.c.post(self.action,{'action':'book','booking_id':booking.pk,'return_to':'me_desk'}).status_code,302)
        self.row.refresh_from_db();self.assertEqual(self.row.visit_appointment_id,booking.pk);self.assertEqual(CustomerRequestEvent.objects.get().action,'تأیید نوبت واقعی')
