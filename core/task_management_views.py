from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .forms import TaskForm
from .models import EmployeeProfile, Task


MANAGEMENT_ROLES = ('admin', 'internal_manager', 'manager')
PERSONNEL_ROLES = ('employee', 'call_center', 'consultant', 'receptionist')


def _role_of(user):
    return getattr(getattr(user, 'profile', None), 'role', 'employee')


def _employee_for_task(request, task):
    role = _role_of(request.user)
    if role not in MANAGEMENT_ROLES:
        raise PermissionDenied('Task management access denied.')

    employee = get_object_or_404(
        EmployeeProfile.objects.select_related('user', 'branch'),
        user=task.assigned_to,
    )

    if role == 'admin':
        return employee
    if role == 'internal_manager':
        if employee.role in PERSONNEL_ROLES:
            return employee
        raise PermissionDenied('Employee access denied.')
    if employee.branch_id == getattr(request.user.profile, 'branch_id', None):
        return employee
    raise PermissionDenied('Employee access denied.')


@login_required
def manager_task_edit(request, pk):
    task = get_object_or_404(Task.objects.select_related('assigned_to'), pk=pk)
    employee = _employee_for_task(request, task)

    meeting_action = getattr(task, 'meeting_action', None)
    if meeting_action is not None:
        messages.info(request, 'این وظیفه از صورتجلسه ایجاد شده است؛ ویرایش آن از خود صورتجلسه انجام می‌شود.')
        return redirect('meeting_action_update', pk=meeting_action.pk)

    form = TaskForm(request.POST or None, instance=task)
    form.fields.pop('assigned_to', None)
    if request.method == 'POST' and form.is_valid():
        obj = form.save(commit=False)
        obj.assigned_to = employee.user
        obj.save()
        messages.success(request, 'وظیفه ویرایش شد.')
        return redirect('employee_task_create', pk=employee.pk)

    return render(request, 'core/employee_management_form.html', {
        'form': form,
        'employee': employee,
        'title': 'ویرایش وظیفه',
        'subtitle': 'عنوان، شرح، مهلت یا اولویت این وظیفه را اصلاح کنید.',
        'button': 'ذخیره تغییرات',
        'form_kind': 'task_edit',
        'editing_task': task,
    })


@require_POST
@login_required
def manager_task_delete(request, pk):
    task = get_object_or_404(Task.objects.select_related('assigned_to'), pk=pk)
    employee = _employee_for_task(request, task)

    if getattr(task, 'meeting_action', None) is not None:
        messages.error(request, 'وظیفه‌های ساخته‌شده از صورتجلسه از اینجا حذف نمی‌شوند؛ از خود صورتجلسه مدیریتشان کنید.')
        return redirect('employee_task_create', pk=employee.pk)

    title = task.title
    task.delete()
    messages.success(request, f'وظیفه «{title}» حذف شد.')
    return redirect('employee_task_create', pk=employee.pk)
