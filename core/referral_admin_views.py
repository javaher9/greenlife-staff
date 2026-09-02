from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect

from .models import ReferralProfile


def system_admin_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        profile=getattr(request.user, 'profile', None)
        if not (request.user.is_superuser or getattr(profile, 'role', None)=='admin'):
            messages.error(request, 'حذف اعضای شبکه فقط برای مدیر سیستم مجاز است.')
            return redirect('referral_network')
        return view(request, *args, **kwargs)
    return wrapped


@system_admin_required
def referral_member_delete(request, pk):
    if request.method!='POST':
        messages.error(request, 'حذف عضو فقط از داخل پنل مدیریت انجام می‌شود.')
        return redirect('referral_network')

    target=get_object_or_404(
        ReferralProfile.objects.select_related('user', 'user__profile'),
        pk=pk,
    )

    if target.user_id==request.user.id:
        messages.error(request, 'حساب مدیر سیستم قابل حذف از شبکه نیست.')
        return redirect('referral_network')

    if getattr(getattr(target.user, 'profile', None), 'role', None)!='referrer':
        messages.error(request, 'فقط اعضای معرف شبکه از این بخش قابل حذف هستند.')
        return redirect('referral_network')

    has_history=target.leads.exists() or target.members.exists()
    name=str(target)

    if has_history:
        # Keep historical lead/sale/network relations intact; remove the member
        # from active screens and prevent future login/referrals.
        target.is_active=False
        target.save(update_fields=['is_active', 'updated_at'])
        target.user.is_active=False
        target.user.save(update_fields=['is_active'])
        employee=getattr(target.user, 'profile', None)
        if employee and employee.is_active:
            employee.is_active=False
            employee.save(update_fields=['is_active'])
        messages.success(
            request,
            f'«{name}» غیرفعال شد. سوابق قبلی او برای گزارش‌ها و پورسانت‌ها حفظ شده است.',
        )
    else:
        user=target.user
        user.delete()
        messages.success(request, f'«{name}» از شبکه فروش حذف شد.')

    return redirect('referral_network')
