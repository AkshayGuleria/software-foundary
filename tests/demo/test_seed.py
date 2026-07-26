from datetime import timedelta

import pytest

from foundry.demo.seed import run_demo_seed
from foundry.metrics.rollup import compute_project_metrics
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.models import utcnow
from foundry.store.store import Store


async def _make_store(tmp_path) -> Store:
    engine = make_engine(str(tmp_path / "demo.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_seed_creates_at_least_one_closed_successful_run(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    projects = await store.list_projects()
    assert len(projects) >= 1

    all_runs = await store.list_runs()
    closed_runs = [r for r in all_runs if r.status == "closed"]
    assert len(closed_runs) >= 1

    closed_run = closed_runs[0]
    units = await store.list_units(closed_run.id)
    task_units = [u for u in units if u.type == "task"]
    assert task_units
    assert all(u.status == "closed" for u in task_units)

    await store.stop()


@pytest.mark.asyncio
async def test_seed_creates_runs_with_pending_human_and_agent_gates(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    all_gates = []
    for run in await store.list_runs():
        all_gates.extend(await store.list_gates_for_run(run.id))

    pending_human = [g for g in all_gates if g.gate_type == "human" and g.decision == "pending"]
    pending_agent = [g for g in all_gates if g.gate_type == "agent" and g.decision == "pending"]
    assert pending_human, "expected at least one pending human gate in the seed data"
    assert pending_agent, "expected at least one pending agent gate in the seed data"

    await store.stop()


@pytest.mark.asyncio
async def test_seed_creates_a_rejection_rework_run_and_a_cancelled_run(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    all_runs = await store.list_runs()
    gates_by_run = {run.id: await store.list_gates_for_run(run.id) for run in all_runs}
    all_gates = [g for gates in gates_by_run.values() for g in gates]
    rejected_gates = [g for g in all_gates if g.decision == "rejected"]
    assert rejected_gates, "expected at least one rejected gate in the seed data's history"

    # Find the run that actually contains a rejected gate, and prove the
    # rejection genuinely triggered rework -- not just that a gate row says
    # "rejected" with nothing downstream reacting to it. A regression where
    # the rejected gate never reopens/redispatches `implement` would leave
    # this assertion catching attempt == 0 everywhere.
    rejection_run = next(r for r in all_runs if any(g.decision == "rejected" for g in gates_by_run[r.id]))
    units = await store.list_units(rejection_run.id)
    implement_units = [u for u in units if u.step_id == "implement" and u.type == "task"]
    assert implement_units, "expected implement task unit(s) in the rejection-rework run"
    assert any(u.attempt > 0 for u in implement_units), (
        "expected at least one implement unit to have been reopened and "
        "redispatched (attempt > 0) after the review gate's rejection -- a "
        "gate row alone claiming 'rejected' doesn't prove rework happened"
    )

    # sdlc_story runs don't auto-close (matching sibling seed runs), so this
    # run should still be "active" -- but round 2 of the review should have
    # gone through for real, carrying the run all the way to its final
    # human gate (integrate) being approved. Verified empirically against
    # the actual shipped behavior, not assumed.
    assert rejection_run.status == "active"
    integrate_units = [u for u in units if u.step_id == "integrate" and u.type == "task"]
    assert integrate_units, "expected an integrate task unit in the rejection-rework run"
    integrate_gates = [g for g in gates_by_run[rejection_run.id] if g.work_unit_id == integrate_units[0].id]
    assert integrate_gates, "expected a gate on the integrate unit"
    assert integrate_gates[0].decision == "approved"

    cancelled_runs = [r for r in all_runs if r.status == "cancelled"]
    assert cancelled_runs, "expected at least one cancelled run"

    await store.stop()


@pytest.mark.asyncio
async def test_seed_produces_the_full_expected_dataset_shape(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    projects = await store.list_projects()
    assert len(projects) == 5

    statuses = [p.status for p in projects]
    assert statuses.count("active") == 3
    assert statuses.count("paused") == 1
    assert statuses.count("archived") == 1

    all_runs = await store.list_runs()
    assert len(all_runs) == 10

    runs_by_project: dict[str, int] = {}
    for run in all_runs:
        runs_by_project[run.project_id] = runs_by_project.get(run.project_id, 0) + 1
    assert len(runs_by_project) == 5, "every project should have at least one run"
    assert all(count >= 2 for count in runs_by_project.values()), (
        "expected every project to have 2+ runs (spec: '2-4 runs spanning every state')"
    )

    await store.stop()


@pytest.mark.asyncio
async def test_seed_backdates_timestamps_and_widens_gate_approval_latency(tmp_path):
    store = await _make_store(tmp_path)

    before_seed = utcnow()
    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    projects = {p.name: p for p in await store.list_projects()}

    async def _metrics_and_runs(project_name: str):
        runs = await store.list_runs(project_id=projects[project_name].id)
        events, gates, units, sessions, artifacts = [], [], [], [], []
        for run in runs:
            events.extend(await store.list_events(run.id))
            gates.extend(await store.list_gates_for_run(run.id))
            units.extend(await store.list_units(run.id))
            sessions.extend(await store.list_sessions_for_run(run.id))
            artifacts.extend(await store.list_artifacts(run.id))
        return compute_project_metrics(events, gates, units, sessions, artifacts), runs

    acme_metrics, acme_runs = await _metrics_and_runs("acme-reports")
    gamma_metrics, gamma_runs = await _metrics_and_runs("gamma-api")

    # (a) backdating: each project's runs land well in the past, and at
    # clearly different points from each other -- not clustered at the
    # exact seed moment.
    acme_created = min(r.created_at for r in acme_runs)
    gamma_created = min(r.created_at for r in gamma_runs)
    assert (before_seed - acme_created) > timedelta(days=10)
    assert (before_seed - gamma_created) > timedelta(days=3)
    assert abs((acme_created - gamma_created).total_seconds()) > timedelta(days=5).total_seconds()

    # (b) approval latency: genuinely non-zero for at least one project, and
    # not identical across projects (the whole point of a comparison view).
    assert acme_metrics["approval_latency_seconds"] > 0 or gamma_metrics["approval_latency_seconds"] > 0
    assert abs(acme_metrics["approval_latency_seconds"] - gamma_metrics["approval_latency_seconds"]) > 60, (
        "expected approval_latency_seconds to differ meaningfully between projects"
    )

    await store.stop()


@pytest.mark.asyncio
async def test_seed_creates_an_open_human_task_and_memory_items(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    open_human_tasks = []
    for run in await store.list_runs():
        units = await store.list_units(run.id)
        open_human_tasks.extend(u for u in units if u.type == "human_task" and u.status == "open")
    assert open_human_tasks, "expected at least one open human_task unit (budget-exceeded escalation)"

    memory_items = await store.list_memory_items()
    assert len(memory_items) >= 3
    assert {m.kind for m in memory_items} >= {"lesson", "pattern", "pitfall"}

    await store.stop()


@pytest.mark.asyncio
async def test_seed_varies_project_settings_and_lifecycle_states(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    projects = await store.list_projects()
    assert len(projects) >= 5

    drivers = {p.default_driver for p in projects}
    assert len(drivers) > 1, "expected varied default_driver across demo projects, not all identical"

    statuses = {p.status for p in projects}
    assert "paused" in statuses
    assert "archived" in statuses

    await store.stop()
