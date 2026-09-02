from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .meeting_forms import (
    MeetingActionFormSet, MeetingActionManageForm, MeetingActionProgressForm,
    MeetingMinuteForm, MeetingStepForm,
)
from .models import (
    AuditLog, MeetingActionItem, MeetingActionStep, MeetingActionUpdate,
    MeetingMinute, StaffNotification, Task,
)


MEETING_MANAGER_ROLES=('admin','internal_manager')


def role_of(user):
    return getattr(getattr(user,'profile',None),'role','employee')


def meeting_manager_required(view):
    @wraps(view)
    @login_required
    def wrapped(request,*args,**kwargs):
        if role_of(request.user) not in MEETING_MANAGER_ROLES:
            messages.error(request,'این بخش فقط برای مدیر سیستم و مدیر داخلی فعال است.')
            return redirect('dashboard')
        return view(request,*args,**kwargs)
    return wrapped


def _audit(request,action,obj,summary,metadata=None):
    forwarded=request.META.get('HTTP_X_FORWARDED_FOR','')
    ip=(forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None
    AuditLog.objects.create(
        actor=request.user,action=action,path=request.path,method=request.method,
        object_type=obj.__class__.__name__,object_id=str(obj.pk),summary=summary[:250],
        metadata=metadata or {},ip_address=ip,
    )


def _task_status(action_status):
    return {'todo':'todo','doing':'doing','blocked':'doing','awaiting_approval':'doing','done':'done'}[action_status]


def _sync_task(action,created_by=None):
    priority='high' if action.priority in ('high','urgent') else 'normal'
    description=f'مصوبه جلسه «{action.meeting.title}»'
    if action.description: description+=f'\n\n{action.description}'
    if action.task_id:
        task=action.task
        task.title=f'[مصوبه] {action.title}'
        task.description=description
        task.assigned_to=action.assigned_to
        task.due_date=action.due_date
        task.priority=priority
        task.status=_task_status(action.status)
        task.save()
    else:
        task=Task.objects.create(
            title=f'[مصوبه] {action.title}',description=description,assigned_to=action.assigned_to,
            created_by=created_by or action.meeting.created_by,due_date=action.due_date,
            priority=priority,status=_task_status(action.status),
        )
        action.task=task
        action.save(update_fields=['task'])
    return task


def _notify_assignee(action,kind='assigned'):
    title='مصوبه جدید به شما واگذار شد' if kind=='assigned' else 'مصوبه شما به‌روزرسانی شد'
    StaffNotification.objects.create(
        user=action.assigned_to,title=title,
        message=f'«{action.title}» از جلسه «{action.meeting.title}» — وضعیت: {action.get_status_display()}',
        notification_type='meeting_action',related_date=action.due_date or timezone.localdate(),
    )


@meeting_manager_required
def meeting_minute_create(request):
    form=MeetingMinuteForm(request.POST or None)
    action_forms=MeetingActionFormSet(
        request.POST or None,queryset=MeetingActionItem.objects.none(),prefix='actions',
    )
    if request.method=='POST' and form.is_valid() and action_forms.is_valid():
        with transaction.atomic():
            meeting=form.save(commit=False)
            meeting.created_by=request.user
            meeting.save()
            form.save_m2m()
            created=[]
            for action_form in action_forms:
                if not action_form.cleaned_data or not action_form.cleaned_data.get('title'): continue
                action=action_form.save(commit=False)
                action.meeting=meeting
                action.save()
                _sync_task(action,request.user)
                _notify_assignee(action)
                created.append(action)
            _audit(request,'meeting_minute_create',meeting,f'ثبت صورت‌جلسه با {len(created)} مصوبه',{
                'action_count':len(created),'attendee_ids':list(meeting.attendees.values_list('id',flat=True)),
            })
        messages.success(request,'صورت‌جلسه ثبت شد و مصوبات در «کارهای من» مسئولان قرار گرفت.')
        return redirect('meeting_minute_detail',pk=meeting.pk)
    return render(request,'core/meetings/form.html',{'form':form,'action_forms':action_forms})


@meeting_manager_required
def meeting_minute_list(request):
    qs=MeetingMinute.objects.select_related('created_by').prefetch_related(
        'attendees','action_items__steps','action_items__assigned_to',
    ).annotate(
        action_count=Count('action_items',distinct=True),
        done_count=Count('action_items',filter=Q(action_items__status='done'),distinct=True),
    )
    status=request.GET.get('status','')
    if status in ('open','closed'): qs=qs.filter(status=status)
    return render(request,'core/meetings/list.html',{'meetings':qs,'selected_status':status})


@meeting_manager_required
def meeting_minute_detail(request,pk):
    meeting=get_object_or_404(
        MeetingMinute.objects.select_related('created_by').prefetch_related(
            'attendees','action_items__assigned_to__profile','action_items__steps',
            'action_items__updates__user',
        ),pk=pk,
    )
    if request.method=='POST' and request.POST.get('action')=='toggle_close':
        meeting.status='closed' if meeting.status=='open' else 'open'
        meeting.closed_at=timezone.now() if meeting.status=='closed' else None
        meeting.save(update_fields=['status','closed_at','updated_at'])
        _audit(request,'meeting_minute_status',meeting,f'وضعیت جلسه به {meeting.get_status_display()} تغییر کرد')
        messages.success(request,'وضعیت صورت‌جلسه به‌روزرسانی شد.')
        return redirect('meeting_minute_detail',pk=meeting.pk)
    return render(request,'core/meetings/detail.html',{'meeting':meeting})


@meeting_manager_required
def meeting_dashboard(request):
    actions=list(MeetingActionItem.objects.select_related(
        'meeting','assigned_to','assigned_to__profile',
    ).prefetch_related('steps'))
    selected=request.GET.get('status','all')
    today=timezone.localdate()
    counts={
        'open':sum(a.status!='done' for a in actions),
        'doing':sum(a.status=='doing' for a in actions),
        'awaiting':sum(a.status=='awaiting_approval' for a in actions),
        'overdue':sum(a.is_overdue for a in actions),
        'done':sum(a.status=='done' for a in actions),
    }
    total=len(actions)
    overall=round(sum(a.progress_percent for a in actions)/total) if total else 0
    owner_map={}
    for action in actions:
        row=owner_map.setdefault(action.assigned_to_id,{
            'user':action.assigned_to,'actions':[],'count':0,'progress':0,
        })
        row['actions'].append(action); row['count']+=1
    owners=[]
    for row in owner_map.values():
        row['progress']=round(sum(a.progress_percent for a in row['actions'])/row['count'])
        owners.append(row)
    owners.sort(key=lambda x:(x['progress'],-x['count']))
    visible=actions
    if selected=='overdue': visible=[a for a in actions if a.is_overdue]
    elif selected in dict(MeetingActionItem.STATUS): visible=[a for a in actions if a.status==selected]
    visible.sort(key=lambda a:(not a.is_overdue,a.status,a.due_date or today,a.id))
    return render(request,'core/meetings/dashboard.html',{
        'actions':visible[:100],'counts':counts,'owners':owners[:8],
        'overall_progress':overall,'selected_status':selected,'today':today,
    })


@login_required
def meeting_action_update(request,pk):
    action=get_object_or_404(
        MeetingActionItem.objects.select_related('meeting','assigned_to','task').prefetch_related('steps','updates__user'),pk=pk,
    )
    manager=role_of(request.user) in MEETING_MANAGER_ROLES
    if not manager and action.assigned_to_id!=request.user.id:
        messages.error(request,'این مصوبه به شما واگذار نشده است.')
        return redirect('task_list')
    progress_form=MeetingActionProgressForm(
        request.POST or None,manager=manager,initial={'status':action.status},prefix='progress',
    )
    manage_form=MeetingActionManageForm(request.POST or None,instance=action,prefix='manage') if manager else None
    if request.method=='POST' and request.POST.get('action')=='progress' and progress_form.is_valid():
        before=action.status
        action.status=progress_form.cleaned_data['status']
        note=progress_form.cleaned_data['note'].strip()
        if action.status=='done':
            action.approved_by=request.user; action.approved_at=timezone.now()
        elif before=='done':
            action.approved_by=None; action.approved_at=None
        if note: action.completion_note=note
        action.save()
        MeetingActionUpdate.objects.create(
            action=action,user=request.user,previous_status=before,new_status=action.status,note=note,
        )
        _sync_task(action,request.user)
        if manager and request.user.id!=action.assigned_to_id: _notify_assignee(action,'updated')
        _audit(request,'meeting_action_status',action,f'وضعیت مصوبه از {before} به {action.status}',{'note':note[:300]})
        messages.success(request,'پیشرفت مصوبه ثبت شد.')
        return redirect('meeting_action_update',pk=action.pk)
    if request.method=='POST' and request.POST.get('action')=='manage' and manager and manage_form.is_valid():
        old_assignee=action.assigned_to_id
        action=manage_form.save()
        _sync_task(action,request.user)
        if old_assignee!=action.assigned_to_id: _notify_assignee(action)
        _audit(request,'meeting_action_manage',action,'مسئول، مهلت یا اولویت مصوبه ویرایش شد')
        messages.success(request,'اطلاعات اجرایی مصوبه به‌روزرسانی شد.')
        return redirect('meeting_action_update',pk=action.pk)
    return render(request,'core/meetings/action_update.html',{
        'action_item':action,'progress_form':progress_form,'manage_form':manage_form,
        'step_form':MeetingStepForm(),'is_meeting_manager':manager,
    })


@login_required
def meeting_step_add(request,pk):
    action=get_object_or_404(MeetingActionItem,pk=pk)
    manager=role_of(request.user) in MEETING_MANAGER_ROLES
    if request.method!='POST' or (not manager and action.assigned_to_id!=request.user.id):
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('task_list')
    form=MeetingStepForm(request.POST)
    if form.is_valid():
        MeetingActionStep.objects.create(
            action=action,title=form.cleaned_data['title'],sort_order=action.steps.count(),
        )
        messages.success(request,'مرحله جدید اضافه شد.')
    return redirect('meeting_action_update',pk=action.pk)


@login_required
def meeting_step_toggle(request,pk):
    step=get_object_or_404(MeetingActionStep.objects.select_related('action'),pk=pk)
    manager=role_of(request.user) in MEETING_MANAGER_ROLES
    if request.method!='POST' or (not manager and step.action.assigned_to_id!=request.user.id):
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('task_list')
    step.is_done=not step.is_done
    step.completed_by=request.user if step.is_done else None
    step.completed_at=timezone.now() if step.is_done else None
    step.save(update_fields=['is_done','completed_by','completed_at'])
    _audit(request,'meeting_step_toggle',step,f'مرحله {"انجام شد" if step.is_done else "باز شد"}')
    return redirect('meeting_action_update',pk=step.action_id)
