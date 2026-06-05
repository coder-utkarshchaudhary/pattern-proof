"""
Network Inspector: captures HTTP requests/responses, redacts secrets/PII.
Stores events in MongoDB network_events collection.
"""
import hashlib
import json
import re
import uuid
from datetime import datetime
from db.nosql import network_col
from utils.logger import get_logger

logger = get_logger(__name__)

# Patterns to redact from headers and bodies
_REDACT_HEADERS = {"authorization", "cookie", "set-cookie", "x-api-key", "x-auth-token"}
_REDACT_PATTERNS = [
    re.compile(r'"(password|token|secret|api_key|apikey|access_token|refresh_token)"\s*:\s*"[^"]*"', re.I),
    re.compile(r'Bearer\s+[A-Za-z0-9\-._~+/]+=*', re.I),
]

def redact_headers(headers: dict) -> dict:
    return {k: "[REDACTED]" if k.lower() in _REDACT_HEADERS else v for k, v in headers.items()}

def redact_body(body: str) -> str:
    for pattern in _REDACT_PATTERNS:
        body = pattern.sub(lambda m: m.group(0).split(":")[0] + ': "[REDACTED]"', body)
    return body

async def record_network_event(
    audit_id: str, state_id: str | None,
    url: str, method: str, status_code: int,
    request_headers: dict, response_headers: dict,
    request_body: str | None, response_body: str | None,
) -> dict:
    """Store a redacted network event in MongoDB."""
    redacted_req = redact_body(request_body or "")
    redacted_resp = redact_body(response_body or "")
    doc = {
        "_id": str(uuid.uuid4()),
        "audit_id": audit_id,
        "state_id": state_id,
        "url": url,
        "method": method,
        "status_code": status_code,
        "request_hash": hashlib.sha256((request_body or "").encode()).hexdigest(),
        "response_hash": hashlib.sha256((response_body or "").encode()).hexdigest(),
        "headers_redacted": redact_headers({**request_headers, **response_headers}),
        "redacted_request_body": redacted_req[:5000],  # truncate large bodies
        "redacted_response_body": redacted_resp[:5000],
        "created_at": datetime.utcnow().isoformat(),
    }
    await network_col().insert_one(doc)
    return doc
