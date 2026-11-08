import re
import tempfile
from datetime import date, time, timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings, Client
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from core.models import *
from core.jalali import format_jalali
from core.tests.test_consultant_finance import ConsultantFinanceEntryTests
from intake.models import IntakeInvitation

class SyntheticJourneyTests(TestCase):
    def setUp(self):
        self.day=date(2026,11,9)
        clock=patch('django.utils.timezone.localdate',return_value=self.day)
        clock.start(); self.addCleanup(clock.stop)
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        settings=override_settings(MEDIA_ROOT=self.tmp.name)
        settings.enable(); self.addCleanup(settings.disable)
        self.branch=Branch.objects.create(name='نیاوران')
        self.users={}
        for role in ('call_center','receptionist','scan_station','doctor','consultant','manager'):
            user=User.objects.create_user('journey-'+role,password='TestOnly123!')
            EmployeeProfile.objects.update_or_create(user=user,defaults={'role':role,'branch':self.branch,'is_active':True})
            self.users[role]=User.objects.get(pk=user.pk)
        self.group=CallCenterLeadGroup.objects.create(name='Synthetic audit')
        self.sms=patch('intake.views.send_sms').start()
        self.addCleanup(patch.stopall)

    def stage(self,name):
        print('JOURNEY PASS: '+name,flush=True)

    def post(self,role,name,data=None,args=None):
        self.client.force_login(self.users[role])
        response=self.client.post(reverse(name,args=args),data or {})
        self.assertLess(response.status_code,400,(name,response.status_code))
        return response

    def test_full_journey(self):
        self.post('call_center','call_center_direct_lead_create',{
            'full_name':'تست ممیزی چرخه','phone':'09120009991','group':self.group.pk,
            'interested_service':'کاهش وزن','notes':'Synthetic only'})
        lead=ReferralLead.objects.get(phone='09120009991')
        self.assertEqual(lead.assigned_to_id,self.users['call_center'].profile.pk)
        self.stage('lead registration and assignment')
        self.post('call_center','call_center_lead',{'contact_result':'follow_up',
            'next_follow_up':format_jalali(self.day),'interested_service':'کاهش وزن','notes':'Synthetic contact'},[lead.pk])
        lead.refresh_from_db(); self.assertEqual(lead.status,'contacted')
        self.stage('contact outcome')
        self.post('call_center','call_center_appointment_slot_create',{
            'branch':self.branch.pk,'appointment_date':self.day.isoformat(),'appointment_time':'11:00'},[lead.pk])
        appt=VisitAppointment.objects.get(lead=lead)
        self.stage('appointment booking')
        self.post('receptionist','receptionist_appointment_status',args=[appt.pk,'arrived'])
        patient=PatientProfile.objects.get(phone=lead.phone)
        self.stage('arrival and automatic patient record')
        self.post('receptionist','intake_send_link',args=[appt.pk])
        self.sms.assert_called_once()
        url=re.search(r'https?://\S+',self.sms.call_args.args[1]).group(0)
        path='/intake/form/'+url.split('/intake/form/')[1]
        guest=Client(enforce_csrf_checks=True)
        guest.get(path)
        response=guest.post(path,{
            'goal':'کاهش وزن','body_area':'شکم و پهلو','conditions':['کم‌کاری تیروئید'],
            'medication_status':'بله','medications':'لووتیروکسین','allergy_status':'خیر',
            'safety_none':'yes','screening_confirmed':'on','appetite':'زیاد',
            'eating_habits':['ریزه‌خواری'],'mental_state':'گاهی اضطراب یا غمگینی',
            'hopelessness':'گاهی','activity':'کم','sleep':'۶ تا ۸ ساعت',
            'previous_treatments':'رژیم غذایی','current_weight':'89.2','target_weight':'75',
            'motivation':'سلامتی','consent':'on'},
            HTTP_X_CSRFTOKEN=guest.cookies['csrftoken'].value)
        self.assertEqual(response.status_code,200)
        self.assertIsNotNone(IntakeInvitation.objects.get(appointment=appt).completed_at)
        self.stage('anonymous intake with CSRF and mocked SMS')
        self.post('scan_station','scan_station',{
            'appointment_id':appt.pk,'operator_id':self.users['receptionist'].profile.pk,
            'weight_kg':'89.2','inbody_score':'80','skeletal_muscle_kg':'30','fat_kg':'20','whr':'0.8','visceral_fat':'8'})
        self.assertEqual(BodyAnalysisRecord.objects.filter(patient=patient).count(),1)
        self.stage('scan recording')
        self.post('doctor','doctor_dashboard',{'appointment_id':appt.pk,'action':'device',
            'device_name':'Audit Device','sessions':'1','area':'شکم'})
        self.post('doctor','doctor_dashboard',{'appointment_id':appt.pk,'action':'send_to_consultant'})
        appt.refresh_from_db(); self.assertEqual(appt.care_stage,'consultant')
        self.stage('doctor prescription and handoff')
        self.client.force_login(self.users['consultant'])
        self.client.get(reverse('consultant_sales_outcomes'),{'appointment':appt.pk})
        plan=ConsultationPlan.objects.get(appointment=appt)
        item=plan.items.get()
        snapshot=dict(item.doctor_snapshot)
        self.post('consultant','consultant_sales_outcomes',{'appointment_id':appt.pk,
            'action':'update_item','item_id':item.pk,'unit_price_million':'2','quantity':'1','included':'1'})
        item.refresh_from_db(); self.assertEqual(item.doctor_snapshot,snapshot)
        self.post('consultant','consultant_sales_outcomes',{'appointment_id':appt.pk,'action':'finalize','discount_million':'0'})
        self.post('consultant','consultant_sales_outcomes',{'appointment_id':appt.pk,'action':'send_to_reception'})
        self.stage('consultant package and reception handoff')
        payload={'date':format_jalali(self.day),'entry_type':'inc','person_name':lead.full_name,
            'amount':'20000000','sale_reason':'device_package','sale_origin':'afsariyeh',
            'appointment':appt.pk,'payment_method':'Pos S','service':'Audit Device',
            'account_heading':'Audit','terminal_or_payee':'Audit','tracking_number':'AUDIT-ONLY-01',
            'description':'Synthetic receipt','receipt_image':ConsultantFinanceEntryTests.receipt()}
        self.post('receptionist','finance_entry',payload)
        payment=FinancialTransaction.objects.get(appointment=appt)
        self.assertEqual(payment.review_status,'pending')
        lead.refresh_from_db(); self.assertNotEqual(lead.status,'won')
        self.post('manager','finance_entry_review',args=[payment.pk,'approve'])
        plan.refresh_from_db(); appt.refresh_from_db(); lead.refresh_from_db()
        self.assertEqual(plan.status,'paid'); self.assertEqual(appt.care_stage,'closed')
        self.assertEqual(lead.status,'won')
        self.stage('receipt pending then approved settlement')
        before=plan.final_amount_toman
        self.post('consultant','consultant_sales_outcomes',{'appointment_id':appt.pk,
            'action':'update_item','item_id':item.pk,'unit_price_million':'3','quantity':'1','included':'1'})
        plan.refresh_from_db()
        print('AUDIT paid plan amount before/after:',before,plan.final_amount_toman,flush=True)
        with self.subTest(guard='paid package immutable'):
            self.assertEqual(plan.final_amount_toman,before,'Paid package can be changed after settlement')

        kind=DeviceTypeSchedule.objects.create(code='AUDIT1',name='Audit Device',treatment_minutes=30,preparation_minutes=10)
        cabin=DeviceCabin.objects.create(branch=self.branch,name='Audit')
        device=PhysicalDevice.objects.create(branch=self.branch,device_type=kind,cabin=cabin,name='Audit',work_start=time(9,0),last_start=time(18,0))
        self.post('consultant','device_booking_schedule',{'appointment':appt.pk,'day':format_jalali(self.day+timedelta(days=1)),
            'plan_item':item.pk,'device':device.pk,'start_time':'09:00'})
        booking=DeviceSessionBooking.objects.get(appointment=appt)
        self.stage('next device appointment')
        self.post('consultant','device_booking_status',args=[booking.pk,'completed'])
        item.refresh_from_db()
        task=Task.objects.get(pk=item.doctor_snapshot['treatment_followup_task_id'])
        self.assertEqual(task.assigned_to_id,self.users['call_center'].pk)
        self.post('call_center','patient_360_followup_complete',{'result':'Synthetic follow-up completed'},[patient.pk,task.pk])
        task.refresh_from_db(); self.assertEqual(task.status,'done')
        self.stage('treatment completion and call-center follow-up')


    def test_missing_patient_id_must_not_mutate_first_queue_record(self):
        appt=VisitAppointment.objects.create(branch=self.branch,full_name='Synthetic ID guard',
            phone='09120009992',appointment_date=self.day,appointment_time=time(10,0),
            status='arrived',care_stage='consultant',source='receptionist',created_by=self.users['receptionist'])
        plan=ConsultationPlan.objects.create(appointment=appt,consultant=self.users['consultant'],status='draft')
        self.post('consultant','consultant_sales_outcomes',{'action':'no_sale','failure_reason':'financial'})
        plan.refresh_from_db()
        self.assertEqual(plan.status,'draft','Missing appointment_id changed first queued patient')
