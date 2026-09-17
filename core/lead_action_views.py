from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .forms import ReferralLeadManageForm
from .models import ReferralLead
from .referral_views import _default_call_center_group, _notify_call_center_assignment


ALLOWED_ROLES = ('admin', 'manager', 'internal_manager')


@login_required
def management_lead_follow_up(request, pk):
    """Management-safe follow-up page for Lead Hub urgent actions.

    Lead Hub includes leads from technical/public sources whose referrer may be
    inactive. The older referral-network manage view scopes by active referral
    profiles, which can turn a valid Lead Hub action into a 404. This endpoint
    authorizes against the management role instead and edits the lead directly.
    """
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
    })
