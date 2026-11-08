import re
from datetime import timedelta
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .bulk_sms_views import _may_manage_bulk_sms
from .sms_interest_models import SmsInterestInvitation

CHOICES = [
    ('weight', 'کاهش وزن و درمان چاقی', 'هدف شما ثبت شد. برای انتخاب مسیر مناسب، شرایط بدنی و سبک زندگی شما بررسی می‌شود و مشاور درباره گزینه‌های قابل‌بررسی راهنمایی‌تان می‌کند.'),
    ('local', 'لاغری موضعی شکم، پهلو یا سایر نواحی', 'ناحیه موردنظر شما در گفت‌وگوی اولیه مشخص می‌شود. روش مناسب به شرایط بدن، نوع بافت و هدف شما بستگی دارد.'),
    ('device', 'فرم‌دهی و لاغری با دستگاه', 'هدف شما ثبت شد. انتخاب دستگاه و تعداد جلسات به شرایط بدنی و ناحیه موردنظر بستگی دارد؛ مشاور برای ارزیابی اولیه راهنمایی‌تان می‌کند.'),
    ('unsure', 'نمی‌دانم کدام مسیر مناسب من است', 'کاملاً طبیعی است. مشاور با چند سؤال کوتاه کمک می‌کند مسیر مناسب را پیدا کنید و بدانید قدم اول چیست.'),
]
LEGACY_LABELS = {'fit': 'انتخاب خدمت مناسب', 'process': 'روند کار و نتیجه', 'cost': 'هزینه و شرایط پرداخت', 'later': 'فعلاً قصد مراجعه ندارد'}


@login_required
@require_http_methods(['GET', 'POST'])
@never_cache
def inbox(request):
    if not _may_manage_bulk_sms(request.user):
        raise PermissionDenied()
    if request.method == 'POST':
        number = request.POST.get('number', '').strip()
        if not re.fullmatch(r'09[0-9]{9}', number):
            return HttpResponseBadRequest('شماره موبایل معتبر وارد کنید.')
        item = SmsInterestInvitation.objects.create(number=number, created_by=request.user)
        return redirect(reverse('sms_interest_inbox') + '?invitation=' + str(item.pk))
    selected = None
    if request.GET.get('invitation', '').isdigit():
        selected = get_object_or_404(SmsInterestInvitation, pk=request.GET['invitation'], created_by=request.user)
    all_items = SmsInterestInvitation.objects.order_by('-created_at')
    status = request.GET.get('status', 'callback')
    if status == 'callback':
        filtered_items = all_items.filter(callback_at__isnull=False)
    elif status == 'answered':
        filtered_items = all_items.filter(answered_at__isnull=False, callback_at__isnull=True).exclude(choice='later')
    elif status == 'later':
        filtered_items = all_items.filter(choice='later')
    elif status == 'waiting':
        filtered_items = all_items.filter(answered_at__isnull=True)
    else:
        status = 'all'
        filtered_items = all_items
    items = list(filtered_items[:100])
    labels = {**LEGACY_LABELS, **{key: title for key, title, _ in CHOICES}}
    for item in items:
        item.choice_label = labels.get(item.choice, 'هنوز پاسخ نداده')
    short_base = getattr(settings, 'SMS_SHORT_BASE_URL', '').rstrip('/') or ('https://' + request.get_host())
    link = short_base + reverse('sms_interest_short', args=[selected.short_code]) if selected else ''
    today = timezone.localdate()
    stats = {
        'callback': all_items.filter(callback_at__isnull=False).count(),
        'today': all_items.filter(answered_at__date=today).count(),
        'answered': all_items.filter(answered_at__isnull=False).count(),
        'waiting': all_items.filter(answered_at__isnull=True).count(),
    }
    return render(request, 'core/sms_interest_inbox.html', {
        'items': items, 'selected': selected, 'link': link,
        'status': status, 'stats': stats,
    })


@require_http_methods(['GET', 'POST'])
@never_cache
def public(request, token=None, code=None):
    item = get_object_or_404(SmsInterestInvitation, **({'short_code': code} if code else {'token': token}))
    expired = timezone.now() > item.created_at + timedelta(days=30)
    direct_choice = request.GET.get('select')
    direct_callback = request.GET.get('callback') == '1'
    if (request.method == 'POST' or direct_choice or direct_callback) and not expired:
        with transaction.atomic():
            item = SmsInterestInvitation.objects.select_for_update().get(pk=item.pk)
            if direct_callback or request.POST.get('action') == 'callback':
                if item.choice not in {x[0] for x in CHOICES}:
                    return HttpResponseBadRequest('ابتدا یک گزینه انتخاب کنید.')
                if item.callback_at is None:
                    item.callback_at = timezone.now()
                    item.save(update_fields=['callback_at'])
            else:
                choice = direct_choice or request.POST.get('choice')
                if choice != 'later' and choice not in {x[0] for x in CHOICES}:
                    return HttpResponseBadRequest('گزینه نامعتبر است.')
                item.choice = choice
                item.answered_at = timezone.now()
                if choice == 'later':
                    item.callback_at = None
                item.save(update_fields=['choice', 'answered_at', 'callback_at'])
        return redirect('sms_interest_short', code=item.short_code)
    answer = next((x for x in CHOICES if x[0] == item.choice), None)
    response = render(request, 'core/sms_interest_public.html', {'item': item, 'choices': CHOICES, 'answer': answer, 'declined': item.choice == 'later', 'expired': expired})
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response

