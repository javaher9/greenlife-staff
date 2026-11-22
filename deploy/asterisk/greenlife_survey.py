#!/usr/bin/env python3
"""Send an optional Asterisk DTMF survey result to Staff over HTTPS."""

import json
import re
import sys
import uuid
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener


CONFIG_PATH = Path("/etc/asterisk/greenlife-survey.json")
RATINGS_PATH = "/api/private/phone-center/ratings/"
KEY = re.compile(r"[A-Za-z0-9_-]{1,64}")
NODE = re.compile(r"[A-Za-z0-9._-]{1,64}")
LINKED_ID = re.compile(r"(?:[A-Za-z0-9._-]{1,64}-)?[0-9]{8,16}\.[0-9]{1,16}")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_config():
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError
    url = config.get("url", "")
    token = config.get("token", "")
    node = config.get("node_id", "")
    operators = config.get("operators")
    if not all(isinstance(value, str) for value in (url, token, node)):
        raise ValueError
    address = urlsplit(url)
    if (
        address.scheme != "https"
        or not address.hostname
        or address.username is not None
        or address.path != RATINGS_PATH
        or address.query
        or address.fragment
        or not re.fullmatch(r"[!-~]{1,2048}", url)
        or not re.fullmatch(r"[!-~]{32,512}", token)
        or not NODE.fullmatch(node)
        or not isinstance(operators, dict)
    ):
        raise ValueError
    return config


def consume_agi_environment(stream):
    for _ in range(64):
        line = stream.readline(4096)
        if line in ("\n", "\r\n"):
            return True
        if not line.endswith("\n"):
            return False
    return False


def main():
    if not consume_agi_environment(sys.stdin) or len(sys.argv) != 4:
        return 1
    operator, linked_id, score = sys.argv[1:]
    if not KEY.fullmatch(operator) or not LINKED_ID.fullmatch(linked_id) or score not in {"1", "2", "3", "4", "5"}:
        return 1

    try:
        config = read_config()
    except (OSError, ValueError):
        print("Staff survey configuration unavailable or invalid", file=sys.stderr)
        return 1
    profile_id = config["operators"].get(operator)
    if type(profile_id) is not int or not 0 < profile_id < 2**63:
        print("Staff survey operator is not mapped", file=sys.stderr)
        return 1

    call_id = uuid.uuid5(uuid.NAMESPACE_URL, f"greenlife:staff:phone-rating:v1:{config['node_id']}:{linked_id}")
    request = Request(
        config["url"],
        json.dumps({"call_id": str(call_id), "operator_id": profile_id, "score": int(score)}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config['token']}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        # Never forward the bearer token on redirects or through environment-provided proxies.
        opener = build_opener(NoRedirect(), ProxyHandler({}))
        with opener.open(request, timeout=2) as response:
            if response.status in (200, 201):
                return 0
    except HTTPError as error:
        print(f"Staff survey rejected (HTTP {error.code})", file=sys.stderr)
        return 1
    except (URLError, OSError, ValueError):
        pass
    print("Staff survey delivery failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
