"""Privacy-safe CRM lead monitoring and daily SMS planning, without dispatch."""
import logging
import time
from datetime import datetime, time as dt_time, timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.db.models import Count
from django.utils import timezone

from core.models import MarketingWorkerState, MarketingSmsPlan, ReferralLead

logger = logging.getLogger(__name__)

# Messages are intentionally general: no clinical diagnosis, medical history,
# false weight-loss guarantees or sensitive personal details. No sending here.
SMS_ROTATION = (
    ("lead_site", "ورودی‌های وب‌سایت",
     "سلام از گرین‌لایف. اگر هنوز پرسشی درباره خدمات تناسب‌اندام و مشاوره دارید، همکاران ما آماده راهنمایی هستند. تلفن: 02134247\nلغو 11",
     "پاسخ به علاقه‌مندی ثبت‌شده در وب‌سایت، بدون وعده درمانی"),
    ("lead_instagram", "ورودی‌های اینستاگرام",
     "گرین‌لایف: برای آشنایی بیشتر با خدمات ما یا گرفتن وقت مشاوره، می‌توانید با 02134247 تماس بگیرید. انتخاب و تصمیم نهایی با شماست.\nلغو 11",
     "دعوت غیرتهاجمی به گفت‌وگو، بدون ادعای نتیجه"),
    ("visit_no_show", "نوبت‌های بدون مراجعه",
     "سلام از گرین‌لایف. اگر مایل به هماهنگی مجدد زمان گفت‌وگو با مجموعه ما هستید، از طریق 02134247 همراهتان هستیم.\nلغو 11",
     "پیگیری مودبانه بدون افشای اطلاعات پزشکی"),
    ("lead_followup", "درخواست‌های پیگیری",
     "سلام؛ گرین‌لایف هستیم. در صورتی که هنوز برای دریافت اطلاعات یا هماهنگی مشاوره تمایل دارید، با 02134247 تماس بگیرید.\nلغو 11",
     "ادامه گفت‌وگو صرفاً با مخاطبان علاقه‌مند"),
    ("lead_no_answer", "لیدهای بی‌پاسخ",
     "سلام از گرین‌لایف. هر زمان تمایل داشتید درباره خدمات مجموعه بیشتر بدانید، با 02134247 تماس بگیرید.\nلغو 11",
     "یادآوری ملایم؛ بدون تماس یا ارسال تکراری"),
)


def _heartbeat(key, now, count, activity):
    MarketingWorkerState.objects.update_or_create(
        key=key,
        defaults={
            "heartbeat_at": now,
            "last_run_leads": count,
            "activity": activity[:180],
            "last_error": "",
        },
    )


def _plan_today(day):
    """Create one proposal per day. Never call an SMS gateway or queue."""
    selected = SMS_ROTATION[day.toordinal() % len(SMS_ROTATION)]
    key, title, message, rationale = selected
    # Do not make phone lists, snapshots, or infer that CRM entry equals
    # verified consent. Audience count is an optional bounded estimate only.
    def build_defaults():
        from core.bulk_sms_audiences import audience_preview
        count = None
        limited = False
        try:
            estimate = audience_preview(
                [key], date_filter={"preset": "30", "event": "lead" if key.startswith("lead_") else "visit"},
                max_contacts=1600, include_numbers=False,
            )
            count, limited = estimate["count"], estimate["truncated"]
        except (ValueError, TypeError):
            # No viable segment or filtered events must not stop planning.
            logger.info("Daily SMS proposal segment preview unavailable")
        return {
            "segment_key": key,
            "segment_title": title,
            "body": message,
            "rationale": rationale,
            "candidate_count": count,
            "preview_limited": limited,
            "status": "proposal",
        }

    existing = MarketingSmsPlan.objects.filter(day=day).first()
    if existing:
        return existing
    proposal, _ = MarketingSmsPlan.objects.get_or_create(day=day, defaults=build_defaults())
    return proposal


def monitor_once():
    now = timezone.now()
    day = timezone.localdate(now)
    start = timezone.make_aware(datetime.combine(day, dt_time.min))
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), dt_time.min))
    todays_leads = ReferralLead.objects.filter(
        country__code="IR",
        created_at__gte=start,
        created_at__lt=end,
    )
    count = todays_leads.count()
    _heartbeat("commander", now, count, "پایش ورود لیدهای واقعی CRM ایران؛ بدون تغییر پرونده یا پیامک")

    # A real source monitor: observes attribution INSIDE CRM, not web search.
    try:
        sources = list(todays_leads.values("source").annotate(n=Count("id")).order_by("-n")[:3])
        top = "، ".join(f"{x['source']}:{x['n']}" for x in sources) or "بدون ورودی"
        _heartbeat("source", now, count, f"پایش منبع ثبت لید در CRM؛ امروز {count} ورودی؛ {top} (بدون جست‌وجوی بیرونی)")
    except Exception:
        logger.exception("CRM source monitor failed")

    # A real operational quality monitor: explicit status counts; no
    # fabricated qualification or clinical scoring.
    try:
        actionable = todays_leads.filter(status__in=["appointment", "visited", "won"]).count()
        _heartbeat(
            "quality", now, actionable,
            f"پایش مرحله ثبت‌شده لید: {actionable} نوبت/مراجعه/فروش از {count} ورودی امروز؛ کیفیت بالینی اندازه‌گیری نشده",
        )
    except Exception:
        logger.exception("CRM lead quality status monitor failed")

    # SMS agent plans one new campaign concept a day, NOT an automatic send.
    try:
        plan = _plan_today(day)
        candidate = "نامشخص" if plan.candidate_count is None else str(plan.candidate_count)
        _heartbeat(
            "sms", now, plan.candidate_count or 0,
            f"برنامه روزانه پیامک آماده: {plan.segment_title}؛ پیش‌نمایش {candidate} شماره CRM؛ بدون ارسال خودکار",
        )
    except Exception:
        logger.exception("Daily SMS planning failed")
    return count


class Command(BaseCommand):
    help = "Run truthful CRM monitoring and daily marketing SMS proposals; never dispatch SMS."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true")
        parser.add_argument("--interval", type=int, default=60)

    def handle(self, *args, **options):
        interval = max(60, min(int(options["interval"]), 300))
        while True:
            close_old_connections()
            try:
                count = monitor_once()
                self.stdout.write(f"CRM monitoring heartbeat OK; new Iran rows today={count}")
            except Exception:
                logger.exception("Marketing lead monitor cycle failed")
                if not options["loop"]:
                    raise
            finally:
                close_old_connections()
            if not options["loop"]:
                return
            time.sleep(interval)
