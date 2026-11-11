"""One atomic leave transition for full-page and quick-action clients."""
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404
from .internal_manager_scope import can_review_leave
from .models import AuditLog, LeaveRequest, StaffNotification


class LeaveConflict(Exception):
    pass


@transaction.atomic
def decide_leave(request, pk, status, note=''):
    leave = get_object_or_404(LeaveRequest.objects.select_for_update(), pk=pk)
    if not can_review_leave(request, leave):
        raise PermissionDenied
    if status not in ('approved', 'rejected'):
        raise ValidationError('نتیجه بررسی معتبر نیست.')
    note = note.strip()
    if status == 'rejected' and not note:
        raise ValidationError('برای رد درخواست، دلیل را ثبت کنید.')
    # Conditional update also protects backends without SELECT FOR UPDATE.
    changed = LeaveRequest.objects.filter(pk=pk, status='pending').update(
        status=status, reviewed_by=request.user, manager_note=note,
    )
    if not changed:
        raise LeaveConflict('این درخواست قبلاً بررسی شده است؛ صفحه را تازه کنید.')
    AuditLog.objects.create(
        actor=request.user, action='leave_decision', path=request.path, method='POST',
        object_type='LeaveRequest', object_id=str(pk), summary='Leave request reviewed',
        metadata={'before':'pending', 'after':status, 'note':note},
    )
    # The audit timestamp is the authoritative decision time; no invented legacy date.
    StaffNotification.objects.create(
        user=leave.user, title='نتیجه درخواست مرخصی',
        message=('درخواست شما تأیید شد.' if status == 'approved' else 'درخواست شما رد شد.') + ('\n' + note if note else ''),
        notification_type='leave_decision', related_date=leave.start_date,
    )
    return leave
