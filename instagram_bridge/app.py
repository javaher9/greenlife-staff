import os
import socket
from urllib.parse import urlparse

import requests
from flask import Flask, jsonify, request

app = Flask(__name__)

INSTAGRAM_APP_ID = os.getenv("INSTAGRAM_APP_ID", "1521798383059885").strip()
ALLOWED_REDIRECT_URI = os.getenv(
    "INSTAGRAM_REDIRECT_URI",
    "https://staff.greenlifeclinics.com/api/instagram/callback/",
).strip()
META_TOKEN_URL = "https://api.instagram.com/oauth/access_token"


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


@app.post("/meta/token-exchange")
def token_exchange():
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
        response = requests.post(
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
        return jsonify({
            "error": "meta_network_error",
            "detail": f"{type(exc).__name__}: {exc}",
        }), 502

    content_type = response.headers.get("content-type", "")
    try:
        body = response.json()
    except ValueError:
        body = {"raw": response.text[:2000]}

    return jsonify({
        "upstream_status": response.status_code,
        "content_type": content_type,
        "body": body,
    }), response.status_code


@app.get("/")
def index():
    return jsonify({
        "service": "Greenlife Instagram Bridge",
        "status": "ready",
        "health": "/health",
    })
