from datetime import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.forms import visit_appointment_time_choices
from core.jalali import format_jalali
from core.models import Branch, EmployeeProfile, ReferralLead, ReferralProfile, StaffNotification, VisitAppointment


class SharedAppointmentTests(TestCase):
    def setUp(self):
        self.call_branch=Branch.objects.create(name='کال‌سنتر')
        self.niavaran=Branch.objects.create(name='نیاوران')
        self.poonak=Branch.objects.create(name='پونک')

        self.operator=User.objects.create_user(
            username='appointment-operator',password='pass123456',
            first_name='نرگس',
        )
        EmployeeProfile.objects.update_or_create(
            user=self.operator,
            defaults={'role':'call_center','branch':self.call_branch,'is_active':True},
        )

        self.receptionist=User.objects.create_user(
            username='appointment-reception',password='pass123456',
            first_name='منشی',
        )
        EmployeeProfile.objects.update_or_create(
            user=self.receptionist,
            defaults={'role':'receptionist','branch':self.niavaran,'is_active':True},
        )

        self.other_receptionist=User.objects.create_user(
            username='appointment-reception-2',password='pass123456',
            first_name='منشی دوم',
        )
        EmployeeProfile.objects.update_or_create(
            user=self.other_receptionist,
            defaults={'role':'receptionist','branch':self.poonak,'is_active':True},
        )

        self.referrer_user=User.objects.create_user(
            username='appointment-referrer',password='pass123456',
            first_name='معرف',
        )
        EmployeeProfile.objects.update_or_create(
            user=self.referrer_user,
            defaults={'role':'employee','branch':self.niavaran,'is_active':True},
        )
        self.referrer=ReferralProfile.objects.create(
            user=self.referrer_user,referral_code='GLAPPTROOT',created_by=self.referrer_user,
        )

        self.lead=ReferralLead.objects.create(
            referrer=self.referrer,full_name='بیمار نوبت',phone='09120001111',
            interested_service='لاغری',assigned_to=self.operator.profile,
        )
        self.other_lead=ReferralLead.objects.create(
            referrer=self.referrer,full_name='بیمار دوم',phone='09120002222',
            interested_service='پوست',assigned_to=self.operator.profile,
        )
        self.day=timezone.localdate()
        self.jalali_day=format_jalali(self.day)

    def test_slots_run_every_fifteen_minutes_from_nine_through_eighteen(self):
        values=[value for value,_label in visit_appointment_time_choices()]
        self.assertEqual(values[0],'09:00')
        self.assertEqual(values[-1],'18:00')
        self.assertEqual(len(values),37)
        self.assertIn('09:15',values)
        self.assertIn('17:45',values)

    def test_call_center_can_create_real_appointment_for_own_lead(self):
        self.client.force_login(self.operator)
        response=self.client.post(reverse('call_center_appointment_create',args=[self.lead.pk]),{
            'branch':self.niavaran.pk,
            'appointment_date':self.jalali_day,
            'appointment_time':'09:15',
            'notes':'لطفاً بدون معطلی پذیرش شود',
        })
        self.assertRedirects(response,reverse('call_center_lead',args=[self.lead.pk]))
        item=VisitAppointment.objects.get(lead=self.lead)
        self.assertEqual(item.branch,self.niavaran)
        self.assertEqual(item.appointment_time,time(9,15))
        self.assertEqual(item.source,'call_center')
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status,'appointment')
        self.assertTrue(StaffNotification.objects.filter(
            user=self.receptionist,notification_type='appointment',
        ).exists())
        self.assertFalse(StaffNotification.objects.filter(
            user=self.other_receptionist,notification_type='appointment',
        ).exists())

    def test_call_center_cannot_book_someone_elses_lead(self):
        other_operator=User.objects.create_user(username='other-operator',password='pass123456')
        EmployeeProfile.objects.update_or_create(
            user=other_operator,
            defaults={'role':'call_center','branch':self.call_branch,'is_active':True},
        )
        self.lead.assigned_to=other_operator.profile
        self.lead.save(update_fields=['assigned_to','updated_at'])
        self.client.force_login(self.operator)
        response=self.client.get(reverse('call_center_appointment_create',args=[self.lead.pk]))
        self.assertEqual(response.status_code,404)

    def test_same_branch_same_slot_cannot_be_double_booked(self):
        VisitAppointment.objects.create(
            lead=self.lead,branch=self.niavaran,full_name=self.lead.full_name,
            phone=self.lead.phone,service=self.lead.interested_service,
            appointment_date=self.day,appointment_time=time(10,0),
            source='call_center',created_by=self.operator,
        )
        self.client.force_login(self.operator)
        response=self.client.post(reverse('call_center_appointment_create',args=[self.other_lead.pk]),{
            'branch':self.niavaran.pk,
            'appointment_date':self.jalali_day,
            'appointment_time':'10:00',
            'notes':'',
        })
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'قبلاً رزرو شده')
        self.assertEqual(VisitAppointment.objects.filter(
            branch=self.niavaran,appointment_date=self.day,appointment_time=time(10,0)
        ).exclude(status='cancelled').count(),1)

    def test_same_time_is_available_in_different_branch(self):
        VisitAppointment.objects.create(
            branch=self.niavaran,full_name='نیاوران',phone='09123334444',
            appointment_date=self.day,appointment_time=time(11,0),
            source='receptionist',created_by=self.receptionist,
        )
        VisitAppointment.objects.create(
            branch=self.poonak,full_name='پونک',phone='09125556666',
            appointment_date=self.day,appointment_time=time(11,0),
            source='receptionist',created_by=self.other_receptionist,
        )
        self.assertEqual(VisitAppointment.objects.filter(
            appointment_date=self.day,appointment_time=time(11,0)
        ).count(),2)

    def test_availability_marks_booked_slot_unavailable(self):
        VisitAppointment.objects.create(
            branch=self.niavaran,full_name='بیمار',phone='09127778888',
            appointment_date=self.day,appointment_time=time(12,15),
            source='receptionist',created_by=self.receptionist,
        )
        self.client.force_login(self.operator)
        response=self.client.get(reverse('appointment_availability'),{
            'branch':self.niavaran.pk,
            'date':self.jalali_day,
        })
        self.assertEqual(response.status_code,200)
        data=response.json()
        slot=next(x for x in data['slots'] if x['value']=='12:15')
        self.assertFalse(slot['available'])
        free=next(x for x in data['slots'] if x['value']=='12:30')
        self.assertTrue(free['available'])

    def test_receptionist_dashboard_sees_only_own_branch_real_appointments(self):
        VisitAppointment.objects.create(
            branch=self.niavaran,full_name='مراجعه نیاوران',phone='09121110000',
            service='لاغری',appointment_date=self.day,appointment_time=time(13,0),
            source='call_center',created_by=self.operator,
        )
        VisitAppointment.objects.create(
            branch=self.poonak,full_name='مراجعه پونک',phone='09122220000',
            service='پوست',appointment_date=self.day,appointment_time=time(13,15),
            source='call_center',created_by=self.operator,
        )
        self.client.force_login(self.receptionist)
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        )
        self.assertContains(response,'مراجعه نیاوران')
        self.assertNotContains(response,'مراجعه پونک')
        self.assertContains(response,'نوبت‌های واقعی همین شعبه')
        self.assertNotContains(response,'پزشک / مشاور')

    def test_receptionist_can_create_manual_appointment_in_own_branch(self):
        self.client.force_login(self.receptionist)
        response=self.client.post(reverse('receptionist_appointment_create'),{
            'full_name':'مراجعه دستی',
            'phone':'09129990000',
            'service':'مشاوره',
            'appointment_date':self.jalali_day,
            'appointment_time':'14:45',
            'notes':'ثبت توسط منشی',
        })
        self.assertEqual(response.status_code,302)
        item=VisitAppointment.objects.get(full_name='مراجعه دستی')
        self.assertEqual(item.branch,self.niavaran)
        self.assertEqual(item.source,'receptionist')

    def test_receptionist_cannot_query_other_branch_availability(self):
        self.client.force_login(self.receptionist)
        response=self.client.get(reverse('appointment_availability'),{
            'branch':self.poonak.pk,
            'date':self.jalali_day,
        })
        self.assertEqual(response.status_code,403)

    def test_cancelled_slot_becomes_available_again(self):
        item=VisitAppointment.objects.create(
            branch=self.niavaran,full_name='لغو شونده',phone='09124440000',
            appointment_date=self.day,appointment_time=time(15,0),
            source='receptionist',created_by=self.receptionist,
        )
        self.client.force_login(self.receptionist)
        response=self.client.post(
            reverse('receptionist_appointment_status',args=[item.pk,'cancelled'])
        )
        self.assertEqual(response.status_code,302)
        item.refresh_from_db()
        self.assertEqual(item.status,'cancelled')
        replacement=VisitAppointment.objects.create(
            branch=self.niavaran,full_name='جایگزین',phone='09125550000',
            appointment_date=self.day,appointment_time=time(15,0),
            source='receptionist',created_by=self.receptionist,
        )
        self.assertIsNotNone(replacement.pk)
