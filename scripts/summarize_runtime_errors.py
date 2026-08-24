#!/usr/bin/env python3
"""Print only aggregate exception classes from container logs.

The public CI log must never contain request bodies, usernames, or traceback
messages, so this intentionally discards every line except exception names.
"""
import collections
import re
import sys


text = sys.stdin.read()
classes = collections.Counter(re.findall(
    r'(?m)^(?:[\w.]+\.)?([A-Za-z_]\w*(?:Error|Exception)):',
    text,
))
internal_errors = len(re.findall(r'Internal Server Error:', text))
summary = ','.join(f'{name}:{count}' for name, count in sorted(classes.items())) or 'none'
print(f'Previous web runtime errors: internal_server_errors={internal_errors}, classes={summary}')
