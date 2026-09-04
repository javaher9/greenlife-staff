#!/usr/bin/env python3
"""Harden server-owned production settings without printing secret values."""

import os
import secrets
import sys
from pathlib import Path


WEAK_SECRET_KEYS = {
    "",
    "change-me",
    "dev-only-change-me",
    "replace-with-a-long-random-value",
    "replace-with-a-long-random-value-generated-on-the-server",
}


def read_values(lines):
    values = {}
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        values[key.strip()] = value.strip().strip("\"'")
    return values


def set_value(lines, key, value):
    prefix = f"{key}="
    indexes = [index for index, line in enumerate(lines) if line.lstrip().startswith(prefix)]
    replacement = f"{key}={value}\n"
    if indexes:
        for index in indexes:
            lines[index] = replacement
    else:
        if lines and lines[-1].strip():
            lines.append("\n")
        lines.append(replacement)


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: harden_env.py PATH_TO_ENV")

    env_path = Path(sys.argv[1]).resolve()
    lines = env_path.read_text(encoding="utf-8").splitlines(keepends=True)
    values = read_values(lines)
    changed = []

    if values.get("DEBUG", "0") != "1":
        if values.get("SECRET_KEY", "") in WEAK_SECRET_KEYS:
            set_value(lines, "SECRET_KEY", secrets.token_urlsafe(64))
            changed.append("SECRET_KEY")

        for key, value in (
            ("DISABLE_CSRF", "0"),
            ("CSRF_COOKIE_SECURE", "1"),
            ("SESSION_COOKIE_SECURE", "1"),
            ("ALLOWED_HOSTS", "staff.greenlifeclinics.com,localhost,127.0.0.1"),
            ("CSRF_TRUSTED_ORIGINS", "https://staff.greenlifeclinics.com"),
        ):
            if values.get(key) != value:
                set_value(lines, key, value)
                changed.append(key)

    temp_path = env_path.with_name(f".{env_path.name}.tmp")
    temp_path.write_text("".join(lines), encoding="utf-8")
    os.chmod(temp_path, 0o600)
    os.replace(temp_path, env_path)
    os.chmod(env_path, 0o600)

    if changed:
        print("Production environment hardened: " + ", ".join(changed))
    else:
        print("Production environment already hardened.")


if __name__ == "__main__":
    main()
