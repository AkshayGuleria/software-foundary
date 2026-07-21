import pytest

from foundry.store.models import WorkUnit


@pytest.mark.asyncio
async def test_list_active_sessions_returns_empty_when_none_running(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_list_active_sessions_includes_running_excludes_ended(api_client):
    client, store, _scheduler = api_client
    project = await store.create_project("demo", "/tmp/demo")
    run = await store.create_run(project.id, "x.toml", "demo run")
    unit = (
        await store.create_work_units(
            [WorkUnit(run_id=run.id, step_id="a", type="session", status="running")]
        )
    )[0]
    await store.create_session_row(
        id=unit.id,
        work_unit_id=unit.id,
        driver="FakeDriver",
        status="running",
        model="fake",
        tokens_in=10,
        tokens_out=20,
    )
    ended_unit = (
        await store.create_work_units([WorkUnit(run_id=run.id, step_id="b", type="session", status="closed")])
    )[0]
    await store.create_session_row(
        id=ended_unit.id, work_unit_id=ended_unit.id, driver="FakeDriver", status="ended"
    )

    resp = await client.get("/api/sessions")
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["run_id"] == run.id
    assert data[0]["step_id"] == "a"
    assert data[0]["tokens_in"] == 10
    assert data[0]["tokens_out"] == 20
