"""Real callbacks must not disappear between call attempts or long waits."""
from datetime import time, timedelta
from urllib.parse import parse_qs, urlsplit

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.forms import CallCenterLeadForm
from core.models import EmployeeProfile, LeadFollowUpLog, ReferralLead, ReferralProfile


class CallbackAgendaTests(TestCase):
    def setUp(self):
        self.today=timezone.localdate()
        self.worker=User.objects.create_user("callback-worker",first_name="فاطمه",last_name="بابایی")
        self.other=User.objects.create_user("callback-foreign",first_name="بنفشه")
        self.manager=User.objects.create_user("callback-manager",first_name="هاشمی")
        self.ref_user=User.objects.create_user("callback-source")
        self.worker_profile=EmployeeProfile.objects.update_or_create(
            user=self.worker,defaults={"role":"call_center","is_active":True})[0]
        self.other_profile=EmployeeProfile.objects.update_or_create(
            user=self.other,defaults={"role":"call_center","is_active":True})[0]
        EmployeeProfile.objects.update_or_create(
            user=self.manager,defaults={"role":"internal_manager","is_active":True})
        self.ref=ReferralProfile.objects.get_or_create(
            user=self.ref_user,defaults={"referral_code":"CALLBACKAGENDA"})[0]
        self.old=self.lead("قدیمی شش ماهه", "09121111801", self.worker_profile, self.today)
        # Deliberately backdate creation; today must still show the callback.
        ReferralLead.objects.filter(pk=self.old.pk).update(
            created_at=timezone.now()-timedelta(days=185))
        self.overdue=self.lead("عقب‌افتاده", "09121111802",self.worker_profile,self.today-timedelta(days=5))
        self.future=self.lead("شش ماه بعد", "09121111803",self.worker_profile,self.today+timedelta(days=183))
        self.foreign=self.lead("مربوط به اپراتور دیگر","09121111804",self.other_profile,self.today)

    def lead(self,name,phone,operator,due):
        return ReferralLead.objects.create(
            referrer=self.ref,full_name=name,phone=phone,assigned_to=operator,
            status="contacted",contact_result="follow_up",next_follow_up=due,
        )

    def test_old_scheduled_lead_is_in_todays_popup_and_full_agenda(self):
        self.client.force_login(self.worker)
        response=self.client.get(reverse("call_center_dashboard"))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'id="ccCallbackToday"')
        self.assertContains(response,self.old.full_name)
        self.assertContains(response,"تماس‌های مقرر امروز")
        items=self.client.get(reverse("call_center_follow_up_agenda"),{"tab":"today"})
        self.assertEqual(items.status_code,200)
        self.assertContains(items,self.old.full_name)
        self.assertNotContains(items,self.foreign.full_name)

    def test_all_future_promises_searchable_beyond_preview_limit(self):
        for index in range(48):
            self.lead(f"دوره آینده {index}",f"0912777{index:04d}",self.worker_profile,
                      self.today+timedelta(days=185))
        self.client.force_login(self.worker)
        p=self.client.get(reverse("call_center_follow_up_agenda"),{"tab":"future"})
        self.assertEqual(p.context["counts"]["future"],49)
        self.assertEqual(p.context["page"].paginator.count,49)
        self.assertEqual(len(p.context["cards"]),40)
        next_page=self.client.get(reverse("call_center_follow_up_agenda"),
                                  {"tab":"future","page":2})
        self.assertEqual(len(next_page.context["cards"]),9)
        found=self.client.get(reverse("call_center_follow_up_agenda"),
                              {"tab":"future","q":self.future.phone})
        self.assertEqual(found.context["page"].paginator.count,1)
        self.assertEqual(found.context["cards"][0]["lead"].pk,self.future.pk)

    def test_no_answer_preserves_original_due_date_and_creates_audit_log(self):
        self.client.force_login(self.worker)
        url=reverse("call_center_save_call_result",args=[self.old.pk])
        result=self.client.post(url,{"result":"no_answer"})
        self.assertEqual(result.status_code,200,result.content)
        self.old.refresh_from_db()
        self.assertEqual(self.old.next_follow_up,self.today)
        self.assertEqual(self.old.contact_result,"no_answer")
        self.assertEqual(LeadFollowUpLog.objects.filter(lead=self.old,action="attempt").count(),1)
        done=self.client.get(reverse("call_center_follow_up_agenda"),{"tab":"done"})
        self.assertEqual(done.context["counts"]["done"],1)
        self.assertContains(done,self.old.full_name)

    def test_six_month_interval_stores_real_clock_and_changes_date(self):
        self.client.force_login(self.worker)
        result=self.client.post(reverse("call_center_save_call_result",args=[self.old.pk]),{
            "result":"follow_up","follow_up_interval":"months:6",
            "follow_up_note":"مشتری درخواست تماس شش ماه بعد دارد",
        })
        self.assertEqual(result.status_code,200,result.content)
        self.old.refresh_from_db()
        self.assertGreater(self.old.next_follow_up,self.today+timedelta(days=170))
        self.assertIsNotNone(self.old.next_follow_up_time)
        log=LeadFollowUpLog.objects.filter(lead=self.old).latest("pk")
        self.assertEqual(log.previous_date,self.today)
        self.assertEqual(log.scheduled_for,self.old.next_follow_up)
        self.assertEqual(log.scheduled_time,self.old.next_follow_up_time)
        self.assertIn("شش ماه",log.note)
        self.assertEqual(self.client.get(reverse("call_center_follow_up_agenda"),
                          {"tab":"today"}).context["counts"]["today"],0)

    def test_explicit_date_time_is_persisted_and_legacy_date_has_no_fake_time(self):
        self.client.force_login(self.worker)
        scheduled=self.today+timedelta(days=5)
        result=self.client.post(reverse("call_center_save_call_result",args=[self.old.pk]),{
            "result":"follow_up","next_follow_up":scheduled.isoformat(),
            "follow_up_time":"11:35",
        })
        self.assertEqual(result.status_code,200,result.content)
        self.old.refresh_from_db()
        self.assertEqual(self.old.next_follow_up_time,time(11,35))
        self.assertIsNone(self.future.next_follow_up_time)
        p=self.client.get(reverse("call_center_follow_up_agenda"),{"tab":"future"})
        self.assertContains(p,"11:35")
        self.assertContains(p,"ثبت نشده")

    def test_details_form_does_not_clear_promised_date_on_no_answer(self):
        original=self.today+timedelta(days=19)
        self.overdue.next_follow_up=original
        self.overdue.next_follow_up_time=time(14,20)
        self.overdue.save()
        form=CallCenterLeadForm({
            "contact_result":"no_answer","next_follow_up":"","notes":"تماس مجدد، پاسخی نبود",
        },instance=self.overdue,operator=self.worker_profile)
        self.assertTrue(form.is_valid(),form.errors.as_json())
        form.save()
        self.overdue.refresh_from_db()
        self.assertEqual(self.overdue.next_follow_up,original)
        self.assertEqual(self.overdue.next_follow_up_time,time(14,20))

    def test_role_boundaries_and_internal_manager_oversight(self):
        self.client.force_login(self.other)
        page=self.client.get(reverse("call_center_follow_up_agenda"),{"tab":"today"})
        self.assertContains(page,self.foreign.full_name)
        self.assertNotContains(page,self.old.full_name)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(reverse("call_center_follow_up_agenda")).status_code,403)
        manager=self.client.get(reverse("management_follow_up_agenda"))
        self.assertEqual(manager.status_code,200)
        self.assertContains(manager,"نظارت بر تعهدات تماس کال‌سنتر")
        self.assertContains(manager,self.old.full_name)
        self.assertContains(manager,"نرگس")
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(reverse("management_follow_up_agenda")).status_code,403)

    def test_terminal_leads_do_not_pollute_due_counts(self):
        ReferralLead.objects.filter(pk=self.old.pk).update(status="won")
        ReferralLead.objects.filter(pk=self.overdue.pk).update(status="lost")
        self.client.force_login(self.worker)
        result=self.client.get(reverse("call_center_follow_up_agenda"))
        self.assertEqual(result.context["counts"]["today"],0)
        self.assertEqual(result.context["counts"]["overdue"],0)

    def test_management_recorded_actions_use_actor_and_original_due_time(self):
        due_time = time(9, 30)
        newer_due = self.today + timedelta(days=10)
        LeadFollowUpLog.objects.create(
            lead=self.old, actor=self.worker, previous_date=self.today,
            previous_time=due_time, scheduled_for=newer_due,
            action="scheduled", result="follow_up",
        )
        LeadFollowUpLog.objects.create(
            lead=self.old, actor=self.worker,
            previous_date=self.today, previous_time=due_time,
            action="attempt", result="no_answer",
        )
        LeadFollowUpLog.objects.create(
            lead=self.foreign, actor=self.manager, previous_date=self.today,
            action="attempt", result="no_answer",
        )
        LeadFollowUpLog.objects.create(
            lead=self.future, actor=self.worker, scheduled_for=newer_due,
            action="scheduled", result="follow_up",
        )
        ReferralLead.objects.filter(pk=self.old.pk).update(
            assigned_to=self.other_profile, contact_result="follow_up",
            next_follow_up=newer_due, next_follow_up_time=time(11),
        )
        self.client.force_login(self.manager)
        response = self.client.get(reverse("management_follow_up_agenda"), {
            "tab": "done", "operator": self.worker_profile.pk,
        })
        self.assertEqual(response.context["counts"]["done"], 1)
        rows = list(response.context["page"])
        self.assertEqual([row["id"] for row in rows], [self.old.pk])
        row = rows[0]
        self.assertEqual(row["handled_by"], "نرگس")
        self.assertEqual(row["assigned_name"], "بنفشه")
        self.assertEqual(row["next_follow_up"], self.today)
        self.assertEqual(row["next_follow_up_time"], due_time)
        self.assertEqual(row["result_label"], "پاسخ نداد")
        self.assertEqual(timezone.localdate(row["handled_at"]), self.today)

    def test_management_unassigned_name_filter_and_pii_boundary(self):
        unassigned = self.lead("مشتری بی مسئول", "09121111805", None, self.today)
        unscheduled = self.lead("مشتری بدون موعد", "09121111806", None, None)
        no_follow_up = self.lead("مشتری جدید", "09121111807", None, None)
        ReferralLead.objects.filter(pk=no_follow_up.pk).update(contact_result="")
        self.client.force_login(self.manager)
        url = reverse("management_follow_up_agenda")
        result = self.client.get(url, {"tab": "all", "operator": "unassigned", "q": "مشتری"})
        self.assertEqual(result.context["unassigned"], 2)
        self.assertEqual([row["id"] for row in result.context["page"]], [unassigned.pk, unscheduled.pk])
        for row in result.context["page"]:
            self.assertNotIn("phone", row)
            self.assertFalse(row["detail_url"])
        self.assertNotContains(result, unassigned.phone)
        self.assertNotContains(result, reverse("management_lead_follow_up", args=[unassigned.pk]))
        self.assertEqual(self.client.get(url, {"tab": "all", "q": unassigned.phone}).context["page"].paginator.count, 0)

        EmployeeProfile.objects.filter(user=self.manager).update(role="manager")
        overview = self.client.get(url, {"tab": "all", "operator": "unassigned"})
        self.assertEqual(overview.context["page"][0]["detail_url"],
                         reverse("management_lead_follow_up", args=[unassigned.pk]))

    def test_management_pagination_retains_filters_and_chronological_order(self):
        future_date = self.today + timedelta(days=2)
        for index in range(52):
            lead = self.lead(f"پیگیری گروه الف {index}", f"0912777{index:04d}",
                             self.worker_profile, future_date)
            if index == 51:
                ReferralLead.objects.filter(pk=lead.pk).update(next_follow_up_time=time(8))
                timed_lead_id = lead.pk

        self.client.force_login(self.manager)
        options = {
            "tab": "all", "q": "پیگیری گروه الف", "date": future_date.isoformat(),
            "operator": str(self.worker_profile.pk),
        }
        url = reverse("management_follow_up_agenda")
        response = self.client.get(url, options)
        self.assertEqual(response.context["page"].paginator.count, 52)
        self.assertEqual(response.context["page"][0]["id"], timed_lead_id)
        self.assertEqual(response.context["exact_date_input"], future_date.isoformat())
        self.assertEqual(parse_qs(response.context["page_query"]), {key: [value] for key, value in options.items()})
        done_link = next(item["url"] for item in response.context["tabs"] if item["key"] == "done")
        self.assertNotIn("date", parse_qs(urlsplit(done_link).query))
        second_page = self.client.get(url, {**options, "page": 2})
        self.assertEqual(len(second_page.context["page"]), 2)
        invalid = self.client.get(url, {"date": "invalid", "operator": "12399999999999999999"})
        self.assertFalse(invalid.context["has_filters"])
