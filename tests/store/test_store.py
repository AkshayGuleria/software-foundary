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

    units = await store.create_work_units(
        [
            WorkUnit(run_id=run.id, step_id="a", type="task", status="open"),
            WorkUnit(run_id=run.id, step_id="b", type="task", status="open"),
        ]
    )
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
    units = await store.create_work_units(
        [
            WorkUnit(run_id=run.id, step_id="approve", type="human_task", status="ready"),
        ]
    )

    await store.complete_human_task(units[0].id)

    unit = await store.get_unit(units[0].id)
    assert unit.status == "closed"

    await store.stop()


@pytest.mark.asyncio
async def test_write_before_start_or_after_stop_raises(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))

    with pytest.raises(RuntimeError):
        await store.create_project("never-started", "/tmp/never-started")

    await store.start()
    await store.create_project("started", "/tmp/started")
    await store.stop()

    with pytest.raises(RuntimeError):
        await store.create_project("after-stop", "/tmp/after-stop")


@pytest.mark.asyncio
async def test_artifact_gate_and_session_row_lifecycle(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo4", "/tmp/demo4")
    run = await store.create_run(project.id, "pb.toml", "demo run 4")
    units = await store.create_work_units(
        [
            WorkUnit(run_id=run.id, step_id="write_doc", type="task", status="open"),
        ]
    )
    unit = units[0]

    artifact = await store.create_artifact(
        run_id=run.id,
        work_unit_id=unit.id,
        kind="doc",
        produced_by_role="writer",
        payload_json={"text": "hello"},
    )
    artifacts = await store.list_artifacts(run.id)
    assert [a.id for a in artifacts] == [artifact.id]

    gate = await store.create_gate(
        work_unit_id=unit.id,
        artifact_id=artifact.id,
        gate_type="human",
    )
    await store.decide_gate(gate.id, "approved", feedback={"note": "looks good"}, decided_by="alice")

    gates = await store.list_gates_for_run(run.id)
    assert len(gates) == 1
    decided_gate = gates[0]
    assert decided_gate.id == gate.id
    assert decided_gate.decision == "approved"
    assert decided_gate.decided_by == "alice"
    assert decided_gate.decided_at is not None
    assert decided_gate.feedback_json == {"note": "looks good"}

    session_row = await store.create_session_row(work_unit_id=unit.id, driver="claude-code")
    await store.update_session_row(session_row.id, status="running", pid=1234)

    fetched = await store.get_session_row(session_row.id)
    assert fetched.status == "running"
    assert fetched.pid == 1234

    await store.stop()


@pytest.mark.asyncio
async def test_list_projects_and_get_project(tmp_path):
    store = await make_store(tmp_path)
    p1 = await store.create_project("proj-a", "/tmp/a")
    p2 = await store.create_project("proj-b", "/tmp/b")

    all_projects = await store.list_projects()
    assert {p.id for p in all_projects} == {p1.id, p2.id}

    fetched = await store.get_project(p1.id)
    assert fetched.name == "proj-a"
    assert await store.get_project("does-not-exist") is None

    await store.stop()


@pytest.mark.asyncio
async def test_get_run_and_list_runs_with_filters(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj", "/tmp/proj")
    run1 = await store.create_run(project.id, "pb1.toml", "run one")
    run2 = await store.create_run(project.id, "pb2.toml", "run two")
    await store.update_run(run2.id, status="closed")

    assert (await store.get_run(run1.id)).title == "run one"
    assert await store.get_run("does-not-exist") is None

    all_runs = await store.list_runs(project_id=project.id)
    assert {r.id for r in all_runs} == {run1.id, run2.id}

    active_only = await store.list_runs(project_id=project.id, status="active")
    assert [r.id for r in active_only] == [run1.id]

    await store.stop()


@pytest.mark.asyncio
async def test_get_next_artifact_version_increments_per_work_unit(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj2", "/tmp/proj2")
    run = await store.create_run(project.id, "pb.toml", "run")
    units = await store.create_work_units([WorkUnit(run_id=run.id, step_id="a", type="task", status="open")])
    unit = units[0]

    assert await store.get_next_artifact_version(unit.id) == 1

    await store.create_artifact(
        run_id=run.id,
        work_unit_id=unit.id,
        kind="a_artifact",
        version=1,
        produced_by_role="planner",
        payload_json={},
    )
    assert await store.get_next_artifact_version(unit.id) == 2

    await store.create_artifact(
        run_id=run.id,
        work_unit_id=unit.id,
        kind="a_artifact",
        version=2,
        produced_by_role="planner",
        payload_json={},
    )
    assert await store.get_next_artifact_version(unit.id) == 3

    await store.stop()


@pytest.mark.asyncio
async def test_append_event_redacts_payload_before_persisting(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj3", "/tmp/proj3")
    run = await store.create_run(project.id, "pb.toml", "run")

    seq = await store.append_event(run.id, None, "test.event", {"secret_token": "shh", "ok": True})
    events = await store.list_events(run.id, after_seq=seq - 1)
    assert events[0].payload_json["secret_token"] == "***REDACTED***"
    assert events[0].payload_json["ok"] is True

    await store.stop()
