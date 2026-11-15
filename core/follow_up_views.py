"""Full, paginated callback agenda for call center and internal management.

The existing ReferralLead.next_follow_up date remains authoritative, including
promises made six months ago. Lists are recomputed from the database each
request; nothing can disappear due to the dashboard's 50-row work queue limit.
"""
from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseForbidden
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from .call_center_identity import call_center_display_name
from .follow_up_agenda import due_follow_up_scope
from .models import EmployeeProfile, LeadFollowUpLog, ReferralLead


def _active_due_leads():
    return due_follow_up_scope(ReferralLead.objects.all())


def _completed_ids(today, *, actor_id=None):
    # Only callbacks whose prior promise was due today count as completed.
    # Scheduling a brand-new lead for the future is not today's completed call.
    logs=LeadFollowUpLog.objects.filter(
        created_at__date=today,previous_date=today,
        action__in=('attempt','scheduled','closed'),
    )
    if actor_id is not None:
        logs=logs.filter(actor_id=actor_id)
    return logs.values_list('lead_id',flat=True).distinct()


def _scope(request, role):
    if role=='call_center':
        return _active_due_leads().filter(assigned_to=request.user.profile)
    return _active_due_leads().select_related('assigned_to__user')


def _category_counts(scope, today, user_id=None):
    complete=LeadFollowUpLog.objects.filter(
        created_at__date=today,previous_date=today,
        action__in=('attempt','scheduled','closed'),
    )
    if user_id:
        complete=complete.filter(actor_id=user_id)
    return {
        'today':scope.filter(next_follow_up=today).count(),
        'overdue':scope.filter(next_follow_up__lt=today).count(),
        'future':scope.filter(next_follow_up__gt=today).count(),
        'done':complete.values('lead_id').distinct().count(),
        'unscheduled':scope.filter(contact_result='follow_up',next_follow_up__isnull=True).count(),
    }


@login_required
@require_GET
def call_center_follow_up_agenda(request):
    profile=getattr(request.user,'profile',None)
    if not profile or not profile.is_active or not request.user.is_active or profile.role!='call_center':
        return HttpResponseForbidden('دسترسی مجاز نیست.')
    today=timezone.localdate()
    scope=_scope(request,'call_center')
    counts=_category_counts(scope,today,request.user.id)
    tab=(request.GET.get('tab') or 'today').strip()
    if tab not in ('today','overdue','future','done','unscheduled'):
        tab='today'
    if tab=='today':
        rows=scope.filter(next_follow_up=today)
    elif tab=='overdue':
        rows=scope.filter(next_follow_up__lt=today)
    elif tab=='future':
        rows=scope.filter(next_follow_up__gt=today)
    elif tab=='unscheduled':
        rows=scope.filter(contact_result='follow_up',next_follow_up__isnull=True)
    else:
        ids=_completed_ids(today,actor_id=request.user.pk)
        # Show even a now-closed lead in today's completed history.
        rows=ReferralLead.objects.filter(pk__in=ids,assigned_to=profile)

    query=(request.GET.get('q') or '').strip()[:100]
    if query:
        rows=rows.filter(
            Q(full_name__icontains=query)|Q(phone__icontains=query)|
            Q(alternate_phone__icontains=query)
        )
    exact=(request.GET.get('date') or '').strip()
    try:
        exact_date=date.fromisoformat(exact) if exact else None
    except ValueError:
        exact_date=None
    if exact_date and tab=='future':
        rows=rows.filter(next_follow_up=exact_date)

    rows=rows.select_related('group','assigned_to__user').order_by(
        'next_follow_up','next_follow_up_time','pk',
    )
    page=Paginator(rows,40).get_page(request.GET.get('page'))
    # Prefetch limited history for currently visible leads only.
    history={
        lead.pk:list(LeadFollowUpLog.objects.filter(lead_id=lead.pk)
                     .select_related('actor').order_by('-created_at','-pk')[:3])
        for lead in page.object_list
    }
    cards=[{'lead':lead,'history':history[lead.pk]} for lead in page.object_list]
    params=request.GET.copy()
    params.pop('page',None)
    return render(request,'core/call_center/follow_up_agenda.html',{
        'tab':tab,'counts':counts,'today':today,'cards':cards,'page':page,
        'query':query,'exact_date':exact,'page_query':params.urlencode(),
    })


@login_required
@require_GET
def management_follow_up_agenda(request):
    profile=getattr(request.user,'profile',None)
    if not profile or not profile.is_active or not request.user.is_active or profile.role not in ('admin','manager','internal_manager'):
        return HttpResponseForbidden('دسترسی مجاز نیست.')
    today=timezone.localdate()
    leads=_active_due_leads()
    users=EmployeeProfile.objects.filter(
        role='call_center',is_active=True,user__is_active=True,
    ).select_related('user').order_by('pk')
    completed=LeadFollowUpLog.objects.filter(
        created_at__date=today,previous_date=today,
        action__in=('attempt','scheduled','closed'),
        actor__profile__role='call_center',
    )
    counts=_category_counts(leads,today)
    totals=[]
    for operator in users:
        own=leads.filter(assigned_to=operator)
        handled=completed.filter(actor=operator.user).values('lead_id').distinct().count()
        totals.append({
            'name':call_center_display_name(operator),
            'today':own.filter(next_follow_up=today).count(),
            'overdue':own.filter(next_follow_up__lt=today).count(),
            'future':own.filter(next_follow_up__gt=today).count(),
            'done':handled,
        })
    # All callbacks still requiring a call across all operators, no 5-row limit.
    filter_name=(request.GET.get('tab') or 'today').strip()
    if filter_name=='overdue':
        view=leads.filter(next_follow_up__lt=today)
    elif filter_name=='future':
        view=leads.filter(next_follow_up__gt=today)
    elif filter_name=='unscheduled':
        view=leads.filter(contact_result='follow_up',next_follow_up__isnull=True)
    else:
        filter_name='today'
        view=leads.filter(next_follow_up=today)
    page=Paginator(view.select_related('assigned_to__user').order_by(
        'next_follow_up','next_follow_up_time','pk'
    ),50).get_page(request.GET.get('page'))
    return render(request,'core/call_center/follow_up_management.html',{
        'today':today,'tab':filter_name,'counts':counts,'totals':totals,'page':page,
    })
