"""Create synthetic browser-test data in the explicitly isolated CI database.

This script refuses production, non-loopback PostgreSQL, or any database other
than recruitment_ci. It never sends a message or creates an external advert.
"""
from datetime import timedelta
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "greenlife.settings")

import django

django.setup()

from django.conf import settings
from django.contrib.auth import SESSION_KEY, BACKEND_SESSION_KEY, HASH_SESSION_KEY
from django.contrib.auth.models import User
from django.contrib.sessions.backends.db import SessionStore
from django.utils import timezone
from core.models import Branch, Country
from recruitment.forms import DEFAULT_CRITERIA
from recruitment.models import Activity, Advertisement, Application, Candidate, Evaluation, Job


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    database = settings.DATABASES["default"]
    if not (
        os.environ.get("RECRUITMENT_UI_QA") == "1"
        and settings.DEBUG
        and database["ENGINE"] == "django.db.backends.postgresql"
        and database["HOST"] in {"127.0.0.1", "localhost", "::1"}
        and database["NAME"] == "recruitment_ci"
    ):
        raise SystemExit("Refusing to seed: this is not the isolated recruitment CI database.")

    country, _ = Country.objects.get_or_create(
        code="IR", defaults={"name_english": "Iran", "name_local": "ایران", "sort_order": 1}
    )
    branch, _ = Branch.objects.get_or_create(
        name="شعبه آزمایشی استخدام", defaults={"country": country}
    )
    user, _ = User.objects.get_or_create(username="admin")
    user.first_name, user.last_name = "مدیر", "آزمایشی"
    user.is_active = user.is_staff = user.is_superuser = True
    user.set_unusable_password()
    user.save()
    profile = user.profile
    profile.role, profile.country, profile.branch, profile.is_active = "admin", country, branch, True
    profile.save()

    jobs = []
    for title, organization, salary in [
        ("کارشناس کال‌سنتر — موقعیت آزمایشی", "clinic", 35000000),
        ("مسئول نگهداری کمپ — موقعیت آزمایشی", "camp", 45000000),
    ]:
        job = Job.objects.create(
            country=country, branch=branch if organization == "clinic" else None,
            organization=organization, title=title, headcount=2, status="open",
            description="این اطلاعات فقط برای آزمون رابط کاربری است.",
            requirements="مهارت مرتبط و ارتباط حرفه‌ای", expected_outcomes="انجام دقیق وظایف و گزارش منظم",
            location="محل آزمایشی", shift="شیفت روز", benefits="مزایای آزمایشی",
            criteria=DEFAULT_CRITERIA, salary_min=salary-10000000, salary_max=salary,
            budget_approved=True, budget_approved_by=user, owner=user, created_by=user,
        )
        jobs.append(job)

    now = timezone.now()
    applications = []
    for index, stage in enumerate(["new", "interview", "decision", "probation", "talent"], start=1):
        candidate = Candidate.objects.create(
            country=country, name=f"متقاضی آزمایشی {index}", phone=f"+98900000010{index}",
            city="شهر آزمایشی", resume_text="رزومه ساختگی برای ارزیابی رابط؛ سابقه واقعی نیست.",
        )
        application = Application.objects.create(
            candidate=candidate, job=jobs[index % 2], owner=user, created_by=user,
            stage=stage, source="divar" if index % 2 else "referral",
            next_action="تماس و هماهنگی مرحله بعد", next_action_at=now+timedelta(days=index-2),
            interview_at=now+timedelta(minutes=30) if stage == "interview" else None,
            requested_salary=30000000, offered_salary=30000000 if stage == "probation" else None,
            start_date=now.date()-timedelta(days=3) if stage == "probation" else None,
            probation_review_at=now.date()+timedelta(days=7) if stage == "probation" else None,
            decision_reason="ذخیره برای فرصت آینده" if stage == "talent" else "",
            review_required=stage == "decision",
            review_reason="نیازمند بررسی مدیریت — نمونه آزمایشی" if stage == "decision" else "",
        )
        Activity.objects.create(
            job=application.job, application=application, actor=user, kind="created",
            text="پرونده آزمایشی ساخته شد.",
        )
        applications.append(application)

    Evaluation.objects.create(
        application=applications[2], reviewer=user,
        scores=[dict(item, score=85) for item in DEFAULT_CRITERIA], total=85,
        evidence="شواهد ساختگی فقط برای آزمون نمایش ارزیابی", recommendation="advance",
    )
    Advertisement.objects.create(
        job=jobs[0], source="divar", title="آگهی آزمایشی کال‌سنتر",
        body="متن نمونه؛ هیچ آگهی واقعی منتشر نشده است.", status="active",
        url="https://example.org/recruitment-test", cost=100000, created_by=user,
    )

    session = SessionStore()
    session[SESSION_KEY] = str(user.pk)
    session[BACKEND_SESSION_KEY] = "django.contrib.auth.backends.ModelBackend"
    session[HASH_SESSION_KEY] = user.get_session_auth_hash()
    session["greenlife_country_scope"] = "IR"
    session.set_expiry(1800)
    session.save()
    Path(args.output).write_text(json.dumps({
        "cookie": {"name": settings.SESSION_COOKIE_NAME, "value": session.session_key,
                   "domain": "127.0.0.1", "path": "/", "httpOnly": True, "sameSite": "Lax"},
        "user_id": user.pk, "country_id": country.pk, "job_ids": [j.pk for j in jobs],
        "application_ids": [a.pk for a in applications],
    }), encoding="utf-8")
    Path(args.output).chmod(0o600)
    print("Synthetic recruitment UI fixture ready (two jobs and five applications).")


if __name__ == "__main__":
    main()
