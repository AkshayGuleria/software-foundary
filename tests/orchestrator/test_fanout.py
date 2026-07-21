import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def _setup(tmp_path, script):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/playbook/fixtures/fanout_demo.toml")
    run = await store.create_run(project.id, "fanout_demo.toml", "demo run")
    await materialize(playbook, run.id, store)
    driver = FakeDriver(script)
    orch = Orchestrator(store, driver, playbook, concurrency=10)
    return store, run, orch


@pytest.mark.asyncio
async def test_fan_out_creates_convoy_and_per_slice_units_once_architecture_closes(tmp_path):
    script = {"architecture": FakeStepScript(artifact={"slices": ["auth", "billing", "notifications"]})}
    store, run, orch = await _setup(tmp_path, script)

    # Drive architecture (human-gated) to closed.
    await orch.tick(run.id)  # dispatches architecture
    units = await store.list_units(run.id)
    # architecture has gate="human": find its gate and approve it.
    gates = await store.list_gates_for_run(run.id)
    arch_gate = next(g for g in gates if g.artifact_id is not None)
    await store.decide_gate(arch_gate.id, "approved")
    await orch.tick(run.id)  # apply_gate_decisions closes the architecture task unit

    await orch.tick(run.id)  # this tick should run _fan_out

    units = await store.list_units(run.id)
    convoys = [u for u in units if u.type == "convoy"]
    assert len(convoys) == 1
    assert convoys[0].step_id == "implement"

    implement_units = [u for u in units if u.step_id == "implement" and u.convoy_id == convoys[0].id]
    review_units = [u for u in units if u.step_id == "review" and u.convoy_id == convoys[0].id]
    assert len(implement_units) == 3
    assert len(review_units) == 3
    assert {u.payload_json["slice"] for u in implement_units} == {"auth", "billing", "notifications"}

    integrate_units = [u for u in units if u.step_id == "integrate"]
    assert len(integrate_units) == 1
    deps = await store.list_deps(run.id)
    integrate_deps = {d.needs_unit_id for d in deps if d.unit_id == integrate_units[0].id}
    assert integrate_deps == {convoys[0].id}


@pytest.mark.asyncio
async def test_fan_out_does_not_fire_while_upstream_gate_is_still_pending(tmp_path):
    # Regression test: the session unit dispatch() creates for "architecture"
    # shares that step's step_id (see Orchestrator.dispatch), and FakeDriver
    # closes it synchronously. If _fan_out's step_id -> unit lookup ever
    # picks up that session instead of the architecture *task* unit, it
    # would see "closed" and treat the human gate as satisfied even though
    # the task itself is still "blocked" pending approval — bypassing the
    # gate entirely.
    script = {"architecture": FakeStepScript(artifact={"slices": ["auth", "billing", "notifications"]})}
    store, run, orch = await _setup(tmp_path, script)

    await orch.tick(run.id)  # dispatches architecture; session closes, task blocks on gate
    gates = await store.list_gates_for_run(run.id)
    arch_gate = next(g for g in gates if g.artifact_id is not None)
    assert arch_gate.decision == "pending"

    await orch.tick(run.id)  # must NOT fan out: the gate is still pending

    units = await store.list_units(run.id)
    arch_task = next(u for u in units if u.step_id == "architecture" and u.type == "task")
    assert arch_task.status == "blocked"
    assert [u for u in units if u.type == "convoy"] == []


@pytest.mark.asyncio
async def test_fan_out_is_idempotent_across_ticks(tmp_path):
    script = {"architecture": FakeStepScript(artifact={"slices": ["a", "b"]})}
    store, run, orch = await _setup(tmp_path, script)
    await orch.tick(run.id)
    gates = await store.list_gates_for_run(run.id)
    await store.decide_gate(next(g for g in gates if g.artifact_id is not None).id, "approved")
    for _ in range(4):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    convoys = [u for u in units if u.type == "convoy"]
    assert len(convoys) == 1  # not re-expanded on every subsequent tick


@pytest.mark.asyncio
async def test_convoy_closes_once_every_leaf_slice_unit_closes(tmp_path):
    script = {
        "architecture": FakeStepScript(artifact={"slices": ["a", "b"]}),
        "implement": FakeStepScript(artifact={"diff": "ok"}),
        "review": FakeStepScript(artifact={"verdict": "approved"}),
    }
    store, run, orch = await _setup(tmp_path, script)
    await orch.tick(run.id)
    gates = await store.list_gates_for_run(run.id)
    await store.decide_gate(next(g for g in gates if g.artifact_id is not None).id, "approved")

    for _ in range(15):
        await orch.tick(run.id)
        units = await store.list_units(run.id)
        gates = await store.list_gates_for_run(run.id)
        pending_agent_gates = [g for g in gates if g.decision == "pending" and g.gate_type == "agent"]
        for g in pending_agent_gates:
            await store.decide_gate(g.id, "approved")

    units = await store.list_units(run.id)
    convoy = next(u for u in units if u.type == "convoy")
    assert convoy.status == "closed"
