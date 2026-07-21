import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def _run_one_tick(tmp_path, step, artifact_payload):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(id="p", steps=[step])
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)
    driver = FakeDriver({step.id: FakeStepScript(artifact=artifact_payload)})
    orch = Orchestrator(store, driver, playbook)
    await orch.tick(run.id)
    return store, run


@pytest.mark.asyncio
async def test_escalation_creates_human_task_when_field_is_nonempty(tmp_path):
    step = StepSpec(
        id="integrate", role="integrator", produces="integration_artifact", escalates_on="escalated"
    )
    store, run = await _run_one_tick(
        tmp_path,
        step,
        {"auto_resolved": ["lockfile"], "escalated": [{"file": "auth.py", "reason": "semantic"}]},
    )

    units = await store.list_units(run.id)
    human_tasks = [u for u in units if u.type == "human_task"]
    assert len(human_tasks) == 1
    task_unit = next(u for u in units if u.step_id == "integrate" and u.type == "task")
    assert task_unit.status == "blocked"

    events = await store.list_events(run.id)
    blocked_events = [e for e in events if e.type == "unit.blocked" and e.unit_id == task_unit.id]
    assert blocked_events
    assert blocked_events[0].payload_json["escalated"] == [{"file": "auth.py", "reason": "semantic"}]


@pytest.mark.asyncio
async def test_no_escalation_when_field_is_empty(tmp_path):
    step = StepSpec(
        id="integrate",
        role="integrator",
        produces="integration_artifact",
        escalates_on="escalated",
        gate="none",
    )
    store, run = await _run_one_tick(tmp_path, step, {"auto_resolved": ["lockfile"], "escalated": []})

    units = await store.list_units(run.id)
    assert not [u for u in units if u.type == "human_task"]
    task_unit = next(u for u in units if u.step_id == "integrate" and u.type == "task")
    assert task_unit.status == "closed"


@pytest.mark.asyncio
async def test_step_without_escalates_on_is_unaffected(tmp_path):
    step = StepSpec(id="plain", role="dev", produces="x", gate="none")
    store, run = await _run_one_tick(tmp_path, step, {"anything": "ignored"})
    units = await store.list_units(run.id)
    assert not [u for u in units if u.type == "human_task"]
