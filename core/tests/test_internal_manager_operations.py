from datetime import datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo
from django.contrib.auth.models import User
from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import (EmployeeProfile, Branch, Country, ReferralProfile, ReferralLead,
    SalesTargetBand, TargetPercentPolicy, FinancialTransaction, LeaveRequest, AuditLog,
    StaffNotification, OperationsIncident, CustomerServiceRequest, CustomerPortalMember)
from core.internal_manager_scope import PERSONNEL_ROLES
from core.internal_manager_targets import target_statuses
from core.operations_monitor import direct_gap, reconcile_direct_gap, record_manual_dm
from core.jalali import gregorian_to_jalali


class OperationsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.branch=Branch.objects.create(name='مرکز نمونه')
        cls.country=cls.branch.country
        cls.other_country=Country.objects.get_or_create(code='TR',defaults={'name_local':'ترکیه','name_english':'Turkey'})[0]
        cls.other_branch=Branch.objects.create(name='خارج از حوزه',country=cls.other_country)
        cls.internal=cls.user('im-owner','internal_manager',cls.branch)
        cls.admin=cls.user('im-admin','admin',cls.branch)
        cls.employee=cls.user('im-person','call_center',cls.branch)
        cls.other=cls.user('im-other','employee',cls.other_branch)
        cls.referrer,_=ReferralProfile.objects.get_or_create(user=cls.admin,defaults={'referral_code':'im-tests'})
        cls.lead=ReferralLead.objects.create(referrer=cls.referrer,full_name='مراجع نمونه 09123456789',phone='09123456789',alternate_phone='09351234567',notes='تماس 09351234567',assigned_to=cls.employee.profile)
        cls.jy,cls.jm,_=gregorian_to_jalali(timezone.localdate().year,timezone.localdate().month,timezone.localdate().day)

    @staticmethod
    def user(name,role,branch):
        u=User.objects.create_user(name)
        EmployeeProfile.objects.update_or_create(user=u,defaults={'role':role,'branch':branch,'country':branch.country,'is_active':True})
        return User.objects.get(pk=u.pk)

    def setUp(self):
        self.client.force_login(self.internal)

    def request(self):
        r=RequestFactory().get('/')
        r.user=self.internal;r.country_scope=self.country;r.country_scope_code=self.country.code
        return r

    def leave(self,user=None):
        return LeaveRequest.objects.create(user=user or self.employee,start_date=timezone.localdate(),end_date=timezone.localdate(),reason='دلیل آزمایشی')

    def test_dashboard_and_all_local_links(self):
        from html.parser import HTMLParser
        response=self.client.get('/live/')
        self.assertContains(response,'مدیریت داخلی · پیگیری امروز')
        class Links(HTMLParser):
            links=[]
            def handle_starttag(self,tag,attrs):
                attrs=dict(attrs)
                if tag=='a' and attrs.get('href','').startswith('/'):
                    self.links.append(attrs['href'])
        # Restrict check to the new dashboard; legacy shell has unrelated links.
        parser=Links();parser.feed(response.content.decode().split('<main class="im">')[1].split('</main>')[0])
        for url in parser.links:
            result=self.client.get(url)
            self.assertLess(result.status_code,400,url)

    def test_target_context_allowlist_and_direct_post_denied(self):
        SalesTargetBand.objects.create(key=f'{self.jy}-{self.jm:02d}:branch:{self.branch.pk}',period_year=self.jy,period_month=self.jm,scope='branch',branch=self.branch,heavy_limit=70,sales_floor=100,target_one=130,target_two=160)
        FinancialTransaction.objects.create(source='manual',entry_type='inc',review_status='approved',occurred_at=timezone.now(),amount=Decimal('987654321'),branch=self.branch)
        result=self.client.get('/sales-targets/?edit=1')
        self.assertEqual(result.status_code,200)
        for row in result.context['target_branches']:
            self.assertEqual(set(row),{'name','level','status','action'})
        self.assertNotContains(result,'987654321')
        self.assertNotIn('total',result.context)
        self.assertNotIn('target_policy',result.context)
        self.assertEqual(self.client.post('/sales-targets/',{'action':'set_floor'}).status_code,405)
        self.client.force_login(self.admin)
        result=self.client.get('/sales-targets/')
        self.assertIn('total',result.context)

    def test_target_exact_existing_thresholds_missing_and_empty(self):
        key=f'{self.jy}-{self.jm:02d}:branch:{self.branch.pk}'
        def current():
            return next(x for x in target_statuses(self.request())['target_branches'] if x['name']==self.branch.name)['level']
        self.assertEqual(current(),'unset')
        SalesTargetBand.objects.create(key=key,period_year=self.jy,period_month=self.jm,scope='branch',branch=self.branch,heavy_limit=70,sales_floor=100,target_one=130,target_two=160)
        TargetPercentPolicy.objects.create(period_year=self.jy,period_month=self.jm,heavy_percent=60,target_one_percent=120,target_two_percent=150)
        self.assertEqual(current(),'unknown')
        f=FinancialTransaction.objects.create(source='manual',entry_type='inc',review_status='approved',occurred_at=timezone.now(),amount=1,branch=self.branch)
        for amount,level in [(59,'heavy'),(60,'light'),(99,'light'),(100,'neutral'),(120,'one'),(150,'two')]:
            FinancialTransaction.objects.filter(pk=f.pk).update(amount=amount*10000000)
            self.assertEqual(current(),level)

    def test_lead_page_api_detail_do_not_expose_contact_or_notes(self):
        for url in ['/management/all-leads/','/management/all-leads/data/',reverse('supervisory_lead',args=[self.lead.pk])]:
            response=self.client.get(url)
            self.assertEqual(response.status_code,200,url)
            for phone in ('09123456789','09351234567'):
                self.assertNotContains(response,phone)
        data=self.client.get('/management/all-leads/data/').json()['items'][0]
        self.assertEqual(data['url'],reverse('supervisory_lead',args=[self.lead.pk]))
        self.assertNotIn('phone',data)
        self.assertEqual(self.client.get('/management/all-leads/data/?q=09123456789').json()['total'],0)

    def test_old_detail_exports_and_mutations_are_blocked(self):
        for name,args in [('referral_lead_manage',[self.lead.pk]),('referral_export_csv',[]),('referral_crm_export',[])]:
            url=reverse(name,args=args)
            self.assertEqual(self.client.get(url).status_code,403)
            self.assertEqual(self.client.post(url,{}).status_code,403)

    def test_scope_cannot_be_changed_by_id(self):
        foreign=ReferralLead.objects.create(referrer=self.referrer,full_name='خارج از حوزه',phone='09111112222',country=self.other_country)
        self.assertEqual(self.client.get(reverse('supervisory_lead',args=[foreign.pk])).status_code,404)
        self.assertNotContains(self.client.get('/management/all-leads/data/'),'خارج از حوزه')
        for user in (self.internal,self.admin,self.other):
            leave=self.leave(user)
            self.assertEqual(self.client.get(reverse('leave_review',args=[leave.pk])).status_code,403)
            self.assertEqual(self.client.post('/action-center/quick/',{'kind':'leave','pk':leave.pk,'action':'approved'}).status_code,403)

    def test_each_personnel_role_and_audit_notification(self):
        for i,role in enumerate(PERSONNEL_ROLES):
            worker=self.user('role-'+role,role,self.branch)
            leave=self.leave(worker)
            self.assertContains(self.client.get('/requests/?status=pending'),worker.username)
            self.assertEqual(self.client.get(reverse('leave_review',args=[leave.pk])).status_code,200)
            result=self.client.post('/action-center/quick/',{'kind':'leave','pk':leave.pk,'action':'approved'})
            self.assertEqual(result.status_code,200)
            leave.refresh_from_db();self.assertEqual(leave.reviewed_by,self.internal)
            self.assertEqual(AuditLog.objects.filter(action='leave_decision',object_id=str(leave.pk)).count(),1)
            self.assertEqual(StaffNotification.objects.filter(user=worker,notification_type='leave_decision').count(),1)

    def test_rejection_note_duplicate_and_full_page_use_same_service(self):
        leave=self.leave()
        url=reverse('leave_review',args=[leave.pk])
        self.assertEqual(self.client.post('/action-center/quick/',{'kind':'leave','pk':leave.pk,'action':'rejected'}).status_code,400)
        response=self.client.post(url,{'status':'rejected','manager_note':'نیاز به هماهنگی'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(self.client.post('/action-center/quick/',{'kind':'leave','pk':leave.pk,'action':'approved'}).status_code,409)
        leave.refresh_from_db();self.assertEqual(leave.status,'rejected')
        self.assertEqual(AuditLog.objects.filter(action='leave_decision',object_id=str(leave.pk)).count(),1)

    def test_csrf_enforced(self):
        from django.test import Client
        c=Client(enforce_csrf_checks=True);c.force_login(self.internal)
        leave=self.leave()
        response=c.post('/action-center/quick/',{'kind':'leave','pk':leave.pk,'action':'approved'})
        self.assertIn(response.status_code,(302,403))  # Existing safe CSRF recovery redirects to GET.
        leave.refresh_from_db();self.assertEqual(leave.status,'pending')

    def test_contacted_customer_request_remains_alert_and_foreign_hidden(self):
        member=CustomerPortalMember.objects.create(phone='09011223344',full_name='نمونه',referral_code='im-customer')
        row=CustomerServiceRequest.objects.create(member=member,branch=self.branch,kind='visit',status='contacted')
        self.assertContains(self.client.get('/api/alerts/management/'),'customer-requests-pending')
        self.assertContains(self.client.get('/staff/customer-requests/?status=open'),'نمونه')
        row.branch=self.other_branch;row.save()
        self.assertNotContains(self.client.get('/api/alerts/management/'),'customer-requests-pending')
        self.assertEqual(self.client.post(reverse('staff_customer_request_action',args=[row.pk]),{'action':'claim'}).status_code,404)

    def test_guard_does_not_change_other_roles(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get('/sales-targets/').status_code,403)
        self.assertEqual(self.client.get('/management/all-leads/').status_code,403)
        self.assertEqual(self.client.get('/my-sales-targets/').status_code,200)


class DirectClockTests(TestCase):
    def dt(self,hour,minute=0,second=0,day=11):
        return datetime(2026,11,day,hour,minute,second,tzinfo=ZoneInfo('Asia/Tehran'))

    def test_exact_boundary_and_reset_at_new_day(self):
        self.assertIsNone(direct_gap(self.dt(7,59)))
        for h,m,s,active in [(8,0,0,False),(9,59,59,False),(10,0,0,False),(10,0,1,True),(23,59,59,True)]:
            self.assertEqual(direct_gap(self.dt(h,m,s))['active'],active)
        self.assertIsNone(direct_gap(self.dt(0,day=12)))
        self.assertFalse(direct_gap(self.dt(8,day=12))['active'])

    def test_other_events_never_reset_clock_and_real_manual_does(self):
        for action in ('write','instagram_api','lead_contact_result','advertising_created','call_center_direct_lead_create'):
            log=AuditLog.objects.create(action=action,path='/',method='POST')
            AuditLog.objects.filter(pk=log.pk).update(created_at=self.dt(10,30))
        self.assertTrue(direct_gap(self.dt(11))['active'])
        log=AuditLog.objects.create(action='instagram_manual_created',path='/',method='POST')
        AuditLog.objects.filter(pk=log.pk).update(created_at=self.dt(10,30))
        self.assertFalse(direct_gap(self.dt(11))['active'])

    def test_persistent_gap_dedup_not_resolved_by_midnight(self):
        country=Country.objects.get(code='IR')
        reconcile_direct_gap(self.dt(11));reconcile_direct_gap(self.dt(11))
        qs=OperationsIncident.objects.filter(country=country)
        self.assertEqual(qs.count(),1)
        reconcile_direct_gap(self.dt(8,day=12))
        self.assertIsNone(qs.get().resolved_at)
        log=AuditLog.objects.create(action='instagram_manual_created',path='/',method='POST',metadata={'country_id':country.pk})
        AuditLog.objects.filter(pk=log.pk).update(created_at=self.dt(9,day=12))
        reconcile_direct_gap(self.dt(9,day=12))
        self.assertIsNotNone(qs.get().resolved_at)


from concurrent.futures import ThreadPoolExecutor
from django.db import connection, close_old_connections
from django.test import TransactionTestCase
from unittest import skipUnless


@skipUnless(connection.vendor == 'postgresql', 'Row-lock concurrency is verified in PostgreSQL CI')
class LeaveConcurrencyTests(TransactionTestCase):
    def test_only_one_concurrent_decision_commits(self):
        from core.leave_decisions import decide_leave, LeaveConflict
        b=Branch.objects.create(name='concurrent branch')
        reviewer=OperationsTests.user('concurrent-reviewer','internal_manager',b)
        worker=OperationsTests.user('concurrent-worker','employee',b)
        item=LeaveRequest.objects.create(user=worker,start_date=timezone.localdate(),end_date=timezone.localdate())
        def decide(status):
            close_old_connections()
            r=RequestFactory().post('/action-center/quick/')
            r.user=User.objects.get(pk=reviewer.pk);r.country_scope=b.country;r.country_scope_code='IR'
            try:
                decide_leave(r,item.pk,status,'concurrency test')
                return 'saved'
            except LeaveConflict:
                return 'conflict'
            finally:
                close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(decide,['approved','rejected']))
        self.assertCountEqual(results,['saved','conflict'])
        self.assertEqual(AuditLog.objects.filter(action='leave_decision',object_id=str(item.pk)).count(),1)
