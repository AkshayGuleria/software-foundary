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
    #
    # The endpoint sorts ascending by created_at (oldest first), so unit1's
    # gate (older_human, must sort FIRST) needs the EARLIEST created_at, and
    # unit4's gate (newer_derived, must sort LAST) needs the LATEST
    # created_at. To make sure the test can only pass if the endpoint's own
    # sort actually runs -- not by coincidentally matching SQLite's
    # insertion-order fallback -- both the WorkUnit insertion order AND the
    # Gate creation-call order are deliberately reversed relative to that
    # created_at order below: unit4's WorkUnit is inserted first (and its
    # gate created first), unit1's WorkUnit is inserted last (and its gate
    # created last), even though unit1 has the earlier timestamp.
    t0 = dt.datetime(2026, 7, 20, 0, 0, 0, tzinfo=dt.UTC)
    unit4, unit2, unit3, unit1 = await store.create_work_units(
        [
            WorkUnit(
                run_id=run.id,
                step_id="step4",
                type="task",
                status="open",
                created_at=t0 + dt.timedelta(minutes=3),
            ),
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
            WorkUnit(run_id=run.id, step_id="step1", type="task", status="open", created_at=t0),
        ]
    )
    # Gate creation order also reversed relative to created_at order: the
    # gate that must sort LAST (newer_derived) is created first here, and
    # the gate that must sort FIRST (older_human) is created last.
    newer_derived = await store.create_gate(work_unit_id=unit4.id, gate_type="derived", decision="pending")
    await store.create_gate(work_unit_id=unit2.id, gate_type="human", decision="approved")  # not pending
    await store.create_gate(work_unit_id=unit3.id, gate_type="agent", decision="pending")  # not human/derived
    older_human = await store.create_gate(work_unit_id=unit1.id, gate_type="human", decision="pending")

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


@pytest.mark.asyncio
async def test_batch_decide_approves_multiple_gates_and_skips_already_decided(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("batch1", ".")
    run = await store.create_run(project.id, "p.toml", "batch1-run")
    unit1, unit2, unit3 = await store.create_work_units(
        [
            WorkUnit(run_id=run.id, step_id="s1", type="task", status="open"),
            WorkUnit(run_id=run.id, step_id="s2", type="task", status="open"),
            WorkUnit(run_id=run.id, step_id="s3", type="task", status="open"),
        ]
    )
    gate1 = await store.create_gate(work_unit_id=unit1.id, gate_type="human", decision="pending")
    gate2 = await store.create_gate(work_unit_id=unit2.id, gate_type="human", decision="pending")
    already_decided = await store.create_gate(work_unit_id=unit3.id, gate_type="human", decision="approved")

    resp = await client.post(
        "/api/gates/batch-decide", json={"gate_ids": [gate1.id, gate2.id, already_decided.id]}
    )

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert sorted(body["approved"]) == sorted([gate1.id, gate2.id])
    assert body["skipped"] == [already_decided.id]

    queue_resp = await client.get("/api/queue")
    assert queue_resp.json()["data"]["gates"] == []


@pytest.mark.asyncio
async def test_batch_decide_with_unknown_gate_id_skips_it(api_client):
    client, _store, _scheduler = api_client

    resp = await client.post("/api/gates/batch-decide", json={"gate_ids": ["does-not-exist"]})

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["approved"] == []
    assert body["skipped"] == ["does-not-exist"]


@pytest.mark.asyncio
async def test_complete_human_task_resolves_it(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("ht1", ".")
    run = await store.create_run(project.id, "p.toml", "ht1-run")
    unit = (
        await store.create_work_units(
            [WorkUnit(run_id=run.id, step_id="_budget", type="human_task", status="open")]
        )
    )[0]

    resp = await client.post(f"/api/human-tasks/{unit.id}/complete")

    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "closed"

    queue_resp = await client.get("/api/queue")
    assert queue_resp.json()["data"]["human_tasks"] == []


@pytest.mark.asyncio
async def test_complete_human_task_404s_for_missing_unit(api_client):
    client, _store, _scheduler = api_client

    resp = await client.post("/api/human-tasks/does-not-exist/complete")

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_complete_human_task_409s_for_non_human_task_unit(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("ht2", ".")
    run = await store.create_run(project.id, "p.toml", "ht2-run")
    unit = (
        await store.create_work_units([WorkUnit(run_id=run.id, step_id="s1", type="task", status="open")])
    )[0]

    resp = await client.post(f"/api/human-tasks/{unit.id}/complete")

    assert resp.status_code == 409
