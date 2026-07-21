import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.kg.service import build_kg
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_interference_warning_fires_when_slices_touch_overlapping_files(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "shared.py").write_text("X = 1\n")
    # NOTE: plain `import shared` (not `from proj import shared`) -- build_kg's root
    # is tmp_path/proj itself, so module names are resolved relative to that
    # directory. "from proj import shared" would require a *sibling* package named
    # "proj" containing shared.py, which doesn't exist here and left both files'
    # resolved imports empty (see task-6-report.md for the reproduction).
    (tmp_path / "proj" / "auth.py").write_text("import shared\n")
    (tmp_path / "proj" / "billing.py").write_text("import shared\n")
    kg_snapshot = build_kg(str(tmp_path / "proj"))

    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/playbook/fixtures/fanout_demo.toml")
    run = await store.create_run(project.id, "fanout_demo.toml", "demo")
    await materialize(playbook, run.id, store)

    script = {
        "architecture": FakeStepScript(artifact={"slices": ["auth", "billing"]}),
        "implement": FakeStepScript(artifact={}),  # overridden per-slice below via a subclass in Step 1b
    }

    class _PerSliceDriver(FakeDriver):
        async def stream_events(self, handle):
            step_id = self._handle_step.get(handle.id, "")
            if step_id != "implement":
                async for ev in super().stream_events(handle):
                    yield ev
                return
            from foundry.drivers.base import DriverEvent

            yield DriverEvent(kind="tool_call", payload={"tool": "noop"})
            slice_index = self._slice_counter
            self._slice_counter += 1
            files = ["auth.py"] if slice_index == 0 else ["billing.py"]
            yield DriverEvent(kind="completed", payload={"artifact": {"files": files}})

    driver = _PerSliceDriver(script)
    driver._slice_counter = 0
    orch = Orchestrator(store, driver, playbook, concurrency=10, kg_snapshot=kg_snapshot)

    await orch.tick(run.id)
    gates = await store.list_gates_for_run(run.id)
    await store.decide_gate(next(g for g in gates if g.artifact_id is not None).id, "approved")

    for _ in range(6):
        await orch.tick(run.id)

    events = await store.list_events(run.id)
    warnings = [e for e in events if e.type == "convoy.interference_warning"]
    assert len(warnings) == 1
    assert "shared.py" in warnings[0].payload_json["overlapping_files"]


@pytest.mark.asyncio
async def test_no_warning_when_slices_touch_disjoint_files(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "auth.py").write_text("X = 1\n")
    (tmp_path / "proj" / "billing.py").write_text("Y = 1\n")
    kg_snapshot = build_kg(str(tmp_path / "proj"))

    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/playbook/fixtures/fanout_demo.toml")
    run = await store.create_run(project.id, "fanout_demo.toml", "demo")
    await materialize(playbook, run.id, store)

    from foundry.drivers.base import DriverEvent

    class _PerSliceDriver(FakeDriver):
        async def stream_events(self, handle):
            step_id = self._handle_step.get(handle.id, "")
            if step_id != "implement":
                async for ev in super().stream_events(handle):
                    yield ev
                return
            yield DriverEvent(kind="tool_call", payload={"tool": "noop"})
            slice_index = self._slice_counter
            self._slice_counter += 1
            files = ["auth.py"] if slice_index == 0 else ["billing.py"]
            yield DriverEvent(kind="completed", payload={"artifact": {"files": files}})

    driver = _PerSliceDriver({"architecture": FakeStepScript(artifact={"slices": ["auth", "billing"]})})
    driver._slice_counter = 0
    orch = Orchestrator(store, driver, playbook, concurrency=10, kg_snapshot=kg_snapshot)

    await orch.tick(run.id)
    gates = await store.list_gates_for_run(run.id)
    await store.decide_gate(next(g for g in gates if g.artifact_id is not None).id, "approved")

    for _ in range(6):
        await orch.tick(run.id)

    events = await store.list_events(run.id)
    assert not [e for e in events if e.type == "convoy.interference_warning"]
