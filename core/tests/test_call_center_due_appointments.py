from datetime import timedelta
from django.test import TestCase
from django.utils import timezone

from core.call_center_kpi import due_call_center_appointment_counts
from core.models import Branch, EmployeeProfile, ReferralLead, ReferralProfile, VisitAppointment
from django.contrib.auth.models import User


class DueAppointmentKpiTests(TestCase):
    def test_future_booking_is_not_a_missed_visit(self):
        branch=Branch.objects.create(name='Due KPI Branch')
        user=User.objects.create_user('due-operator',password='pass')
        EmployeeProfile.objects.update_or_create(user=user,defaults={'role':'call_center','branch':branch,'is_active':True})
        source=User.objects.create_user('due-source',password='pass')
        ref=ReferralProfile.objects.create(user=source,referral_code='GLDUETEST',created_by=source)
        lead=ReferralLead.objects.create(referrer=ref,full_name='آینده',phone='09121110000',assigned_to=user.profile,first_appointment_by=user)
        today=timezone.localdate()
        VisitAppointment.objects.create(lead=lead,branch=branch,full_name='آینده',phone=lead.phone,appointment_date=today+timedelta(days=2),appointment_time=timezone.datetime.strptime('11:00','%H:%M').time(),source='call_center',created_by=user,status='booked')
        due,visited=due_call_center_appointment_counts(user.profile,today.replace(day=1),today)
        self.assertEqual((due,visited),(0,0))
