from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ReferralLeadManageForm
from .models import ReferralLead
from .referral_views import _default_call_center_group, _notify_call_center_assignment


ALLOWED_ROLES = ('admin', 'manager', 'internal_manager')


def _is_admin(user):
    profile = getattr(user, 'profile', None)
    return bool(user.is_superuser or (profile and profile.role == 'admin'))


@login_required
def management_lead_follow_up(request, pk):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in ALLOWED_ROLES:
        messages.error(request, 'دسترسی به پیگیری مدیریتی لید ندارید.')
        return redirect('lead_management_dashboard')

    lead = get_object_or_404(
        ReferralLead.objects.select_related('assigned_to__user', 'group', 'referrer__user'),
        pk=pk,
    )
    form = ReferralLeadManageForm(request.POST or None, instance=lead)
    if request.method == 'POST' and form.is_valid():
        previous_assignee = lead.assigned_to_id
        updated = form.save()
        if updated.assigned_to_id != previous_assignee:
            if updated.assigned_to_id:
                updated.group = _default_call_center_group(updated.assigned_to)
                updated.save(update_fields=['group', 'updated_at'])
                _notify_call_center_assignment(updated)
            elif updated.group_id:
                updated.group = None
                updated.save(update_fields=['group', 'updated_at'])
        messages.success(request, 'اقدام لید ثبت شد و صف اقدام فوری به‌روزرسانی می‌شود.')
        return redirect('lead_management_dashboard')

    action_title = 'تخصیص مسئول' if not lead.assigned_to_id else 'ثبت نتیجه تماس / پیگیری'
    return render(request, 'core/referrals/form.html', {
        'form': form,
        'title': action_title,
        'subtitle': f'{lead.full_name} · {lead.phone}',
        'button': 'ثبت اقدام',
        'lead': lead,
        'lead_admin_actions': _is_admin(request.user),
    })


@login_required
def admin_lead_edit(request, pk):
    if not _is_admin(request.user):
        messages.error(request, 'ویرایش لید فقط برای ادمین مجاز است.')
        return redirect('lead_management_dashboard')
    lead = get_object_or_404(ReferralLead, pk=pk)
    if request.method == 'POST':
        full_name = (request.POST.get('full_name') or '').strip()
        phone = (request.POST.get('phone') or '').strip()
        if not full_name or not phone:
            messages.error(request, 'نام و موبایل الزامی است.')
        else:
            lead.full_name = full_name
            lead.phone = phone
            lead.save(update_fields=['full_name', 'phone', 'updated_at'])
            messages.success(request, 'اطلاعات لید ویرایش شد.')
            return redirect('lead_management_dashboard')
    return render(request, 'core/lead_admin_edit.html', {'lead': lead})


@login_required
def admin_lead_delete(request, pk):
    if not _is_admin(request.user):
        messages.error(request, 'حذف لید فقط برای ادمین مجاز است.')
        return redirect('lead_management_dashboard')
    lead = get_object_or_404(ReferralLead, pk=pk)
    if request.method == 'POST':
        label = f'{lead.full_name} · {lead.phone}'
        lead.delete()
        messages.success(request, f'لید {label} حذف شد.')
        return redirect('lead_management_dashboard')
    return render(request, 'core/lead_admin_delete.html', {'lead': lead})
