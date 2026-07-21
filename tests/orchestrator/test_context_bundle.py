import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.kg.service import build_kg
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_context_composed_event_fires_on_dispatch(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(id="p", steps=[StepSpec(id="a", role="dev", produces="x", gate="none")])
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    orch = Orchestrator(store, FakeDriver({"a": FakeStepScript(artifact={})}), playbook)
    await orch.tick(run.id)

    events = await store.list_events(run.id)
    composed = [e for e in events if e.type == "context.composed"]
    assert len(composed) == 1
    assert composed[0].payload_json["files_in_bundle"] == 0  # no upstream artifact declared files
    assert composed[0].payload_json["memory_items"] == 0  # no memory exists yet for this project


@pytest.mark.asyncio
async def test_context_bundle_includes_blast_radius_from_upstream_artifact_files(tmp_path):
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
                produces="code_diff_artifact",
                gate="none",
            ),
        ],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    # Build a minimal on-disk project and its KG snapshot so blast_radius has real
    # data to work with. NOTE: the fixture must live *inside* the KG root and be
    # imported by a path resolvable relative to that root (build_kg resolves
    # module names against files under `project_root`, not against the outer
    # package name) -- a plain `import b` from a.py resolves to sibling file
    # b.py; a self-referential `from fixture_project import b` does not resolve
    # to anything under this root and silently produces zero edges.
    (tmp_path / "fixture_project").mkdir()
    (tmp_path / "fixture_project" / "a.py").write_text("import b\n")
    (tmp_path / "fixture_project" / "b.py").write_text("X = 1\n")
    kg_snapshot = build_kg(str(tmp_path / "fixture_project"))

    script = {
        "architecture": FakeStepScript(artifact={"files": ["a.py"]}),
        "implement": FakeStepScript(artifact={}),
    }
    orch = Orchestrator(store, FakeDriver(script), playbook, kg_snapshot=kg_snapshot)

    for _ in range(3):
        await orch.tick(run.id)

    events = await store.list_events(run.id)
    composed = [e for e in events if e.type == "context.composed"]
    implement_event = next(e for e in composed if e.payload_json["files_in_bundle"] > 0)
    assert implement_event.payload_json["files_in_bundle"] >= 2  # a.py + its blast-radius neighbor b.py


@pytest.mark.asyncio
async def test_context_bundle_includes_relevant_memory(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    await store.create_memory_item(
        scope="project",
        kind="lesson",
        title="implement step lesson",
        body_md="always check the budget before dispatching implement work",
        project_id=project.id,
    )
    playbook = PlaybookSpec(id="p", steps=[StepSpec(id="implement", role="dev", produces="x", gate="none")])
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    orch = Orchestrator(store, FakeDriver({"implement": FakeStepScript(artifact={})}), playbook)
    await orch.tick(run.id)

    events = await store.list_events(run.id)
    composed = next(e for e in events if e.type == "context.composed")
    assert composed.payload_json["memory_items"] >= 1
