from __future__ import annotations

import re

_SENSITIVE_KEY_PATTERN = re.compile(r"(key|token|secret|password|passwd|credential|auth)", re.IGNORECASE)
_REDACTED = "***REDACTED***"


def redact_event_payload(payload: dict) -> dict:
    return {k: _redact_value(k, v) for k, v in payload.items()}


def _redact_value(key: str, value):
    if _SENSITIVE_KEY_PATTERN.search(key):
        return _REDACTED
    if isinstance(value, dict):
        return redact_event_payload(value)
    return value
