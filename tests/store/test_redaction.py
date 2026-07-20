from foundry.store.redaction import redact_event_payload


def test_redacts_sensitive_keys_case_insensitively():
    payload = {"api_key": "sk-abc123", "Token": "xyz", "note": "fine"}
    redacted = redact_event_payload(payload)
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["Token"] == "***REDACTED***"
    assert redacted["note"] == "fine"


def test_redacts_nested_dicts_and_lists():
    payload = {"tool_call": {"env": {"AWS_SECRET_ACCESS_KEY": "abc"}, "args": ["--password", "hunter2"]}}
    redacted = redact_event_payload(payload)
    assert redacted["tool_call"]["env"]["AWS_SECRET_ACCESS_KEY"] == "***REDACTED***"
    # list items aren't key/value pairs, so only dict keys drive redaction — the raw
    # list is passed through unless a later task adds value-pattern scanning.
    assert redacted["tool_call"]["args"] == ["--password", "hunter2"]


def test_leaves_non_sensitive_payload_untouched():
    payload = {"unit_id": "01J...", "status": "closed"}
    assert redact_event_payload(payload) == payload
