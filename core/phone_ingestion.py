"""Common verification for data posted by the phone system."""
from hmac import compare_digest
import os
from uuid import UUID


def phone_ingest_token(environment_name):
    token = os.environ.get(environment_name, '').strip()
    return token if len(token) >= 32 else ''


def authorized_feeder(request, token):
    scheme, _, supplied = request.headers.get('Authorization', '').partition(' ')
    return bool(token) and scheme.lower() == 'bearer' and compare_digest(supplied.encode(), token.encode())


def opaque_call_id(value):
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError
    call_id = UUID(value)
    if call_id.version not in (4, 5) or str(call_id) != value.lower():
        raise ValueError
    return call_id
