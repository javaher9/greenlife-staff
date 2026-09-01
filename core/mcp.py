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
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .jalali import parse_jalali
from .models import AuditLog, EmployeeProfile
from .reporting import answer_query, daily_reports_summary, day_summary


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "greenlife-staff", "version": "1.3.1"}
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
            "Set an exact Staff account to employee or call center. "
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
                    "enum": ["employee", "call_center"],
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
    if role not in {"employee", "call_center"}:
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
