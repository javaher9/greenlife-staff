from datetime import timedelta
from django.contrib.auth.models import User
from django.db.models import Sum
from django.utils import timezone
from .models import Attendance, DailyReport, ScoreEvent, KPIRecord, LeaveRequest
from .jalali import format_jalali, to_persian_digits
from .operations import missing_report_days, shift_rule

def full_name(u): return u.get_full_name() or u.username

def _clean_report_text(value):
    if not isinstance(value,str): return ''
    return value.replace(r'\u200c','‌').replace(r'\u200f','‏').replace(r'\u200e','‎').replace(r'\n','\n').replace(r'\t','\t').strip()

def scope_users(user):
    qs=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    role=getattr(getattr(user,'profile',None),'role','employee')
    if role=='manager': qs=qs.filter(profile__branch=user.profile.branch)
    elif role=='employee': qs=qs.filter(pk=user.pk)
    return qs

def day_summary(user, day=None):
    day=day or timezone.localdate(); users=scope_users(user)
    records=Attendance.objects.filter(user__in=users,date=day).select_related('user','branch')
    leaves=LeaveRequest.objects.filter(user__in=users,status='approved',start_date__lte=day,end_date__gte=day).select_related('user')
    by={r.user_id:r for r in records}; lmap={x.user_id:x for x in leaves}; rows=[]
    for u in users.order_by('last_name','first_name'):
        r=by.get(u.id); leave=lmap.get(u.id); rule=shift_rule(u,day)
        if leave and not (r and r.check_in): status='leave'; status_fa=leave.get_request_type_display()
        elif r: status=r.status; status_fa=r.get_status_display()
        else: status='missing'; status_fa='ثبت نشده'
        rows.append({'id':u.id,'name':full_name(u),'branch':getattr(getattr(u,'profile',None),'branch',None).name if getattr(getattr(u,'profile',None),'branch',None) else None,
                     'check_in':timezone.localtime(r.check_in).strftime('%H:%M') if r and r.check_in else None,
                     'check_out':timezone.localtime(r.check_out).strftime('%H:%M') if r and r.check_out else None,
                     'status':status,'status_fa':status_fa,'shift':rule['name']})
    late=[x for x in rows if x['status']=='late']; missing=[x for x in rows if x['status']=='missing']; leave_rows=[x for x in rows if x['status']=='leave']
    return {'date':format_jalali(day),'gregorian_date':str(day),'employees':len(rows),'present':sum(1 for x in rows if x['check_in']),'late':len(late),'missing':len(missing),'leave':len(leave_rows),'late_people':late,'missing_people':missing,'leave_people':leave_rows,'rows':rows}

def leaderboard(user, days=30):
    start=timezone.localdate()-timedelta(days=days-1); users=scope_users(user)
    scores=ScoreEvent.objects.filter(user__in=users,event_date__gte=start).values('user').annotate(total=Sum('points')).order_by('-total')
    umap={u.id:u for u in users}; return [{'name':full_name(umap[x['user']]),'points':x['total'] or 0} for x in scores if x['user'] in umap]

def daily_reports_summary(user, day=None, branch=None, employee=None, include_raw=False):
    """Return report content for one local day without exposing media URLs.

    The MCP caller is authenticated as an active administrator, but this helper
    still applies the normal Staff role/branch scope.  AI summaries are preferred
    for the compact ``content`` field; unprocessed reports safely fall back to
    their typed text or transcript so management can still review them.
    """
    day=day or timezone.localdate(); users=scope_users(user)
    qs=DailyReport.objects.filter(user__in=users,created_at__date=day).select_related(
        'user','branch','manager_comment_by'
    ).order_by('created_at','id')
    if branch: qs=qs.filter(branch__name=branch)
    if employee is not None: qs=qs.filter(user=employee)

    rows=[]
    for report in qs:
        typed_text=_clean_report_text(report.text)
        transcript=_clean_report_text(report.transcript)
        ai_summary=_clean_report_text(report.ai_summary)
        if ai_summary:
            content=ai_summary; content_source='ai_summary'
        elif typed_text and transcript:
            content=f'{typed_text}\n{transcript}'; content_source='text_and_transcript'
        elif typed_text:
            content=typed_text; content_source='text'
        elif transcript:
            content=transcript; content_source='transcript'
        elif report.audio:
            content='گزارش صوتی ثبت شده ولی متن آن هنوز آماده نیست.'; content_source='audio_pending'
        else:
            content='گزارش بدون متن ثبت شده است.'; content_source='empty'

        item={
            'id':report.id,
            'name':full_name(report.user),
            'branch':report.branch.name if report.branch else None,
            'submitted_at':timezone.localtime(report.created_at).strftime('%H:%M'),
            'content':content[:12000],
            'content_source':content_source,
            'tags':report.ai_tags if isinstance(report.ai_tags,list) else [],
            'follow_up':_clean_report_text(report.follow_up)[:4000],
            'manager_comment':_clean_report_text(report.manager_comment)[:1000],
            'process_status':report.process_status,
            'process_status_fa':report.get_process_status_display(),
            'has_audio':bool(report.audio),
        }
        if include_raw:
            item['text']=typed_text[:12000]
            item['transcript']=transcript[:12000]
            item['ai_summary']=ai_summary[:12000]
        rows.append(item)

    reporters=[]
    for row in rows:
        if row['name'] not in reporters: reporters.append(row['name'])
    return {
        'date':format_jalali(day),
        'gregorian_date':str(day),
        'report_count':len(rows),
        'reporter_count':len(reporters),
        'reporters':reporters,
        'needs_processing':sum(1 for row in rows if row['content_source']=='audio_pending'),
        'reports':rows,
    }

def answer_query(user, query):
    q=(query or '').strip(); today=timezone.localdate(); day=today
    if 'دیروز' in q: day=today-timedelta(days=1)
    summary=day_summary(user,day)
    if 'درآمد' in q or 'فروش' in q or 'مالی' in q:
        from .finance import finance_summary
        from .models import Branch
        branch=None
        for b in Branch.objects.filter(is_active=True):
            if b.name and b.name in q: branch=b; break
        if getattr(getattr(user,'profile',None),'role','employee')=='manager': branch=user.profile.branch
        fs=finance_summary(day,branch)
        label=branch.name if branch else 'کل شعب'
        amount=to_persian_digits(f"{fs['total']:,.0f}")
        return {'answer':f"درآمد {label} در {fs['date']} برابر {amount} است و {to_persian_digits(fs['count'])} تراکنش ثبت شده است.",'data':{'total':str(fs['total']),'count':fs['count'],'by_branch':fs['by_branch']},'date':fs['date']}
    missing_report_query=('گزارش نداد' in q or 'گزارش نداده' in q or 'گزارش ارسال نکرد' in q or 'چند شب گزارش' in q)
    report_content_query=(
        ('گزارش' in q and any(x in q for x in ('امروز','دیروز','روزانه','شبانه','ثبت شده','ثبت‌شده','خلاصه','متن','محتوا')))
        and not missing_report_query
    )
    if report_content_query:
        target=None
        for u in scope_users(user):
            parts=[p for p in full_name(u).split() if len(p)>1]
            if any(p in q for p in parts): target=u; break
        branch=None
        for b in set(x for x in scope_users(user).values_list('profile__branch__name',flat=True) if x):
            if b in q: branch=b; break
        result=daily_reports_summary(user,day,branch=branch,employee=target)
        names='، '.join(result['reporters']) or 'هیچ‌کس'
        if result['report_count']:
            answer=f"در {result['date']}، {to_persian_digits(result['report_count'])} گزارش توسط {to_persian_digits(result['reporter_count'])} نفر ثبت شده است: {names}."
        else:
            answer=f"در {result['date']} گزارشی ثبت نشده است."
        return {'answer':answer,'data':result,'date':result['date']}
    # Employee-name specific query
    matches=[]
    for row in summary['rows']:
        parts=[p for p in row['name'].split() if len(p)>1]
        if any(p in q for p in parts): matches.append(row)
    if matches:
        r=matches[0]
        if r['check_in']:
            text=f"{r['name']} در {summary['date']} ساعت {to_persian_digits(r['check_in'])} وارد شده و وضعیت او «{r['status_fa']}» است."
        else: text=f"برای {r['name']} در {summary['date']} ورود ثبت نشده است."
        return {'answer':text,'data':r,'date':summary['date']}
    if 'دیر' in q or 'تاخیر' in q or 'تأخیر' in q:
        if not summary['late_people']: text=f"در {summary['date']} تأخیری ثبت نشده است."
        else: text='؛ '.join(f"{x['name']} ساعت {to_persian_digits(x['check_in'])}" for x in summary['late_people'])
        return {'answer':text,'data':summary['late_people'],'date':summary['date']}
    if 'غایب' in q or 'نیامد' in q or 'نیومد' in q or 'بدون ورود' in q:
        names='، '.join(x['name'] for x in summary['missing_people']) or 'هیچ‌کس'
        return {'answer':f"افراد بدون ورود در {summary['date']}: {names}",'data':summary['missing_people'],'date':summary['date']}
    if missing_report_query:
        target=None
        for u in scope_users(user):
            parts=[p for p in full_name(u).split() if len(p)>1]
            if any(p in q for p in parts): target=u; break
        if target:
            days=missing_report_days(target,days=31,end=today-timedelta(days=1))
            text=f"{full_name(target)} در ۳۱ روز اخیر {to_persian_digits(len(days))} شب گزارش ارسال نکرده است."
            return {'answer':text,'data':[format_jalali(x) for x in days],'date':format_jalali(today)}
        rows=[]
        for u in scope_users(user):
            days=missing_report_days(u,days=31,end=today-timedelta(days=1))
            if days: rows.append({'name':full_name(u),'count':len(days)})
        rows.sort(key=lambda x:x['count'],reverse=True)
        text='، '.join(f"{x['name']} ({to_persian_digits(x['count'])} شب)" for x in rows[:10]) or 'در ۳۱ روز اخیر گزارش جاافتاده‌ای ثبت نشده است.'
        return {'answer':text,'data':rows,'date':format_jalali(today)}
    if 'امتیاز' in q or 'رتبه' in q or 'برتر' in q:
        board=leaderboard(user); top=board[:5]
        text='، '.join(f"{x['name']} ({to_persian_digits(x['points'])} امتیاز)" for x in top) or 'هنوز امتیازی ثبت نشده است.'
        return {'answer':text,'data':top,'date':format_jalali(today)}
    return {'answer':f"در {summary['date']} از {to_persian_digits(summary['employees'])} نفر، {to_persian_digits(summary['present'])} نفر ورود ثبت کرده‌اند، {to_persian_digits(summary['late'])} نفر تأخیر داشته‌اند و {to_persian_digits(summary['missing'])} نفر بدون ورود هستند.",'data':summary,'date':summary['date']}
