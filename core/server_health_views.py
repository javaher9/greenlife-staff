import glob
import os
import shutil
import time
from functools import wraps
from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render


def _is_server_health_admin(user):
    return bool(
        getattr(user, "is_authenticated", False)
        and (
            getattr(user, "is_superuser", False)
            or (getattr(user, "username", "") or "").lower()
            in {name.lower() for name in settings.EXECUTIVE_USERNAMES}
        )
    )


def server_health_required(view_func):
    @wraps(view_func)
    @login_required
    def wrapper(request, *args, **kwargs):
        if not _is_server_health_admin(request.user):
            raise PermissionDenied("Server health access denied.")
        return view_func(request, *args, **kwargs)

    return wrapper


def _read_first_line(path):
    try:
        return Path(path).read_text(encoding="utf-8").strip().splitlines()[0]
    except (OSError, IndexError):
        return ""


def _read_cpu_totals():
    line = _read_first_line("/proc/stat")
    parts = line.split()
    if not parts or parts[0] != "cpu":
        return None
    try:
        values = [int(value) for value in parts[1:9]]
    except ValueError:
        return None
    if len(values) < 4:
        return None
    idle = values[3] + (values[4] if len(values) > 4 else 0)
    total = sum(values)
    return total, idle


def _read_cgroup_cpu_usage_usec():
    raw = Path("/sys/fs/cgroup/cpu.stat")
    if not raw.exists():
        return None
    try:
        for line in raw.read_text(encoding="utf-8").splitlines():
            key, value = line.split(None, 1)
            if key == "usage_usec":
                return int(value)
    except (OSError, ValueError):
        return None
    return None


def _cgroup_cpu_capacity():
    line = _read_first_line("/sys/fs/cgroup/cpu.max")
    if line:
        parts = line.split()
        if len(parts) == 2:
            quota, period = parts
            if quota != "max":
                try:
                    cpus = float(quota) / float(period)
                    if cpus > 0:
                        return cpus
                except (ValueError, ZeroDivisionError):
                    pass
    return float(os.cpu_count() or 1)


def _sample_cpu(sample_seconds=0.10):
    first = _read_cpu_totals()
    cgroup_first = _read_cgroup_cpu_usage_usec()
    started = time.monotonic()
    time.sleep(sample_seconds)
    elapsed = max(time.monotonic() - started, 0.001)
    second = _read_cpu_totals()
    cgroup_second = _read_cgroup_cpu_usage_usec()

    server_percent = None
    if first and second:
        total_delta = second[0] - first[0]
        idle_delta = second[1] - first[1]
        if total_delta > 0:
            server_percent = round(
                max(0.0, min(100.0, (total_delta - idle_delta) * 100.0 / total_delta)),
                1,
            )

    app_percent = None
    if cgroup_first is not None and cgroup_second is not None:
        usage_delta = max(0, cgroup_second - cgroup_first)
        capacity = max(_cgroup_cpu_capacity(), 0.01)
        app_percent = round(
            max(0.0, min(100.0, usage_delta / (elapsed * 1_000_000.0 * capacity) * 100.0)),
            1,
        )
    return server_percent, app_percent


def _memory_stats():
    values = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if ":" not in line:
                continue
            key, raw = line.split(":", 1)
            token = raw.strip().split()[0]
            values[key] = int(token) * 1024
    except (OSError, ValueError, IndexError):
        return None

    total = values.get("MemTotal")
    if not total:
        return None
    available = values.get("MemAvailable")
    if available is None:
        available = (
            values.get("MemFree", 0)
            + values.get("Buffers", 0)
            + values.get("Cached", 0)
        )
    used = max(0, total - available)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "available_bytes": available,
        "percent": round(used * 100.0 / total, 1),
    }


def _cgroup_memory_stats():
    try:
        current = int(_read_first_line("/sys/fs/cgroup/memory.current"))
    except ValueError:
        return None
    maximum_raw = _read_first_line("/sys/fs/cgroup/memory.max")
    if not maximum_raw or maximum_raw == "max":
        return {"used_bytes": current, "limit_bytes": None, "percent": None}
    try:
        maximum = int(maximum_raw)
    except ValueError:
        return None
    return {
        "used_bytes": current,
        "limit_bytes": maximum,
        "percent": round(current * 100.0 / maximum, 1) if maximum > 0 else None,
    }


def _disk_stats():
    try:
        usage = shutil.disk_usage("/")
    except OSError:
        return None
    used = usage.total - usage.free
    return {
        "total_bytes": usage.total,
        "used_bytes": used,
        "free_bytes": usage.free,
        "percent": round(used * 100.0 / usage.total, 1) if usage.total else 0.0,
    }


def _network_stats():
    received = 0
    sent = 0
    try:
        lines = Path("/proc/net/dev").read_text(encoding="utf-8").splitlines()[2:]
        for line in lines:
            if ":" not in line:
                continue
            interface, raw = line.split(":", 1)
            if interface.strip() == "lo":
                continue
            fields = raw.split()
            if len(fields) >= 9:
                received += int(fields[0])
                sent += int(fields[8])
    except (OSError, ValueError):
        return None
    return {"rx_bytes": received, "tx_bytes": sent}


def _uptime_seconds():
    try:
        return int(float(_read_first_line("/proc/uptime").split()[0]))
    except (ValueError, IndexError):
        return None


def _temperature_c():
    readings = []
    paths = list(glob.glob("/sys/class/thermal/thermal_zone*/temp"))
    paths += list(glob.glob("/sys/class/hwmon/hwmon*/temp*_input"))
    for path in paths:
        try:
            raw = float(_read_first_line(path))
        except ValueError:
            continue
        value = raw / 1000.0 if raw > 200 else raw
        if 0.0 < value < 125.0:
            readings.append(value)
    return round(max(readings), 1) if readings else None


def _database_health():
    started = time.perf_counter()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {
            "status": "ok",
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 1),
        }
    except Exception:
        return {"status": "error", "latency_ms": None}


@server_health_required
def server_health_dashboard(request):
    response = render(request, "core/server_health.html")
    response["Cache-Control"] = "no-store, private"
    response["Pragma"] = "no-cache"
    return response


@server_health_required
def server_health_api(request):
    cpu_percent, app_cpu_percent = _sample_cpu()
    try:
        load_1, load_5, load_15 = os.getloadavg()
    except (AttributeError, OSError):
        load_1 = load_5 = load_15 = None

    payload = {
        "ok": True,
        "sampled_at": int(time.time()),
        "server": {
            "cpu_percent": cpu_percent,
            "cpu_count": os.cpu_count() or 1,
            "memory": _memory_stats(),
            "disk": _disk_stats(),
            "load": {
                "one": round(load_1, 2) if load_1 is not None else None,
                "five": round(load_5, 2) if load_5 is not None else None,
                "fifteen": round(load_15, 2) if load_15 is not None else None,
            },
            "uptime_seconds": _uptime_seconds(),
            "temperature_c": _temperature_c(),
        },
        "app": {
            "cpu_percent": app_cpu_percent,
            "memory": _cgroup_memory_stats(),
        },
        "network": _network_stats(),
        "database": _database_health(),
        "notes": {
            "temperature": (
                "available"
                if _temperature_c() is not None
                else "VM/container does not expose a physical CPU temperature sensor."
            ),
            "network": "Network counters are for the application container namespace.",
        },
    }
    response = JsonResponse(payload)
    response["Cache-Control"] = "no-store, private, max-age=0"
    response["Pragma"] = "no-cache"
    return response
