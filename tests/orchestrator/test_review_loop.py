import pytest

from foundry.drivers.base import DriverEvent
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import LoopSpec, PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


def _playbook():
    return PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="implement", role="dev", produces="code_diff_artifact", gate="none", writes=False),
            StepSpec(
                id="review",
                role="reviewer",
                needs=["implement"],
                produces="review_artifact",
                gate="agent",
                loop=LoopSpec(back_to="implement", max_rounds=3),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_agent_gate_auto_approved_closes_the_reviewed_unit(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = _playbook()
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"diff": "x"}),
            "review": FakeStepScript(artifact={"verdict": "approved"}),
        }
    )
    orch = Orchestrator(store, driver, playbook)

    for _ in range(6):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.status == "closed"
    assert implement_unit.attempt == 0


@pytest.mark.asyncio
async def test_agent_gate_rejection_reworks_the_producing_unit(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = _playbook()
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"diff": "x"}),
            "review": FakeStepScript(artifact={"verdict": "needs_changes"}),
        }
    )
    orch = Orchestrator(store, driver, playbook)

    for _ in range(4):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.attempt >= 1


@pytest.mark.asyncio
async def test_review_loop_escalates_to_human_after_max_rounds(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="implement", role="dev", produces="code_diff_artifact", gate="none"),
            StepSpec(
                id="review",
                role="reviewer",
                needs=["implement"],
                produces="review_artifact",
                gate="agent",
                loop=LoopSpec(back_to="implement", max_rounds=2),
            ),
        ],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    step_to_unit = await materialize(playbook, run.id, store)
    await store.update_unit(step_to_unit["implement"], max_attempts=2)

    driver = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"diff": "x"}),
            "review": FakeStepScript(artifact={"verdict": "needs_changes"}),
        }
    )
    orch = Orchestrator(store, driver, playbook)

    for _ in range(10):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.status == "blocked"
    gates = await store.list_gates_for_run(run.id)
    human_gates = [g for g in gates if g.gate_type == "human" and g.work_unit_id == implement_unit.id]
    assert human_gates


@pytest.mark.asyncio
async def test_review_loop_round_cap_is_loop_max_rounds_not_back_to_units_own_max_attempts(tmp_path):
    """Regression test: the round cap that stops the rework loop must come from the
    review step's own loop.max_rounds, not from the reopened unit's max_attempts field.
    That field is a separate concern (the unit's own driver-failure retry cap,
    enforced by _collect) that defaults to 3 and is never populated from
    loop.max_rounds unless someone remembers to set it manually -- so if the round
    cap were sourced from it instead, a playbook author's max_rounds=2 would be
    silently ignored (escalation wouldn't happen until round 3, the unrelated
    default) whenever the two numbers aren't kept in sync by hand.
    """
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="implement", role="dev", produces="code_diff_artifact", gate="none"),
            StepSpec(
                id="review",
                role="reviewer",
                needs=["implement"],
                produces="review_artifact",
                gate="agent",
                loop=LoopSpec(back_to="implement", max_rounds=2),
            ),
        ],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)
    # Deliberately do NOT override implement's max_attempts -- it stays at the
    # model default (3), which must NOT be what caps the rework loop.

    driver = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"diff": "x"}),
            "review": FakeStepScript(artifact={"verdict": "needs_changes"}),
        }
    )
    orch = Orchestrator(store, driver, playbook)

    for _ in range(10):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.max_attempts == 3, "sanity check: default max_attempts, deliberately not overridden"
    assert implement_unit.status == "blocked"
    assert implement_unit.attempt == 2, "must escalate at loop.max_rounds=2, not max_attempts=3's default"


@pytest.mark.asyncio
async def test_agent_gate_rejection_reworks_the_matching_slice_in_a_fan_out_convoy(tmp_path):
    """Regression test: within a single fan-out convoy every slice's implement/review
    units share the SAME convoy_id (one convoy per fan-out step, not per slice -- see
    Orchestrator._fan_out). A rejected review's rework target must be resolved via the
    review unit's own recorded dependency on its matching implement unit, not just "any
    unit with this step_id and convoy_id" -- otherwise a rejection on one slice could
    silently rework a different, unrelated slice while leaving the actually-rejected
    slice untouched.
    """
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
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
                gate="agent",
                loop=LoopSpec(back_to="implement", max_rounds=3),
            ),
        ],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(
        {
            "architecture": FakeStepScript(artifact={"slices": ["a", "b"]}),
            "implement": FakeStepScript(artifact={"diff": "x"}),
        }
    )
    original_stream = driver.stream_events

    async def _review_aware_stream(handle):
        # Only slice index 1 ("b")'s review is ever rejected; slice index 0 ("a")'s
        # review always approves. If the rework target lookup is ambiguous across
        # slices sharing a convoy_id, this would misdirect "b"'s rejection onto "a".
        if driver._handle_step.get(handle.id, "") != "review":
            async for ev in original_stream(handle):
                yield ev
            return
        gates = await store.list_gates_for_run(run.id)
        gate = next((g for g in gates if g.id == handle.id), None)
        if gate is None:
            # The review *task's* own producing session (dispatch()/_collect()), not
            # the separate reviewer-verdict session _dispatch_agent_reviews spawns
            # (whose handle.id is the gate id). Its artifact content is irrelevant --
            # only the gate's verdict, decided below, matters.
            async for ev in original_stream(handle):
                yield ev
            return
        unit = await store.get_unit(gate.work_unit_id)
        yield DriverEvent(kind="tool_call", payload={"tool": "noop"})
        if unit.payload_json.get("slice_index") == 1:
            yield DriverEvent(kind="completed", payload={"artifact": {"verdict": "needs_changes"}})
        else:
            yield DriverEvent(kind="completed", payload={"artifact": {"verdict": "approved"}})

    driver.stream_events = _review_aware_stream
    orch = Orchestrator(store, driver, playbook, concurrency=10)

    for _ in range(15):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    implement_by_slice = {u.payload_json.get("slice_index"): u for u in units if u.step_id == "implement"}

    assert implement_by_slice[1].attempt >= 1, "the rejected slice's own implement unit must be reworked"
    assert implement_by_slice[0].attempt == 0, "an unrelated, already-approved slice must not be touched"
