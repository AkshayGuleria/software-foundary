import pytest


@pytest.mark.asyncio
async def test_create_run_materializes_and_registers_with_scheduler(api_client):
    client, store, scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "title": "my run",
        },
    )

    assert run_resp.status_code == 201, run_resp.text
    body = run_resp.json()["data"]
    assert body["title"] == "my run"
    assert body["status"] == "active"
    run_id = body["id"]

    assert run_id in scheduler._orchestrators
    units = await store.list_units(run_id)
    assert len(units) == 3  # plan, implement, review


@pytest.mark.asyncio
async def test_create_run_with_bad_playbook_returns_400(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/fixtures/dangling_needs.toml",
            "title": "bad",
        },
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_run_for_missing_project_returns_404(api_client):
    client, _store, _scheduler = api_client

    resp = await client.post(
        "/api/runs",
        json={
            "project_id": "does-not-exist",
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
        },
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_detail_shows_units_and_gates_with_cost_estimate(api_client):
    client, store, scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]
    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/playbook/fixtures/sdlc_mini.toml",
            "title": "plan-gated run",
        },
    )
    run_id = run_resp.json()["data"]["id"]

    # sdlc_mini: requirement -> (architecture, test_plan) -> plan_approval (derived
    # gate) -> implement. requirement/architecture/test_plan each carry their own
    # success-path "human" gate, and M1a gates stay pending until a human decides
    # (no auto-approve) — so drive the run forward by approving each human gate as
    # it appears, until plan_approval's derived gate materializes.
    for _ in range(3):
        await scheduler.tick_all_once()
        gates = await store.list_gates_for_run(run_id)
        pending_human = [g for g in gates if g.gate_type == "human" and g.decision == "pending"]
        for g in pending_human:
            await store.decide_gate(g.id, "approved", decided_by="test")
    await scheduler.tick_all_once()

    detail_resp = await client.get(f"/api/runs/{run_id}")
    assert detail_resp.status_code == 200
    body = detail_resp.json()["data"]
    assert body["run"]["id"] == run_id
    # 5 step-level units (requirement, architecture, test_plan, plan_approval,
    # implement) + 1 session unit per dispatched task (requirement, architecture,
    # test_plan each ran once) = 8.
    assert len(body["units"]) == 8

    derived_gates = [g for g in body["gates"] if g["gate_type"] == "derived"]
    assert len(derived_gates) == 1
    assert derived_gates[0]["decision"] == "pending"
    assert derived_gates[0]["cost_estimate"]["estimated_writes_steps"] == 1

    # sdlc_mini has no fan-out, so units should carry convoy_id as a present
    # (non-missing) field, expected None.
    assert all("convoy_id" in u for u in body["units"])
    assert all(u["convoy_id"] is None for u in body["units"])


@pytest.mark.asyncio
async def test_list_runs_filters_by_project_and_status(api_client):
    client, _store, _scheduler = api_client

    proj1 = (await client.post("/api/projects", json={"name": "p1", "path": "/tmp/p1"})).json()["data"]["id"]
    proj2 = (await client.post("/api/projects", json={"name": "p2", "path": "/tmp/p2"})).json()["data"]["id"]
    await client.post(
        "/api/runs",
        json={"project_id": proj1, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )
    await client.post(
        "/api/runs",
        json={"project_id": proj2, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )

    resp = await client.get(f"/api/runs?project_id={proj1}")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


@pytest.mark.asyncio
async def test_get_run_graph_returns_units_and_deps(api_client):
    client, _store, _scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
        )
    ).json()["data"]["id"]

    resp = await client.get(f"/api/runs/{run_id}/graph")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body["units"]) == 3
    assert len(body["deps"]) == 2  # implement needs plan, review needs implement


@pytest.mark.asyncio
async def test_get_run_artifacts_latest_only_returns_max_version(api_client):
    client, store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/gated_demo.toml"},
        )
    ).json()["data"]["id"]

    for _ in range(5):
        await scheduler.tick_all_once()

    gates = await store.list_gates_for_run(run_id)
    await store.decide_gate(gates[0].id, "rejected", decided_by="test")
    for _ in range(5):
        await scheduler.tick_all_once()
    gates = await store.list_gates_for_run(run_id)
    pending = [g for g in gates if g.decision == "pending"]
    if pending:
        await store.decide_gate(pending[0].id, "approved", decided_by="test")
        for _ in range(5):
            await scheduler.tick_all_once()

    resp = await client.get(f"/api/runs/{run_id}/artifacts?latest=1")
    assert resp.status_code == 200
    a_artifacts = [a for a in resp.json()["data"] if a["kind"] == "a_artifact"]
    assert len(a_artifacts) == 1
    assert a_artifacts[0]["version"] == 2


@pytest.mark.asyncio
async def test_cancel_run_flips_non_terminal_units_and_stops_scheduling(api_client):
    client, store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/gated_demo.toml"},
        )
    ).json()["data"]["id"]

    for _ in range(5):
        await scheduler.tick_all_once()

    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 204

    units = await store.list_units(run_id)
    assert all(u.status in ("closed", "failed", "killed") for u in units)

    run_row = await store.get_run(run_id)
    assert run_row.status == "cancelled"
    assert run_id not in scheduler._orchestrators


@pytest.mark.asyncio
async def test_double_cancel_returns_409(api_client):
    client, _store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
        )
    ).json()["data"]["id"]

    first = await client.post(f"/api/runs/{run_id}/cancel")
    assert first.status_code == 204

    second = await client.post(f"/api/runs/{run_id}/cancel")
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_cancel_missing_run_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/runs/does-not-exist/cancel")
    assert resp.status_code == 404
