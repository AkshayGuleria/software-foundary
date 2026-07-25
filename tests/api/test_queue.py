import datetime as dt

import pytest

from foundry.store.models import WorkUnit


@pytest.mark.asyncio
async def test_queue_empty_when_nothing_pending(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/queue")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["gates"] == []
    assert body["human_tasks"] == []


@pytest.mark.asyncio
async def test_queue_lists_pending_human_and_derived_gates_oldest_first(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("acme", ".")
    run = await store.create_run(project.id, "p.toml", "acme-run")
    # Explicit, clearly-separated created_at values -- a batch create_work_units
    # call can produce timestamps too close together (or, on SQLite, in a
    # return order not guaranteed by insertion order absent ORDER BY) to
    # reliably prove sort-by-age otherwise.
    t0 = dt.datetime(2026, 7, 20, 0, 0, 0, tzinfo=dt.UTC)
    unit1, unit2, unit3, unit4 = await store.create_work_units(
        [
            WorkUnit(run_id=run.id, step_id="step1", type="task", status="open", created_at=t0),
            WorkUnit(
                run_id=run.id,
                step_id="step2",
                type="task",
                status="open",
                created_at=t0 + dt.timedelta(minutes=1),
            ),
            WorkUnit(
                run_id=run.id,
                step_id="step3",
                type="task",
                status="open",
                created_at=t0 + dt.timedelta(minutes=2),
            ),
            WorkUnit(
                run_id=run.id,
                step_id="step4",
                type="task",
                status="open",
                created_at=t0 + dt.timedelta(minutes=3),
            ),
        ]
    )
    older_human = await store.create_gate(work_unit_id=unit1.id, gate_type="human", decision="pending")
    await store.create_gate(work_unit_id=unit2.id, gate_type="human", decision="approved")  # not pending
    await store.create_gate(work_unit_id=unit3.id, gate_type="agent", decision="pending")  # not human/derived
    newer_derived = await store.create_gate(work_unit_id=unit4.id, gate_type="derived", decision="pending")

    resp = await client.get("/api/queue")

    assert resp.status_code == 200
    gates = resp.json()["data"]["gates"]
    assert [g["id"] for g in gates] == [older_human.id, newer_derived.id]
    assert gates[0]["project_id"] == project.id
    assert gates[0]["run_id"] == run.id
    assert gates[0]["step_id"] == "step1"


@pytest.mark.asyncio
async def test_queue_lists_open_human_tasks_not_closed_ones(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("acme2", ".")
    run = await store.create_run(project.id, "p.toml", "acme2-run")
    open_unit, closed_unit = await store.create_work_units(
        [
            WorkUnit(run_id=run.id, step_id="_budget", type="human_task", status="open"),
            WorkUnit(run_id=run.id, step_id="implement.escalation", type="human_task", status="closed"),
        ]
    )

    resp = await client.get("/api/queue")

    assert resp.status_code == 200
    human_tasks = resp.json()["data"]["human_tasks"]
    assert [h["id"] for h in human_tasks] == [open_unit.id]
    assert human_tasks[0]["reason"] == "Budget exceeded"
    assert human_tasks[0]["project_id"] == project.id
    assert human_tasks[0]["run_id"] == run.id
