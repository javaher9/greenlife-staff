"""Learning access is derived on the server; never accept client heart/clinic claims."""
import json
from pathlib import Path
from django.db import transaction
from django.middleware.csrf import get_token
from django.views.decorators.http import require_http_methods
from .customer_portal_views import _member
from .me_diet_views import today
from .me_sync_views import reply
from .me_sync_models import MeDailyAward
from .me_nutrition_models import MeNutritionProgress
from .models import CustomerPortalMember, VisitAppointment

LESSONS = json.loads(Path(__file__).with_name('me_nutrition_lessons.json').read_text(encoding='utf8'))


def access(member):
    if not member:
        return 0, False
    # OTP-verified normalized member phone, not a client-submitted appointment ID.
    phones = [member.phone, '+98'+member.phone[1:], '98'+member.phone[1:]]
    clinic = VisitAppointment.objects.filter(phone__in=phones, status='completed', appointment_date__lte=today()).exists()
    return MeDailyAward.objects.filter(member=member).count(), clinic


def unlocked(group, hearts, clinic):
    return clinic if group['clinic'] else hearts >= group['hearts']


def snapshot(request, member):
    hearts, clinic = access(member)
    progress = MeNutritionProgress.objects.filter(member=member).first() if member else None
    groups = [{**g, 'unlocked': unlocked(g, hearts, clinic)} for g in LESSONS['groups']]
    ids = {i for g in groups if g['unlocked'] for i in g['ids']}
    # Titles are public previews. Locked lesson explanations never leave this endpoint.
    return {'version': LESSONS['version'], 'authenticated': bool(member), 'csrf': get_token(request),
            'hearts': hearts, 'clinic': clinic, 'groups': groups, 'sources': LESSONS['sources'],
            'catalog': [{'id': i['id'], 'title': i['title']} for i in LESSONS['items']],
            'items': [i for i in LESSONS['items'] if i['id'] in ids],
            'choices': progress.choices if progress else {}}


@require_http_methods(['GET', 'POST'])
def nutrition(request):
    member = _member(request)
    if request.method == 'GET':
        return reply(snapshot(request, member))
    if not member:
        return reply({'error': 'برای نگه‌داشتن پیشرفت روی همهٔ دستگاه‌ها، وارد حساب شو.'}, 401)
    try:
        if request.content_type != 'application/json' or len(request.body) > 1000:
            raise ValueError()
        data = json.loads(request.body)
        if not isinstance(data, dict) or set(data) != {'version', 'id', 'choice'}:
            raise ValueError()
        if data['version'] != LESSONS['version'] or type(data['id']) is not int or data['choice'] not in ('change', 'portion'):
            raise ValueError()
        group = next(g for g in LESSONS['groups'] if data['id'] in g['ids'])
    except (ValueError, TypeError, KeyError, StopIteration):
        return reply({'error': 'انتخاب معتبر نیست؛ صفحه را تازه کن.'}, 400)
    with transaction.atomic():
        CustomerPortalMember.objects.select_for_update().get(pk=member.pk)
        if not unlocked(group, *access(member)):
            return reply({'error': 'این مرحله هنوز برای حسابت باز نشده است.'}, 403)
        progress, _ = MeNutritionProgress.objects.get_or_create(member=member)
        progress.choices[str(data['id'])] = data['choice']
        progress.save()
    return reply(snapshot(request, member))
