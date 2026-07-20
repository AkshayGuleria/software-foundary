import pytest


async def _create_run(client, playbook_path: str) -> tuple[str, str]:
    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]
    run_resp = await client.post(
        "/api/runs", json={"project_id": project_id, "playbook_path": playbook_path, "title": "gate test run"}
    )
    return project_id, run_resp.json()["data"]["id"]


@pytest.mark.asyncio
async def test_full_plan_approve_implement_reject_rework_approve_cycle(api_client):
    """The M1 exit criterion, driven entirely through the HTTP API (standing in
    for the browser) — no direct Store/Orchestrator calls below this line."""
    client, store, scheduler = api_client
    _project_id, run_id = await _create_run(client, "tests/orchestrator/fixtures/gated_demo.toml")

    for _ in range(5):
        await scheduler.tick_all_once()

    detail = (await client.get(f"/api/runs/{run_id}")).json()["data"]
    gate = next(g for g in detail["gates"] if g["decision"] == "pending")

    # Reject with feedback — the rework loop.
    reject_resp = await client.post(
        f"/api/gates/{gate['id']}/decide",
        json={"decision": "rejected", "feedback_chips": ["incomplete"], "feedback_text": "add more detail"},
    )
    assert reject_resp.status_code == 200

    for _ in range(5):
        await scheduler.tick_all_once()

    detail = (await client.get(f"/api/runs/{run_id}")).json()["data"]
    a_task = next(u for u in detail["units"] if u["step_id"] == "a")
    assert a_task["status"] == "blocked"  # re-dispatched, produced a second artifact, gated again
    new_gate = next(g for g in detail["gates"] if g["decision"] == "pending")
    assert new_gate["id"] != gate["id"]

    # Approve the reworked artifact.
    approve_resp = await client.post(f"/api/gates/{new_gate['id']}/decide", json={"decision": "approved"})
    assert approve_resp.status_code == 200

    for _ in range(5):
        await scheduler.tick_all_once()

    run_row = await store.get_run(run_id)
    assert run_row.status == "closed"

    artifacts_resp = await client.get(f"/api/runs/{run_id}/artifacts")
    a_artifacts = sorted(
        [a for a in artifacts_resp.json()["data"] if a["kind"] == "a_artifact"], key=lambda a: a["version"]
    )
    assert [a["version"] for a in a_artifacts] == [1, 2]  # rework really did increment the version


@pytest.mark.asyncio
async def test_decide_missing_gate_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/gates/does-not-exist/decide", json={"decision": "approved"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_decide_already_decided_gate_returns_409(api_client):
    client, store, scheduler = api_client
    _project_id, run_id = await _create_run(client, "tests/orchestrator/fixtures/gated_demo.toml")

    for _ in range(5):
        await scheduler.tick_all_once()

    gates = await store.list_gates_for_run(run_id)
    gate_id = gates[0].id

    first = await client.post(f"/api/gates/{gate_id}/decide", json={"decision": "approved"})
    assert first.status_code == 200

    second = await client.post(f"/api/gates/{gate_id}/decide", json={"decision": "approved"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_decide_rejects_invalid_decision_value(api_client):
    client, store, scheduler = api_client
    _project_id, run_id = await _create_run(client, "tests/orchestrator/fixtures/gated_demo.toml")
    for _ in range(5):
        await scheduler.tick_all_once()
    gates = await store.list_gates_for_run(run_id)

    resp = await client.post(f"/api/gates/{gates[0].id}/decide", json={"decision": "maybe"})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
