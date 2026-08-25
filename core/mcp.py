"""Read-only Model Context Protocol endpoint for GreenLife Staff.

The endpoint intentionally implements a small, stateless subset of Streamable
HTTP.  It exposes only management reporting tools and never mutates Staff data.
Authentication reuses the server-side ``STAFF_REPORT_API_KEY`` secret.
"""

import hmac
import json
import os
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .jalali import parse_jalali
from .reporting import answer_query, day_summary


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "greenlife-staff", "version": "1.0.0"}

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
]


def _configured_key():
    return os.getenv("MCP_API_KEY") or os.getenv("STAFF_REPORT_API_KEY") or ""


def _authorized(request):
    expected = _configured_key()
    if not expected:
        return False
    supplied = request.headers.get("X-Staff-API-Key", "")
    authorization = request.headers.get("Authorization", "")
    if authorization.lower().startswith("bearer "):
        supplied = authorization[7:].strip()
    return bool(supplied) and hmac.compare_digest(supplied, expected)


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

    if not _configured_key():
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
                    "Use these read-only tools for GreenLife Staff management reporting. "
                    "Never infer attendance values when a tool call can retrieve them."
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
        elif tool_name == "ask_management":
            data = _management_answer(arguments.get("question"))
        else:
            return _rpc_error(request_id, -32602, f"Unknown tool: {tool_name}")
    except (ValueError, TypeError) as exc:
        return _rpc_error(request_id, -32602, str(exc))
    except Exception:
        # Do not leak database or infrastructure details to remote clients.
        return _rpc_error(request_id, -32603, "GreenLife reporting is temporarily unavailable")

    return _rpc_result(request_id, _tool_result(data))
