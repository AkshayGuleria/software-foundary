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


@pytest.mark.asyncio
async def test_repeated_gate_rejection_caps_at_max_attempts_then_blocks(tmp_path):
    # Every other retry/reopen path in tick.py (_collect's task-failure retry,
    # reconcile's session-crash retry, the review-loop's max_rounds cap) guards
    # against unbounded reopening with a next_attempt >= cap check. This proves
    # apply_gate_decisions's rejected-gate branch does the same: a unit that
    # keeps getting its gate rejected reopens up to max_attempts times, then
    # blocks with a max_attempts event instead of cycling forever.
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

    await orch.tick(run.id)  # dispatch -> collect -> first gate created, unit blocked

    units = await store.list_units(run.id)
    unit = next(u for u in units if u.step_id == "test_plan")
    assert unit.max_attempts == 3

    for _ in range(unit.max_attempts):
        gates = await store.list_gates_for_run(run.id)
        pending = [g for g in gates if g.decision == "pending"]
        assert pending, "expected a pending gate to reject each round"
        await store.decide_gate(pending[-1].id, "rejected", decided_by="test")
        await orch.tick(run.id)
        unit = await store.get_unit(unit.id)
        # "blocked" alone isn't the cap signal -- the unit is *also* "blocked"
        # every round while it waits on its freshly re-created gate. Only the
        # max_attempts event marks the terminal (no more reopening) state.
        events_so_far = await store.list_events(run.id)
        if any(
            e.type == "unit.blocked" and e.payload_json.get("reason") == "max_attempts" for e in events_so_far
        ):
            break

    assert unit.status == "blocked"
    assert unit.attempt == unit.max_attempts

    events = await store.list_events(run.id)
    assert any(e.type == "unit.blocked" and e.payload_json.get("reason") == "max_attempts" for e in events)

    # Further ticks must not spontaneously reopen the unit -- it stays blocked
    # (a fresh escalation gate is now pending) until a human decides again,
    # rather than looping forever on its own.
    for _ in range(3):
        await orch.tick(run.id)
    unit = await store.get_unit(unit.id)
    assert unit.status == "blocked"
