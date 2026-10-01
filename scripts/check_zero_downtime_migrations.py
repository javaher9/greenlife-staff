#!/usr/bin/env python3
import pathlib
import re
import subprocess
import sys

try:
    changed = subprocess.check_output(
        ["git", "diff", "--name-only", "HEAD^", "HEAD"],
        text=True,
    ).splitlines()
except subprocess.CalledProcessError:
    sys.exit(0)

migration_files = [
    pathlib.Path(p) for p in changed
    if re.match(r"^core/migrations/\d+.*\.py$", p)
]
if not migration_files:
    print("Zero-downtime migration gate: no new migration files.")
    sys.exit(0)

unsafe_ops = {
    "RemoveField": "removes a column while the old app may still use it",
    "DeleteModel": "drops a table while the old app may still use it",
    "RenameField": "renames a column before old workers are drained",
    "RenameModel": "renames a table before old workers are drained",
}

problems = []
for path in migration_files:
    text = path.read_text(encoding="utf-8")
    for op, reason in unsafe_ops.items():
        if f"migrations.{op}(" in text:
            problems.append(f"{path}: {op} — {reason}")

if problems:
    print("ERROR: destructive migration blocked by zero-downtime safety gate.", file=sys.stderr)
    for item in problems:
        print(" - " + item, file=sys.stderr)
    print(
        "Use an expand/contract migration: add the new schema first, deploy compatible code, "
        "then remove/rename old schema in a later maintenance release.",
        file=sys.stderr,
    )
    sys.exit(1)

print("Zero-downtime migration gate passed.")
