import pytest

from foundry.api.scheduler import Scheduler
from foundry.drivers.base import SessionHealth
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store

FIXTURE = "tests/orchestrator/fixtures/linear_demo.toml"


class BrokenDriver:
    def spawn(self, spec):
        raise RuntimeError("boom")

    async def stream_events(self, handle):
        return
        yield  # pragma: no cover - unreachable, spawn() always raises first

    def cancel(self, handle, tree_kill: bool = True) -> None:
        pass

    def adopt(self) -> list:
        return []

    def health(self, handle):
        return SessionHealth(alive=False)


async def make_store(tmp_path) -> Store:
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_tick_all_once_advances_registered_run_and_unregisters_on_completion(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "sched run")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    scheduler = Scheduler(store)
    scheduler.register(run.id, FakeDriver(script), playbook)

    for _ in range(10):
        await scheduler.tick_all_once()

    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    assert all(u.status == "closed" for u in task_units)

    run_row = await store.get_run(run.id)
    assert run_row.status == "closed"
    assert run_row.closed_at is not None

    assert run.id not in scheduler._orchestrators  # unregistered once finished

    await store.stop()


@pytest.mark.asyncio
async def test_tick_all_once_leaves_a_blocked_run_registered(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj2", str(tmp_path))
    playbook = load_playbook("tests/orchestrator/fixtures/gated_demo.toml")
    run = await store.create_run(project.id, "gated_demo.toml", "sched run 2")
    await materialize(playbook, run.id, store)

    script = {"a": FakeStepScript(artifact={"ok": True}), "b": FakeStepScript(artifact={"ok": True})}
    scheduler = Scheduler(store)
    scheduler.register(run.id, FakeDriver(script), playbook)

    for _ in range(5):
        await scheduler.tick_all_once()

    assert run.id in scheduler._orchestrators  # still waiting on the gate — must not unregister

    run_row = await store.get_run(run.id)
    assert run_row.status == "active"

    await store.stop()


@pytest.mark.asyncio
async def test_tick_all_once_isolates_a_failing_run_from_the_others(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj3", str(tmp_path))
    playbook = load_playbook(FIXTURE)

    broken_run = await store.create_run(project.id, FIXTURE, "broken run")
    await materialize(playbook, broken_run.id, store)

    working_run = await store.create_run(project.id, FIXTURE, "working run")
    await materialize(playbook, working_run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    scheduler = Scheduler(store)
    scheduler.register(broken_run.id, BrokenDriver(), playbook)
    scheduler.register(working_run.id, FakeDriver(script), playbook)

    for _ in range(10):
        await scheduler.tick_all_once()

    # The broken run never crashed the loop: it's still registered, never finished,
    # and its failures were recorded as events rather than propagated.
    assert broken_run.id in scheduler._orchestrators
    broken_events = await store.list_events(broken_run.id)
    assert any(e.type == "run.tick_error" for e in broken_events)

    # The working run made normal progress on every tick despite the other run's
    # failures, and was unregistered once it closed.
    working_task_units = [u for u in await store.list_units(working_run.id) if u.type == "task"]
    assert all(u.status == "closed" for u in working_task_units)

    working_run_row = await store.get_run(working_run.id)
    assert working_run_row.status == "closed"

    assert working_run.id not in scheduler._orchestrators

    await store.stop()
