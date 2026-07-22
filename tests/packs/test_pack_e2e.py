import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.packs.resolve import resolve_pack_version
from foundry.playbook.lint import lint_plan_first
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_bugfix_pack_playbook_runs_to_completion_with_gate_override(tmp_path):
    playbook_path = "packs/default/playbooks/bugfix.toml"
    playbook = load_playbook(playbook_path)  # the exact, unmodified engine entry point every run uses
    lint_plan_first(playbook)  # the exact, unmodified plan-first invariant check

    pin = resolve_pack_version(playbook_path)
    assert pin == "default@0.1.0"

    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    run = await store.create_run(
        project.id, playbook_path, playbook.description or playbook.id, pack_version_pin=pin
    )
    await materialize(playbook, run.id, store)

    script = {step.id: FakeStepScript(artifact={"ok": True}) for step in playbook.steps}
    driver = FakeDriver(script)
    orch = Orchestrator(store, driver, playbook, gate_overrides={"diagnose": "approved"})

    # `Orchestrator.tick`'s `TickResult.complete` field defaults to True and is
    # never actually set by `tick()` itself (only `run_to_completion` computes
    # it) -- so `getattr(result, "complete", False)` would be True after the
    # very first tick, long before the run is actually done. The real
    # completion signal (matching Scheduler._is_finished, the same check
    # `POST /api/runs`'s polling loop uses to decide when to close a run) is
    # "every task-type work unit has reached status=closed".
    #
    # "diagnose_approval" is a `derived_gate` step (bugfix.toml's plan-first
    # gate for its one writes=true step, "fix") -- distinct from the
    # `diagnose`/`review` human gates. It is never in `gate_overrides` in this
    # test, so like "review" it must be decided the same way a human/dashboard
    # user (or the CLI's own auto-approve convenience loop) would: any pending
    # gate, human or derived, gets approved once it exists.
    for _ in range(10):
        await orch.tick(run.id)
        gates = await store.list_gates_for_run(run.id)
        pending = [g for g in gates if g.decision == "pending" and g.gate_type in ("human", "derived")]
        for g in pending:
            await store.decide_gate(g.id, "approved", decided_by="test")

        units = await store.list_units(run.id)
        task_units = [u for u in units if u.type == "task"]
        if task_units and all(u.status == "closed" for u in task_units):
            break

    units = await store.list_units(run.id)
    task_units = [u for u in units if u.type == "task"]
    assert task_units
    assert all(u.status == "closed" for u in task_units)

    events = await store.list_events(run.id)
    assert any(e.type == "gate.policy_overridden" for e in events)

    await store.stop()
