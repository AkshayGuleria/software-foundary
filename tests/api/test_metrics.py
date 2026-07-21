import pytest


@pytest.mark.asyncio
async def test_get_metrics_for_project_with_no_runs_returns_zeroed_metrics(api_client):
    client, _store, _scheduler = api_client

    resp = await client.post("/api/projects", json={"name": "demo", "path": "/tmp/demo"})
    project_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/metrics/{project_id}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["rework_rate"] == 0
    assert body["retry_count"] == 0


@pytest.mark.asyncio
async def test_get_metrics_for_unknown_project_404s(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/metrics/01JUNKNOWN")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_metrics_aggregates_across_multiple_runs_in_a_project(api_client):
    """One project, two runs — one gate approved, one rejected. Guards against
    the route only aggregating the last run's events instead of all of them."""
    client, store, scheduler = api_client

    resp = await client.post("/api/projects", json={"name": "demo", "path": "/tmp/demo"})
    project_id = resp.json()["data"]["id"]

    run_ids = []
    for _ in range(2):
        run_resp = await client.post(
            "/api/runs",
            json={
                "project_id": project_id,
                "playbook_path": "tests/orchestrator/fixtures/gated_demo.toml",
                "title": "run",
            },
        )
        run_ids.append(run_resp.json()["data"]["id"])

    for _ in range(5):
        await scheduler.tick_all_once()

    gates_run1 = await store.list_gates_for_run(run_ids[0])
    gates_run2 = await store.list_gates_for_run(run_ids[1])
    await store.decide_gate(
        next(g for g in gates_run1 if g.decision == "pending").id, "approved", decided_by="test"
    )
    await store.decide_gate(
        next(g for g in gates_run2 if g.decision == "pending").id, "rejected", decided_by="test"
    )

    resp = await client.get(f"/api/metrics/{project_id}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    # 1 rejected / 2 decided across BOTH runs — only correct if the route sums
    # every run's gates rather than e.g. only the last-created run's.
    assert body["rework_rate"] == pytest.approx(0.5)
