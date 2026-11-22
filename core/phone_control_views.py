"""Advanced phone-center control and private live supervision API."""
import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, RequestDataTooBig
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods, require_safe

from .phone_call_metrics import metric_report
from .phone_center_views import can_access_phone_center
from .phone_ratings import rating_report
from .phone_supervision import SupervisionError, start_supervision, supervision_snapshot


@login_required
@require_safe
@never_cache
def phone_control(request):
    if not can_access_phone_center(request.user):
        raise PermissionDenied
    ratings = rating_report(request.GET)
    metrics = metric_report(ratings['start'], ratings['end'])
    metrics['peak'] = max((day['count'] for day in metrics['daily']), default=1) or 1
    return render(request, 'core/phone_control.html', {'ratings': ratings, 'metrics': metrics})


@login_required
@require_http_methods(['GET', 'POST'])
@csrf_protect
@never_cache
def phone_control_live(request):
    if not can_access_phone_center(request.user):
        raise PermissionDenied
    if request.method == 'GET':
        return JsonResponse(supervision_snapshot(request.user))

    if request.content_type != 'application/json':
        return JsonResponse({'message': 'درخواست باید JSON باشد.'}, status=415)
    try:
        if len(request.body) > 2048:
            raise RequestDataTooBig
        data = json.loads(request.body)
    except RequestDataTooBig:
        return JsonResponse({'message': 'درخواست بیش از اندازه بزرگ است.'}, status=413)
    except ValueError:
        return JsonResponse({'message': 'درخواست معتبر نیست.'}, status=400)
    if not isinstance(data, dict) or set(data) != {'call_id', 'mode'}:
        return JsonResponse({'message': 'تماس و نوع ورود را مشخص کنید.'}, status=400)
    try:
        response = start_supervision(request.user, data['call_id'], data['mode'])
    except SupervisionError as exc:
        return JsonResponse({'message': exc.message, 'code': exc.code}, status=exc.status)
    return JsonResponse(response, status=202)
