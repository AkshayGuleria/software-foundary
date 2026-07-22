# tests/api/test_portfolio_e2e.py
import pytest

from foundry.store.models import WorkUnit


@pytest.mark.asyncio
async def test_five_projects_three_active_portfolio_shows_attention_ranked_health(api_client):
    client, store, _scheduler = api_client

    # Five projects registered.
    projects = [await store.create_project(f"project-{i}", ".") for i in range(5)]

    # Three running concurrently: each gets an active run with a mix of
    # pending/rejected gates so their attention scores differ meaningfully.
    # Work units are created in batches via create_work_units(list[WorkUnit]) -
    # there is no singular create_unit helper.
    active_specs = [
        (projects[0], 3, 0),  # 3 pending gates, 0 rejected -> highest pending-gate signal
        (projects[1], 1, 1),  # 1 pending, 1 rejected -> rework-rate signal
        (projects[2], 0, 0),  # active run, no gates yet -> lowest of the three active ones
    ]
    for project, pending_count, rejected_count in active_specs:
        run = await store.create_run(project.id, "p.toml", f"{project.name}-run")
        specs = [
            WorkUnit(run_id=run.id, step_id=f"pending-{i}", type="task", status="open")
            for i in range(pending_count)
        ] + [
            WorkUnit(run_id=run.id, step_id=f"rejected-{i}", type="task", status="open")
            for i in range(rejected_count)
        ]
        created = await store.create_work_units(specs) if specs else []
        pending_units, rejected_units = created[:pending_count], created[pending_count:]
        for unit in pending_units:
            await store.create_gate(work_unit_id=unit.id, gate_type="human", decision="pending")
        for unit in rejected_units:
            await store.create_gate(work_unit_id=unit.id, gate_type="human", decision="rejected")

    # Two projects with no active runs (one with a closed run, one untouched).
    closed_run = await store.create_run(projects[3].id, "p.toml", "old-run")
    await store.update_run(closed_run.id, status="closed")
    # projects[4] has zero runs at all.

    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()["data"]

    assert len(body) == 5

    by_name = {row["name"]: row for row in body}
    assert by_name["project-0"]["active_run_count"] == 1
    assert by_name["project-0"]["pending_gate_count"] == 3
    assert by_name["project-1"]["pending_gate_count"] == 1
    # rework_rate = rejected / total-gates-seen-among-active-runs (including
    # still-pending ones), not rejected/decided-only - confirmed by Task 2's
    # own review against its test fixture (2 pending + 1 rejected -> 1/3).
    # Here: 1 pending + 1 rejected -> 1/2.
    assert by_name["project-1"]["rework_rate"] == pytest.approx(0.5)
    assert by_name["project-2"]["active_run_count"] == 1
    assert by_name["project-2"]["pending_gate_count"] == 0
    assert by_name["project-3"]["active_run_count"] == 0
    assert by_name["project-3"]["last_run_status"] == "closed"
    assert by_name["project-4"]["active_run_count"] == 0
    assert by_name["project-4"]["last_run_status"] is None
    assert by_name["project-4"]["attention_score"] == 0.0

    # Attention-ranked: the three active projects with real signal (0, 1, 2)
    # must all outrank the two untouched/closed ones (3, 4), and within the
    # active set, more pending/rejected gates ranks higher.
    scores = {row["name"]: row["attention_score"] for row in body}
    assert scores["project-0"] > scores["project-2"]
    assert scores["project-1"] > scores["project-2"]
    assert scores["project-2"] > scores["project-3"]
    assert scores["project-2"] > scores["project-4"]

    # The response itself is already sorted descending by attention_score -
    # this is what PortfolioHomePage renders directly, with no client-side sort.
    returned_scores = [row["attention_score"] for row in body]
    assert returned_scores == sorted(returned_scores, reverse=True)
