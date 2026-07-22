import pytest

from foundry.api.scheduler import Scheduler
from foundry.cli import _recover_active_runs
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store

FIXTURE = "tests/orchestrator/fixtures/linear_demo.toml"


async def make_store(tmp_path) -> Store:
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_recover_active_runs_rehydrates_persisted_gate_overrides(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj", str(tmp_path))
    run = await store.create_run(project.id, FIXTURE, "recovered run")
    await store.update_run(run.id, gate_overrides_json={"implement": "approved"})

    assert run.status == "active"  # sanity: the recovery loop only picks up active runs

    scheduler = Scheduler(store)
    await _recover_active_runs(store, scheduler)

    orchestrator = scheduler._orchestrators[run.id]
    assert orchestrator.gate_overrides == {"implement": "approved"}

    await store.stop()


@pytest.mark.asyncio
async def test_recover_active_runs_with_no_overrides_registers_with_none(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj2", str(tmp_path))
    run = await store.create_run(project.id, FIXTURE, "recovered run 2")
    # gate_overrides_json defaults to {} -- must normalize to an empty dict on
    # the Orchestrator, not crash or leave it None-vs-{} inconsistent.

    scheduler = Scheduler(store)
    await _recover_active_runs(store, scheduler)

    orchestrator = scheduler._orchestrators[run.id]
    assert orchestrator.gate_overrides == {}

    await store.stop()


@pytest.mark.asyncio
async def test_recover_active_runs_skips_non_active_runs(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj3", str(tmp_path))
    run = await store.create_run(project.id, FIXTURE, "closed run")
    await store.update_run(run.id, status="closed")

    scheduler = Scheduler(store)
    await _recover_active_runs(store, scheduler)

    assert run.id not in scheduler._orchestrators

    await store.stop()
