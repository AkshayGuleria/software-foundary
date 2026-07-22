import pytest

from foundry.store.models import WorkUnit


@pytest.mark.asyncio
async def test_portfolio_empty_when_no_projects(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_portfolio_ranks_project_with_pending_gates_and_rejections_higher(api_client):
    client, store, _scheduler = api_client

    quiet = await store.create_project("quiet", ".")
    busy = await store.create_project("busy", ".")

    # "quiet" has one closed run, nothing pending -> low attention.
    quiet_run = await store.create_run(quiet.id, "p.toml", "quiet-run")
    await store.update_run(quiet_run.id, status="closed")

    # "busy" has one active run with two pending gates and one rejected gate
    # -> should rank above "quiet". There is no create_unit helper — work
    # units are created in batches via create_work_units(list[WorkUnit]).
    busy_run = await store.create_run(busy.id, "p.toml", "busy-run")
    unit1, unit2, unit3 = await store.create_work_units(
        [
            WorkUnit(run_id=busy_run.id, step_id="step1", type="task", status="open"),
            WorkUnit(run_id=busy_run.id, step_id="step2", type="task", status="open"),
            WorkUnit(run_id=busy_run.id, step_id="step3", type="task", status="open"),
        ]
    )
    await store.create_gate(work_unit_id=unit1.id, gate_type="human", decision="pending")
    await store.create_gate(work_unit_id=unit2.id, gate_type="human", decision="pending")
    await store.create_gate(work_unit_id=unit3.id, gate_type="human", decision="rejected")

    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body) == 2

    by_name = {row["name"]: row for row in body}
    assert by_name["busy"]["active_run_count"] == 1
    assert by_name["busy"]["pending_gate_count"] == 2
    assert by_name["busy"]["rework_rate"] == pytest.approx(1 / 3)
    assert by_name["quiet"]["active_run_count"] == 0
    assert by_name["quiet"]["pending_gate_count"] == 0
    assert by_name["quiet"]["rework_rate"] is None
    assert by_name["quiet"]["last_run_status"] == "closed"

    # Sorted descending by attention_score: "busy" (pending gates + rejections) first.
    assert body[0]["name"] == "busy"
    assert body[0]["attention_score"] > body[1]["attention_score"]


@pytest.mark.asyncio
async def test_portfolio_project_with_no_runs_has_zero_attention(api_client):
    client, store, _scheduler = api_client
    await store.create_project("untouched", ".")

    resp = await client.get("/api/portfolio")
    body = resp.json()["data"]
    assert body[0]["last_run_status"] is None
    assert body[0]["last_run_at"] is None
    assert body[0]["attention_score"] == 0.0


@pytest.mark.asyncio
async def test_portfolio_active_run_alone_outranks_closed_run(api_client):
    """Regression test for the missing active_run_count term.

    Two projects with identical (zero) pending-gate/rework/budget signal
    must still be ranked apart if one has an in-flight active run and the
    other's only run is closed. Before the fix, both scored ~0 (only
    differing by sub-millisecond staleness-timer noise between when their
    fixture runs were created), so an active-but-otherwise-quiet project
    could not reliably outrank a closed/never-run project. The
    active_run_count * 5.0 term closes that gap deterministically.
    """
    client, store, _scheduler = api_client

    active_project = await store.create_project("active-quiet", ".")
    closed_project = await store.create_project("closed-quiet", ".")

    # Active project: one open run, zero gates/rework/budget signal.
    await store.create_run(active_project.id, "p.toml", "active-run")

    # Closed project: one closed run, likewise zero gates/rework/budget signal.
    closed_run = await store.create_run(closed_project.id, "p.toml", "closed-run")
    await store.update_run(closed_run.id, status="closed")

    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()["data"]

    by_name = {row["name"]: row for row in body}
    assert by_name["active-quiet"]["active_run_count"] == 1
    assert by_name["closed-quiet"]["active_run_count"] == 0

    active_score = by_name["active-quiet"]["attention_score"]
    closed_score = by_name["closed-quiet"]["attention_score"]

    # 1 active run contributes exactly +5.0 (active_run_count * 5.0), which
    # dwarfs any staleness-timer noise between the two fixture runs (created
    # microseconds apart, i.e. staleness_hours * 0.5 differs by a
    # negligible fraction of an hour). Assert a gap well above that noise
    # floor to prove the new term -- not timing jitter -- drives the result.
    assert active_score - closed_score > 1.0
