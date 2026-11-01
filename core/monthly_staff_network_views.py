"""Read-only monthly sales-network totals for the internal manager."""
from collections import Counter
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.shortcuts import render
from django.utils import timezone

from .jalali import gregorian_to_jalali, jalali_to_gregorian
from .models import EmployeeProfile, ReferralLead, ReferralProfile


@login_required
def monthly_staff_network_report(request):
    role=getattr(getattr(request.user,'profile',None),'role',None)
    if not (request.user.is_superuser or role in ('admin','internal_manager')):
        raise PermissionDenied('این گزارش ویژه مدیریت داخلی است.')

    today=timezone.localdate()
    this_year,this_month,_=gregorian_to_jalali(today.year,today.month,today.day)
    try:
        year=int(str(request.GET.get('year',this_year)).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹','0123456789')))
        month=int(str(request.GET.get('month',this_month)).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹','0123456789')))
        if not (1400<=year<=1500 and 1<=month<=12):
            raise ValueError()
    except (ValueError,TypeError):
        year,month=this_year,this_month
    start=date(*jalali_to_gregorian(year,month,1))
    ny,nm=(year+1,1) if month==12 else (year,month+1)
    end=date(*jalali_to_gregorian(ny,nm,1))

    # Network ownership belongs to the highest staff root. This counts levels
    # 1 and 2 as one staff member's network; no referral is double-counted.
    profiles=list(ReferralProfile.objects.values('id','user_id','sponsor_id','created_at'))
    by_id={p['id']:p for p in profiles}
    staff=list(EmployeeProfile.objects.filter(is_active=True,user__is_active=True)
               .exclude(role='referrer').select_related('user','branch').order_by('user__last_name','user__first_name','id'))
    owner_by_user={p.user_id:p.user_id for p in staff}
    owner_for_profile={}
    def root_owner(pid):
        if pid in owner_for_profile:
            return owner_for_profile[pid]
        visited=set()
        cur=by_id.get(pid)
        while cur and cur['id'] not in visited:
            visited.add(cur['id'])
            if not cur['sponsor_id']:
                owner=owner_by_user.get(cur['user_id'])
                break
            cur=by_id.get(cur['sponsor_id'])
        else:
            owner=None
        owner_for_profile[pid]=owner
        return owner

    member_counts=Counter()
    for profile in profiles:
        if profile['sponsor_id'] and start<=timezone.localtime(profile['created_at']).date()<end:
            owner=root_owner(profile['id'])
            if owner:
                member_counts[owner]+=1

    lead_counts=Counter()
    leads=ReferralLead.objects.filter(
        created_at__date__gte=start,created_at__date__lt=end
    ).values('referrer_id').annotate(total=Count('id'))
    for lead in leads:
        owner=root_owner(lead['referrer_id'])
        if owner:
            lead_counts[owner]+=lead['total']

    rows=[{'person':p,'leads':lead_counts[p.user_id],
           'members':member_counts[p.user_id],
           'total':lead_counts[p.user_id]+member_counts[p.user_id]} for p in staff]
    rows.sort(key=lambda row:(-row['total'],-row['leads'],row['person'].user.get_full_name()))
    return render(request,'core/monthly_staff_network_report.html',{
        'rows':rows,'year':year,'month':month,
        'years':range(this_year,max(1399,this_year-5),-1),
        'months':[(i,n) for i,n in enumerate(('فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند'),1)],
        'total_leads':sum(x['leads'] for x in rows),
        'total_members':sum(x['members'] for x in rows),
        'total_all':sum(x['total'] for x in rows),
    })
