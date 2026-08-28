from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone

from .models import LeaveRequest, AttendanceCorrectionRequest, DeviceIssue, Task
from .operations import approve_correction, award_task
from .views import role_of


def _allowed_manager(request, user):
    role = role_of(request.user)
    if role == 'admin':
        return True
    if role != 'manager':
        return False
    manager_branch = getattr(getattr(request.user, 'profile', None), 'branch_id', None)
    user_branch = getattr(getattr(user, 'profile', None), 'branch_id', None)
    return manager_branch and manager_branch == user_branch


@login_required
def quick_action(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'message': 'درخواست نامعتبر است.'}, status=405)
    if role_of(request.user) not in ('admin', 'manager'):
        return JsonResponse({'ok': False, 'message': 'دسترسی مجاز نیست.'}, status=403)

    kind = (request.POST.get('kind') or '').strip()
    action = (request.POST.get('action') or '').strip()
    try:
        pk = int(request.POST.get('pk') or 0)
    except (TypeError, ValueError):
        pk = 0
    if not pk:
        return JsonResponse({'ok': False, 'message': 'شناسه اقدام نامعتبر است.'}, status=400)

    if kind == 'leave':
        obj = get_object_or_404(LeaveRequest.objects.select_related('user', 'user__profile'), pk=pk)
        if not _allowed_manager(request, obj.user):
            return JsonResponse({'ok': False, 'message': 'دسترسی مجاز نیست.'}, status=403)
        if obj.status != 'pending':
            return JsonResponse({'ok': True, 'message': 'این مورد قبلاً بررسی شده است.'})
        if action not in ('approved', 'rejected'):
            return JsonResponse({'ok': False, 'message': 'نتیجه نامعتبر است.'}, status=400)
        obj.status = action
        obj.reviewed_by = request.user
        obj.save(update_fields=['status', 'reviewed_by'])
        return JsonResponse({'ok': True, 'message': 'درخواست تایید شد.' if action == 'approved' else 'درخواست رد شد.'})

    if kind == 'correction':
        obj = get_object_or_404(AttendanceCorrectionRequest.objects.select_related('user', 'user__profile'), pk=pk)
        if not _allowed_manager(request, obj.user):
            return JsonResponse({'ok': False, 'message': 'دسترسی مجاز نیست.'}, status=403)
        if obj.status != 'pending':
            return JsonResponse({'ok': True, 'message': 'این مورد قبلاً بررسی شده است.'})
        if action not in ('approved', 'rejected'):
            return JsonResponse({'ok': False, 'message': 'نتیجه نامعتبر است.'}, status=400)
        approve_correction(obj, request.user, action, '')
        return JsonResponse({'ok': True, 'message': 'اصلاح حضور تایید شد.' if action == 'approved' else 'اصلاح حضور رد شد.'})

    if kind == 'device':
        obj = get_object_or_404(DeviceIssue.objects.select_related('reporter', 'reporter__profile'), pk=pk)
        if not _allowed_manager(request, obj.reporter):
            return JsonResponse({'ok': False, 'message': 'دسترسی مجاز نیست.'}, status=403)
        if action == 'reviewing':
            obj.status = 'reviewing'
            obj.save(update_fields=['status', 'updated_at'])
            return JsonResponse({'ok': True, 'message': 'وضعیت به «در حال بررسی» تغییر کرد.', 'keep': True})
        if action == 'resolved':
            obj.status = 'resolved'
            obj.resolved_at = timezone.now()
            obj.resolved_by = request.user
            obj.save(update_fields=['status', 'resolved_at', 'resolved_by', 'updated_at'])
            return JsonResponse({'ok': True, 'message': 'خرابی دستگاه رفع‌شده ثبت شد.'})
        return JsonResponse({'ok': False, 'message': 'نتیجه نامعتبر است.'}, status=400)

    if kind == 'task':
        obj = get_object_or_404(Task.objects.select_related('assigned_to', 'assigned_to__profile'), pk=pk)
        if not _allowed_manager(request, obj.assigned_to):
            return JsonResponse({'ok': False, 'message': 'دسترسی مجاز نیست.'}, status=403)
        if action != 'done':
            return JsonResponse({'ok': False, 'message': 'نتیجه نامعتبر است.'}, status=400)
        if obj.status != 'done':
            obj.status = 'done'
            obj.save(update_fields=['status', 'updated_at'])
            award_task(obj)
        return JsonResponse({'ok': True, 'message': 'وظیفه انجام‌شده ثبت شد.'})

    return JsonResponse({'ok': False, 'message': 'این نوع اقدام هنوز میان‌بر نهایی ندارد.'}, status=400)
