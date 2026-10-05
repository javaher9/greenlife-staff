"""Private Model Context Protocol endpoint for GreenLife Staff.

The endpoint intentionally implements a small, stateless subset of Streamable
HTTP. Authentication reuses the server-side ``STAFF_REPORT_API_KEY`` secret.
Operational role changes are deliberately narrow, explicit and audited.
"""

import hashlib
import hmac
import json
import os
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .jalali import parse_jalali
from .models import AuditLog, EmployeeProfile, ReferralLead, ReferralProfile, ReferralSale
from .reporting import answer_query, daily_reports_summary, day_summary


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "greenlife-staff", "version": "1.4.0"}
DEFAULT_WORK_TOKEN_SHA256 = "e9affd40ddff8a5d22ab70a5720a856e95d64853bc3e552484abf219518c4ae5"

TOOLS = [
    {
        "name": "get_attendance_summary",
        "title": "GreenLife attendance summary",
        "description": (
            "Read the GreenLife Staff attendance summary for one date, including "
            "late, present, missing and leave counts plus employee names and times."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": (
                        "Optional date: Jalali YYYY/MM/DD, Gregorian YYYY-MM-DD, "
                        "or today/yesterday (امروز/دیروز). Defaults to today in Tehran."
                    ),
                }
            },
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "get_daily_reports",
        "title": "GreenLife daily staff reports",
        "description": (
            "Read the content of Staff daily or nightly reports for one date, "
            "including AI summaries, transcripts, follow-up items and manager comments."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": (
                        "Optional date: Jalali YYYY/MM/DD, Gregorian YYYY-MM-DD, "
                        "or today/yesterday (امروز/دیروز). Defaults to today in Tehran."
                    ),
                },
                "branch": {
                    "type": "string",
                    "maxLength": 80,
                    "description": "Optional exact GreenLife branch name.",
                },
                "include_raw": {
                    "type": "boolean",
                    "description": (
                        "Include separate typed-text, transcript and AI-summary fields. "
                        "Defaults to false; compact content is always returned."
                    ),
                },
            },
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "get_referral_network_summary",
        "title": "GreenLife sales network all-time summary",
        "description": (
            "Read the internal GreenLife sales/referral network for all time, including "
            "member and lead rankings, direct and total network member counts, direct and "
            "network lead counts, won leads and approved sales."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "ask_management",
        "title": "Ask GreenLife management data",
        "description": (
            "Answer a read-only Persian management question about Staff attendance, "
            "late arrivals, missing attendance, reports, scores or recorded finance data."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 500,
                    "description": "Management question in Persian or English.",
                }
            },
            "required": ["question"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "find_staff",
        "title": "Find GreenLife staff accounts",
        "description": (
            "Find active Staff accounts by name, username, phone or job title before "
            "an exact operational role change."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "minLength": 2,
                    "maxLength": 80,
                    "description": "A staff name, surname, username, phone or job title fragment.",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
    {
        "name": "set_operational_role",
        "title": "Set GreenLife operational staff role",
        "description": (
            "Set an exact Staff account to employee, call center or consultant. "
            "Requires exact profile IDs and explicit confirmation; every change is audited."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "profile_ids": {
                    "type": "array",
                    "items": {"type": "integer", "minimum": 1},
                    "minItems": 1,
                    "maxItems": 25,
                    "description": "Exact EmployeeProfile IDs returned by find_staff.",
                },
                "role": {
                    "type": "string",
                    "enum": ["employee", "call_center", "consultant"],
                },
                "job_title": {"type": "string", "maxLength": 120},
                "confirm": {
                    "type": "boolean",
                    "description": "Must be true after the user explicitly authorizes the change.",
                },
            },
            "required": ["profile_ids", "role", "confirm"],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    },
]


def _configured_key():
    return os.getenv("MCP_API_KEY") or os.getenv("STAFF_REPORT_API_KEY") or ""


def _configured_work_token_hash():
    return os.getenv("MCP_WORK_TOKEN_SHA256") or DEFAULT_WORK_TOKEN_SHA256


def _authentication_configured():
    return bool(_configured_key() or _configured_work_token_hash())


def _authorized(request):
    supplied = request.headers.get("X-Staff-API-Key", "")
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    if not supplied:
        return False

    expected = _configured_key()
    if expected and hmac.compare_digest(supplied, expected):
        return True

    expected_digest = _configured_work_token_hash()
    supplied_digest = hashlib.sha256(supplied.encode("utf-8")).hexdigest()
    return bool(expected_digest) and hmac.compare_digest(supplied_digest, expected_digest)


def _admin_user():
    return (
        User.objects.filter(profile__role="admin", profile__is_active=True).first()
        or User.objects.filter(is_superuser=True, is_active=True).first()
    )


def _resolve_date(raw):
    value = (raw or "").strip()
    today = timezone.localdate()
    if not value or value.lower() == "today" or value == "امروز":
        return today
    if value.lower() == "yesterday" or value == "دیروز":
        return today - timedelta(days=1)
    if "/" in value:
        return parse_jalali(value)
    return date.fromisoformat(value)


def _attendance_summary(raw_date=None):
    day = _resolve_date(raw_date)
    admin = _admin_user()
    if not admin:
        raise RuntimeError("No active GreenLife admin user is configured.")
    return day_summary(admin, day)


def _management_answer(question):
    text = (question or "").strip()
    if not text:
        raise ValueError("question is required")
    if len(text) > 500:
        raise ValueError("question is too long")
    admin = _admin_user()
    if not admin:
        raise RuntimeError("No active GreenLife admin user is configured.")
    return answer_query(admin, text)


def _daily_reports(raw_date=None, branch=None, include_raw=False):
    day = _resolve_date(raw_date)
    branch = (branch or "").strip() or None
    if branch and len(branch) > 80:
        raise ValueError("branch is too long")
    if not isinstance(include_raw, bool):
        raise ValueError("include_raw must be a boolean")
    admin = _admin_user()
    if not admin:
        raise RuntimeError("No active GreenLife admin user is configured.")
    return daily_reports_summary(
        admin,
        day,
        branch=branch,
        include_raw=include_raw,
    )


def _referral_network_summary():
    """Return an all-time, read-only snapshot of the internal sales network."""
    profiles = list(
        ReferralProfile.objects.select_related("user", "user__profile", "sponsor").all()
    )
    included = []
    excluded = []
    for profile in profiles:
        employee = getattr(profile.user, "profile", None)
        reason = None
        if not profile.is_active or not profile.user.is_active:
            reason = "inactive"
        elif profile.user.username.startswith("lead-source-"):
            reason = "synthetic_lead_source"
        elif employee and employee.role == "call_center":
            reason = "call_center"
        if reason:
            excluded.append(
                {
                    "profile_id": profile.id,
                    "name": profile.user.get_full_name() or profile.user.username,
                    "reason": reason,
                }
            )
        else:
            included.append(profile)

    profile_ids = {profile.id for profile in included}
    children = {profile_id: [] for profile_id in profile_ids}
    for profile in included:
        if profile.sponsor_id in profile_ids:
            children[profile.sponsor_id].append(profile.id)

    def descendant_ids(profile_id):
        found = set()
        pending = list(children.get(profile_id, []))
        while pending:
            child_id = pending.pop()
            if child_id in found:
                continue
            found.add(child_id)
            pending.extend(children.get(child_id, []))
        return found

    lead_stats = {
        item["referrer_id"]: item
        for item in ReferralLead.objects.filter(referrer_id__in=profile_ids)
        .values("referrer_id")
        .annotate(total=Count("id"), won=Count("id", filter=Q(status="won")))
    }
    sale_stats = {
        item["lead__referrer_id"]: item
        for item in ReferralSale.objects.filter(
            lead__referrer_id__in=profile_ids,
            status__in=("approved", "paid"),
        )
        .values("lead__referrer_id")
        .annotate(total=Count("id"), amount=Sum("amount"))
    }

    rows = []
    for profile in included:
        descendants = descendant_ids(profile.id)
        network_ids = descendants | {profile.id}
        rows.append(
            {
                "profile_id": profile.id,
                "name": profile.user.get_full_name() or profile.user.username,
                "username": profile.user.username,
                "level": profile.level,
                "sponsor": (
                    profile.sponsor.user.get_full_name() or profile.sponsor.user.username
                    if profile.sponsor_id and profile.sponsor_id in profile_ids
                    else None
                ),
                "direct_members": len(children.get(profile.id, [])),
                "total_members": len(descendants),
                "direct_leads": lead_stats.get(profile.id, {}).get("total", 0),
                "network_leads": sum(
                    lead_stats.get(item_id, {}).get("total", 0) for item_id in network_ids
                ),
                "won_leads": lead_stats.get(profile.id, {}).get("won", 0),
                "approved_sales": sale_stats.get(profile.id, {}).get("total", 0),
                "approved_sales_amount": int(
                    sale_stats.get(profile.id, {}).get("amount") or 0
                ),
            }
        )

    member_order = sorted(
        rows,
        key=lambda row: (
            -row["total_members"],
            -row["direct_leads"],
            row["name"],
            row["profile_id"],
        ),
    )
    lead_order = sorted(
        rows,
        key=lambda row: (
            -row["direct_leads"],
            -row["total_members"],
            row["name"],
            row["profile_id"],
        ),
    )
    member_rank = {row["profile_id"]: rank for rank, row in enumerate(member_order, 1)}
    lead_rank = {row["profile_id"]: rank for rank, row in enumerate(lead_order, 1)}
    for row in rows:
        row["member_rank"] = member_rank[row["profile_id"]]
        row["lead_rank"] = lead_rank[row["profile_id"]]
    rows.sort(key=lambda row: (row["member_rank"], row["lead_rank"]))

    return {
        "scope": "internal_sales_network_all_time",
        "generated_at": timezone.now().isoformat(),
        "ranking_note": (
            "member_rank sorts by total_members, then direct_leads; "
            "lead_rank sorts by direct_leads, then total_members."
        ),
        "totals": {
            "active_profiles": len(rows),
            "root_profiles": sum(
                1 for profile in included if profile.sponsor_id not in profile_ids
            ),
            "all_leads": sum(row["direct_leads"] for row in rows),
            "won_leads": sum(row["won_leads"] for row in rows),
            "approved_sales": sum(row["approved_sales"] for row in rows),
            "approved_sales_amount": sum(row["approved_sales_amount"] for row in rows),
            "excluded_profiles": len(excluded),
        },
        "rows": rows,
        "excluded_profiles": excluded,
    }


def _staff_row(profile):
    user = profile.user
    return {
        "profile_id": profile.id,
        "user_id": user.id,
        "name": user.get_full_name() or user.username,
        "username": user.username,
        "phone": profile.phone,
        "branch": profile.branch.name if profile.branch else None,
        "role": profile.role,
        "role_display": profile.get_role_display(),
        "job_title": profile.job_title,
        "is_active": bool(profile.is_active and user.is_active),
    }


def _find_staff(query):
    value = (query or "").strip()
    if len(value) < 2:
        raise ValueError("query must contain at least 2 characters")
    if len(value) > 80:
        raise ValueError("query is too long")
    profiles = (
        EmployeeProfile.objects.select_related("user", "branch")
        .filter(user__is_active=True, is_active=True)
        .filter(
            Q(user__first_name__icontains=value)
            | Q(user__last_name__icontains=value)
            | Q(user__username__icontains=value)
            | Q(phone__icontains=value)
            | Q(job_title__icontains=value)
        )
        .order_by("user__last_name", "user__first_name", "user__username")[:20]
    )
    matches = [_staff_row(profile) for profile in profiles]
    return {"query": value, "match_count": len(matches), "matches": matches}


def _set_operational_role(profile_ids, role, job_title=None, confirm=False):
    if confirm is not True:
        raise ValueError("confirm must be true")
    if role not in {"employee", "call_center", "consultant"}:
        raise ValueError("role is not an allowed operational role")
    if not isinstance(profile_ids, list) or not profile_ids or len(profile_ids) > 25:
        raise ValueError("profile_ids must contain between 1 and 25 exact IDs")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in profile_ids):
        raise ValueError("profile_ids must contain positive integers")
    profile_ids = list(dict.fromkeys(profile_ids))
    if job_title is not None and not isinstance(job_title, str):
        raise ValueError("job_title must be a string")
    job_title = (job_title or "").strip()
    if len(job_title) > 120:
        raise ValueError("job_title is too long")

    actor = _admin_user()
    if not actor:
        raise RuntimeError("No active GreenLife admin user is configured.")

    with transaction.atomic():
        profiles = list(
            EmployeeProfile.objects.select_for_update()
            .select_related("user")
            .filter(pk__in=profile_ids, user__is_active=True, is_active=True)
            .order_by("pk")
        )
        found_ids = {profile.id for profile in profiles}
        missing_ids = [profile_id for profile_id in profile_ids if profile_id not in found_ids]
        if missing_ids:
            raise ValueError(f"active profiles not found: {missing_ids}")

        changes = []
        for profile in profiles:
            before = {"role": profile.role, "job_title": profile.job_title}
            profile.role = role
            if job_title:
                profile.job_title = job_title
            elif role == "call_center" and not profile.job_title:
                profile.job_title = "کارشناس کال‌سنتر"
            elif role == "consultant" and not profile.job_title:
                profile.job_title = "مشاور"
            profile.save(update_fields=["role", "job_title"])
            changes.append(
                {
                    "profile_id": profile.id,
                    "name": profile.user.get_full_name() or profile.user.username,
                    "before": before,
                    "after": {"role": profile.role, "job_title": profile.job_title},
                }
            )

        AuditLog.objects.create(
            actor=actor,
            action="mcp_operational_role",
            path="/mcp/",
            method="POST",
            object_type="EmployeeProfile",
            object_id=",".join(str(profile_id) for profile_id in profile_ids),
            summary=f"Operational role changed to {role} for {len(profiles)} staff",
            metadata={"role": role, "changes": changes},
        )

    return {"updated_count": len(changes), "role": role, "updated": changes}


def _rpc_result(request_id, result):
    return JsonResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def _rpc_error(request_id, code, message, *, status=200):
    return JsonResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status=status,
    )


def _tool_result(data):
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, ensure_ascii=False, default=str),
            }
        ],
        "structuredContent": data,
        "isError": False,
    }


@csrf_exempt
@never_cache
@require_http_methods(["GET", "POST", "DELETE"])
def mcp_endpoint(request):
    """Serve stateless MCP requests over HTTPS at ``/mcp/``."""

    if not _authentication_configured():
        return JsonResponse({"error": "MCP is not configured"}, status=503)
    if not _authorized(request):
        response = JsonResponse({"error": "unauthorized"}, status=401)
        response["WWW-Authenticate"] = 'Bearer realm="greenlife-staff"'
        return response

    if request.method == "GET":
        response = JsonResponse(
            {"name": SERVER_INFO["name"], "transport": "streamable-http", "status": "ready"}
        )
        response["Allow"] = "POST, DELETE"
        return response
    if request.method == "DELETE":
        return HttpResponse(status=204)

    try:
        payload = json.loads(request.body or b"{}")
    except (TypeError, ValueError, json.JSONDecodeError):
        return _rpc_error(None, -32700, "Parse error")

    if not isinstance(payload, dict):
        return _rpc_error(None, -32600, "Invalid Request")

    request_id = payload.get("id")
    method = payload.get("method")
    params = payload.get("params") or {}

    # Notifications do not have a JSON-RPC response body.
    if method == "notifications/initialized" and request_id is None:
        return HttpResponse(status=202)
    if method == "initialize":
        return _rpc_result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "Use reporting tools for live GreenLife data. Before changing a role, "
                    "resolve exact staff accounts with find_staff and call set_operational_role "
                    "only after explicit user authorization."
                ),
            },
        )
    if method == "ping":
        return _rpc_result(request_id, {})
    if method == "tools/list":
        return _rpc_result(request_id, {"tools": TOOLS})
    if method != "tools/call":
        return _rpc_error(request_id, -32601, "Method not found")

    tool_name = params.get("name")
    arguments = params.get("arguments") or {}
    if not isinstance(arguments, dict):
        return _rpc_error(request_id, -32602, "Invalid tool arguments")

    try:
        if tool_name == "get_attendance_summary":
            data = _attendance_summary(arguments.get("date"))
        elif tool_name == "get_daily_reports":
            data = _daily_reports(
                arguments.get("date"),
                arguments.get("branch"),
                arguments.get("include_raw", False),
            )
        elif tool_name == "get_referral_network_summary":
            data = _referral_network_summary()
        elif tool_name == "ask_management":
            data = _management_answer(arguments.get("question"))
        elif tool_name == "find_staff":
            data = _find_staff(arguments.get("query"))
        elif tool_name == "set_operational_role":
            data = _set_operational_role(
                arguments.get("profile_ids"),
                arguments.get("role"),
                arguments.get("job_title"),
                arguments.get("confirm", False),
            )
        else:
            return _rpc_error(request_id, -32602, f"Unknown tool: {tool_name}")
    except (ValueError, TypeError) as exc:
        return _rpc_error(request_id, -32602, str(exc))
    except Exception:
        # Do not leak database or infrastructure details to remote clients.
        return _rpc_error(request_id, -32603, "GreenLife reporting is temporarily unavailable")

    return _rpc_result(request_id, _tool_result(data))
