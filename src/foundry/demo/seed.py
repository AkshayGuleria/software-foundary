from __future__ import annotations

import os
from datetime import UTC, datetime

from foundry.demo.toy_repo import generate_toy_repo
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator, TickResult
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.store import Store

SDLC_PLAYBOOK = "packs/default/playbooks/sdlc_story.toml"
BUGFIX_PLAYBOOK = "packs/default/playbooks/bugfix.toml"

# Every step in both default-pack playbooks produces one of these kinds;
# a single generic scripted artifact per step id is enough to drive them
# to completion since FakeDriver only inspects `step_id` to pick a script,
# never the artifact schema itself.
_HAPPY_PATH_SCRIPT = {
    "requirement": FakeStepScript(artifact={"summary": "Add CSV export to the reports page"}),
    "architecture": FakeStepScript(artifact={"slices": ["export_button", "csv_writer"]}),
    "test_plan": FakeStepScript(artifact={"cases": ["exports a valid CSV", "handles empty report"]}),
    "implement": FakeStepScript(artifact={"diff": "+ add export_csv()", "files": ["reports/export.py"]}),
    "review": FakeStepScript(artifact={"verdict": "approved"}),
    "integrate": FakeStepScript(artifact={"merged": True}),
    "diagnose": FakeStepScript(artifact={"root_cause": "off-by-one in pagination"}),
    "fix": FakeStepScript(artifact={"diff": "- page - 1\n+ page", "files": ["reports/paginate.py"]}),
}


async def _run_to_pending_or_completion(
    store: Store, run_id: str, orchestrator: Orchestrator, max_ticks: int = 30
) -> TickResult:
    """Tick until the run completes or stops making forward progress.

    Unlike a fixed tick count, this is robust to playbook shape changes --
    it just keeps ticking until either the run reports complete, or two
    consecutive ticks close/fail zero additional units (meaning everything
    remaining is blocked on a pending gate or open human_task, which no
    amount of further ticking will resolve on its own).
    """
    result = TickResult(dispatched=0, closed=0, failed=0, complete=False)
    previous_progress = -1
    for _ in range(max_ticks):
        result = await orchestrator.tick(run_id)
        current_progress = result.closed + result.failed
        # Check if run has no pending units
        units = await store.list_units(run_id)
        pending = [u for u in units if u.status not in ("closed", "failed", "blocked")]
        if not pending:
            result.complete = True
            return result
        # Check if two consecutive ticks made no progress
        if current_progress == 0 and previous_progress == 0:
            break
        previous_progress = current_progress
    # Set complete based on final state
    units = await store.list_units(run_id)
    pending = [u for u in units if u.status not in ("closed", "failed", "blocked")]
    result.complete = not pending
    return result


async def _auto_approve_and_complete(store: Store, run_id: str, orchestrator: Orchestrator) -> None:
    """Tick, auto-approving every approvable gate, until the run completes.

    Mirrors cli.py's `_run` polling loop exactly (same approvable-gate
    filter: only gates with a produced artifact, or a derived plan-approval
    gate -- never blind-approve a no-artifact failure-escalation gate).
    """
    await _run_to_pending_or_completion(store, run_id, orchestrator)
    for _ in range(20):
        gates = await store.list_gates_for_run(run_id)
        approvable = [
            g
            for g in gates
            if g.decision == "pending" and (g.artifact_id is not None or g.gate_type == "derived")
        ]
        if not approvable:
            # One more tick to ensure artifact_ids are attached to any newly created gates
            await _run_to_pending_or_completion(store, run_id, orchestrator)
            # Check again for approvable gates now that artifact_ids may have been attached
            gates = await store.list_gates_for_run(run_id)
            approvable = [
                g
                for g in gates
                if g.decision == "pending" and (g.artifact_id is not None or g.gate_type == "derived")
            ]
            if not approvable:
                return
            # If we found approvable gates after the extra tick, fall through to approve them
        for gate in approvable:
            await store.decide_gate(gate.id, "approved", decided_by="demo-seed")
        await _run_to_pending_or_completion(store, run_id, orchestrator)


async def _seed_closed_successful_run(store: Store, project, project_dir: str) -> None:
    playbook = load_playbook(BUGFIX_PLAYBOOK)
    run = await store.create_run(project.id, BUGFIX_PLAYBOOK, "Fix pagination off-by-one")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
    await _auto_approve_and_complete(store, run.id, orchestrator)

    # Verify all task units are closed before closing the run
    units = await store.list_units(run.id)
    task_units = [u for u in units if u.type == "task"]
    if task_units and all(u.status == "closed" for u in task_units):
        # Close the run now that all tasks are complete
        await store.update_run(run.id, status="closed", closed_at=datetime.now(UTC))


async def run_demo_seed(store: Store, base_dir: str) -> None:
    """Populate `store` with a believable slice of a working deployment.

    `base_dir` is where each demo project's generated toy repo lives --
    the caller (CLI command, or the follow-up hot-swap API route) is
    responsible for choosing a directory this can safely write into.
    """
    os.makedirs(base_dir, exist_ok=True)

    project_dir = os.path.join(base_dir, "acme-reports")
    generate_toy_repo(project_dir, num_files=12)
    project = await store.create_project("acme-reports", project_dir)

    await _seed_closed_successful_run(store, project, project_dir)
