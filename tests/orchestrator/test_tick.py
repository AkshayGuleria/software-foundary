import asyncio

import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.models import WorkUnit
from foundry.store.store import Store

FIXTURE = "tests/orchestrator/fixtures/linear_demo.toml"
GATED_FIXTURE = "tests/orchestrator/fixtures/gated_demo.toml"


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
async def test_reconcile_marks_the_crashed_session_row_failed_not_just_the_unit(tmp_path):
    # Regression: reconcile()'s dead-session branch used to update only the
    # session WorkUnit's status to "failed", never the parallel SessionRow
    # audit row (dispatch() creates one alongside every session unit) --
    # SessionRow.status stayed stuck at "running" forever for a genuinely
    # crashed session. metrics/rollup.py's crash_count filters SessionRow by
    # status == "failed", so a real crash was invisible to that metric even
    # though the session WorkUnit correctly recorded the failure.
    store = await make_store(tmp_path)
    project = await store.create_project("demo2b", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run 2b")
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
    implement_session = next(u for u in units if u.type == "session" and u.step_id == "implement")
    session_row_before = await store.get_session_row(implement_session.id)
    assert session_row_before.status == "running"

    fast_script = {**slow_script, "implement": FakeStepScript(artifact={"diff": "..."})}
    fresh_orch = Orchestrator(store, FakeDriver(fast_script), playbook)  # fresh driver: adopt() -> []
    await fresh_orch.tick(run.id)  # reconcile() discovers the dead session

    session_row_after = await store.get_session_row(implement_session.id)
    assert session_row_after.status == "failed"

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


@pytest.mark.asyncio
async def test_reconcile_recovers_task_orphaned_after_session_finalized_no_artifact(tmp_path):
    """Finding 1: session closed, task never finalized, no artifact was ever produced.

    This reproduces the crash window between session-close and task-close without
    relying on timing: the orphaned state is constructed directly via store writes
    (a closed session row + a task manually left "in_progress"), exactly as it would
    look immediately after a process crash in that gap.
    """
    store = await make_store(tmp_path)
    project = await store.create_project("demo4", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run 4")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    orch1 = Orchestrator(store, FakeDriver(script), playbook)
    await orch1.tick(run.id)  # dispatches "plan" through a real session and closes it normally

    units = await store.list_units(run.id)
    implement_task = next(u for u in units if u.step_id == "implement" and u.type == "task")
    assert implement_task.status == "open"  # not yet unblocked by the orchestrator

    # Directly construct the orphaned state: a session that finished (closed) owning
    # a task that was never finalized — no dispatch()/_collect() call involved.
    orphan_session = (
        await store.create_work_units(
            [WorkUnit(run_id=run.id, step_id="implement", type="session", status="closed")]
        )
    )[0]
    await store.update_unit(implement_task.id, owner_session_id=orphan_session.id, status="in_progress")

    fresh_orch = Orchestrator(store, FakeDriver(script), playbook)
    result = await fresh_orch.run_to_completion(run.id)

    assert result.complete is True
    units = await store.list_units(run.id)
    implement_task = next(u for u in units if u.step_id == "implement" and u.type == "task")
    review_task = next(u for u in units if u.step_id == "review" and u.type == "task")
    assert implement_task.status == "closed"
    assert review_task.status == "closed"

    artifacts = await store.list_artifacts(run.id)
    implement_artifacts = [a for a in artifacts if a.kind == "code_diff_artifact"]
    assert len(implement_artifacts) == 1  # retried once, exactly one artifact produced

    events = await store.list_events(run.id)
    assert any(
        e.type == "unit.retried" and e.payload_json.get("reason") == "orphaned_after_session_finalized"
        for e in events
    )

    await store.stop()


@pytest.mark.asyncio
async def test_reconcile_recovers_orphaned_task_with_existing_artifact_closes_directly(tmp_path):
    """Finding 1: session closed, task never finalized, but the artifact already exists.

    The crash happened between artifact creation and task close/block — the fix must
    not redo the agent's work or create a duplicate artifact, just finalize the task.
    """
    store = await make_store(tmp_path)
    project = await store.create_project("demo5", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run 5")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    orch1 = Orchestrator(store, FakeDriver(script), playbook)
    await orch1.tick(run.id)  # dispatches "plan" through a real session and closes it normally

    units = await store.list_units(run.id)
    implement_task = next(u for u in units if u.step_id == "implement" and u.type == "task")

    orphan_session = (
        await store.create_work_units(
            [WorkUnit(run_id=run.id, step_id="implement", type="session", status="closed")]
        )
    )[0]
    await store.update_unit(implement_task.id, owner_session_id=orphan_session.id, status="in_progress")
    await store.create_artifact(
        run_id=run.id,
        work_unit_id=implement_task.id,
        kind="code_diff_artifact",
        version=1,
        produced_by_role="developer",
        payload_json={"diff": "pre-crash"},
    )

    fresh_orch = Orchestrator(store, FakeDriver(script), playbook)
    result = await fresh_orch.run_to_completion(run.id)

    assert result.complete is True
    units = await store.list_units(run.id)
    implement_task = next(u for u in units if u.step_id == "implement" and u.type == "task")
    assert implement_task.status == "closed"
    assert implement_task.attempt == 0  # no retry: no new session was ever spawned

    artifacts = await store.list_artifacts(run.id)
    implement_artifacts = [a for a in artifacts if a.kind == "code_diff_artifact"]
    assert len(implement_artifacts) == 1  # the pre-crash artifact only, no duplicate

    events = await store.list_events(run.id)
    assert any(e.type == "unit.closed" and e.payload_json.get("recovered") is True for e in events)

    await store.stop()


@pytest.mark.asyncio
async def test_reconcile_recovers_orphaned_gated_task_with_pending_gate(tmp_path):
    """The crash-recovery path for a gated step creates the same kind of pending
    gate the normal success path does — it must not auto-approve either."""
    store = await make_store(tmp_path)
    project = await store.create_project("demo7", str(tmp_path))
    playbook = load_playbook(GATED_FIXTURE)
    run = await store.create_run(project.id, GATED_FIXTURE, "gated demo run 2")
    await materialize(playbook, run.id, store)

    units = await store.list_units(run.id)
    a_task = next(u for u in units if u.step_id == "a" and u.type == "task")

    orphan_session = (
        await store.create_work_units([WorkUnit(run_id=run.id, step_id="a", type="session", status="closed")])
    )[0]
    await store.update_unit(a_task.id, owner_session_id=orphan_session.id, status="in_progress")
    await store.create_artifact(
        run_id=run.id,
        work_unit_id=a_task.id,
        kind="a_artifact",
        version=1,
        produced_by_role="planner",
        payload_json={"ok": True},
    )

    script = {
        "a": FakeStepScript(artifact={"ok": True}),
        "b": FakeStepScript(artifact={"ok": True}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)
    result = await orchestrator.run_to_completion(run.id)

    assert result.complete is False
    a_task = await store.get_unit(a_task.id)
    assert a_task.status == "blocked"

    gates = await store.list_gates_for_run(run.id)
    assert len(gates) == 1
    assert gates[0].work_unit_id == a_task.id
    assert gates[0].decision == "pending"

    artifacts = await store.list_artifacts(run.id)
    a_artifacts = [x for x in artifacts if x.kind == "a_artifact"]
    assert len(a_artifacts) == 1  # recovery reused the existing artifact, didn't duplicate it

    events = await store.list_events(run.id)
    assert any(e.type == "gate.created" and e.payload_json.get("recovered") is True for e in events)

    await store.decide_gate(gates[0].id, "approved", decided_by="test-human")
    result = await orchestrator.run_to_completion(run.id)
    assert result.complete is True

    await store.stop()


@pytest.mark.asyncio
async def test_gated_step_creates_pending_gate_then_completes_once_decided(tmp_path):
    """M1: gates on successful steps stay pending until a human (here, the test
    standing in for the API) decides — they no longer auto-approve."""
    store = await make_store(tmp_path)
    project = await store.create_project("demo6", str(tmp_path))
    playbook = load_playbook(GATED_FIXTURE)
    run = await store.create_run(project.id, GATED_FIXTURE, "gated demo run")
    await materialize(playbook, run.id, store)

    script = {
        "a": FakeStepScript(artifact={"ok": True}),
        "b": FakeStepScript(artifact={"ok": True}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)

    result = await orchestrator.run_to_completion(run.id)
    assert result.complete is False

    gates = await store.list_gates_for_run(run.id)
    assert len(gates) == 1
    assert gates[0].decision == "pending"

    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    a_task = next(u for u in task_units if u.step_id == "a")
    b_task = next(u for u in task_units if u.step_id == "b")
    assert a_task.status == "blocked"
    assert b_task.status == "open"  # never unblocked — "a" hasn't closed yet

    await store.decide_gate(gates[0].id, "approved", decided_by="test-human")
    result = await orchestrator.run_to_completion(run.id)

    assert result.complete is True
    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    assert all(u.status == "closed" for u in task_units)

    await store.stop()


@pytest.mark.asyncio
async def test_reject_then_rework_increments_artifact_version(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo8", str(tmp_path))
    playbook = load_playbook(GATED_FIXTURE)
    run = await store.create_run(project.id, GATED_FIXTURE, "rework demo run")
    await materialize(playbook, run.id, store)

    script = {
        "a": FakeStepScript(artifact={"round": 1}),
        "b": FakeStepScript(artifact={"ok": True}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)
    await orchestrator.run_to_completion(run.id)

    gates = await store.list_gates_for_run(run.id)
    assert len(gates) == 1
    await store.decide_gate(gates[0].id, "rejected", feedback={"note": "try again"}, decided_by="test-human")

    # rejection reopens the task; give it a fresh script for round 2 and re-run
    orchestrator.driver = FakeDriver(
        {"a": FakeStepScript(artifact={"round": 2}), "b": FakeStepScript(artifact={"ok": True})}
    )
    await orchestrator.run_to_completion(run.id)

    artifacts = await store.list_artifacts(run.id)
    a_artifacts = sorted([x for x in artifacts if x.kind == "a_artifact"], key=lambda a: a.version)
    assert [a.version for a in a_artifacts] == [1, 2]
    assert a_artifacts[0].payload_json == {"round": 1}
    assert a_artifacts[1].payload_json == {"round": 2}

    await store.stop()
