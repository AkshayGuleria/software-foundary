import pytest

from foundry.drivers.base import DriverEvent
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.budget import check_budget
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.models import Run
from foundry.store.store import Store


def _run(token_budget=0, tokens_used=0):
    return Run(
        id="r1",
        project_id="p1",
        playbook_ref="x",
        title="t",
        token_budget=token_budget,
        tokens_used=tokens_used,
    )


def test_zero_budget_is_always_ok():
    assert check_budget(_run(token_budget=0, tokens_used=999_999)) == "ok"


def test_under_80_percent_is_ok():
    assert check_budget(_run(token_budget=1000, tokens_used=500)) == "ok"


def test_between_80_and_100_percent_is_warning():
    assert check_budget(_run(token_budget=1000, tokens_used=850)) == "warning"


def test_at_or_over_100_percent_is_exceeded():
    assert check_budget(_run(token_budget=1000, tokens_used=1000)) == "exceeded"
    assert check_budget(_run(token_budget=1000, tokens_used=1500)) == "exceeded"


class _UsageEmittingFakeDriver(FakeDriver):
    async def stream_events(self, handle):
        yield DriverEvent(kind="usage", payload={"tokens_in": 600, "tokens_out": 500})
        async for ev in super().stream_events(handle):
            yield ev


@pytest.mark.asyncio
async def test_dispatch_pauses_once_budget_exceeded(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="a", role="dev", produces="x", gate="none"),
            StepSpec(id="b", role="dev", needs=["a"], produces="y", gate="none"),
        ],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await store.update_run(run.id, token_budget=1000)
    await materialize(playbook, run.id, store)

    driver = _UsageEmittingFakeDriver({"a": FakeStepScript(artifact={}), "b": FakeStepScript(artifact={})})
    orch = Orchestrator(store, driver, playbook)

    await orch.tick(run.id)  # dispatches "a", consumes 1100 tokens > 1000 budget

    run_row = await store.get_run(run.id)
    assert run_row.tokens_used >= 1000

    await orch.tick(run.id)  # "b" should NOT dispatch — budget exceeded

    units = await store.list_units(run.id)
    b_unit = next(u for u in units if u.step_id == "b")
    assert b_unit.status != "in_progress"
    human_tasks = [u for u in units if u.type == "human_task"]
    assert human_tasks
