import pytest

from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_materialize_creates_units_and_dep_edges(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/playbook/fixtures/sdlc_mini.toml")
    run = await store.create_run(project.id, "sdlc_mini.toml", "demo run")

    step_to_unit = await materialize(playbook, run.id, store)
    assert set(step_to_unit) == {"requirement", "architecture", "test_plan", "plan_approval", "implement"}

    units = await store.list_units(run.id)
    assert len(units) == 5
    plan_approval_unit = next(u for u in units if u.step_id == "plan_approval")
    assert plan_approval_unit.type == "gate"
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.type == "task"
    assert implement_unit.status == "open"

    deps = await store.list_deps(run.id)
    implement_deps = [d.needs_unit_id for d in deps if d.unit_id == step_to_unit["implement"]]
    assert implement_deps == [step_to_unit["plan_approval"]]

    plan_approval_deps = {d.needs_unit_id for d in deps if d.unit_id == step_to_unit["plan_approval"]}
    assert plan_approval_deps == {
        step_to_unit["requirement"], step_to_unit["architecture"], step_to_unit["test_plan"],
    }

    await store.stop()
