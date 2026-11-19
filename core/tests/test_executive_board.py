from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone
from core.executive_board import board, presence_by_user
from core.management.commands.monitor_executive_sites import classify
from core.models import Attendance, ExecutiveSiteReading


class ExecutiveBoardTests(TestCase):
    def test_sensor_states_and_stale_stats(self):
        self.assertEqual(classify(None, 0), ('warning',1))
        self.assertEqual(classify(503, 1), ('down',2))
        self.assertEqual(classify(403, 2), ('unknown',0))
        self.assertEqual(classify(200, 2), ('up',0))
        now=timezone.localtime()
        ExecutiveSiteReading.objects.create(domain='rejim.ir',state='down',checked_at=now-timedelta(minutes=5))
        data=board(now, {})
        self.assertEqual(len(data['pages']),6)
        self.assertEqual(len(data['sites']),5)
        site=next(s for s in data['sites'] if s['domain']=='rejim.ir')
        self.assertEqual(site['status'],'stale')
        self.assertIsNone(site['visits'])

    def test_check_in_checkout_and_missing_record_are_distinct(self):
        now=timezone.localtime()
        user=get_user_model().objects.create_user('board-worker')
        self.assertNotIn(user.pk,presence_by_user(now))
        attendance=Attendance.objects.create(user=user,date=now.date(),check_in=now,status='late')
        self.assertEqual(presence_by_user(now)[user.pk][0], 'present')
        attendance.check_out=now
        attendance.save()
        self.assertEqual(presence_by_user(now)[user.pk][0], 'off')

    def test_scan_moves_only_the_matching_appointment(self):
        from core.models import Branch, VisitAppointment, PatientProfile, BodyAnalysisRecord
        now=timezone.localtime()
        branch=Branch.objects.create(name='نیاوران')
        appointment=VisitAppointment.objects.create(branch=branch,appointment_date=now.date(),appointment_time='10:00',
                                                      status='arrived',phone='09900000001',full_name='private')
        def stages():
            return {s['key']:s for s in board(timezone.localtime(),{})['rooms'][0]['stages']}
        original=stages()['reception']['tokens']
        self.assertEqual(len(original),1)
        patient=PatientProfile.objects.create(full_name='private',phone='09900000001')
        BodyAnalysisRecord.objects.create(patient=patient,measurements={'scan_appointment_id':appointment.pk})
        current=stages()
        self.assertEqual(current['scan']['tokens'],original)
        self.assertFalse(current['reception']['tokens'])
        self.assertNotIn(patient.phone,str(current))
