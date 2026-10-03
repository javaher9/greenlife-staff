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
PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
GRAPH_VERSION = os.getenv("WHATSAPP_GRAPH_VERSION", "v26.0").strip()
STAFF_LEAD_URL = os.getenv(
    "STAFF_LEAD_URL",
    "https://staff.greenlifeclinics.com/api/integrations/leads/",
).strip()
STAFF_LEAD_TOKEN = os.getenv("STAFF_LEAD_TOKEN", "").strip()


@app.get("/")
def index():
    return jsonify({
        "service": "Greenlife WhatsApp Bridge",
        "status": "ready",
        "health": "/health",
        "webhook": "/webhook",
    })


@app.get("/health")
def health():
    return jsonify({
        "ok": True,
        "service": "greenlife-whatsapp-bridge",
        "configured": bool(VERIFY_TOKEN and ACCESS_TOKEN and PHONE_NUMBER_ID),
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

    forwarded = 0
    if STAFF_LEAD_TOKEN:
        try:
            for entry in payload.get("entry", []):
                for change in entry.get("changes", []):
                    value = change.get("value") or {}
                    contacts = value.get("contacts") or []
                    contact_name = ""
                    if contacts:
                        profile = contacts[0].get("profile") or {}
                        contact_name = str(profile.get("name") or "").strip()
                    for message in value.get("messages") or []:
                        wa_id = str(message.get("from") or "").strip()
                        if not wa_id:
                            continue
                        text = ""
                        if message.get("type") == "text":
                            text = str((message.get("text") or {}).get("body") or "").strip()
                        lead_payload = {
                            "channel": "whatsapp",
                            "source": "whatsapp",
                            "full_name": contact_name or "WhatsApp",
                            "phone": "+" + wa_id if not wa_id.startswith("+") else wa_id,
                            "message": text,
                            "external_id": str(message.get("id") or ""),
                        }
                        requests.post(
                            STAFF_LEAD_URL,
                            json=lead_payload,
                            headers={"X-Lead-Token": STAFF_LEAD_TOKEN},
                            timeout=12,
                        )
                        forwarded += 1
        except requests.RequestException:
            pass

    return jsonify({"ok": True, "forwarded": forwarded}), 200


@app.post("/send-text")
def send_text():
    api_key = os.getenv("BRIDGE_API_KEY", "").strip()
    supplied = request.headers.get("X-Bridge-Key", "").strip()
    if not api_key or not supplied or not hmac.compare_digest(api_key, supplied):
        return jsonify({"ok": False, "error": "unauthorized"}), 401

    if not ACCESS_TOKEN or not PHONE_NUMBER_ID:
        return jsonify({"ok": False, "error": "not_configured"}), 503

    data = request.get_json(silent=True) or {}
    to = str(data.get("to") or "").strip()
    body = str(data.get("text") or "").strip()
    if not to or not body:
        return jsonify({"ok": False, "error": "to_and_text_required"}), 400

    url = f"https://graph.facebook.com/{GRAPH_VERSION}/{PHONE_NUMBER_ID}/messages"
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
        payload = response.json()
    except ValueError:
        payload = {"raw": response.text[:2000]}
    return jsonify({
        "ok": response.ok,
        "upstream_status": response.status_code,
        "body": payload,
    }), (200 if response.ok else 502)
