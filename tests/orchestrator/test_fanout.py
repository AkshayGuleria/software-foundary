import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
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


async def _setup_with_playbook(tmp_path, playbook, script):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    run = await store.create_run(project.id, "p.toml", "demo run")
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


@pytest.mark.asyncio
async def test_fan_out_over_empty_array_fails_the_convoy_instead_of_deadlocking(tmp_path):
    # Regression: a fan_out array resolving to [] used to create a convoy with
    # no leaf units, which _close_convoys's `if not leaf_units: continue` guard
    # left open forever with no error surfaced anywhere.
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="architecture", role="architect", produces="architecture_artifact", gate="none"),
            StepSpec(
                id="implement",
                role="dev",
                needs=["architecture"],
                fan_out="architecture_artifact.slices",
                produces="code_diff_artifact",
                gate="none",
            ),
        ],
    )
    script = {"architecture": FakeStepScript(artifact={"slices": []})}
    store, run, orch = await _setup_with_playbook(tmp_path, playbook, script)

    for _ in range(3):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    convoy = next(u for u in units if u.type == "convoy")
    assert convoy.status == "failed"

    events = await store.list_events(run.id)
    closed_events = [e for e in events if e.type == "convoy.closed" and e.unit_id == convoy.id]
    assert closed_events
    assert closed_events[-1].payload_json == {"status": "failed", "reason": "empty_fan_out"}

    # Not re-processed as a fresh empty fan-out on later ticks.
    for _ in range(3):
        await orch.tick(run.id)
    convoys = [u for u in (await store.list_units(run.id)) if u.type == "convoy"]
    assert len(convoys) == 1


@pytest.mark.asyncio
async def test_convoy_closes_only_once_every_fan_out_from_branch_closes(tmp_path):
    # Regression: _close_convoys used to pick a single "leaf" step by walking
    # playbook.steps and letting the *last* fan_out_from match win, silently
    # ignoring any other branch chained off the same fan_out step. With a
    # human-gated "review" branch and a gate=none "docs" branch both fanned
    # out from "implement", the convoy must not close just because "docs"
    # (declared last) raced ahead and closed first.
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="architecture", role="architect", produces="architecture_artifact", gate="none"),
            StepSpec(
                id="implement",
                role="dev",
                needs=["architecture"],
                fan_out="architecture_artifact.slices",
                produces="code_diff_artifact",
                gate="none",
            ),
            StepSpec(
                id="review",
                role="reviewer",
                needs=["implement"],
                fan_out_from="implement",
                produces="review_artifact",
                gate="human",
            ),
            StepSpec(
                id="docs",
                role="writer",
                needs=["implement"],
                fan_out_from="implement",
                produces="docs_artifact",
                gate="none",
            ),
        ],
    )
    script = {
        "architecture": FakeStepScript(artifact={"slices": ["a", "b"]}),
        "implement": FakeStepScript(artifact={"diff": "ok"}),
    }
    store, run, orch = await _setup_with_playbook(tmp_path, playbook, script)

    for _ in range(6):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    convoy = next(u for u in units if u.type == "convoy")
    docs_units = [u for u in units if u.step_id == "docs" and u.convoy_id == convoy.id]
    review_units = [u for u in units if u.step_id == "review" and u.convoy_id == convoy.id]
    assert len(docs_units) == 2 and len(review_units) == 2
    assert all(u.status == "closed" for u in docs_units)
    assert all(u.status == "blocked" for u in review_units)  # pending human gate
    # docs (declared last in playbook.steps) closed already; review hasn't --
    # the convoy must not have closed yet (it may be "open" or "ready" --
    # convoy units have no needs of their own so unblock() flips them to
    # "ready" almost immediately; what matters is they never reach "closed").
    assert convoy.status in ("open", "ready")

    gates = await store.list_gates_for_run(run.id)
    for gate in [g for g in gates if g.decision == "pending"]:
        await store.decide_gate(gate.id, "approved")
    for _ in range(4):
        await orch.tick(run.id)

    convoy = next(u for u in (await store.list_units(run.id)) if u.type == "convoy")
    assert convoy.status == "closed"
