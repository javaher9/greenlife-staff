"""Monitor the owner's fixed websites, independently of dashboard traffic."""
import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urljoin
from urllib.request import HTTPRedirectHandler, Request, ProxyHandler, build_opener

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from core.executive_board import DOMAINS, month_start
from core.models import ExecutiveSiteReading


class SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(urljoin(req.full_url, newurl))
        if (target.scheme != 'https'
                or (target.hostname or '').removeprefix('www.') != (urlsplit(req.full_url).hostname or '').removeprefix('www.')
                or target.port not in (None, 443)):
            raise HTTPError(req.full_url, 403, 'External redirect', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check(domain, proxy=None):
    request = Request('https://' + domain + '/', headers={'User-Agent': 'GreenLife-Availability/1.0'})
    try:
        handlers = [SafeRedirects()]
        if proxy:
            handlers.append(ProxyHandler({'https':proxy}))
        with build_opener(*handlers).open(request, timeout=4) as response:
            return response.status
    except HTTPError as error:
        return error.code
    except (URLError, OSError, ValueError):
        return None


def classify(code, previous):
    if code in (401, 403, 429):
        return 'unknown', 0
    if code is not None and 200 <= code < 300:
        return 'up', 0
    failures = min(previous + 1, 2)
    return ('down' if failures == 2 else 'warning'), failures


def analytics(domain, day, previous):
    # Optional Matomo instances must report these sites in Tehran time.
    endpoint = os.getenv('EXECUTIVE_MATOMO_URL', '')
    site = os.getenv('EXECUTIVE_MATOMO_' + domain.upper().replace('.', '_').replace('-', '_'))
    if not site or not endpoint.startswith('https://'):
        return {}
    if previous.get('day') == day.isoformat() and time.time() - previous.get('attempt', 0) < 300:
        return previous
    try:
        start = month_start(day)
        params = dict(module='API', method='VisitsSummary.getVisits', period='day',
                      date=f'{start},{day}', idSite=site, format='JSON',
                      token_auth=os.getenv('EXECUTIVE_MATOMO_TOKEN', ''))
        with build_opener(SafeRedirects()).open(Request(endpoint, data=urlencode(params).encode()), timeout=4) as response:
            values = json.load(response)
        days = [start + timedelta(days=n) for n in range((day-start).days+1)]
        totals = [int(values[d.isoformat()]) for d in days]
        if any(v < 0 for v in totals):
            raise ValueError()
        return dict(day=day.isoformat(), today=totals[-1], month=sum(totals), attempt=time.time())
    except (OSError, URLError, KeyError, TypeError, ValueError):
        return dict(day=day.isoformat(), attempt=time.time())


class Command(BaseCommand):
    help = 'Check the five executive board sites every 30 seconds.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true')

    def handle(self, *args, **options):
        while True:
            started = time.monotonic()
            close_old_connections()
            with ThreadPoolExecutor(max_workers=len(DOMAINS)) as pool:
                for domain, code in zip(DOMAINS, pool.map(check, DOMAINS)):
                    now = timezone.localtime()
                    old = ExecutiveSiteReading.objects.filter(pk=domain).first()
                    previous = old.failures if old and now-old.checked_at < timedelta(seconds=90) else 0
                    state, failures = classify(code, previous)
                    secondary = os.getenv('EXECUTIVE_SECONDARY_PROXY')
                    if state == 'down' and secondary:
                        confirmed, _ = classify(check(domain, secondary), 1)
                        if confirmed != 'down':
                            state, failures = 'unknown', 0
                    stats = analytics(domain, now.date(), old.analytics if old else {})
                    ExecutiveSiteReading.objects.update_or_create(domain=domain, defaults=dict(
                        checked_at=now, state=state, failures=failures, status_code=code, analytics=stats))
            if not options['loop']:
                return
            time.sleep(max(1, 30 - (time.monotonic()-started)))
