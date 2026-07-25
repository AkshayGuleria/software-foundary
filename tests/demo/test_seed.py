import pytest

from foundry.demo.seed import run_demo_seed
from foundry.store.db import init_db, make_engine, make_sessionmaker
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

    all_gates = []
    for run in await store.list_runs():
        all_gates.extend(await store.list_gates_for_run(run.id))
    rejected_gates = [g for g in all_gates if g.decision == "rejected"]
    assert rejected_gates, "expected at least one rejected gate in the seed data's history"

    all_runs = await store.list_runs()
    cancelled_runs = [r for r in all_runs if r.status == "cancelled"]
    assert cancelled_runs, "expected at least one cancelled run"

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
