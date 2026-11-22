"""Private playback and single-use import of approved assistant auditions."""
from hashlib import sha256
from hmac import compare_digest
import re

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, RequestDataTooBig
from django.http import Http404, HttpResponse
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_safe

from .models import PhoneVoiceSample
from .phone_center_views import can_access_phone_center


# Only the three exact approved files are accepted. An existing slot is immutable.
_APPROVED = {
    'camellia': 'c4c8a06be4f94c3d260e1ab15e3e62b1c0e584333fa60c8252e048795aa12f68',
    'rose': '6b713055202773ca56ea54ed1fad24331cd11ad0212a569bfe74e6074c0ddd8e',
    'yasaman': '9fa11e01abec04aeff365bfd0f9b5145560853eb6ffd005d7342e00ad17f8c0b',
}
_IMPORT_TOKEN_HASH = '30b393b440d492103b4e08b2eb4b6f5480c7b82a4e2f0b2367e02df9a6c94900'


@csrf_exempt
@never_cache
@require_POST
def install_sample(request, assistant):
    scheme, _, token = request.headers.get('Authorization', '').partition(' ')
    if (
        assistant not in _APPROVED or scheme != 'Bearer' or len(token) != 64
        or not compare_digest(sha256(token.encode()).hexdigest(), _IMPORT_TOKEN_HASH)
    ):
        raise Http404
    if PhoneVoiceSample.objects.filter(pk=assistant).exists():
        return HttpResponse(status=409)
    try:
        contents = request.body
    except RequestDataTooBig:
        return HttpResponse(status=413)
    if len(contents) > 128 * 1024 or not compare_digest(sha256(contents).hexdigest(), _APPROVED[assistant]):
        return HttpResponse(status=400)
    _, created = PhoneVoiceSample.objects.get_or_create(assistant=assistant, defaults={'contents': contents})
    return HttpResponse(status=201 if created else 409)


@login_required
@require_safe
@never_cache
def play_sample(request, assistant):
    if not can_access_phone_center(request.user):
        raise PermissionDenied
    sample = PhoneVoiceSample.objects.filter(pk=assistant).first()
    if sample is None:
        raise Http404
    contents = bytes(sample.contents)
    size = len(contents)
    bounds = re.fullmatch(r'bytes=([0-9]{0,12})-([0-9]{0,12})', request.headers.get('Range', ''))
    headers = {'Accept-Ranges': 'bytes', 'Content-Length': str(size)}
    if bounds and any(bounds.groups()):
        first, last = bounds.groups()
        start = int(first) if first else max(0, size - int(last))
        end = min(int(last), size - 1) if first and last else size - 1
        if start > end:
            return HttpResponse(status=416, headers={'Content-Range': f'bytes */{size}'})
        headers.update({
            'Content-Range': f'bytes {start}-{end}/{size}',
            'Content-Length': str(end - start + 1),
        })
        return HttpResponse(contents[start:end + 1], status=206, content_type='audio/wav', headers=headers)
    return HttpResponse(contents, content_type='audio/wav', headers=headers)
