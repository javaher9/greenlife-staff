from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.test import TestCase

from core.agent_activity_views import _appointment_cards
from core.device_booking_models import BranchDeviceTypeStatus, DeviceTypeSchedule, PhysicalDevice
from core.models import Branch, VisitAppointment


class AppointmentCardTests(TestCase):
    def test_tehran_registration_cohort_shared_scale_and_inventory(self):
        # First day of Aban 1405, local midnight.
        start = datetime(2026, 10, 23, tzinfo=ZoneInfo('Asia/Tehran'))
        now = start + timedelta(hours=10)
        north = Branch.objects.create(name='کلینیک نیاوران')
        west = Branch.objects.create(name='پونک')
        for index, (branch, created, status) in enumerate([
            (north, start - timedelta(seconds=1), 'completed'),
            (north, start, 'completed'), (north, now, 'booked'),
            (north, now, 'cancelled'), (west, now, 'booked'),
            (north, now + timedelta(seconds=1), 'completed'),
        ]):
            appointment = VisitAppointment.objects.create(
                branch=branch, full_name='Test visitor', phone='09120000000', appointment_date=now.date() + timedelta(days=36),
                appointment_time=f'{index + 10}:00', status=status,
            )
            VisitAppointment.objects.filter(pk=appointment.pk).update(created_at=created)
        kind = DeviceTypeSchedule.objects.create(code='qa-kind')
        off = DeviceTypeSchedule.objects.create(code='qa-off', is_active=False)
        for index, (branch, device_type, active) in enumerate([
            (north, kind, True), (north, kind, False), (north, off, True), (west, kind, True),
        ]):
            PhysicalDevice.objects.create(branch=branch, device_type=device_type, is_active=active, name=str(index))
        BranchDeviceTypeStatus.objects.create(branch=west, device_type=kind, is_active=False)

        month, lifetime = _appointment_cards(now)
        self.assertEqual([(x['total'], x['done']) for x in month], [(3, 1), (1, 0), (0, 0)])
        self.assertEqual((lifetime[0]['total'], lifetime[0]['done']), (4, 2))
        self.assertAlmostEqual(month[1]['total_level'], 100 / 3)
        self.assertEqual(month[0]['done_level'], month[1]['total_level'])
        self.assertFalse(month[2]['available'])
        self.assertEqual([x['devices'] for x in month], [1, 0, None])
        PhysicalDevice.objects.filter(branch=west).delete()
        self.assertIsNone(_appointment_cards(now)[0][1]['devices'])
