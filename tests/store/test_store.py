import pytest

from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.models import UnitDep, WorkUnit
from foundry.store.store import Store


async def make_store(tmp_path) -> Store:
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_ready_units_unblock_after_dependency_closes(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo", "/tmp/demo")
    run = await store.create_run(project.id, "pb.toml", "demo run")

    units = await store.create_work_units([
        WorkUnit(run_id=run.id, step_id="a", type="task", status="open"),
        WorkUnit(run_id=run.id, step_id="b", type="task", status="open"),
    ])
    unit_a, unit_b = units
    await store.add_unit_deps([UnitDep(unit_id=unit_b.id, needs_unit_id=unit_a.id)])

    ready = await store.get_ready_units(run.id)
    assert [u.id for u in ready] == [unit_a.id]

    await store.update_unit(unit_a.id, status="closed")
    ready = await store.get_ready_units(run.id)
    assert [u.id for u in ready] == [unit_b.id]

    await store.stop()


@pytest.mark.asyncio
async def test_event_log_is_monotonic_and_replayable_from_seq(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo2", "/tmp/demo2")
    run = await store.create_run(project.id, "pb.toml", "demo run 2")

    seq1 = await store.append_event(run.id, None, "run.created", {})
    seq2 = await store.append_event(run.id, None, "unit.ready", {"x": 1})
    assert seq2 == seq1 + 1

    all_events = await store.list_events(run.id)
    assert [e.seq for e in all_events] == [seq1, seq2]

    tail = await store.list_events(run.id, after_seq=seq1)
    assert [e.seq for e in tail] == [seq2]
    assert tail[0].payload_json == {"x": 1}

    await store.stop()


@pytest.mark.asyncio
async def test_complete_human_task_closes_unit(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo3", "/tmp/demo3")
    run = await store.create_run(project.id, "pb.toml", "demo run 3")
    units = await store.create_work_units([
        WorkUnit(run_id=run.id, step_id="approve", type="human_task", status="ready"),
    ])

    await store.complete_human_task(units[0].id)

    unit = await store.get_unit(units[0].id)
    assert unit.status == "closed"

    await store.stop()
