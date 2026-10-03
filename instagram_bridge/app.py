import os
import socket

import requests
from flask import Flask, jsonify, request, Response

app = Flask(__name__)

INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID", "1521798383059885").strip()
ALLOWED_REDIRECT_URI = os.getenv(
    "INSTAGRAM_REDIRECT_URI",
    "https://staff.greenlifeclinics.com/api/instagram/callback/",
).strip()
STAFF_WEBHOOK_URL = os.getenv(
    "STAFF_WEBHOOK_URL",
    "https://staff.greenlifeclinics.com/api/instagram/webhook/",
).strip()
META_TOKEN_URL = "https://api.instagram.com/oauth/access_token"
META_GRAPH_BASE = "https://graph.instagram.com"


def _json_body(response):
    try:
        return response.json()
    except ValueError:
        return {"raw": response.text[:2000]}


@app.get("/health")
def health():
    return jsonify({"ok": True, "service": "greenlife-instagram-bridge"})


@app.get("/meta/dns-test")
def dns_test():
    results = {}
    for host in ("api.instagram.com", "graph.instagram.com", "www.instagram.com"):
        try:
            rows = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            results[host] = sorted({row[4][0] for row in rows})
        except Exception as exc:
            results[host] = {"error": f"{type(exc).__name__}: {exc}"}
    return jsonify(results)


@app.post("/meta/oauth-complete")
def oauth_complete():
    payload = request.get_json(silent=True) or {}
    code = str(payload.get("code") or "").strip()
    app_secret = str(payload.get("app_secret") or "").strip()
    app_id = str(payload.get("app_id") or INSTAGRAM_APP_ID).strip()
    redirect_uri = str(payload.get("redirect_uri") or ALLOWED_REDIRECT_URI).strip()

    if not code or not app_secret:
        return jsonify({"error": "missing code or app_secret"}), 400
    if app_id != INSTAGRAM_APP_ID:
        return jsonify({"error": "app_id not allowed"}), 400
    if redirect_uri != ALLOWED_REDIRECT_URI:
        return jsonify({"error": "redirect_uri not allowed"}), 400

    try:
        short_response = requests.post(
            META_TOKEN_URL,
            data={
                "client_id": app_id,
                "client_secret": app_secret,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
                "code": code,
            },
            timeout=20,
        )
    except requests.RequestException as exc:
        return jsonify({"error": "meta_network_error", "stage": "short_token", "detail": f"{type(exc).__name__}: {exc}"}), 502

    short = _json_body(short_response)
    if not short_response.ok:
        return jsonify({"error": "meta_http_error", "stage": "short_token", "upstream_status": short_response.status_code, "body": short}), 502

    token_payload = short
    if not short.get("access_token") and isinstance(short.get("data"), list) and len(short["data"]) == 1:
        token_payload = short["data"][0] if isinstance(short["data"][0], dict) else {}

    short_token = token_payload.get("access_token")
    user_id = str(token_payload.get("user_id") or token_payload.get("id") or "")
    if not short_token:
        return jsonify({"error": "meta_response_error", "stage": "short_token", "detail": "Meta did not return an access token.", "body": short}), 502

    token = short_token
    expires_in = 0
    try:
        long_response = requests.get(
            META_GRAPH_BASE + "/access_token",
            params={
                "grant_type": "ig_exchange_token",
                "client_secret": app_secret,
                "access_token": short_token,
            },
            timeout=20,
        )
        long_body = _json_body(long_response)
        if long_response.ok and long_body.get("access_token"):
            token = long_body["access_token"]
            expires_in = int(long_body.get("expires_in") or 0)
    except requests.RequestException:
        pass

    username = ""
    try:
        profile_response = requests.get(
            META_GRAPH_BASE + "/me",
            params={"fields": "user_id,username", "access_token": token},
            timeout=20,
        )
        profile = _json_body(profile_response)
        if profile_response.ok:
            user_id = str(profile.get("user_id") or profile.get("id") or user_id)
            username = str(profile.get("username") or "")
    except requests.RequestException:
        pass

    return jsonify({
        "ok": True,
        "access_token": token,
        "user_id": user_id,
        "username": username,
        "expires_in": expires_in,
    })


@app.route("/meta/webhook", methods=["GET", "POST"])
def meta_webhook():
    try:
        if request.method == "GET":
            upstream = requests.get(
                STAFF_WEBHOOK_URL,
                params=request.args,
                timeout=20,
                allow_redirects=False,
            )
        else:
            headers = {"Content-Type": request.headers.get("Content-Type", "application/json")}
            signature = request.headers.get("X-Hub-Signature-256")
            if signature:
                headers["X-Hub-Signature-256"] = signature
            upstream = requests.post(
                STAFF_WEBHOOK_URL,
                data=request.get_data(),
                headers=headers,
                timeout=20,
                allow_redirects=False,
            )
    except requests.RequestException as exc:
        return jsonify({"ok": False, "error": "staff_upstream_error", "detail": f"{type(exc).__name__}: {exc}"}), 502

    passthrough_headers = {}
    if upstream.headers.get("Content-Type"):
        passthrough_headers["Content-Type"] = upstream.headers["Content-Type"]
    return Response(upstream.content, status=upstream.status_code, headers=passthrough_headers)


@app.get("/")
def index():
    return jsonify({
        "service": "Greenlife Instagram Bridge",
        "status": "ready",
        "health": "/health",
        "webhook": "/meta/webhook",
    })
