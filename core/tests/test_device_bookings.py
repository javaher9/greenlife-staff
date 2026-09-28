from datetime import datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.device_booking_service import reserve_device_session
from core.models import (
    Branch, ConsultationPlan, ConsultationPlanItem, DeviceBooking,
    DeviceCabin, DeviceKind, DeviceUnit, EmployeeProfile, FinancialTransaction,
    VisitAppointment,
)


class DeviceBookingTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='تست دستگاه و کابین')
        self.user=User.objects.create_user('device-consultant',password='test-pass')
        EmployeeProfile.objects.create(user=self.user,role='consultant',branch=self.branch)
        self.cabin=DeviceCabin.objects.create(branch=self.branch,name='کابین کرایو ۱')
        self.cryo=DeviceKind.objects.get(code='Cryo70')
        self.cryo.treatment_minutes=70
        self.cryo.preparation_minutes=20
        self.cryo.save()
        self.unit=DeviceUnit.objects.create(
            branch=self.branch,kind=self.cryo,name='Cryo دستگاه ۱',home_cabin=self.cabin,
        )
        self.day=timezone.localdate()+timedelta(days=2)
        self.visit,self.item=self._visit('09120010001','بیمار اول')

    def _visit(self,phone,name,title='Cryo70',quantity=5):
        visit=VisitAppointment.objects.create(
            branch=self.branch,full_name=name,phone=phone,
            appointment_date=timezone.localdate(),
            appointment_time=time(10,15*VisitAppointment.objects.filter(branch=self.branch).count()),status='arrived',source='receptionist',
            created_by=self.user,
        )
        plan=ConsultationPlan.objects.create(
            appointment=visit,consultant=self.user,
            status='partial_paid',final_amount_toman=Decimal('20000000'),
        )
        item=ConsultationPlanItem.objects.create(
            plan=plan,kind='device',title=title,
            quantity=quantity,unit_price_toman=Decimal('4000000'),
        )
        FinancialTransaction.objects.create(
            appointment=visit,source='manual',branch=self.branch,
            occurred_at=timezone.now(),amount=Decimal('50000000'),
            entry_type='inc',review_status='pending',recorded_by=self.user,
        )
        return visit,item

    def book(self,*,visit=None,item=None,kind=None,cabin=None,units=None,at=time(9,0)):
        return reserve_device_session(
            appointment=visit or self.visit,plan_item=item or self.item,
            kind=kind or self.cryo,cabin=cabin or self.cabin,
            units=units or [self.unit],day=self.day,
            start_time=at,actor=self.user,
        )

    def test_old_booking_retains_snapshot_after_time_settings_change(self):
        old=self.book()
        self.assertEqual(old.treatment_minutes_snapshot,70)
        self.assertEqual(old.preparation_minutes_snapshot,20)
        self.assertEqual(
            int((old.ends_at-old.starts_at).total_seconds()/60),90,
        )
        self.cryo.preparation_minutes=5
        self.cryo.save(update_fields=['preparation_minutes'])
        old.refresh_from_db()
        self.assertEqual(old.preparation_minutes_snapshot,20)
        self.assertEqual(
            int((old.ends_at-old.starts_at).total_seconds()/60),90,
        )
        old.status='cancelled'
        old.save(update_fields=['status'])
        newer=self.book(at=time(11,0))
        self.assertEqual(newer.preparation_minutes_snapshot,5)
        self.assertEqual(
            int((newer.ends_at-newer.starts_at).total_seconds()/60),75,
        )

    def test_cabin_and_machine_overlap_are_rejected(self):
        self.book()
        second,item=self._visit('09120010002','بیمار دوم')
        other=DeviceUnit.objects.create(
            branch=self.branch,kind=self.cryo,name='Cryo دستگاه ۲',
        )
        with self.assertRaises(ValidationError):
            self.book(visit=second,item=item,units=[other],at=time(9,30))
        other_cabin=DeviceCabin.objects.create(
            branch=self.branch,name='کابین کرایو ۲',
        )
        with self.assertRaises(ValidationError):
            self.book(visit=second,item=item,cabin=other_cabin,at=time(9,30))
        accepted=self.book(
            visit=second,item=item,cabin=other_cabin,units=[other],at=time(9,30),
        )
        self.assertEqual(accepted.status,'booked')

    def test_only_one_open_session_per_package_item(self):
        self.book()
        with self.assertRaises(ValidationError):
            self.book(at=time(11,0))

    def test_double_define_reserves_two_physical_devices(self):
        define=DeviceKind.objects.get(code='DIF70')
        first=DeviceUnit.objects.create(
            branch=self.branch,kind=define,name='DIF شماره ۱',
        )
        second=DeviceUnit.objects.create(
            branch=self.branch,kind=define,name='DIF شماره ۲',
        )
        visit,item=self._visit('09120010003','بیمار دابل',title='Double Define')
        with self.assertRaises(ValidationError):
            self.book(visit=visit,item=item,kind=define,units=[first])
        booked=self.book(
            visit=visit,item=item,kind=define,units=[first,second],
        )
        self.assertEqual(booked.units.count(),2)
        self.assertEqual(booked.preparation_minutes_snapshot,30)
        self.assertEqual(
            int((booked.ends_at-booked.starts_at).total_seconds()/60),100,
        )


    def test_per_unit_timing_override_is_snapshotted(self):
        self.unit.treatment_override_min=60
        self.unit.preparation_override_min=10
        self.unit.save(update_fields=['treatment_override_min','preparation_override_min'])
        booked=self.book()
        self.assertEqual(booked.treatment_minutes_snapshot,60)
        self.assertEqual(booked.preparation_minutes_snapshot,10)
        self.unit.preparation_override_min=30
        self.unit.save(update_fields=['preparation_override_min'])
        booked.refresh_from_db()
        self.assertEqual(booked.preparation_minutes_snapshot,10)

    def test_deposit_required(self):
        FinancialTransaction.objects.filter(appointment=self.visit).delete()
        with self.assertRaises(ValidationError):
            self.book()

    def test_consultant_schedule_and_admin_settings_permissions(self):
        self.client.force_login(self.user)
        response=self.client.get(reverse('device_booking_schedule'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'تقویم نوبت‌دهی دستگاه‌ها')
        self.assertEqual(
            self.client.get(reverse('device_booking_settings')).status_code,403,
        )
        admin=User.objects.create_user('device-admin',password='test-pass')
        EmployeeProfile.objects.create(user=admin,role='admin',branch=self.branch)
        self.client.force_login(admin)
        self.assertEqual(
            self.client.get(reverse('device_booking_settings')).status_code,200,
        )
