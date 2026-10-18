from datetime import timedelta, time
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Branch, EmployeeProfile, CustomerPortalOTP, CustomerPortalMember,
    CustomerServiceRequest, CustomerClubReferral, CustomerClubPoints,
    CustomerClubPolicy, VisitAppointment,
)


class CustomerPortalTests(TestCase):
    def setUp(self):
        cache.clear()
        self.branch=Branch.objects.create(name='تست کلینیک')
        self.user=User.objects.create_user(username='cust-center',password='securepass!')
        self.staff=EmployeeProfile.objects.get(user=self.user)
        self.staff.role='call_center'
        self.staff.branch=self.branch
        self.staff.save(update_fields=['role','branch'])

    def authenticate_customer(self,phone='09123456789'):
        member=CustomerPortalMember.objects.create(
            phone=phone,full_name='مراجع نمونه',referral_code='GLC'+phone[-9:]
        )
        session=self.client.session
        session['gl_customer_member_id']=member.id
        session['gl_customer_auth_at']=timezone.now().timestamp()
        session.save()
        return member

    def test_patient_buttons_never_open_staff_booking_or_referrals(self):
        from core.models import TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection
        user=User.objects.create_superuser('orange-test','orange-test@t.test','pass')
        item=TreatmentCatalogItem.objects.create(category='diet',name='Por-150')
        content=TreatmentRichContent.objects.create(master_item=item,is_active=True)
        TreatmentRichSection.objects.create(content=content,title='صبحانه',body='پرتقال')
        self.client.force_login(user)
        page=self.client.get(reverse('diet_daily_preview',args=[item.pk]))
        self.assertEqual(page.status_code,200)
        source=page.content.decode('utf-8')
        for destination in (
            reverse('customer_club'),
            reverse('customer_request',args=['visit']),
            reverse('customer_request',args=['device'])
        ):
            self.assertIn('href="%s"' % destination,source)
        self.assertNotIn('href="/appointments/"',source)
        self.assertNotIn('href="/device-bookings/"',source)
        self.assertNotIn('href="/referrals/"',source)

    def test_needs_real_sms_otp_and_uses_one_time_code(self):
        member_response=self.client.get(reverse('customer_request',args=['visit']))
        self.assertEqual(member_response.status_code,302)
        with patch('core.customer_portal_views.send_sms') as sent:
            sent.return_value=(Mock(pk=1234),{})
            resp=self.client.post(reverse('customer_login'),{
                'action':'send','phone':'09123456789'
            })
        self.assertEqual(resp.status_code,200)
        self.assertEqual(sent.call_count,1)
        otp=CustomerPortalOTP.objects.get(phone='09123456789')
        self.assertTrue(otp.code_hash)
        self.assertEqual(self.client.session.get('gl_pending_phone'),'09123456789')
        self.assertIsNone(self.client.session.get('gl_customer_member_id'))
        denied=self.client.post(reverse('customer_login'),{'action':'verify','code':'000001'})
        self.assertEqual(denied.status_code,200)
        self.assertIsNone(self.client.session.get('gl_customer_member_id'))
        from django.contrib.auth.hashers import make_password
        otp.refresh_from_db()
        otp.code_hash=make_password('123456')
        otp.save(update_fields=['code_hash'])
        result=self.client.post(reverse('customer_login'),{'action':'verify','code':'123456'})
        self.assertEqual(result.status_code,302)
        self.assertTrue(self.client.session.get('gl_customer_member_id'))
        otp.refresh_from_db()
        self.assertFalse(otp.code_hash)

    def test_visit_request_routes_to_staff_and_never_confirms_without_crm_appointment(self):
        member=self.authenticate_customer()
        url=reverse('customer_request',args=['visit'])
        form={
            'full_name':'مراجع نمونه','branch':str(self.branch.pk),
            'preferred_date':timezone.localdate().isoformat(),
            'daypart':'morning','note':'تماس پیش از ظهر',
        }
        result=self.client.post(url,form)
        self.assertRedirects(result,url)
        row=CustomerServiceRequest.objects.get(member=member)
        self.assertEqual(row.status,'pending')
        self.assertEqual(row.kind,'visit')
        self.assertEqual(row.branch_id,self.branch.pk)
        duplicate=self.client.post(url,form)
        self.assertEqual(duplicate.status_code,200)
        self.assertEqual(CustomerServiceRequest.objects.filter(member=member).count(),1)
        self.client.force_login(self.user)
        self.assertEqual(self.client.get(reverse('staff_customer_requests')).status_code,200)
        act=reverse('staff_customer_request_action',args=[row.pk])
        self.assertEqual(self.client.post(act,{'action':'claim'}).status_code,302)
        row.refresh_from_db()
        self.assertEqual(row.status,'contacted')
        self.assertEqual(row.assigned_to_id,self.staff.pk)
        bad=self.client.post(act,{'action':'book','booking_id':'9999999'})
        self.assertEqual(bad.status_code,404)
        row.refresh_from_db()
        self.assertEqual(row.status,'contacted')
        apt=VisitAppointment.objects.create(
            branch=self.branch,full_name='مراجع نمونه',phone=member.phone,
            appointment_date=timezone.localdate()+timedelta(days=1),
            appointment_time=time(10,0),
        )
        done=self.client.post(act,{'action':'book','booking_id':str(apt.pk)})
        self.assertEqual(done.status_code,302)
        row.refresh_from_db()
        self.assertEqual(row.status,'booked')
        self.assertEqual(row.visit_appointment_id,apt.pk)

    def test_branch_scoped_device_inbox_and_referrals_do_not_auto_award(self):
        owner=self.authenticate_customer()
        branch2=Branch.objects.create(name='مرکز دوم')
        device_req=CustomerServiceRequest.objects.create(member=owner,branch=branch2,kind='device')
        consultant=User.objects.create_user(username='branch-consultant',password='securepass!')
        consultant_profile=EmployeeProfile.objects.get(user=consultant)
        consultant_profile.role='consultant'
        consultant_profile.branch=self.branch
        consultant_profile.save(update_fields=['role','branch'])
        self.client.force_login(consultant)
        self.assertNotContains(self.client.get(reverse('staff_customer_requests')+'?status=all'),str(owner.phone))
        from django.http import Http404
        with self.assertRaises(Http404):
            # The staff action cannot access another branch even by guessed ID.
            from core.customer_portal_views import staff_customer_request_action
            from django.test import RequestFactory
            req=RequestFactory().post('/',{'action':'claim'})
            req.user=consultant
            staff_customer_request_action(req,device_req.pk)
        friend=CustomerPortalMember.objects.create(
            phone='09121111111',referral_code='GLCFRIENDABC'
        )
        referral=CustomerClubReferral.objects.create(referrer=owner,invited=friend)
        self.assertFalse(CustomerClubPoints.objects.filter(referral=referral).exists())
        self.client.force_login(User.objects.create_superuser('portal-admin','portal-admin@example.com','pass'))
        rsp=self.client.post(reverse('staff_customer_club'),{
            'action':'policy','referral_points':'15','enabled':'on'
        })
        self.assertEqual(rsp.status_code,302)
        # A referral is not proof of an actual attended visit.
        rsp=self.client.post(reverse('staff_customer_club'),{
            'action':'qualify','referral_id':referral.pk
        })
        self.assertEqual(rsp.status_code,200)
        self.assertFalse(CustomerClubPoints.objects.filter(referral=referral).exists())
        VisitAppointment.objects.create(
            branch=branch2,full_name='دوست',phone=friend.phone,
            status='arrived',appointment_date=timezone.localdate(),
            appointment_time=time(11,0),
        )
        rsp=self.client.post(reverse('staff_customer_club'),{
            'action':'qualify','referral_id':referral.pk
        })
        self.assertEqual(rsp.status_code,302)
        self.assertEqual(CustomerClubPoints.objects.get(referral=referral).amount,15)
        self.client.post(reverse('staff_customer_club'),{
            'action':'award','referral_id':referral.pk
        })
        self.assertEqual(CustomerClubPoints.objects.filter(referral=referral).count(),1)
