import pytest

from foundry.playbook.schema import LoopSpec, PlaybookSpec, StepSpec


@pytest.mark.asyncio
async def test_schema_help_covers_every_real_field(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/playbooks/schema-help")
    assert resp.status_code == 200
    body = resp.json()["data"]

    by_model: dict[str, set[str]] = {}
    for entry in body:
        by_model.setdefault(entry["model"], set()).add(entry["field"])

    assert by_model["PlaybookSpec"] == set(PlaybookSpec.model_fields.keys())
    assert by_model["StepSpec"] == set(StepSpec.model_fields.keys())
    assert by_model["LoopSpec"] == set(LoopSpec.model_fields.keys())


@pytest.mark.asyncio
async def test_schema_help_every_field_has_a_description(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/playbooks/schema-help")
    body = resp.json()["data"]
    for entry in body:
        assert entry["description"], f"{entry['model']}.{entry['field']} has no description"


@pytest.mark.asyncio
async def test_schema_help_reflects_real_required_and_default_values(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/playbooks/schema-help")
    body = resp.json()["data"]
    by_key = {(e["model"], e["field"]): e for e in body}

    steps_field = by_key[("PlaybookSpec", "steps")]
    assert steps_field["required"] is True
    assert steps_field["default"] is None

    gate_field = by_key[("StepSpec", "gate")]
    assert gate_field["required"] is False
    assert gate_field["default"] == "'none'"

    writes_field = by_key[("StepSpec", "writes")]
    assert writes_field["required"] is False
    assert writes_field["default"] == "False"
