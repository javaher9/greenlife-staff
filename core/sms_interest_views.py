import re
from datetime import timedelta
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
    ('fit', 'کدام خدمت برای من مناسب است؟', 'انتخاب مناسب از شناخت هدف شما شروع می‌شود. مشاور می‌تواند گزینه‌های مرتبط را توضیح دهد؛ تشخیص و تصمیم درمانی به ارزیابی پزشک نیاز دارد.'),
    ('process', 'روند کار و نتیجه چگونه است؟', 'می‌توانید پیش از تصمیم‌گیری درباره مراحل، تعداد جلسات احتمالی و مراقبت‌ها سؤال کنید. نتیجه برای افراد مختلف یکسان نیست؛ مشاور مسیر دریافت توضیح متناسب با خدمت را هماهنگ می‌کند.'),
    ('cost', 'هزینه و شرایط پرداخت چیست؟', 'هزینه به خدمت و برنامه پیشنهادی بستگی دارد. با درخواست تماس، جزئیات هزینه و شرایط موجود را پیش از تصمیم‌گیری دریافت کنید.'),
    ('later', 'فعلاً قصد مراجعه ندارم', 'متشکریم که گفتید. برای این دعوت درخواست پیگیری ثبت نمی‌شود. هر زمان آماده بودید می‌توانید دوباره انتخاب کنید.'),
]


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
    items = list(SmsInterestInvitation.objects.order_by('-created_at')[:100])
    labels = {key: title for key, title, _ in CHOICES}
    for item in items:
        item.choice_label = labels.get(item.choice, 'هنوز پاسخ نداده')
    link = request.build_absolute_uri(reverse('sms_interest_public', args=[selected.token])) if selected else ''
    return render(request, 'core/sms_interest_inbox.html', {'items': items, 'selected': selected, 'link': link})


@require_http_methods(['GET', 'POST'])
@never_cache
def public(request, token):
    item = get_object_or_404(SmsInterestInvitation, token=token)
    expired = timezone.now() > item.created_at + timedelta(days=30)
    if request.method == 'POST' and not expired:
        with transaction.atomic():
            item = SmsInterestInvitation.objects.select_for_update().get(pk=item.pk)
            if request.POST.get('action') == 'callback':
                if item.choice not in ('fit', 'process', 'cost'):
                    return HttpResponseBadRequest('ابتدا یک گزینه انتخاب کنید.')
                if item.callback_at is None:
                    item.callback_at = timezone.now()
                    item.save(update_fields=['callback_at'])
            else:
                choice = request.POST.get('choice')
                if choice not in {x[0] for x in CHOICES}:
                    return HttpResponseBadRequest('گزینه نامعتبر است.')
                item.choice = choice
                item.answered_at = timezone.now()
                if choice == 'later':
                    item.callback_at = None
                item.save(update_fields=['choice', 'answered_at', 'callback_at'])
        return redirect('sms_interest_public', token=item.token)
    answer = next((x for x in CHOICES if x[0] == item.choice), None)
    response = render(request, 'core/sms_interest_public.html', {'item': item, 'choices': CHOICES, 'answer': answer, 'expired': expired})
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response

