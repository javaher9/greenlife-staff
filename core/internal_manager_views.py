"""Small operational dashboard, built from existing records and safe projections."""
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q, Count
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET
from .internal_manager_scope import supervised_users
from .internal_manager_targets import target_statuses
from .country_workspace import scoped_queryset
from .supervision_text import safe_label
from .models import (LeaveRequest, Task, Attendance, Branch, DeviceIssue,
    InternalRequest, VisitAppointment, AttendanceCorrectionRequest, ReferralLead)


def internal_gate(request):
    p=getattr(request.user,'profile',None)
    if not request.user.is_active or not p or not p.is_active or p.role != 'internal_manager':
        raise PermissionDenied


@login_required
@require_GET
def qualitative_targets(request):
    internal_gate(request)
    try:
        context=target_statuses(request)
    except ValidationError:
        return HttpResponseBadRequest('دوره شمسی نامعتبر است.')
    return render(request,'core/internal_manager_targets.html',context)


def lead_projection(lead):
    from .all_leads_views import STATES
    from .call_center_identity import call_center_display_name
    return {'name':safe_label(lead.full_name),'flower':safe_label(call_center_display_name(lead.assigned_to)) if lead.assigned_to_id else 'بدون مسئول',
        'source':lead.get_source_display(),'group':safe_label(lead.group.name) if lead.group_id else 'مشخص نشده',
        'created_at':lead.created_at,'last_action':lead.last_action,'next_follow_up':lead.next_follow_up,
        'state':STATES[lead.archive_state],
        'attention':not lead.assigned_to_id or bool(lead.next_follow_up and lead.next_follow_up < timezone.localdate() and lead.status in ('new','contacted','appointment'))}


@login_required
@require_GET
def supervisory_lead(request,pk):
    internal_gate(request)
    from .all_leads_views import archive_queryset
    lead=get_object_or_404(archive_queryset(request).select_related('assigned_to__user','group'),pk=pk)
    row=lead_projection(lead)
    row['branch']=safe_label(Branch.objects.filter(pk=lead.last_branch).values_list('name',flat=True).first()) or 'ارتباط شعبه ثبت نشده'
    return render(request,'core/supervisory_lead.html',{'lead':row})


def dashboard_context(request):
    from .management_alert_views import collect_alerts
    today=timezone.localdate()
    users=supervised_users(request)
    branches=scoped_queryset(request,Branch.objects.filter(is_active=True))
    leaves=LeaveRequest.objects.filter(user__in=users)
    pending=leaves.filter(status='pending').select_related('user__profile__branch').order_by('created_at')
    targets=target_statuses(request)
    appointments=VisitAppointment.objects.filter(branch__in=branches,status='arrived').exclude(care_stage='closed').select_related('branch').order_by('appointment_date','appointment_time')[:30]
    appointments=list(appointments)
    visible_lead_ids=set(scoped_queryset(request,ReferralLead.objects.filter(pk__in=[x.lead_id for x in appointments])).values_list('pk',flat=True))
    journeys=[{'name':safe_label(x.full_name),'branch':safe_label(x.branch.name),'stage':x.get_care_stage_display(),
        'url':reverse('supervisory_lead',args=[x.lead_id]) if x.lead_id in visible_lead_ids else ''} for x in appointments]
    return {**targets,'alerts':collect_alerts(request.user,request=request),'pending_leaves':pending[:6],
        'pending_leave_count':pending.count(),
        'correction_count':AttendanceCorrectionRequest.objects.filter(user__in=users,status='pending').count(),
        'attendance_rows':list(Attendance.objects.filter(user__in=users,date=today).select_related('user__profile__branch')[:80]),
        'today_leaves':leaves.filter(status='approved',start_date__lte=today+timezone.timedelta(days=1),end_date__gte=today).select_related('user')[:40],
        'devices':DeviceIssue.objects.filter(branch__in=branches).exclude(status='resolved').select_related('reporter','branch')[:20],
        'internal_requests':InternalRequest.objects.filter(requester__in=users,category__in=('repair','it','hr','other'),status__in=('open','doing')).select_related('assigned_to')[:20],
        'journeys':journeys,
        'overdue_tasks':Task.objects.filter(assigned_to__in=users,status__in=('todo','doing'),due_date__lt=today).select_related('assigned_to').order_by('due_date')[:30],
    }


@login_required
@require_GET
def internal_dashboard(request):
    internal_gate(request)
    try:
        context=dashboard_context(request)
    except ValidationError:
        return HttpResponseBadRequest('دوره شمسی نامعتبر است.')
    return render(request,'core/internal_manager_dashboard.html',context)


@login_required
@require_GET
def monitoring_history(request):
    internal_gate(request)
    from django.core.paginator import Paginator
    from .models import OperationsIncident
    rows=scoped_queryset(request,OperationsIncident.objects.all()).order_by('-day','-deadline')
    return render(request,'core/monitoring_history.html',{'incidents':Paginator(rows,40).get_page(request.GET.get('page'))})
