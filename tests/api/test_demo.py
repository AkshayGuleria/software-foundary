import asyncio

import pytest
from httpx import ASGITransport, AsyncClient

from foundry.api.app import create_app
from foundry.api.scheduler import Scheduler
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


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
async def test_demo_activate_when_already_active_is_a_noop(demo_api_client):
    client, app = demo_api_client

    resp1 = await client.post("/api/demo/activate")
    assert resp1.status_code == 200
    store_id_before = id(app.state.store)

    resp2 = await client.post("/api/demo/activate")

    assert resp2.status_code == 200
    assert resp2.json()["data"]["active"] is True
    # A true no-op never tears down/rebuilds the store -- if it had, this
    # would be a *different* Store object entirely, not just equal state.
    assert id(app.state.store) == store_id_before


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

    # The reset path also does the recover-before-seed / recover-after-seed
    # double-dip (build_store_and_scheduler's recovery ran against the
    # freshly-wiped, still-empty db before the reseed wrote any rows) --
    # confirm the RESET path re-registers active runs too, not just activate.
    active_runs = await app.state.store.list_runs(status="active")
    assert active_runs
    registered_ids = set(app.state.scheduler._orchestrators.keys())
    assert {r.id for r in active_runs} <= registered_ids


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


@pytest.mark.asyncio
async def test_demo_activate_deactivate_reactivate_is_repeatable(demo_api_client):
    client, app = demo_api_client

    r1 = await client.post("/api/demo/activate")
    assert r1.status_code == 200
    assert r1.json()["data"]["active"] is True
    first_count = len(await app.state.store.list_projects())

    r2 = await client.post("/api/demo/deactivate")
    assert r2.status_code == 200
    assert r2.json()["data"]["active"] is False

    r3 = await client.post("/api/demo/activate")
    assert r3.status_code == 200
    assert r3.json()["data"]["active"] is True
    second_count = len(await app.state.store.list_projects())

    assert first_count == second_count == 5


@pytest.mark.asyncio
async def test_demo_activate_failure_leaves_server_serviceable(demo_api_client, monkeypatch):
    client, app = demo_api_client

    async def _boom(store, repos_dir):
        raise RuntimeError("seed failed")

    # Patch the name as imported into `foundry.api.routes.demo` -- that's the
    # module-level binding `_swap_database` actually calls.
    monkeypatch.setattr("foundry.api.routes.demo.run_demo_seed", _boom)

    # A generic unhandled exception in a route isn't caught by any handler
    # registered on this app, and httpx's ASGITransport re-raises it into the
    # calling test rather than surfacing it as a response object -- confirmed
    # by hand against a minimal FastAPI app before writing this assertion.
    with pytest.raises(RuntimeError, match="seed failed"):
        await client.post("/api/demo/activate")

    # The server must still be serviceable. Critically this has to be a
    # *write* (goes through Store.write -> the writer queue), not a read:
    # Store.read() opens its own session straight off the engine and works
    # fine regardless of writer-task state, so it can't tell a wedged store
    # apart from a healthy one. Store.write() is the operation that's
    # actually broken pre-fix -- app.state.store would still be the old,
    # already-stop()'d store (stop() flips `_running` False and joins the
    # writer task), so write() would raise "Store is not running" on every
    # call, forever, unless app.state got rebuilt onto a fresh live store.
    project = await asyncio.wait_for(
        app.state.store.create_project("post-failure-check", "/tmp/post-failure-check"), timeout=5
    )
    assert project.name == "post-failure-check"

    # And it must have fallen back to the original db, not be left dangling
    # mid-swap on the (never-fully-built) demo db.
    status_resp = await client.get("/api/demo/status")
    assert status_resp.status_code == 200
    body = status_resp.json()["data"]
    assert body["active"] is False
    assert body["db_path"] == app.state.original_db_path


@pytest.mark.asyncio
async def test_demo_status_does_not_500_when_original_db_path_is_none(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)
    # Bare defaults: no `original_db_path` passed, mirroring any `create_app`
    # caller that doesn't care about demo mode (the demo router is still
    # mounted unconditionally on every app).
    app = create_app(store, scheduler)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/demo/status")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["db_path"] == ""
    assert body["active"] is False

    await store.stop()
    await engine.dispose()
