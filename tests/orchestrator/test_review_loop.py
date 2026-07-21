import pytest

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
