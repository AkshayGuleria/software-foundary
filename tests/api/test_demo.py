import asyncio

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


@pytest.mark.asyncio
async def test_demo_deactivate_swaps_back_to_original_db(demo_api_client):
    client, app = demo_api_client
    await app.state.store.create_project("pre-existing", "/tmp/pre-existing")

    await client.post("/api/demo/activate")
    resp = await client.post("/api/demo/deactivate")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["active"] is False
    assert body["db_path"] == app.state.original_db_path

    projects = await app.state.store.list_projects()
    assert [p.name for p in projects] == ["pre-existing"]


@pytest.mark.asyncio
async def test_demo_deactivate_when_already_inactive_does_not_crash(demo_api_client):
    client, _app = demo_api_client

    resp = await client.post("/api/demo/deactivate")

    assert resp.status_code == 200
    assert resp.json()["data"]["active"] is False


@pytest.mark.asyncio
async def test_demo_reseed_wipes_and_reseeds_in_place(demo_api_client):
    client, app = demo_api_client
    await client.post("/api/demo/activate")
    await app.state.store.create_project("manually-added", "/tmp/manual")
    assert len(await app.state.store.list_projects()) == 6

    resp = await client.post("/api/demo/reseed")

    assert resp.status_code == 200
    projects = await app.state.store.list_projects()
    assert len(projects) == 5
    assert "manually-added" not in [p.name for p in projects]


@pytest.mark.asyncio
async def test_demo_reseed_409_when_not_active(demo_api_client):
    client, _app = demo_api_client

    resp = await client.post("/api/demo/reseed")

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_activate_requests_do_not_double_seed(demo_api_client):
    client, app = demo_api_client

    responses = await asyncio.gather(
        client.post("/api/demo/activate"),
        client.post("/api/demo/activate"),
    )

    assert all(r.status_code == 200 for r in responses)
    projects = await app.state.store.list_projects()
    assert len(projects) == 5
