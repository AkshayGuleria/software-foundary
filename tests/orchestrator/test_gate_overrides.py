import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_gate_override_auto_approves_without_leaving_gate_pending(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(
        id="p", steps=[StepSpec(id="test_plan", role="qa", produces="test_plan_artifact", gate="human")]
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    orch = Orchestrator(
        store,
        FakeDriver({"test_plan": FakeStepScript(artifact={})}),
        playbook,
        gate_overrides={"test_plan": "approved"},
    )
    await orch.tick(run.id)
    await orch.tick(run.id)  # apply_gate_decisions picks up the pre-decided gate

    units = await store.list_units(run.id)
    unit = next(u for u in units if u.step_id == "test_plan")
    assert unit.status == "closed"

    gates = await store.list_gates_for_run(run.id)
    gate = next(g for g in gates if g.work_unit_id == unit.id)
    assert gate.decision == "approved"
    assert gate.decided_by == "run_override"

    events = await store.list_events(run.id)
    assert any(e.type == "gate.policy_overridden" for e in events)


@pytest.mark.asyncio
async def test_no_override_leaves_gate_pending_as_before(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(
        id="p", steps=[StepSpec(id="test_plan", role="qa", produces="test_plan_artifact", gate="human")]
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    orch = Orchestrator(store, FakeDriver({"test_plan": FakeStepScript(artifact={})}), playbook)
    await orch.tick(run.id)

    gates = await store.list_gates_for_run(run.id)
    assert gates[0].decision == "pending"
