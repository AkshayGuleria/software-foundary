from __future__ import annotations

import os

from foundry.demo.toy_repo import generate_toy_repo
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator, TickResult
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.models import utcnow
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
    previous_progress = None
    for _ in range(max_ticks):
        result = await orchestrator.tick(run_id)
        units = await store.list_units(run_id)
        pending = [u for u in units if u.status not in ("closed", "failed", "blocked")]
        if not pending:
            result.complete = True
            return result
        current_progress = result.closed + result.failed
        if current_progress == previous_progress:
            break
        previous_progress = current_progress
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
        await store.update_run(run.id, status="closed", closed_at=utcnow())


async def _seed_active_pending_human_gate_run(store: Store, project, project_dir: str) -> None:
    """Bugfix run stopped right at its first human gate (diagnose)."""
    playbook = load_playbook(BUGFIX_PLAYBOOK)
    run = await store.create_run(project.id, BUGFIX_PLAYBOOK, "Fix export button not responding")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
    # Tick until the diagnose step's artifact is produced and its human
    # gate is pending -- do NOT approve it, that's the whole point of this
    # seed run.
    await _run_to_pending_or_completion(store, run.id, orchestrator)


async def _seed_active_pending_agent_gate_run(store: Store, project, project_dir: str) -> None:
    """SDLC run stopped with its (agent-type) review gate pending.

    Requires the upstream plan_approval derived gate and the human-gated
    requirement/architecture/test_plan steps to already be approved --
    those aren't auto-approved by ticking alone (see cli.py's own _run),
    so this seeds them directly the same way a real dashboard user would
    click through them, then stops before the agent review gate resolves.

    Deviation from a same-tick FakeDriver dispatch: Orchestrator.tick()
    normally creates AND resolves an agent-type gate in the same tick,
    because `_dispatch_agent_reviews` runs right after `dispatch()` and
    FakeDriver's `stream_events` completes synchronously (no delay_s set)
    -- so a plain Orchestrator here would never leave the review gate
    observably pending; by the time `_run_to_pending_or_completion`'s
    stall detection notices, it's already been auto-approved and the run
    has moved on to `integrate`. In real operation this isn't a gap: a
    real driver's `stream_events` call takes actual wall-clock time, so
    the gate `dispatch()` just created stays genuinely pending for that
    whole window under WAL's unrestricted reads. `Orchestrator.tick()` now
    takes a `dispatch_agent_reviews` flag (default True, so every other
    caller and test is unaffected) to opt out of the auto-resolve step for
    a given tick; `_ReviewGateHoldOrchestrator` below just pins that flag
    to False so this seed run's review gate is created but never resolved,
    reproducing the pending window a slow real driver would leave.
    """
    playbook = load_playbook(SDLC_PLAYBOOK)
    run = await store.create_run(project.id, SDLC_PLAYBOOK, "Add CSV export to the reports page")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = _ReviewGateHoldOrchestrator(store, driver, playbook, project_path=project_dir)
    await _run_to_pending_or_completion(store, run.id, orchestrator)

    # Approve the three human gates + the derived plan-approval gate so the
    # implement/review steps can dispatch -- but stop there, leaving the
    # agent-type review gate itself pending.
    for _ in range(10):
        gates = await store.list_gates_for_run(run.id)
        pending = [g for g in gates if g.decision == "pending"]
        review_pending = [g for g in pending if g.gate_type == "agent"]
        if review_pending:
            return
        approvable = [g for g in pending if g.artifact_id is not None or g.gate_type == "derived"]
        if not approvable:
            return
        for gate in approvable:
            await store.decide_gate(gate.id, "approved", decided_by="demo-seed")
        await _run_to_pending_or_completion(store, run.id, orchestrator)


class _ReviewGateHoldOrchestrator(Orchestrator):
    """Orchestrator whose tick() never auto-resolves agent-type review gates.

    Used only by `_seed_active_pending_agent_gate_run` -- see that
    function's docstring for why a plain `Orchestrator` can't produce a
    durably pending agent gate when paired with FakeDriver's synchronous
    `stream_events`.
    """

    async def tick(self, run_id: str) -> TickResult:
        return await super().tick(run_id, dispatch_agent_reviews=False)


async def run_demo_seed(store: Store, base_dir: str) -> None:
    """Populate `store` with a believable slice of a working deployment.

    `base_dir` is where each demo project's generated toy repo lives --
    the caller (CLI command, or the follow-up hot-swap API route) is
    responsible for choosing a directory this can safely write into.
    """
    os.makedirs(base_dir, exist_ok=True)

    acme_dir = os.path.join(base_dir, "acme-reports")
    generate_toy_repo(acme_dir, num_files=12)
    acme = await store.create_project("acme-reports", acme_dir)
    await _seed_closed_successful_run(store, acme, acme_dir)

    beta_dir = os.path.join(base_dir, "beta-dashboard")
    generate_toy_repo(beta_dir, num_files=14)
    beta = await store.create_project("beta-dashboard", beta_dir)
    await _seed_active_pending_human_gate_run(store, beta, beta_dir)
    await _seed_active_pending_agent_gate_run(store, beta, beta_dir)
