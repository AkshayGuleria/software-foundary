import pytest


@pytest.mark.asyncio
async def test_demo_status_reports_inactive_on_original_db(demo_api_client):
    client, app = demo_api_client

    resp = await client.get("/api/demo/status")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["active"] is False
    assert body["db_path"] == app.state.original_db_path


@pytest.mark.asyncio
async def test_demo_activate_swaps_to_demo_db_and_seeds_when_empty(demo_api_client):
    client, app = demo_api_client

    resp = await client.post("/api/demo/activate")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["active"] is True
    assert body["db_path"] == app.state.demo_db_path

    projects = await app.state.store.list_projects()
    assert len(projects) == 5


@pytest.mark.asyncio
async def test_demo_activate_does_not_reseed_when_already_seeded(demo_api_client):
    client, app = demo_api_client

    await client.post("/api/demo/activate")
    first_count = len(await app.state.store.list_projects())

    resp = await client.post("/api/demo/activate")

    assert resp.status_code == 200
    second_count = len(await app.state.store.list_projects())
    assert first_count == second_count == 5


@pytest.mark.asyncio
async def test_demo_activate_recovers_active_runs_into_the_new_scheduler(demo_api_client):
    client, app = demo_api_client

    await client.post("/api/demo/activate")

    # The seeded dataset always includes runs left in status="active" (e.g.
    # the pending-human-gate and pending-agent-gate scenarios). Activation's
    # swap must recover them into the freshly built scheduler, not just seed
    # the rows -- otherwise those runs would sit inert, never ticked again.
    active_runs = await app.state.store.list_runs(status="active")
    assert active_runs
    registered_ids = set(app.state.scheduler._orchestrators.keys())
    assert {r.id for r in active_runs} <= registered_ids
