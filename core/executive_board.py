"""Read-only, non-identifying operational views for the owner command room."""
from collections import Counter, defaultdict
import os
from datetime import timedelta
from urllib.parse import urlsplit

from django.db.models import Count, Exists, OuterRef, Q
from django.utils.crypto import salted_hmac

from .call_center_identity import call_center_display_name
from .instagram_views import INSTAGRAM_PAGE_SOURCES
from .jalali import gregorian_to_jalali
from .sales_target_metrics import jalali_month_dates
from .models import (Attendance, BodyAnalysisRecord, EmployeeProfile, ExecutiveSiteReading, LeaveRequest,
                     ReferralLead, ReferralProfile, ShiftAssignment, VisitAppointment)

DOMAINS = ('greenlifeclinics.com', 'drjavaherian.com', 'greenlife-international.com',
           'rejim.ir', 'greenliferealstates.com')
STATES = {'up':'در دسترس', 'warning':'در انتظار بررسی دوم', 'down':'اختلال از محل پایش',
          'unknown':'وضعیت نامشخص', 'stale':'پایش به‌روز نیست'}
STAGES = [('booked','نوبت امروز'), ('reception','پذیرش'), ('form','فرم تکمیل‌شده'), ('scan','اسکن و انتظار پزشک'),
          ('consultant','مشاور'), ('payment','پرداخت'), ('closed','تکمیل')]
BRANCHES = ('نیاوران','پونک','اصفهان')


def month_start(day):
    year, month, _ = gregorian_to_jalali(day.year, day.month, day.day)
    return jalali_month_dates(year, month)[0]


def presence_by_user(now):
    day = now.date()
    records = {r.user_id:r for r in Attendance.objects.filter(date=day).only(
        'user_id','check_in','check_out','status','break_started_at')}
    leaves = set(LeaveRequest.objects.filter(status='approved',start_date__lte=day,end_date__gte=day)
                 .exclude(request_type__in=['hourly','mission']).values_list('user_id',flat=True))
    result = {uid:('leave','مرخصی') for uid in leaves}
    for uid,start,end in ShiftAssignment.objects.filter(date=day).values_list('user_id','shift__start_time','shift__end_time'):
        clock = now.time()
        if not (start <= clock < end if start < end else clock >= start or clock < end):
            result.setdefault(uid,('off','خارج از شیفت'))
    for uid, r in records.items():
        if r.status in ('present','late') and r.check_in and not r.check_out:
            result[uid] = ('break','در استراحت') if r.break_started_at else ('present','حاضر')
        elif r.check_out:
            result[uid] = ('off','خروج ثبت شده')
        elif r.status in ('absent','leave'):
            result[uid] = (r.status, 'غیبت ثبت شده' if r.status=='absent' else 'مرخصی')
    return result


def board(now, instagram):
    start = now.replace(hour=0,minute=0,second=0,microsecond=0)
    leads = ReferralLead.objects.filter(created_at__range=(start,now))
    booking = VisitAppointment.objects.filter(lead_id=OuterRef('pk')).exclude(status='cancelled')
    forms = defaultdict(Counter)
    for url,created,booked in leads.filter(source='link',referrer__user__username='lead-source-website').annotate(
            booked=Exists(booking)).values_list('source_url','created_at','booked'):
        try:
            domain = (urlsplit(url).hostname or '').lower().removeprefix('www.')
        except ValueError:
            continue
        if domain in DOMAINS:
            forms[domain]['count'] += 1
            forms[domain]['bookings'] += int(booked)
            forms[domain][created.astimezone(now.tzinfo).hour] += 1
    readings = ExecutiveSiteReading.objects.in_bulk(DOMAINS)
    sites = []
    for domain in DOMAINS:
        reading = readings.get(domain)
        status = (reading.state if now-reading.checked_at < timedelta(seconds=95) else 'stale') if reading else 'unknown'
        stats = reading.analytics if reading and reading.analytics.get('day')==now.date().isoformat() else {}
        stats = stats if now.timestamp()-stats.get('attempt',0)<900 else {}
        f = forms[domain]
        hours = [f[h] for h in range(24)]
        sites.append(dict(domain=domain,status=status,label=STATES[status],visits=stats.get('today'),
                          month=stats.get('month'),forms=f['count'],bookings=f['bookings'],
                          checked=reading.checked_at.astimezone(now.tzinfo).strftime('%H:%M:%S') if reading else '—',
                          hours=[round(n*100/max(1,max(hours))) for n in hours]))
    marked = leads.filter(notes__icontains='[instagram_page:').annotate(booked=Exists(booking))
    pages = []
    for slug,label in INSTAGRAM_PAGE_SOURCES.items():
        data = marked.filter(notes__icontains=f'[instagram_page:{slug}]').aggregate(
            leads=Count('pk'), booked=Count('pk',filter=Q(booked=True)))
        connected = instagram.get('tone')=='connected' and (instagram.get('account') or '').strip('@').lower()==label.lower()
        avatar = os.getenv('EXECUTIVE_IG_AVATAR_' + slug.upper(), '')
        pages.append(dict(handle=label,avatar=avatar if avatar.startswith('https://') else '',
                          mark=label.split('.')[-1][:2].upper(), dm=instagram.get('count') if connected else None, **data))
    members = ReferralProfile.objects.filter(sponsor__isnull=False)
    network_leads = leads.filter(Q(referrer__sponsor__isnull=False)|Q(group__name='شبکه فروش پرسنل'))
    branches = list(network_leads.annotate(booked=Exists(booking)).values('referrer__user__username',
        'referrer__user__first_name','referrer__user__last_name').annotate(n=Count('pk'),bookings=Count('pk',filter=Q(booked=True)))
        .order_by('-n','referrer_id'))
    network = dict(members=members.filter(created_at__range=(start,now)).count(),leads=sum(b['n'] for b in branches),
                   rows=[dict(name=(' '.join((b['referrer__user__first_name'],b['referrer__user__last_name'])).strip()
                                    or 'عضو شبکه'),n=b['n'],bookings=b['bookings']) for b in branches])
    rooms = {b:defaultdict(list) for b in BRANCHES}
    scans = list(BodyAnalysisRecord.objects.filter(recorded_at__range=(start,now)).values_list('measurements__scan_appointment_id', flat=True))
    scanned = {pk for pk in scans if isinstance(pk,int)}
    visits = VisitAppointment.objects.filter(appointment_date=now.date(),status__in=['booked','arrived','completed']).order_by('pk')
    for pk,name,status,care,submitted in visits.values_list('pk','branch__name','status','care_stage','intake_invitation__completed_at'):
        branch = next((b for b in BRANCHES if b in name.replace('ي','ی')),None)
        if not branch:
            continue
        if status == 'booked':
            stage = 'form' if submitted else 'booked'
        elif status == 'completed':
            stage = 'closed'
        else:
            stage = care if care in ('consultant','payment','closed') else 'scan' if pk in scanned else 'form' if submitted else 'reception'
        token = salted_hmac('executive-visit',f'{now.date()}:{pk}').hexdigest()[:16]
        rooms[branch][stage].append(token)
    team = defaultdict(list)
    presence = presence_by_user(now)
    staff = EmployeeProfile.objects.filter(is_active=True,user__is_active=True,branch__isnull=False).exclude(
        role__in=('referrer','scan_station')).select_related('branch','user').order_by('branch__name','role','pk')
    for p in staff:
        state,label = presence.get(p.user_id, ('unknown','ورود ثبت نشده'))
        name = call_center_display_name(p.user) if p.role=='call_center' else p.user.get_full_name() or p.user.username
        team[p.branch.name].append(dict(name=name,pk=p.pk,state=state,label=label,role=p.get_role_display()))
    return dict(teams=[dict(name=name,people=people,present=sum(p['state']=='present' for p in people)) for name,people in team.items()],sites=sites,pages=pages,network=network,rooms=[
        dict(name=b,stages=[dict(key=k,name=label,count=len(data[k]),tokens=data[k][:10]) for k,label in STAGES])
        for b,data in rooms.items()], scans=len(scans))
