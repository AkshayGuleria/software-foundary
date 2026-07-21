import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_compound_step_writes_memory_items(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(
        id="p",
        steps=[StepSpec(id="compound", role="reviewer", produces="memory_items_artifact", gate="none")],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    script = {
        "compound": FakeStepScript(
            artifact={
                "items": [
                    {"kind": "lesson", "title": "Watch budgets", "body_md": "Pause, don't kill."},
                    {"kind": "pattern", "title": "Retry with backoff", "body_md": "Reuse the cap logic."},
                ]
            }
        )
    }
    orch = Orchestrator(store, FakeDriver(script), playbook)
    await orch.tick(run.id)

    items = await store.list_memory_items(project_id=project.id)
    assert {i.title for i in items} == {"Watch budgets", "Retry with backoff"}
    assert {i.kind for i in items} == {"lesson", "pattern"}
    assert all(i.source_run_id == run.id for i in items)

    units = await store.list_units(run.id)
    compound_unit = next(u for u in units if u.step_id == "compound")
    assert compound_unit.status == "closed"


@pytest.mark.asyncio
async def test_non_compound_step_does_not_write_memory(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(id="p", steps=[StepSpec(id="plain", role="dev", produces="x", gate="none")])
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    script = {"plain": FakeStepScript(artifact={"items": [{"kind": "lesson"}]})}
    orch = Orchestrator(store, FakeDriver(script), playbook)
    await orch.tick(run.id)

    items = await store.list_memory_items(project_id=project.id)
    assert items == []
