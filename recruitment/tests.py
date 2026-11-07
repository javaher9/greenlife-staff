"""Regression coverage for recruitment authorization and the hiring workflow."""
import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.utils import timezone

from core.models import Branch, Country, EmployeeProfile
from .models import Activity, Advertisement, Application, Candidate, Evaluation, Job


@override_settings(EXECUTIVE_USERNAMES={'recruitment-owner'}, ALLOWED_HOSTS=['testserver', 'localhost'])
class RecruitmentTests(TestCase):
    base = '/management/recruitment/'
    api = base + 'api/'

    @classmethod
    def setUpTestData(cls):
        cls.iran, _ = Country.objects.get_or_create(code='IR', defaults={'name_english': 'Iran', 'name_local': 'ایران'})
        cls.turkey, _ = Country.objects.get_or_create(code='TR', defaults={'name_english': 'Turkey', 'name_local': 'ترکیه'})
        cls.branch = Branch.objects.create(name='Recruitment Tehran', country=cls.iran)
        cls.tr_branch = Branch.objects.create(name='Recruitment Istanbul', country=cls.turkey)
        cls.executive = cls.make_user('recruitment-owner', 'admin')
        cls.manager = cls.make_user('recruitment-internal', 'internal_manager')
        cls.reviewer = cls.make_user('recruitment-reviewer', 'admin')
        cls.employee = cls.make_user('recruitment-employee', 'employee')
        cls.branch_manager = cls.make_user('recruitment-branch', 'manager')
        cls.inactive = cls.make_user('recruitment-inactive', 'internal_manager', active=False)
        cls.job = Job.objects.create(
            country=cls.iran, branch=cls.branch, organization='clinic', title='منشی آزمون',
            owner=cls.manager, created_by=cls.executive, status='open',
            salary_min=20000000, salary_max=30000000, budget_approved=True,
            criteria=[{'label': 'دقت', 'weight': 60}, {'label': 'ارتباط حرفه‌ای', 'weight': 40}],
        )
        cls.other_job = Job.objects.create(
            country=cls.iran, organization='camp', title='مسئول کمپ آزمون',
            owner=cls.manager, created_by=cls.executive, status='open',
            criteria=[{'label': 'مهارت عملی', 'weight': 100}],
        )
        cls.tr_job = Job.objects.create(
            country=cls.turkey, branch=cls.tr_branch, title='Istanbul Test Job',
            owner=cls.executive, created_by=cls.executive,
            criteria=[{'label': 'Skill', 'weight': 100}],
        )

    @classmethod
    def make_user(cls, username, role, active=True):
        user = User.objects.create_user(username, password='test-password')
        EmployeeProfile.objects.update_or_create(user=user, defaults={
            'role': role, 'branch': cls.branch, 'country': cls.iran, 'is_active': active,
        })
        return User.objects.get(pk=user.pk)

    def setUp(self):
        self.client.force_login(self.manager)

    def future(self):
        return (timezone.now() + timedelta(days=1)).isoformat()

    def new_application(self, **changes):
        data = {'name': 'متقاضی آزمون', 'phone': '09123456789', 'job': self.job.pk,
                'owner': self.manager.pk, 'next_action': 'تماس اولیه', 'next_action_at': self.future()}
        data.update(changes)
        return self.client.post(self.api + 'applications/', data)

    def application(self, **changes):
        response = self.new_application(**changes)
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertTrue(response.json()['ok'])
        return Application.objects.get(pk=response.json()['application']['id'])

    def update(self, app, **changes):
        data = {'action': 'update', 'stage': app.stage, 'owner': app.owner_id,
                'next_action': app.next_action or 'پیگیری', 'next_action_at': self.future(),
                'source': app.source, 'requested_salary': app.requested_salary or '',
                'offered_salary': app.offered_salary or '', 'decision_reason': app.decision_reason}
        data.update(changes)
        return self.app_post(app, data)

    def app_post(self, app, data):
        values = dict(data)
        if values.get('action') == 'candidate_update':
            candidate = Candidate.objects.get(pk=app.candidate_id)
            values.setdefault('expected_candidate_updated_at', candidate.updated_at.isoformat())
        if values.get('action', 'update') in {'update', 'approve', 'probation'}:
            latest = Application.objects.get(pk=app.pk)
            values.setdefault('expected_updated_at', latest.updated_at.isoformat())
        return self.client.post(f'{self.api}applications/{app.pk}/', values)

    def job_post(self, job, data):
        values = dict(data)
        latest = Job.objects.get(pk=job.pk)
        values.setdefault('expected_updated_at', latest.updated_at.isoformat())
        return self.client.post(f'{self.api}jobs/{job.pk}/', values)

    def job_data(self, **changes):
        data = {'title': 'استخدام آزمایشی', 'country': self.iran.pk, 'branch': self.branch.pk,
                'organization': 'clinic', 'owner': self.manager.pk, 'headcount': 1,
                'status': 'open', 'salary_min': '20000000', 'salary_max': '30000000',
                'criteria': json.dumps([{'label': 'مهارت', 'weight': 100}])}
        data.update(changes)
        return data

    def test_anonymous_cannot_read_or_write_recruitment(self):
        self.client.logout()
        for path in [self.base, self.api]:
            response = self.client.get(path)
            self.assertIn(response.status_code, (302, 401, 403))
        response = self.client.post(self.api + 'jobs/', self.job_data())
        self.assertIn(response.status_code, (302, 401, 403))
        self.assertFalse(Job.objects.filter(title='استخدام آزمایشی').exists())

    def test_employee_branch_manager_and_inactive_manager_are_denied(self):
        for user in (self.employee, self.branch_manager, self.inactive):
            with self.subTest(user=user.username):
                self.client.force_login(user)
                self.assertEqual(self.client.get(self.api).status_code, 403)
                self.assertEqual(self.client.post(self.api + 'jobs/', self.job_data()).status_code, 403)

    def test_internal_manager_can_open_page_with_management_menu(self):
        response = self.client.get(self.base)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'استخدام')
        self.assertContains(response, 'href="/management/recruitment/"')
        self.assertTemplateUsed(response, 'recruitment/dashboard.html')
        data = self.client.get(self.api).json()
        self.assertTrue(data['ok'])
        self.assertFalse(data['can_approve'])
        self.assertIn(self.job.pk, [j['id'] for j in data['jobs']])
        self.assertNotIn(self.tr_job.pk, [j['id'] for j in data['jobs']])

    def test_executive_sees_approval_permission(self):
        self.client.force_login(self.executive)
        self.assertTrue(self.client.get(self.api).json()['can_approve'])

    def test_csrf_is_required_for_writes(self):
        protected_client = Client(enforce_csrf_checks=True)
        protected_client.force_login(self.manager)
        response = protected_client.post(self.api + 'jobs/', self.job_data())
        # Shared CSRF recovery redirects authenticated users without executing writes.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response['Location'], self.api + 'jobs/')
        self.assertFalse(Job.objects.filter(title='استخدام آزمایشی').exists())

    def test_job_creation_does_not_allow_client_to_approve_budget(self):
        response = self.client.post(self.api + 'jobs/', self.job_data(budget_approved='true'))
        self.assertEqual(response.status_code, 200, response.content.decode())
        job = Job.objects.get(pk=response.json()['job']['id'])
        self.assertFalse(job.budget_approved)
        denied = self.job_post(job, {'action': 'approve_budget'})
        self.assertEqual(denied.status_code, 403)
        self.client.force_login(self.executive)
        allowed = self.job_post(job, {'action': 'approve_budget', 'note': 'بودجه مصوب'})
        self.assertEqual(allowed.status_code, 200)
        job.refresh_from_db()
        self.assertTrue(job.budget_approved)
        self.assertEqual(job.budget_approved_by_id, self.executive.pk)

    def test_salary_budget_change_invalidates_approval(self):
        response = self.job_post(self.job, self.job_data(action='save', salary_max='40000000'))
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.job.refresh_from_db()
        self.assertFalse(self.job.budget_approved)

    def test_invalid_job_budget_criteria_and_country_branch_are_rejected(self):
        cases = [
            {'salary_min': '40000000', 'salary_max': '10000000'},
            {'criteria': json.dumps([{'label': 'مهارت', 'weight': 80}])},
            {'criteria': 'not-json'},
            {'branch': self.tr_branch.pk},
            {'owner': self.employee.pk},
            {'country': 'invalid'},
        ]
        for fields in cases:
            with self.subTest(fields=fields):
                response = self.client.post(self.api + 'jobs/', self.job_data(**fields))
                self.assertEqual(response.status_code, 400, response.content.decode())
                self.assertFalse(response.json()['ok'])

    def test_normalized_phone_deduplicates_same_person_across_jobs(self):
        first = self.application(phone='۰۹۱۲۳۴۵۶۷۸۹')
        second = self.application(phone='+989123456789', job=self.other_job.pk)
        self.assertEqual(first.candidate_id, second.candidate_id)
        self.assertEqual(Candidate.objects.count(), 1)
        duplicate = self.new_application(phone='09123456789')
        self.assertEqual(duplicate.status_code, 400)
        self.assertEqual(Application.objects.count(), 2)

    def test_invalid_applicant_inputs_are_rejected_without_partial_records(self):
        for change in [
            {'phone': 'abc'}, {'job': 'nope'}, {'job': self.tr_job.pk},
            {'owner': self.employee.pk}, {'next_action': ''}, {'next_action_at': ''},
            {'next_action_at': 'not-a-date'}, {'requested_salary': '-1'}, {'name': ''},
        ]:
            with self.subTest(change=change):
                response = self.new_application(**change)
                self.assertEqual(response.status_code, 400, response.content.decode())
                self.assertFalse(Application.objects.exists())
                self.assertFalse(Candidate.objects.exists())

    def test_rejection_requires_reason_and_preserves_audit(self):
        app = self.application()
        response = self.update(app, stage='rejected', decision_reason='')
        self.assertEqual(response.status_code, 400)
        app.refresh_from_db()
        self.assertEqual(app.stage, 'new')
        response = self.update(app, stage='rejected', decision_reason='مهارت ثبت نوبت کافی نبود')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'rejected')
        self.assertTrue(Activity.objects.filter(application=app, actor=self.manager).exists())

    def test_talent_pool_requires_reason_and_future_action(self):
        app = self.application()
        invalid = self.update(app, stage='talent', decision_reason='مناسب برای آینده', next_action='', next_action_at='')
        self.assertEqual(invalid.status_code, 400)
        valid = self.update(app, stage='talent', decision_reason='مناسب برای آینده', next_action='تماس برای فرصت بعدی')
        self.assertEqual(valid.status_code, 200, valid.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'talent')

    def test_note_requires_content_and_records_actor(self):
        app = self.application()
        url = f'{self.api}applications/{app.pk}/'
        self.assertEqual(self.app_post(app, {'action': 'note', 'text': ''}).status_code, 400)
        response = self.app_post(app, {'action': 'note', 'text': 'پاسخ تماس دریافت شد'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(Activity.objects.filter(application=app, actor=self.manager, text='پاسخ تماس دریافت شد').exists())

    def test_independent_evaluations_are_hidden_until_reviewer_submits(self):
        app = self.application()
        url = f'{self.api}applications/{app.pk}/'
        score = self.app_post(app, {'action': 'evaluate', 'scores': '[90,80]', 'evidence': 'آزمون ثبت نوبت و مکالمه انجام شد', 'recommendation': 'advance'})
        self.assertEqual(score.status_code, 200, score.content.decode())
        self.assertEqual(Evaluation.objects.get(application=app).total, 86)
        self.client.force_login(self.reviewer)
        detail = self.client.get(url).json()['application']
        self.assertIsNone(detail['score'])
        self.assertEqual(detail['evaluations'], [])
        self.assertTrue(detail['evaluations_hidden'])
        summary = self.client.get(self.api).json()['applications'][0]
        self.assertIsNone(summary['score'])
        second = self.app_post(app, {'action': 'evaluate', 'scores': '[70,80]', 'evidence': 'آزمون مستقل دوم انجام شد', 'recommendation': 'review'})
        self.assertEqual(second.status_code, 200, second.content.decode())
        detail = self.client.get(url).json()['application']
        self.assertEqual(len(detail['evaluations']), 2)
        self.assertFalse(detail['evaluations_hidden'])

    def test_evaluation_rejects_invalid_scores_and_requires_evidence(self):
        app = self.application()
        for fields in [{'scores': '[101,60]'}, {'scores': '[-1,60]'}, {'scores': '[60]'}, {'scores': '["x",60]'}, {'scores': '[70,70]', 'evidence': ''}]:
            with self.subTest(fields=fields):
                data = {'action': 'evaluate', 'evidence': 'شاهد آزمون', 'recommendation': 'advance', **fields}
                self.assertEqual(self.app_post(app, data).status_code, 400)
                self.assertFalse(Evaluation.objects.exists())

    def test_strong_candidate_rejection_is_queued_for_executive(self):
        app = self.application()
        url = f'{self.api}applications/{app.pk}/'
        self.app_post(app, {'action': 'evaluate', 'scores': '[95,95]', 'evidence': 'آزمون عملی کامل', 'recommendation': 'advance'})
        response = self.update(app, stage='rejected', decision_reason='نیاز به بررسی ظرفیت')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertTrue(app.review_required)
        self.assertEqual(app.pending_stage, 'rejected')
        self.assertNotEqual(app.stage, 'rejected')
        self.assertEqual(self.app_post(app, {'action': 'approve', 'decision': 'approve', 'text': 'تأیید'}).status_code, 403)
        self.client.force_login(self.executive)
        approved = self.app_post(app, {'action': 'approve', 'decision': 'approve', 'text': 'بررسی و تأیید تصمیم'})
        self.assertEqual(approved.status_code, 200)
        app.refresh_from_db()
        self.assertEqual(app.stage, 'rejected')
        self.assertFalse(app.review_required)
        self.assertEqual(app.approved_by_id, self.executive.pk)

    def test_out_of_budget_offer_cannot_skip_executive_review(self):
        app = self.application()
        response = self.update(app, stage='offer', offered_salary='40000000')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertTrue(app.review_required)
        self.assertEqual(app.pending_stage, 'offer')
        self.assertNotEqual(app.stage, 'offer')
        skip = self.update(app, stage='accepted', offered_salary='40000000')
        self.assertEqual(skip.status_code, 200, skip.content.decode())
        app.refresh_from_db()
        self.assertNotEqual(app.stage, 'accepted')
        self.assertTrue(app.review_required)

    def test_pdf_resume_is_private_and_downloaded_as_attachment(self):
        pdf = SimpleUploadedFile('cv.pdf', b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF', content_type='application/pdf')
        app = self.application(resume=pdf)
        detail = self.client.get(f'{self.api}applications/{app.pk}/').json()['application']
        download = detail['candidate']['resume_url']
        self.assertNotIn('/media/', download)
        response = self.client.get(download)
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response['Content-Disposition'])
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(download).status_code, 403)
        self.client.force_login(self.manager)
        session = self.client.session
        session['greenlife_country_scope'] = 'TR'
        session.save()
        self.assertEqual(self.client.get(download).status_code, 404)
        self.assertEqual(self.client.get(f'{self.api}applications/{app.pk}/').status_code, 404)

    def test_non_pdf_and_large_pdf_are_rejected_atomically(self):
        for uploaded in [
            SimpleUploadedFile('cv.html', b'<script>alert(1)</script>', content_type='text/html'),
            SimpleUploadedFile('cv.pdf', b'not a pdf', content_type='application/pdf'),
            SimpleUploadedFile('cv.pdf', b'%PDF-' + b'x' * (5 * 1024 * 1024), content_type='application/pdf'),
        ]:
            with self.subTest(name=uploaded.name, size=uploaded.size):
                response = self.new_application(resume=uploaded)
                self.assertEqual(response.status_code, 400, response.content.decode())
                self.assertFalse(Application.objects.exists())
                self.assertFalse(Candidate.objects.exists())

    def test_country_scope_applies_to_detail_updates_and_ads(self):
        self.assertEqual(self.job_post(self.tr_job, self.job_data(action='save')).status_code, 404)
        response = self.client.post(self.api + 'ads/', {'job': self.tr_job.pk, 'title': 'آگهی', 'body': 'شرح آگهی'})
        self.assertEqual(response.status_code, 400)
        session = self.client.session
        session['greenlife_country_scope'] = 'ALL'
        session.save()
        jobs = self.client.get(self.api).json()['jobs']
        self.assertIn(self.job.pk, [j['id'] for j in jobs])
        self.assertIn(self.tr_job.pk, [j['id'] for j in jobs])

    def test_ad_requires_verified_publication_url_before_active_status(self):
        data = {'job': self.job.pk, 'source': 'divar', 'title': 'استخدام منشی', 'body': 'شرح شرایط همکاری', 'status': 'active'}
        self.assertEqual(self.client.post(self.api + 'ads/', data).status_code, 400)
        self.assertEqual(self.client.post(self.api + 'ads/', {**data, 'url': 'javascript:alert(1)'}).status_code, 400)
        response = self.client.post(self.api + 'ads/', {**data, 'url': 'https://divar.ir/v/test-post', 'cost': '150000'})
        self.assertEqual(response.status_code, 200, response.content.decode())
        ad = Advertisement.objects.get()
        self.assertEqual(ad.cost, 150000)
        self.assertEqual(ad.status, 'active')

    def test_probation_outcome_does_not_automatically_finalize_hiring(self):
        app = self.application()
        app.stage = 'probation'
        app.start_date = timezone.localdate()
        app.save(update_fields=['stage', 'start_date'])
        url = f'{self.api}applications/{app.pk}/'
        self.assertEqual(self.app_post(app, {'action': 'probation', 'probation_outcome': ''}).status_code, 400)
        response = self.app_post(app, {'action': 'probation', 'probation_outcome': 'دقت ثبت اطلاعات مناسب بود', 'probation_review_at': timezone.localdate().isoformat()})
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'probation')
        self.assertIn('دقت', app.probation_outcome)
        self.assertTrue(Activity.objects.filter(application=app, actor=self.manager).exists())

    def test_unknown_actions_and_missing_records_fail_safely(self):
        app = self.application()
        self.assertEqual(self.app_post(app, {'action': 'delete'}).status_code, 400)
        self.assertTrue(Application.objects.filter(pk=app.pk).exists())
        self.assertEqual(self.client.get(f'{self.api}applications/99999999/').status_code, 404)
        self.assertEqual(self.client.get(self.api + 'jobs/').status_code, 405)

    def test_candidate_application_does_not_create_staff_account(self):
        before_users = User.objects.count()
        before_profiles = EmployeeProfile.objects.count()
        self.application()
        self.assertEqual(User.objects.count(), before_users)
        self.assertEqual(EmployeeProfile.objects.count(), before_profiles)

    def test_private_application_data_not_returned_after_country_switch(self):
        app = self.application()
        session = self.client.session
        session['greenlife_country_scope'] = 'TR'
        session.save()
        payload = self.client.get(self.api).json()
        self.assertEqual(payload['applications'], [])
        self.assertNotIn(app.candidate.phone, json.dumps(payload))
        response = self.update(app, stage='screening')
        self.assertEqual(response.status_code, 404)
        app.refresh_from_db()
        self.assertEqual(app.stage, 'new')

    def test_manager_cannot_disable_executive_gate_on_key_position(self):
        self.job.requires_executive_approval = True
        self.job.save(update_fields=['requires_executive_approval'])
        data = self.job_data(action='save', requires_executive_approval='')
        response = self.job_post(self.job, data)
        self.assertIn(response.status_code, (200, 400, 403))
        self.job.refresh_from_db()
        self.assertTrue(self.job.requires_executive_approval)

    def test_full_started_to_probation_workflow_is_audited(self):
        app = self.application(requested_salary='25000000')
        response = self.update(app, stage='offer', offered_salary='25000000')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'offer')
        self.assertFalse(app.review_required)
        response = self.update(app, stage='started', offered_salary='25000000', start_date=timezone.localdate().isoformat())
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'started')
        url = f'{self.api}applications/{app.pk}/'
        self.assertEqual(self.app_post(app, {'action': 'probation', 'probation_outcome': 'آموزش کامل و عملکرد مناسب'}).status_code, 200)
        app.refresh_from_db()
        response = self.update(app, stage='hired', offered_salary='25000000', start_date=timezone.localdate().isoformat())
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'hired')
        self.assertGreaterEqual(Activity.objects.filter(application=app).count(), 4)

    def test_changing_offer_after_executive_approval_requires_new_review(self):
        app = self.application()
        self.update(app, stage='offer', offered_salary='40000000')
        app.refresh_from_db()
        self.client.force_login(self.executive)
        url = f'{self.api}applications/{app.pk}/'
        approved = self.app_post(app, {'action': 'approve', 'decision': 'approve', 'text': 'تأیید استثنای حقوق ۴۰ میلیون'})
        self.assertEqual(approved.status_code, 200, approved.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'offer')
        self.client.force_login(self.manager)
        updated = self.update(app, stage='accepted', offered_salary='50000000')
        self.assertEqual(updated.status_code, 200, updated.content.decode())
        app.refresh_from_db()
        self.assertTrue(app.review_required)
        self.assertNotEqual(app.stage, 'accepted')
        self.assertIsNone(app.approved_by_id)

    def test_offer_approval_does_not_authorize_later_strong_candidate_rejection(self):
        app = self.application()
        url = f'{self.api}applications/{app.pk}/'
        self.app_post(app, {'action': 'evaluate', 'scores': '[95,95]', 'evidence': 'ارزیابی عملی', 'recommendation': 'advance'})
        self.update(app, stage='offer', offered_salary='40000000', decision_reason='نیازمند تصمیم مدیریت')
        self.client.force_login(self.executive)
        self.app_post(app, {'action': 'approve', 'decision': 'approve', 'text': 'تأیید استثنای پیشنهاد حقوق'})
        app.refresh_from_db()
        self.assertEqual(app.stage, 'offer')
        self.client.force_login(self.manager)
        response = self.update(app, stage='rejected', decision_reason='نیازمند تصمیم مدیریت')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertNotEqual(app.stage, 'rejected')
        self.assertTrue(app.review_required)
        self.assertEqual(app.pending_stage, 'rejected')

    def test_changed_pending_decision_cannot_approve_stale_offer(self):
        app = self.application()
        self.update(app, stage='offer', offered_salary='40000000')
        app.refresh_from_db()
        self.assertEqual(app.pending_stage, 'offer')
        response = self.update(app, stage='withdrawn', decision_reason='متقاضی از همکاری انصراف داد')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertNotEqual(app.pending_stage, 'offer')
        if app.review_required:
            self.client.force_login(self.executive)
            approved = self.app_post(app, {'action': 'approve', 'decision': 'approve', 'text': 'تأیید تصمیم جدید'})
            self.assertEqual(approved.status_code, 200, approved.content.decode())
        app.refresh_from_db()
        self.assertNotEqual(app.stage, 'offer')

    def test_stale_application_form_cannot_overwrite_a_newer_decision(self):
        app = self.application()
        stale = app.updated_at.isoformat()
        first = self.update(app, stage='screening', next_action='تماس دوم')
        self.assertEqual(first.status_code, 200, first.content.decode())
        response = self.app_post(app, {
            'action': 'update', 'expected_updated_at': stale,
            'stage': 'rejected', 'decision_reason': 'فرم قدیمی',
        })
        self.assertEqual(response.status_code, 409, response.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'screening')
        self.assertEqual(app.next_action, 'تماس دوم')

    def test_stale_budget_approval_cannot_approve_a_changed_salary_range(self):
        stale = self.job.updated_at.isoformat()
        response = self.job_post(self.job, self.job_data(action='save', salary_max='60000000'))
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.client.force_login(self.executive)
        response = self.job_post(self.job, {'action': 'approve_budget', 'expected_updated_at': stale})
        self.assertEqual(response.status_code, 409, response.content.decode())
        self.job.refresh_from_db()
        self.assertFalse(self.job.budget_approved)
        self.assertEqual(self.job.salary_max, 60000000)

    def test_matching_phone_with_different_name_does_not_silently_reuse_identity(self):
        app = self.application()
        response = self.new_application(job=self.other_job.pk, name='شخص متفاوت')
        self.assertEqual(response.status_code, 400, response.content.decode())
        self.assertEqual(Application.objects.count(), 1)
        app.candidate.refresh_from_db()
        self.assertEqual(app.candidate.name, 'متقاضی آزمون')

    def test_probation_cannot_be_recorded_before_starting_work(self):
        app = self.application()
        response = self.app_post(app, {'action': 'probation', 'probation_outcome': 'نتیجه زودهنگام'})
        self.assertEqual(response.status_code, 400)
        app.refresh_from_db()
        self.assertEqual(app.probation_outcome, '')

    def test_valid_csrf_token_allows_authenticated_job_creation(self):
        protected_client = Client(enforce_csrf_checks=True)
        protected_client.force_login(self.manager)
        page = protected_client.get(self.base)
        self.assertEqual(page.status_code, 200)
        csrf = protected_client.cookies['csrftoken'].value
        response = protected_client.post(self.api + 'jobs/', self.job_data(), HTTP_X_CSRFTOKEN=csrf)
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.assertTrue(Job.objects.filter(title='استخدام آزمایشی').exists())

    def test_job_history_is_scoped_and_records_budget_changes(self):
        response = self.job_post(self.job, self.job_data(action='save', salary_max='35000000'))
        self.assertEqual(response.status_code, 200, response.content.decode())
        history = self.client.get(f'{self.api}jobs/{self.job.pk}/')
        self.assertEqual(history.status_code, 200, history.content.decode())
        events = history.json()['job']['activities']
        self.assertTrue(events)
        self.assertTrue(any('salary_max' in event.get('changes', {}) for event in events))
        self.assertEqual(self.client.get(f'{self.api}jobs/{self.tr_job.pk}/').status_code, 404)

    def test_review_disagreement_is_queued_without_changing_stage(self):
        app = self.application()
        self.app_post(app, {'action': 'evaluate', 'scores': '[95,95]', 'evidence': 'آزمون اول', 'recommendation': 'advance'})
        self.client.force_login(self.reviewer)
        response = self.app_post(app, {'action': 'evaluate', 'scores': '[50,50]', 'evidence': 'آزمون دوم', 'recommendation': 'review'})
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertTrue(app.review_required)
        self.assertEqual(app.stage, 'new')
        self.assertTrue(app.review_reason)

    def test_acknowledging_review_disagreement_is_not_salary_exception_approval(self):
        app = self.application()
        self.update(app, stage='new', offered_salary='40000000')
        app.refresh_from_db()
        self.app_post(app, {'action': 'evaluate', 'scores': '[95,95]', 'evidence': 'آزمون اول', 'recommendation': 'advance'})
        self.client.force_login(self.reviewer)
        self.app_post(app, {'action': 'evaluate', 'scores': '[50,50]', 'evidence': 'آزمون دوم', 'recommendation': 'review'})
        self.client.force_login(self.executive)
        response = self.app_post(app, {'action': 'approve', 'decision': 'approve', 'text': 'اختلاف بررسی شد؛ ادامه بررسی اولیه'})
        self.assertEqual(response.status_code, 200, response.content.decode())
        self.client.force_login(self.manager)
        response = self.update(app, stage='offer', offered_salary='40000000')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertTrue(app.review_required)
        self.assertNotEqual(app.stage, 'offer')
        self.assertEqual(app.pending_stage, 'offer')

    def test_candidate_contact_correction_is_shared_across_job_applications(self):
        app = self.application()
        second = self.application(job=self.other_job.pk)
        response = self.app_post(app, {
            'action': 'candidate_update', 'name': 'نام اصلاح‌شده',
            'email': 'applicant@example.com', 'city': 'تهران', 'resume_text': 'سابقه تکمیل‌شده',
        })
        self.assertEqual(response.status_code, 200, response.content.decode())
        candidate = Candidate.objects.get(pk=app.candidate_id)
        self.assertEqual(candidate.name, 'نام اصلاح‌شده')
        self.assertEqual(candidate.email, 'applicant@example.com')
        detail = self.client.get(f'{self.api}applications/{second.pk}/').json()['application']
        self.assertEqual(detail['candidate']['name'], 'نام اصلاح‌شده')
        self.assertTrue(Activity.objects.filter(application=app, kind='candidate_updated', actor=self.manager).exists())

    def test_candidate_edit_cannot_change_identity_phone_or_accept_invalid_pdf(self):
        app = self.application()
        old_phone = app.candidate.phone
        response = self.app_post(app, {'action': 'candidate_update', 'name': app.candidate.name, 'phone': '09122223333'})
        self.assertIn(response.status_code, (200, 400))
        app.candidate.refresh_from_db()
        self.assertEqual(app.candidate.phone, old_phone)
        response = self.app_post(app, {
            'action': 'candidate_update', 'name': 'تغییر نام نامعتبر',
            'resume': SimpleUploadedFile('cv.pdf', b'<html>bad file</html>', content_type='application/pdf'),
        })
        self.assertEqual(response.status_code, 400, response.content.decode())
        app.candidate.refresh_from_db()
        self.assertEqual(app.candidate.name, 'متقاضی آزمون')
        self.assertFalse(app.candidate.resume_data)

    def test_candidate_resume_can_be_added_privately_after_registration(self):
        app = self.application()
        pdf_data = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\n%%EOF'
        response = self.app_post(app, {
            'action': 'candidate_update', 'name': app.candidate.name,
            'resume': SimpleUploadedFile('updated-cv.pdf', pdf_data, content_type='application/pdf'),
        })
        self.assertEqual(response.status_code, 200, response.content.decode())
        details = self.client.get(f'{self.api}applications/{app.pk}/').json()['application']['candidate']
        self.assertEqual(details['resume_name'], 'updated-cv.pdf')
        download = self.client.get(details['resume_url'])
        self.assertEqual(download.content, pdf_data)
        self.assertIn('attachment', download['Content-Disposition'])

    def test_stale_candidate_edit_from_second_application_does_not_overwrite(self):
        app = self.application()
        second = self.application(job=self.other_job.pk)
        stale = Candidate.objects.get(pk=app.candidate_id).updated_at.isoformat()
        first = self.app_post(app, {'action': 'candidate_update', 'name': 'نام جدید', 'city': 'تهران'})
        self.assertEqual(first.status_code, 200, first.content.decode())
        response = self.app_post(second, {
            'action': 'candidate_update', 'expected_candidate_updated_at': stale,
            'name': 'نام فرم قدیمی', 'city': 'رشت',
        })
        self.assertEqual(response.status_code, 409, response.content.decode())
        candidate = Candidate.objects.get(pk=app.candidate_id)
        self.assertEqual(candidate.name, 'نام جدید')
        self.assertEqual(candidate.city, 'تهران')

    def test_disagreement_review_cannot_be_cleared_by_changing_screening_stage(self):
        app = self.application()
        self.app_post(app, {'action': 'evaluate', 'scores': '[95,95]', 'evidence': 'آزمون اول', 'recommendation': 'advance'})
        self.client.force_login(self.reviewer)
        self.app_post(app, {'action': 'evaluate', 'scores': '[50,50]', 'evidence': 'آزمون دوم', 'recommendation': 'review'})
        self.client.force_login(self.manager)
        app.refresh_from_db()
        self.assertTrue(app.review_required)
        response = self.update(app, stage='screening')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertTrue(app.review_required)
        response = self.update(app, stage='offer', offered_salary='25000000')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertNotEqual(app.stage, 'offer')
        self.assertTrue(app.review_required)
        response = self.update(app, stage='screening')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertTrue(app.review_required)
        response = self.update(app, stage='offer', offered_salary='25000000')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertNotEqual(app.stage, 'offer')
        self.assertTrue(app.review_required)
        self.client.force_login(self.executive)
        approved = self.app_post(app, {'action': 'approve', 'decision': 'approve', 'text': 'اختلاف ارزیابی بررسی و پیشنهاد همکاری تأیید شد'})
        self.assertEqual(approved.status_code, 200, approved.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'offer')
        self.assertFalse(app.review_required)
        self.client.force_login(self.manager)
        response = self.update(app, stage='accepted', offered_salary='25000000')
        self.assertEqual(response.status_code, 200, response.content.decode())
        app.refresh_from_db()
        self.assertEqual(app.stage, 'accepted')
        self.assertFalse(app.review_required)
