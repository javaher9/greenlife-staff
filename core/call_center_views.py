from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .models import ReferralLead


@login_required
@require_POST
def mark_call_started(request, pk):
    """Advance a brand-new call-center lead when the operator starts a call.

    Pressing the call button again never downgrades later outcomes such as
    appointment, visit, won or lost.
    """
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'call_center' or not profile.is_active:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    lead = get_object_or_404(ReferralLead, pk=pk, assigned_to=profile)
    changed = False
    if lead.status == 'new':
        lead.status = 'contacted'
        lead.save(update_fields=['status', 'updated_at'])
        changed = True

    labels = {
        'new': 'جدید',
        'contacted': 'تماس گرفته شد',
        'appointment': 'نوبت داده شد',
        'visited': 'مراجعه کرد',
        'won': 'فروش موفق',
        'lost': 'تمایل به پیگیری ندارد',
    }
    return JsonResponse({
        'ok': True,
        'changed': changed,
        'status': lead.status,
        'label': labels.get(lead.status, lead.get_status_display()),
    })
