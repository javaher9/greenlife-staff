"""Low-frequency, read-only lead-monitor heartbeat; no patient data leaves the app."""
import logging
import time
from datetime import datetime, time as dt_time, timedelta

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from core.models import MarketingWorkerState, ReferralLead

logger = logging.getLogger(__name__)


def monitor_once():
    now = timezone.now()
    day = timezone.localdate(now)
    start = timezone.make_aware(datetime.combine(day, dt_time.min))
    end = timezone.make_aware(datetime.combine(day + timedelta(days=1), dt_time.min))
    count = ReferralLead.objects.filter(
        country__code="IR",
        created_at__gte=start,
        created_at__lt=end,
    ).count()
    MarketingWorkerState.objects.update_or_create(
        key="commander",
        defaults={
            "heartbeat_at": now,
            "last_run_leads": count,
            "activity": "پایش ورود لیدهای جدید در CRM ایران؛ بدون ارسال پیام یا تغییر پرونده",
            "last_error": "",
        },
    )
    return count


class Command(BaseCommand):
    help = "Monitor new CRM lead intake without modifying leads or contacting people."

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
