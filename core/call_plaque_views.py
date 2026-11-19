"""Lead-scoped call plaque API. No outbound messages or automatic calls."""
import json
import uuid

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from .call_center_identity import call_center_display_name
from .call_plaque import (
    COMMUNICATION_STYLES, ENUMS, OUTCOMES, disc_code, empty_data, merge_profile,
    normalize_data, safe_data, score_readiness,
)
from .follow_up_agenda import previous_follow_up, record_follow_up
from .jalali import format_jalali
from django.urls import reverse
from .models import AuditLog, LeadCallProfile, LeadCallSession, ReferralLead


def _access(user):
    profile = getattr(user, 'profile', None)
    if not user.is_active or (profile and not profile.is_active):
        return None
    role = getattr(profile, 'role', '')
    queryset = ReferralLead.objects.select_related('group', 'assigned_to__user')
    if role == 'call_center' and profile:
        return queryset.filter(assigned_to=profile), True, False
    if user.is_superuser or role == 'admin':
        return queryset, False, False
    if role == 'internal_manager':
        return queryset, False, True
    if role == 'manager' and profile.branch_id:
        return queryset.filter(assigned_to__branch_id=profile.branch_id), False, True
    return None


def _actor(user):
    return call_center_display_name(user) if user else 'کاربر پیشین'


def _session_payload(session, *, restricted=False):
    data = safe_data(session.data, restricted=restricted)
    return {
        'id': session.pk, 'at': timezone.localtime(session.created_at).isoformat(),
        'actor': _actor(session.actor), 'data': data,
        'outcome': data.get('outcome', ''), 'outcome_label': OUTCOMES.get(data.get('outcome'), ''),
        'readiness': session.readiness,
    }


def _payload(lead, user, *, editable, restricted, profile=None):
    if profile is None:
        profile = LeadCallProfile.objects.filter(lead=lead).select_related('draft__actor', 'latest_session').first()
    data = safe_data(profile.data if profile else empty_data(), restricted=restricted)
    profile_data = dict(data)
    profile_data['disc_code'] = disc_code(data.get('communication_style'))
    profile_data['readiness'] = (profile.readiness if profile else {}) or score_readiness({}, do_not_contact=bool(profile and profile.do_not_contact))
    profile_data['do_not_contact'] = bool(profile and profile.do_not_contact)
    profile_data['updated_at'] = timezone.localtime(profile.latest_session.created_at).isoformat() if profile and profile.latest_session_id else None
    profile_data['evidence'] = {
        key: item for key, item in (profile.answer_evidence if profile else {}).items()
        if not restricted or key in ('timing', 'barrier')
    }
    draft = None
    if editable and profile and profile.draft_id and profile.draft.actor_id == user.pk:
        draft = _session_payload(profile.draft)
    history = [_session_payload(item, restricted=restricted) for item in lead.call_sessions.filter(state='final').select_related('actor')[:30]]
    return {
        'server_now': timezone.now().isoformat(),
        'operational': {
            'result': lead.get_contact_result_display() if lead.contact_result else '',
            'due': format_jalali(lead.next_follow_up) if lead.next_follow_up else '',
            'time': lead.next_follow_up_time.strftime('%H:%M') if lead.next_follow_up_time else '',
            'notes': lead.notes if not restricted else '',
            'appointment_url': reverse('appointment_schedule') + f'?lead={lead.pk}' if editable else '',
        },
        'ok': True, 'lead': {'id': lead.pk, 'name': lead.full_name, 'group': lead.group.name if lead.group_id else '',
                            'group_id': lead.group_id, 'owner': _actor(lead.assigned_to.user) if lead.assigned_to_id else ''},
        'editable': editable, 'restricted': restricted, 'version': profile.revision if profile else 0,
        'profile': profile_data, 'draft': draft, 'history': history,
        'history_total': lead.call_sessions.filter(state='final').count(),
        'labels': {'answers': ENUMS, 'communication': COMMUNICATION_STYLES, 'outcomes': OUTCOMES},
    }


def _apply_operational_result(lead, data, actor, *, do_not_contact):
    """Mirror permitted call outcomes without invoking the SMS-producing legacy view."""
    previous = previous_follow_up(lead)
    advanced = lead.status in ('appointment', 'visited', 'won') or lead.contact_result in ('appointment', 'won')
    outcome = data['outcome']
    if data['followup_consent'] == 'no':
        lead.next_follow_up = None
        lead.next_follow_up_time = None
    if do_not_contact:
        lead.next_follow_up = None
        lead.next_follow_up_time = None
        if not advanced:
            lead.status = 'lost'
            lead.contact_result = 'not_interested'
    elif outcome == 'follow_up':
        followup = timezone.localtime(parse_datetime(data['followup_at']))
        lead.next_follow_up = followup.date()
        lead.next_follow_up_time = followup.time().replace(tzinfo=None)
        if not advanced:
            lead.status = 'contacted'
            lead.contact_result = 'follow_up'
    elif outcome in ('not_interested', 'wrong_number'):
        lead.next_follow_up = None
        lead.next_follow_up_time = None
        if not advanced:
            lead.status = 'lost'
            lead.contact_result = outcome
    elif outcome == 'no_answer' and not advanced and lead.status != 'lost':
        lead.status = 'contacted'
        lead.contact_result = 'no_answer'
    elif outcome == 'answered' and not advanced:
        lead.status = 'contacted'
        # Do not keep an old refusal/no-answer as the displayed new answered call.
        lead.contact_result = 'follow_up' if lead.next_follow_up else ''
    lead.save(update_fields=['status', 'contact_result', 'next_follow_up', 'next_follow_up_time', 'updated_at'])
    record_follow_up(lead, actor=actor, previous=previous,
                     result='not_interested' if do_not_contact else outcome if outcome in ('follow_up', 'no_answer', 'not_interested', 'wrong_number') else '',
                     note=data['notes'] or 'پلاک تماس: ' + OUTCOMES[outcome])


@login_required
@require_http_methods(['GET', 'POST'])
def call_center_call_plaque(request, pk):
    access = _access(request.user)
    if access is None:
        return JsonResponse({'ok': False, 'error': 'دسترسی مجاز نیست.'}, status=403)
    queryset, editable, restricted = access
    if request.method == 'GET':
        lead = get_object_or_404(queryset, pk=pk)
        response = JsonResponse(_payload(lead, request.user, editable=editable, restricted=restricted))
        response['Cache-Control'] = 'no-store'
        return response
    if not editable:
        return JsonResponse({'ok': False, 'error': 'این نما فقط برای مشاهده است؛ ثبت تماس با کارشناس مسئول است.'}, status=403)
    try:
        if len(request.body) > 30000:
            raise ValueError()
        body = json.loads(request.body)
        if not isinstance(body, dict) or set(body) - {'version', 'request_id', 'action', 'data'}:
            raise ValueError()
        action = body.get('action')
        state = {'save_draft': 'draft', 'finalize': 'final', 'discard_draft': 'discard'}.get(action)
        if not state:
            raise ValueError()
        key = uuid.UUID(str(body.get('request_id', '')))
        version = body.get('version')
        if isinstance(version, bool) or not isinstance(version, int) or version < 0:
            raise ValueError()
        data = normalize_data(body.get('data', {}), final=state == 'final') if state != 'discard' else {}
    except (ValueError, TypeError, UnicodeDecodeError, ValidationError) as exc:
        message = ' '.join(exc.messages) if isinstance(exc, ValidationError) else 'اطلاعات درخواست معتبر نیست.'
        return JsonResponse({'ok': False, 'error': message}, status=400)
    try:
        with transaction.atomic():
            # Lead locking also serializes ownership-sensitive legacy changes.
            lead = get_object_or_404(queryset.select_for_update(of=('self',)), pk=pk)
            profile = LeadCallProfile.objects.filter(lead=lead).select_related('draft__actor', 'latest_session').first()
            old = LeadCallSession.objects.filter(request_id=key).first()
            if old:
                # Compare older snapshots with today's defaults for unanswered questions.
                saved_data = normalize_data(old.data) if old.state != 'discard' else {}
                if old.lead_id != lead.pk or old.actor_id != request.user.pk or old.state != state or saved_data != data:
                    return JsonResponse({'ok': False, 'error': 'شناسه این درخواست قبلاً برای اطلاعات دیگری استفاده شده است.'}, status=409)
                payload = _payload(lead, request.user, editable=True, restricted=False, profile=profile)
                payload['replayed'] = True
                payload['saved'] = state
                return JsonResponse(payload)
            if version != (profile.revision if profile else 0):
                return JsonResponse({'ok': False, 'error': 'پلاک در صفحه دیگری تغییر کرده است. ابتدا سوابق تازه را بارگذاری کنید.', 'code': 'stale_version'}, status=409)
            if profile and profile.do_not_contact and state == 'final':
                if data['followup_consent'] == 'yes' or data['whatsapp_consent'] == 'yes' or data['followup_at']:
                    return JsonResponse({'ok': False, 'error': 'درخواست عدم تماس این مخاطب فعال است؛ پیگیری یا ارسال تازه ثبت نمی‌شود.'}, status=400)
            if state == 'final' and data['followup_at'] and data['outcome'] != 'follow_up':
                return JsonResponse({'ok': False, 'error': 'برای زمان‌بندی پیگیری، نتیجه «پیگیری با اجازه» را انتخاب کنید.'}, status=400)
            if profile is None:
                profile = LeadCallProfile.objects.create(lead=lead)
            next_revision = profile.revision + 1
            dnc = profile.do_not_contact or bool(data.get('do_not_contact'))
            merged = merge_profile(profile.data, data) if state == 'final' else None
            if merged is not None:
                merged['do_not_contact'] = dnc
            readiness = score_readiness(merged, do_not_contact=dnc) if merged is not None else {}
            if state == 'final' and data['outcome'] == 'no_answer' and profile.readiness and not dnc:
                readiness = profile.readiness
            event = LeadCallSession.objects.create(
                lead=lead, actor=request.user, request_id=key, state=state,
                revision=next_revision, data=data, readiness=readiness,
            )
            profile.revision = next_revision
            if state == 'draft':
                profile.draft = event
            elif state == 'discard':
                profile.draft = None
            else:
                profile.data = merged
                evidence = dict(profile.answer_evidence)
                for answer_key, answer in data['answers'].items():
                    if answer['state'] != 'unasked':
                        evidence[answer_key] = {'at': timezone.localtime(event.created_at).isoformat(), 'actor': _actor(request.user)}
                for value_key, unknown in (('operator_rating', None), ('communication_style', 'unknown')):
                    if data[value_key] != unknown:
                        evidence[value_key] = {'at': timezone.localtime(event.created_at).isoformat(), 'actor': _actor(request.user)}
                profile.answer_evidence = evidence
                profile.readiness = readiness
                profile.do_not_contact = dnc
                profile.latest_session = event
                profile.draft = None
                _apply_operational_result(lead, data, request.user, do_not_contact=dnc)
            profile.save()
            AuditLog.objects.create(
                actor=request.user, action='call_plaque_' + state, path=request.path, method='POST',
                object_type='ReferralLead', object_id=str(lead.pk), summary='پلاک تماس: ' + dict(LeadCallSession.STATES)[state],
                metadata={'session_id': event.pk, 'revision': next_revision, 'outcome': data.get('outcome', ''), 'do_not_contact': profile.do_not_contact},
            )
            payload = _payload(lead, request.user, editable=True, restricted=False, profile=profile)
            payload['saved'] = state
            return JsonResponse(payload)
    except IntegrityError:
        return JsonResponse({'ok': False, 'error': 'درخواست هم‌زمان ثبت شده است. سوابق را دوباره بارگذاری کنید.'}, status=409)
