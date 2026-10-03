import hashlib
import hmac
import json
import os

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "").strip()
APP_SECRET = os.getenv("WHATSAPP_APP_SECRET", "").strip()
ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
DEFAULT_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v26.0").strip()

ALLOWED_PHONE_NUMBER_IDS = {
    value.strip()
    for value in os.getenv("WHATSAPP_PHONE_NUMBER_IDS", "").split(",")
    if value.strip()
}

STAFF_LEAD_URL = os.getenv(
    "STAFF_LEAD_URL",
    "https://staff.greenlifeclinics.com/api/integrations/leads/",
).strip()
STAFF_LEAD_TOKEN = os.getenv("STAFF_LEAD_TOKEN", "").strip()

STAFF_EVENT_URL = os.getenv(
    "STAFF_WHATSAPP_EVENT_URL",
    "https://staff.greenlifeclinics.com/api/whatsapp/events/",
).strip()
STAFF_EVENT_KEY = os.getenv("STAFF_WHATSAPP_EVENT_KEY", "").strip()

BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "").strip()


def _authorized_bridge_call():
    supplied = request.headers.get("X-Bridge-Key", "").strip()
    return bool(
        BRIDGE_API_KEY
        and supplied
        and hmac.compare_digest(BRIDGE_API_KEY, supplied)
    )


def _allowed_phone_number_id(phone_number_id):
    if not phone_number_id:
        return False
    if not ALLOWED_PHONE_NUMBER_IDS:
        return True
    return phone_number_id in ALLOWED_PHONE_NUMBER_IDS


def _message_body(message):
    message_type = str(message.get("type") or "unknown")
    if message_type == "text":
        return str((message.get("text") or {}).get("body") or "").strip()
    if message_type in ("image", "video", "document"):
        media = message.get(message_type) or {}
        return str(media.get("caption") or "").strip()
    if message_type == "button":
        return str((message.get("button") or {}).get("text") or "").strip()
    if message_type == "interactive":
        interactive = message.get("interactive") or {}
        for key in ("button_reply", "list_reply"):
            reply = interactive.get(key) or {}
            if reply:
                return str(reply.get("title") or reply.get("id") or "").strip()
    return ""


def _post_staff_event(payload):
    if not STAFF_EVENT_KEY or not STAFF_EVENT_URL:
        return False
    try:
        response = requests.post(
            STAFF_EVENT_URL,
            json=payload,
            headers={"X-WhatsApp-Bridge-Key": STAFF_EVENT_KEY},
            timeout=12,
        )
        return response.ok
    except requests.RequestException:
        return False


def _forward_lead(*, contact_name, wa_id, text, message_id, phone_number_id, display_phone_number):
    if not STAFF_LEAD_TOKEN:
        return False
    lead_payload = {
        "channel": "whatsapp",
        "source": "whatsapp",
        "full_name": contact_name or "WhatsApp",
        "phone": "+" + wa_id if wa_id and not wa_id.startswith("+") else wa_id,
        "message": text,
        "external_id": message_id,
        "metadata": {
            "whatsapp_phone_number_id": phone_number_id,
            "whatsapp_display_phone_number": display_phone_number,
        },
    }
    try:
        response = requests.post(
            STAFF_LEAD_URL,
            json=lead_payload,
            headers={"X-Lead-Token": STAFF_LEAD_TOKEN},
            timeout=12,
        )
        return response.ok
    except requests.RequestException:
        return False


@app.get("/")
def index():
    return jsonify({
        "service": "Greenlife WhatsApp Bridge",
        "status": "ready",
        "multi_number": True,
        "health": "/health",
        "webhook": "/webhook",
    })


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "greenlife-whatsapp-bridge",
        "multi_number": True,
        "configured": bool(VERIFY_TOKEN and ACCESS_TOKEN),
        "signature_verification": bool(APP_SECRET),
        "staff_events": bool(STAFF_EVENT_KEY),
        "allowed_numbers": len(ALLOWED_PHONE_NUMBER_IDS),
    })


@app.get("/webhook")
def verify_webhook():
    mode = request.args.get("hub.mode", "")
    token = request.args.get("hub.verify_token", "")
    challenge = request.args.get("hub.challenge", "")
    if mode == "subscribe" and VERIFY_TOKEN and hmac.compare_digest(token, VERIFY_TOKEN):
        return challenge, 200, {"Content-Type": "text/plain"}
    return "Forbidden", 403


@app.post("/webhook")
def receive_webhook():
    raw = request.get_data() or b""

    if APP_SECRET:
        supplied = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            APP_SECRET.encode("utf-8"), raw, hashlib.sha256
        ).hexdigest()
        if not supplied or not hmac.compare_digest(supplied, expected):
            return jsonify({"ok": False, "error": "invalid_signature"}), 403

    try:
        payload = json.loads(raw.decode("utf-8") or "{}")
    except (UnicodeDecodeError, json.JSONDecodeError):
        return jsonify({"ok": False, "error": "invalid_json"}), 400

    stored = 0
    forwarded_leads = 0
    statuses = 0

    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value") or {}
            metadata = value.get("metadata") or {}
            phone_number_id = str(metadata.get("phone_number_id") or "").strip()
            display_phone_number = str(metadata.get("display_phone_number") or "").strip()

            if phone_number_id and not _allowed_phone_number_id(phone_number_id):
                continue

            contacts = value.get("contacts") or []
            contact_name = ""
            if contacts:
                profile = contacts[0].get("profile") or {}
                contact_name = str(profile.get("name") or "").strip()

            for message in value.get("messages") or []:
                wa_id = str(message.get("from") or "").strip()
                message_id = str(message.get("id") or "").strip()
                message_type = str(message.get("type") or "unknown").strip()
                body = _message_body(message)

                if _post_staff_event({
                    "event_type": "message",
                    "phone_number_id": phone_number_id,
                    "display_phone_number": display_phone_number,
                    "contact_phone": "+" + wa_id if wa_id and not wa_id.startswith("+") else wa_id,
                    "contact_name": contact_name,
                    "message_id": message_id,
                    "message_type": message_type,
                    "body": body,
                    "status": "received",
                    "metadata": {
                        "timestamp": message.get("timestamp"),
                    },
                }):
                    stored += 1

                if wa_id and _forward_lead(
                    contact_name=contact_name,
                    wa_id=wa_id,
                    text=body,
                    message_id=message_id,
                    phone_number_id=phone_number_id,
                    display_phone_number=display_phone_number,
                ):
                    forwarded_leads += 1

            for status in value.get("statuses") or []:
                status_name = str(status.get("status") or "").strip()
                if status_name not in {"sent", "delivered", "read", "failed"}:
                    continue
                if _post_staff_event({
                    "event_type": "status",
                    "phone_number_id": phone_number_id,
                    "display_phone_number": display_phone_number,
                    "message_id": str(status.get("id") or "").strip(),
                    "status": status_name,
                    "metadata": {
                        "timestamp": status.get("timestamp"),
                        "recipient_id": status.get("recipient_id"),
                        "errors": status.get("errors") or [],
                    },
                }):
                    statuses += 1

    return jsonify({
        "ok": True,
        "stored": stored,
        "forwarded_leads": forwarded_leads,
        "statuses": statuses,
    }), 200


@app.post("/send-text")
def send_text():
    if not _authorized_bridge_call():
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    if not ACCESS_TOKEN:
        return jsonify({"ok": False, "error": "access_token_not_configured"}), 503

    data = request.get_json(silent=True) or {}
    to = str(data.get("to") or "").strip()
    body = str(data.get("text") or "").strip()
    phone_number_id = str(
        data.get("phone_number_id") or DEFAULT_PHONE_NUMBER_ID or ""
    ).strip()
    outbound_mode = str(data.get("outbound_mode") or "manual").strip().lower()
    if outbound_mode not in {"manual", "automation", "ai", "system"}:
        outbound_mode = "manual"

    if not to or not body:
        return jsonify({"ok": False, "error": "to_and_text_required"}), 400
    if not phone_number_id:
        return jsonify({"ok": False, "error": "phone_number_id_required"}), 400
    if not _allowed_phone_number_id(phone_number_id):
        return jsonify({"ok": False, "error": "phone_number_id_not_allowed"}), 403

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{phone_number_id}/messages"
    try:
        response = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {ACCESS_TOKEN}",
                "Content-Type": "application/json",
            },
            json={
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": body},
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return jsonify({
            "ok": False,
            "error": "meta_network_error",
            "detail": f"{type(exc).__name__}: {exc}",
        }), 502

    try:
        upstream = response.json()
    except ValueError:
        upstream = {"raw": response.text[:2000]}

    if response.ok:
        messages = upstream.get("messages") or []
        message_id = str(messages[0].get("id") or "").strip() if messages else ""
        _post_staff_event({
            "event_type": "outbound_message",
            "phone_number_id": phone_number_id,
            "contact_phone": to,
            "contact_name": "",
            "message_id": message_id,
            "message_type": "text",
            "body": body,
            "status": "sent",
            "outbound_mode": outbound_mode,
        })

    return jsonify({
        "ok": response.ok,
        "upstream_status": response.status_code,
        "body": upstream,
    }), (200 if response.ok else 502)
