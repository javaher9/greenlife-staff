"""Authenticated Instagram lead intake. Disabled until an integration secret is configured."""
import json
import os
import hmac
import re
from django.db import connection, transaction

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .instagram_views import (
    InstagramLeadForm, INSTAGRAM_PAGE_SOURCES, _instagram_page_source,
    _instagram_source_profile, _assign_instagram_lead,
)
from .models import ReferralLead, DuplicateLeadError, LEAD_DUPLICATE_MESSAGE


@csrf_exempt
@require_POST
def instagram_agent_lead_api(request):
    # This endpoint uses bearer authentication rather than browser cookies.
    secret = os.environ.get("INSTAGRAM_AGENT_API_KEY", "")
    if len(secret) < 32:
        return JsonResponse({"status": "disabled"}, status=503)
    supplied = request.headers.get("Authorization", "")
    if not hmac.compare_digest(supplied, "Bearer " + secret):
        return JsonResponse({"status": "unauthorized"}, status=401)
    if request.content_type != "application/json":
        return JsonResponse({"status": "unsupported_media_type"}, status=415)
    if len(request.body) > 8192:
        return JsonResponse({"status": "payload_too_large"}, status=413)
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({"status": "invalid_json"}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({"status": "invalid_payload"}, status=400)
    page = str(data.get("source_page", ""))
    if page not in INSTAGRAM_PAGE_SOURCES:
        return JsonResponse({"status": "invalid_source_page"}, status=422)
    if data.get("contact_consent") is not True:
        return JsonResponse({"status": "consent_required"}, status=422)
    event_id = data.get("external_event_id")
    if not isinstance(event_id, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{8,96}", event_id):
        return JsonResponse({"status": "invalid_event_id"}, status=422)
    event_key = "ig-agent:" + event_id
    # Check idempotency before validating a phone that may now be a duplicate.
    prior = ReferralLead.objects.filter(crm_id=event_key).only("pk").first()
    if prior:
        return JsonResponse({"status": "already_processed", "lead_id": prior.pk}, status=200)
    form = InstagramLeadForm({
        "full_name": data.get("full_name", ""),
        "phone": data.get("phone", ""),
        "interested_service": data.get("interested_service", ""),
        "consent": "on",
    })
    if not form.is_valid():
        # Existing duplicate detection lives in InstagramLeadForm.clean_phone.
        # Avoid echoing submitted personal information in error responses.
        phone_errors = form.errors.get("phone", [])
        if any(str(error) == str(LEAD_DUPLICATE_MESSAGE) for error in phone_errors):
            return JsonResponse({"status": "duplicate_phone"}, status=409)
        return JsonResponse({"status": "validation_error", "fields": list(form.errors.keys())}, status=422)
    cleaned = form.cleaned_data
    slug, label = _instagram_page_source(page)
    # Serialize same-event requests across workers on PostgreSQL.
    # The existing ReferralLead.save() separately serializes duplicate phones.
    with transaction.atomic():
        if connection.vendor == "postgresql":
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                    ["greenlife-instagram-event:" + event_key],
                )
        prior = ReferralLead.objects.filter(crm_id=event_key).only("pk").first()
        if prior:
            return JsonResponse({"status": "already_processed", "lead_id": prior.pk}, status=200)
        try:
            lead = ReferralLead.objects.create(
                referrer=_instagram_source_profile(),
                full_name=cleaned["full_name"].strip(),
                phone=cleaned["phone"],
                interested_service=(cleaned.get("interested_service") or "").strip(),
                status="new",
                source="link",
                crm_id=event_key,
                notes=f"Instagram Agent API | پیج: {label} | [channel:instagram] | [instagram_page:{slug}]",
            )
        except DuplicateLeadError:
            return JsonResponse({"status": "duplicate_phone"}, status=409)
        _assign_instagram_lead(lead)
    return JsonResponse({"status": "created", "lead_id": lead.pk}, status=201)
