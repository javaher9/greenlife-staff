"""Asterisk supervision for explicitly enrolled Staff accounts and PBX call legs."""

from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import timedelta
import ipaddress
import json
import os
import re
import socket
import ssl
import time
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import DatabaseError, transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import AuditLog


MODES = {
    "listen": ("شنود زنده", ""),
    "whisper": ("راهنمایی خصوصی", "w"),
    "join": ("ورود به مکالمه", "B"),
}
AUDIT_ACTION = "phone_supervision_requested"
SPY_GROUP = "greenlife-supervision"
_EXTENSION = re.compile(r"[0-9]{2,10}")
_CHANNEL = re.compile(r"PJSIP/([0-9]{2,10})-[0-9a-fA-F]+")
_PBX_ID = re.compile(r"[A-Za-z0-9_.:-]{1,79}")
_REQUEST_ID = re.compile(r"[0-9a-f]{64}")
_PRIVATE_NETWORKS = tuple(
    ipaddress.ip_network(network)
    for network in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "127.0.0.0/8", "fc00::/7", "::1/128")
)


class SupervisionError(Exception):
    def __init__(self, code, message, status):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


class _PBXUnavailable(Exception):
    pass


@dataclass(frozen=True)
class _Connection:
    host: str
    port: int
    username: str = field(repr=False)
    secret: str = field(repr=False)
    ca_file: str | None
    contexts: frozenset[str]
    supervisors: dict[str, str]
    operators: dict[str, str]


def _configuration():
    raw = os.environ.get("GREENLIFE_SUPERVISION_AMI", "")
    if not raw:
        raise SupervisionError("disabled", "اتصال نظارت زنده به مرکز تلفن فعال نشده است.", 503)
    try:
        config = json.loads(raw)
        supervisors = {name.casefold(): number for name, number in config["supervisors"].items()}
        operators = config["operators"]
        contexts = config["contexts"]
        host, username, secret = config["host"], config["username"], config["secret"]
        port = config.get("port", 5039)
        ca_file = config.get("ca_file")
        if (
            not isinstance(host, str) or not re.fullmatch(r"[A-Za-z0-9.:\-]{1,253}", host)
            or type(port) is not int or not 0 < port <= 65535
            or not re.fullmatch(r"[ -~]{1,120}", username)
            or not re.fullmatch(r"[ -~]{1,250}", secret)
            or (ca_file is not None and not isinstance(ca_file, str))
            or not isinstance(contexts, list) or not contexts
            or not all(_PBX_ID.fullmatch(context) for context in contexts)
            or not supervisors or not operators or not isinstance(operators, dict)
            or not all(name and _EXTENSION.fullmatch(ext) for name, ext in supervisors.items())
            or len(supervisors) != len(config["supervisors"])
            or len(set(supervisors.values())) != len(supervisors)
            or set(supervisors.values()).intersection(operators)
            or not all(
                _EXTENSION.fullmatch(ext) and isinstance(name, str) and 0 < len(name.strip()) <= 80
                for ext, name in operators.items()
            )
        ):
            raise ValueError
        return _Connection(host, port, username, secret, ca_file, frozenset(contexts), supervisors, operators)
    except (KeyError, TypeError, ValueError, AttributeError):
        raise SupervisionError("disabled", "تنظیمات اتصال نظارت زنده نیاز به بررسی دارد.", 503) from None


def _supervisor_extension(config, user):
    extension = config.supervisors.get(user.get_username().casefold())
    if not (user.is_authenticated and user.is_active and extension):
        raise SupervisionError("not_enrolled", "داخلی نظارت برای حساب شما تعریف نشده است.", 403)
    return extension


class _AMI:
    """Limited AMI framing over a verified private TLS connection."""

    def __init__(self, connection, reader, deadline):
        self.connection = connection
        self.reader = reader
        self.deadline = deadline

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise _PBXUnavailable
        return remaining

    def _line(self):
        self.connection.settimeout(self._remaining())
        value = self.reader.readline(4097)
        if not value.endswith(b"\r\n") or len(value) > 4096:
            raise _PBXUnavailable
        return value[:-2]

    def _frame(self):
        result = {}
        for _ in range(64):
            line = self._line()
            if not line:
                return result
            key, separator, value = line.partition(b":")
            if not separator:
                raise _PBXUnavailable
            result[key.decode("ascii").lower()] = value.strip().decode("utf-8", errors="replace")
        raise _PBXUnavailable

    def _send(self, action, fields):
        request_id = uuid4().hex
        headers = {"Action": action, "ActionID": request_id, **fields}
        self.connection.settimeout(self._remaining())
        self.connection.sendall(
            ("".join(f"{key}: {value}\r\n" for key, value in headers.items()) + "\r\n").encode("ascii")
        )
        return request_id

    def _received(self, request_id, key):
        for _ in range(32):
            message = self._frame()
            if message.get("actionid") == request_id and key in message:
                return message
        raise _PBXUnavailable

    def command(self, action, **fields):
        response = self._received(self._send(action, fields), "response")
        if response.get("response") != "Success":
            raise _PBXUnavailable
        return response

    def channels(self):
        request_id = self._send("CoreShowChannels", {})
        if self._received(request_id, "response").get("response") != "Success":
            raise _PBXUnavailable
        channels = []
        for _ in range(1500):
            event = self._received(request_id, "event")
            if event["event"] == "CoreShowChannelsComplete":
                if event.get("listitems") != str(len(channels)):
                    raise _PBXUnavailable
                return channels
            if event["event"] == "CoreShowChannel":
                channels.append(event)
        raise _PBXUnavailable

    def scoped_to_supervision(self, channel):
        response = self.command("Getvar", Channel=channel, Variable="SPYGROUP")
        return SPY_GROUP in response.get("value", "").split(":")

    def originate(self, supervisor, operator, unique_id, mode):
        flags = f"uEbSx(*)g({SPY_GROUP})e(PJSIP/{operator}){MODES[mode][1]}"
        self.command(
            "Originate",
            Channel=f"PJSIP/{supervisor}",
            Application="ChanSpy",
            Data=f"{unique_id},{flags}",
            Timeout="18000",
            Async="true",
            Account=SPY_GROUP,
        )


def _private_address(address):
    addr = ipaddress.ip_address(address)
    addr = getattr(addr, "ipv4_mapped", None) or addr
    return any(addr in network for network in _PRIVATE_NETWORKS)


@contextmanager
def _open_ami(config):
    deadline = time.monotonic() + 5
    try:
        addresses = socket.getaddrinfo(config.host, config.port, type=socket.SOCK_STREAM, proto=socket.IPPROTO_TCP)
        if not addresses or not all(_private_address(address[4][0]) for address in addresses):
            raise _PBXUnavailable
        family, kind, protocol, _, address = addresses[0]
        with socket.socket(family, kind, protocol) as connection:
            connection.settimeout(min(2, max(0.1, deadline - time.monotonic())))
            connection.connect(address)
            tls = ssl.create_default_context(cafile=config.ca_file)
            with tls.wrap_socket(connection, server_hostname=config.host) as secure, secure.makefile("rb") as reader:
                ami = _AMI(secure, reader, deadline)
                if not ami._line().startswith(b"Asterisk Call Manager/"):
                    raise _PBXUnavailable
                ami.command("Login", Username=config.username, Secret=config.secret, Events="off")
                yield ami
    except (OSError, UnicodeError, ValueError):
        raise _PBXUnavailable from None


def _elapsed(duration):
    match = re.fullmatch(r"([0-9]{1,4}):([0-5][0-9]):([0-5][0-9])", duration)
    if not match:
        return None
    hours, minutes, seconds = map(int, match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _accessible_calls(ami, config, user, channels):
    participants = Counter(channel.get("bridgeid") for channel in channels if channel.get("bridgeid"))
    for channel in channels:
        pbx_name = channel.get("channel", "")
        endpoint = _CHANNEL.fullmatch(pbx_name)
        if not endpoint or endpoint[1] not in config.operators:
            continue
        bridge_id = channel.get("bridgeid", "")
        unique_id = channel.get("uniqueid", "")
        if (
            channel.get("channelstatedesc") != "Up"
            or channel.get("context") not in config.contexts
            or participants[bridge_id] != 2
            or not _PBX_ID.fullmatch(bridge_id)
            or not _PBX_ID.fullmatch(unique_id)
            or not ami.scoped_to_supervision(pbx_name)
        ):
            continue
        token = salted_hmac(
            "phone-supervision.v1",
            f"{user.pk}|{pbx_name}|{unique_id}|{bridge_id}",
            algorithm="sha256",
        ).hexdigest()
        yield {
            "id": token,
            "operator": config.operators[endpoint[1]],
            "extension": endpoint[1],
            "elapsed_seconds": _elapsed(channel.get("duration", "")),
        }, unique_id


def _supervisor_busy(channels, extension):
    return any(channel.get("channel", "").startswith(f"PJSIP/{extension}-") for channel in channels)


def supervision_snapshot(user):
    result = {
        "available": False,
        "can_start": False,
        "modes": [{"id": mode, "label": label} for mode, (label, _) in MODES.items()],
        "calls": [],
        "reason": "",
    }
    try:
        config = _configuration()
        supervisor = _supervisor_extension(config, user)
        with _open_ami(config) as ami:
            channels = ami.channels()
            calls = [call for call, _ in _accessible_calls(ami, config, user, channels)]
        busy = _supervisor_busy(channels, supervisor)
        result.update(available=True, can_start=not busy, calls=calls)
        if busy:
            result["reason"] = "داخلی نظارت در حال استفاده است. برای پایان، تماس نظارت را از گوشی قطع کنید."
    except SupervisionError as exc:
        result["reason"] = exc.message
    except _PBXUnavailable:
        result["reason"] = "ارتباط زنده با مرکز تلفن در دسترس نیست."
    return result


def _record_request(user, call_id, extension, mode):
    try:
        with transaction.atomic():
            get_user_model().objects.select_for_update().only("pk").get(pk=user.pk)
            if AuditLog.objects.filter(
                actor=user,
                action=AUDIT_ACTION,
                created_at__gte=timezone.now() - timedelta(seconds=20),
            ).exists():
                raise SupervisionError("busy", "درخواست اخیر نظارت در حال انجام است.", 409)
            AuditLog.objects.create(
                actor=user,
                action=AUDIT_ACTION,
                path="/management/phone-center/",
                method="POST",
                object_type="supervised_call",
                object_id=call_id,
                summary="درخواست نظارت زنده",
                metadata={"mode": mode, "extension": extension},
            )
    except DatabaseError:
        raise SupervisionError("audit_unavailable", "ثبت امن درخواست نظارت در دسترس نیست.", 503) from None


def start_supervision(user, call_id, mode):
    if not isinstance(mode, str) or mode not in MODES or not isinstance(call_id, str) or not _REQUEST_ID.fullmatch(call_id):
        raise SupervisionError("invalid", "تماس یا حالت نظارت معتبر نیست.", 400)
    config = _configuration()
    supervisor = _supervisor_extension(config, user)
    try:
        with _open_ami(config) as ami:
            channels = ami.channels()
            if _supervisor_busy(channels, supervisor):
                raise SupervisionError("busy", "داخلی نظارت در حال استفاده است.", 409)
            for call, unique_id in _accessible_calls(ami, config, user, channels):
                if constant_time_compare(call["id"], call_id):
                    _record_request(user, call_id, call["extension"], mode)
                    ami.originate(supervisor, call["extension"], unique_id, mode)
                    return {
                        "accepted": True,
                        "message": "مرکز تلفن درخواست را پذیرفت. برای شروع نظارت، تماس داخلی خودتان را پاسخ دهید.",
                    }
            raise SupervisionError("stale", "این مکالمه دیگر در فهرست تماس‌های مجاز فعال نیست.", 409)
    except _PBXUnavailable:
        raise SupervisionError(
            "pbx_unavailable",
            "تأیید درخواست از مرکز تلفن ممکن نشد. وضعیت داخلی خودتان را بررسی کنید.",
            503,
        ) from None
