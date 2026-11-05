import json
from datetime import time,timedelta

from django.test import Client,TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog,CallCenterLeadGroup,DuplicateLeadError,LeadContactPhone,PatientProfile,ReferralLead,VisitAppointment
from core.tests.test_call_center_role import CallCenterRoleTests


class LeadContactsTests(TestCase):
    setUp=CallCenterRoleTests.setUp
    make_user=CallCenterRoleTests.make_user

    def read(self,lead=None):
        return self.client.get(reverse('call_center_lead_contacts',args=[(lead or self.lead_one).pk]))

    def save(self,phone,additional=None,version=None):
        if version is None:
            version=self.read().json()['version']
        return self.client.post(reverse('call_center_lead_contacts',args=[self.lead_one.pk]),
            data=json.dumps({'phone':phone,'additional':additional or [],'version':version}),content_type='application/json')

    def test_multiple_numbers_stay_on_one_lead_and_are_searchable(self):
        count=ReferralLead.objects.count()
        response=self.save('۰۹۱۲۰۰۰۰۰۰۱',['+98 912 111 1111','09122222222'])
        self.assertEqual(response.status_code,200,response.content)
        self.assertEqual(response.json()['numbers'],['09120000001','09121111111','09122222222'])
        self.assertEqual(ReferralLead.objects.count(),count)
        self.lead_one.refresh_from_db()
        self.assertEqual(self.lead_one.alternate_phone,'09121111111')
        self.assertEqual(self.lead_one.extra_phones.count(),2)
        page=self.client.get(reverse('call_center_dashboard'),{'q':'09122222222'})
        self.assertEqual(page.context['queue_page'].paginator.count,1)
        self.assertContains(page,'09122222222')

    def test_edit_primary_preserves_patient_and_appointment_identity_and_audit(self):
        patient=PatientProfile.objects.create(phone=self.lead_one.phone,full_name=self.lead_one.full_name)
        appt=VisitAppointment.objects.create(lead=self.lead_one,phone=self.lead_one.phone,full_name=self.lead_one.full_name,
            branch=self.branch,appointment_date=timezone.localdate(),appointment_time=time(11))
        response=self.save('09123333333',['09124444444'])
        self.assertEqual(response.status_code,200,response.content)
        patient.refresh_from_db();appt.refresh_from_db()
        self.assertEqual(patient.phone,'09123333333');self.assertEqual(appt.phone,patient.phone)
        log=AuditLog.objects.get(action='lead_phone_edit')
        self.assertEqual(log.actor,self.operator_one)
        self.assertEqual(log.metadata['before'],['09120000001'])
        self.assertEqual(log.metadata['after'],['09123333333','09124444444'])
        history=self.read().json()['history']
        self.assertEqual(history[0]['before'],['09120000001'])

    def test_promote_secondary_and_reject_stale_edit(self):
        self.save(self.lead_one.phone,['09121111111','09122222222'])
        old=self.read().json()['version']
        response=self.save('09122222222',[self.lead_one.phone,'09121111111'],old)
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['contacts'][0]['wa_url'],'https://wa.me/989122222222')
        self.assertEqual(self.save('09123333333',version=old).status_code,409)
        self.lead_one.refresh_from_db();self.assertEqual(self.lead_one.phone,'09122222222')

    def test_reject_foreign_primary_secondary_and_legacy_duplicates_atomically(self):
        ReferralLead.objects.filter(pk=self.lead_two.pk).update(created_at=timezone.now()-timedelta(days=5),alternate_phone='۰۹۱۲ ۴۴۴ ۴۴۴۴')
        LeadContactPhone.objects.create(lead=self.lead_two,phone='09125555555')
        for number in [self.lead_two.phone,'09124444444','09125555555']:
            response=self.save(self.lead_one.phone,['09123333333',number])
            self.assertEqual(response.status_code,409,response.content)
        self.assertEqual(self.lead_one.extra_phones.count(),0)
        self.assertFalse(AuditLog.objects.filter(action='lead_phone_edit').exists())

    def test_invalid_and_duplicate_numbers_are_not_silently_saved(self):
        for primary,others in [('123',[]),('09120000001abc',[]),(self.lead_one.phone,['+989120000001']),('09120000001',[''])]:
            result=self.save(primary,others)
            if others==['']:
                self.assertEqual(result.status_code,200)
            else:
                self.assertEqual(result.status_code,400,result.content)

    def test_permissions_and_csrf(self):
        self.assertEqual(self.read(self.lead_two).status_code,404)
        foreign=self.client.post(reverse('call_center_lead_contacts',args=[self.lead_two.pk]),data='{}',content_type='application/json')
        self.assertEqual(foreign.status_code,404)
        self.client.force_login(self.staff)
        self.assertEqual(self.read().status_code,403)
        secure=Client(enforce_csrf_checks=True);secure.force_login(self.operator_one)
        response=secure.post(reverse('call_center_lead_contacts',args=[self.lead_one.pk]),data='{}',content_type='application/json')
        self.assertEqual(response.status_code,302)  # Project CSRF failure handler redirects to a safe GET.
        self.assertEqual(response.url,reverse('call_center_lead_contacts',args=[self.lead_one.pk]))
        self.assertFalse(AuditLog.objects.filter(action='lead_phone_edit').exists())

    def test_patient_collision_does_not_merge_or_partially_edit(self):
        patient=PatientProfile.objects.create(phone='09123333333',full_name='شخص دیگر')
        result=self.save(patient.phone,['09124444444'])
        self.assertEqual(result.status_code,409)
        self.lead_one.refresh_from_db();self.assertEqual(self.lead_one.phone,'09120000001')
        self.assertEqual(self.lead_one.extra_phones.count(),0)

    def test_legacy_alternate_survives_and_inbound_dedup_uses_all_numbers(self):
        ReferralLead.objects.filter(pk=self.lead_one.pk).update(alternate_phone='۰۹۱۲۱۱۱۱۱۱۱')
        self.assertEqual(self.read().json()['numbers'],['09120000001','09121111111'])
        self.save('09120000001',['09121111111','09122222222'])
        with self.assertRaises(DuplicateLeadError):
            ReferralLead.objects.create(referrer=self.referrer,full_name='تکراری',phone='+989122222222')

    def test_registration_text_survives_followups_and_is_escaped(self):
        self.lead_one.initial_description=None
        ReferralLead.objects.filter(pk=self.lead_one.pk).update(initial_description=None,notes='[entry:direct]\nمتن اولیه <script>alert(1)</script>')
        self.lead_one.notes='یادداشت تماس بعدی'
        self.lead_one.save(update_fields=['notes'])
        self.lead_one.refresh_from_db()
        self.assertIn('متن اولیه',self.lead_one.registration_description)
        self.assertNotIn('یادداشت تماس بعدی',self.lead_one.registration_description)
        self.assertNotIn('[entry:direct]',self.lead_one.registration_description)
        page=self.client.get(reverse('call_center_dashboard'))
        self.assertContains(page,'lead-description-preview')
        self.assertContains(page,'&lt;script&gt;alert(1)&lt;/script&gt;')
        self.assertNotContains(page,'<script>alert(1)</script>')

    def test_direct_and_instagram_registration_save_all_numbers(self):
        group=CallCenterLeadGroup.objects.create(name='آزمایشی')
        result=self.client.post(reverse('call_center_direct_lead_create'),{'full_name':'ثبت مستقیم جدید','phone':'09123333333',
            'group':group.pk,'notes':'توضیح اولیه','additional_phones':'09124444444\n09125555555'})
        self.assertEqual(result.status_code,302)
        lead=ReferralLead.objects.get(phone='09123333333')
        self.assertEqual(len(lead.contact_numbers),3)
        self.assertEqual(lead.initial_description,'توضیح اولیه')
        result=self.client.post(reverse('instagram_manual_lead'),{'full_name':'دایرکت جدید','phone':'09126666666',
            'instagram_page':'greenlifeclinics','interested_service':'قد و وزن و محل سکونت','additional_phones':'09127777777\n09128888888'})
        self.assertEqual(result.status_code,200)
        lead=ReferralLead.objects.get(phone='09126666666')
        self.assertEqual(len(lead.contact_numbers),3)
        self.assertEqual(lead.initial_description,'قد و وزن و محل سکونت')
