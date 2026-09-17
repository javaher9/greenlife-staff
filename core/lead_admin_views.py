from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render

from .models import ReferralLead


def _is_admin(user):
    profile = getattr(user, 'profile', None)
    return bool(user.is_superuser or (profile and profile.role == 'admin'))


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
            messages.error(request, 'نام و شماره موبایل الزامی است.')
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
        name = lead.full_name
        lead.delete()
        messages.success(request, f'لید «{name}» حذف شد.')
        return redirect('lead_management_dashboard')
    return render(request, 'core/lead_admin_delete.html', {'lead': lead})
