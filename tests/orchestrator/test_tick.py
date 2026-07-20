import asyncio

import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
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
async def test_linear_playbook_runs_to_completion_on_fake_driver(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a", "b"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)

    result = await orchestrator.run_to_completion(run.id)

    assert result.failed == 0
    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    assert len(task_units) == 3
    assert all(u.status == "closed" for u in task_units)

    artifacts = await store.list_artifacts(run.id)
    assert {a.kind for a in artifacts} == {"plan_artifact", "code_diff_artifact", "review_artifact"}

    await store.stop()


@pytest.mark.asyncio
async def test_crash_mid_session_recovers_on_restart_with_no_duplicate_artifacts(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo2", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run 2")
    await materialize(playbook, run.id, store)

    slow_script = {
        "plan": FakeStepScript(artifact={"steps": ["a"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}, mode="delay", delay_s=5.0),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    orch1 = Orchestrator(store, FakeDriver(slow_script), playbook)

    await orch1.tick(run.id)  # closes "plan"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(orch1.tick(run.id), timeout=0.05)  # "kill -9" mid-"implement" session

    units = await store.list_units(run.id)
    implement_task = next(u for u in units if u.step_id == "implement" and u.type == "task")
    assert implement_task.status == "in_progress"
    implement_session = next(u for u in units if u.type == "session" and u.step_id == "implement")
    assert implement_session.status == "running"

    fast_script = {**slow_script, "implement": FakeStepScript(artifact={"diff": "..."})}
    orch2 = Orchestrator(store, FakeDriver(fast_script), playbook)  # fresh driver: adopt() -> []

    result = await orch2.run_to_completion(run.id)

    assert result.failed == 0
    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    assert all(u.status == "closed" for u in task_units)

    artifacts = await store.list_artifacts(run.id)
    implement_artifacts = [a for a in artifacts if a.kind == "code_diff_artifact"]
    assert len(implement_artifacts) == 1  # no duplicate from the crashed attempt

    retried_events = await store.list_events(run.id)
    assert any(e.type == "unit.retried" for e in retried_events)

    await store.stop()


@pytest.mark.asyncio
async def test_failed_session_retries_then_blocks_after_max_attempts(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo3", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run 3")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(mode="fail", error="always fails"),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)

    await orchestrator.run_to_completion(run.id, max_ticks=10)

    units = await store.list_units(run.id)
    plan_task = next(u for u in units if u.step_id == "plan" and u.type == "task")
    assert plan_task.status == "blocked"
    assert plan_task.attempt == plan_task.max_attempts

    gates = await store.list_gates_for_run(run.id)
    assert any(g.work_unit_id == plan_task.id and g.decision == "pending" for g in gates)

    await store.stop()
