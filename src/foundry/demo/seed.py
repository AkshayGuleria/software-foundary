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


async def _seed_rejection_rework_run(store: Store, project, project_dir: str) -> None:
    """SDLC run whose review gate is rejected once, then approved on rework.

    The original plan for this seed run was to preempt the driver with a
    direct `store.decide_gate(..., "rejected", ...)` write, timed to land
    while the gate was briefly observably pending (the same
    `dispatch_agent_reviews=False` trick `_ReviewGateHoldOrchestrator` uses
    above). That doesn't actually get you a genuine reject-THEN-rework
    sequence: `apply_gate_decisions()` only reopens the *gate's own*
    work unit (the review task) on a rejection -- reopening the *upstream*
    `implement` unit the review is actually judging is extra logic that
    lives inside `_dispatch_agent_reviews` itself (see tick.py's
    `back_to_unit` handling, driven by the playbook's `loop.back_to`). A
    direct write bypasses that method entirely, so nothing would ever
    reopen `implement` for rework -- the "rework" half of this seed run's
    name would be a lie.

    The actual fix needs BOTH decisions to flow through the real
    `_dispatch_agent_reviews` path, just with different verdicts on each
    round. `FakeDriver.script` is a plain dict keyed by step_id -- nothing
    stops a caller from mutating it between ticks. So this driver gets its
    own shallow copy (mutating the shared `_HAPPY_PATH_SCRIPT` dict in
    place would leak into every other seed run built from it) with the
    "review" step's script swapped to a non-"approved" verdict for round 1.
    Ticking then drives review to a genuine "rejected" decision through
    `_dispatch_agent_reviews`, which reopens `implement` via `loop.back_to`
    on its own. Once that's happened, the script is flipped back to
    "approved" so round 2's review -- the exact same code path -- passes,
    and the run finishes out normally. No orchestrator subclassing, no
    direct gate-decision write racing the driver.

    One more wrinkle: the approve-and-advance loop below ticks the
    orchestrator one `tick()` at a time rather than via
    `_run_to_pending_or_completion`. With the script still scripted to
    reject, that helper's multi-tick convergence loop would happily cycle
    reject->rework repeatedly -- each cycle still closes/reopens task
    units, which reads as "progress" and never trips its stall check -- all
    the way up to the review step's own `loop.max_rounds` cap, instead of
    stopping after exactly the one round this seed run wants. Ticking once
    at a time lets the script be flipped back to "approved" the instant the
    first rejection is observed.
    """
    playbook = load_playbook(SDLC_PLAYBOOK)
    run = await store.create_run(project.id, SDLC_PLAYBOOK, "Add bulk delete to the reports page")
    await materialize(playbook, run.id, store)

    # Shallow copy -- see docstring -- so mutating "review" below doesn't
    # affect `_HAPPY_PATH_SCRIPT` or any other seed run sharing it.
    script = dict(_HAPPY_PATH_SCRIPT)
    script["review"] = FakeStepScript(artifact={"verdict": "needs_changes"})
    driver = FakeDriver(script)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
    await _run_to_pending_or_completion(store, run.id, orchestrator)

    # Approve human/derived gates one single tick at a time -- deliberately
    # NOT via _run_to_pending_or_completion's multi-tick convergence loop
    # here. With the script still scripted to reject, that loop would keep
    # cycling reject->rework indefinitely: each cycle still closes/reopens
    # task units, which counts as "progress" and never trips its stall
    # check, so it would run all the way up to the review step's own
    # loop.max_rounds cap instead of stopping after exactly one round. One
    # tick at a time lets this catch the review step's FIRST rejection
    # (fired for real, through _dispatch_agent_reviews, the same tick it
    # dispatches review) and flip the script back to "approved" right
    # after -- before a second reject-rework round gets a chance to run.
    for _ in range(15):
        gates = await store.list_gates_for_run(run.id)
        pending = [g for g in gates if g.decision == "pending"]
        approvable = [g for g in pending if g.artifact_id is not None or g.gate_type == "derived"]
        for gate in approvable:
            await store.decide_gate(gate.id, "approved", decided_by="demo-seed")
        await orchestrator.tick(run.id)

        gates = await store.list_gates_for_run(run.id)
        if any(g.decision == "rejected" for g in gates):
            driver.script["review"] = FakeStepScript(artifact={"verdict": "approved"})
            break

    # Round 2: implement re-dispatches (it was reopened by the rejection's
    # loop.back_to handling), a fresh review gate opens, and this time the
    # now-"approved" script drives the normal agent-auto-decide path via
    # the same _dispatch_agent_reviews code as round 1 -- through to the
    # human gate at integrate.
    await _auto_approve_and_complete(store, run.id, orchestrator)


async def _seed_cancelled_run(store: Store, project, project_dir: str) -> None:
    """A run cancelled mid-flight -- direct writes, matching how the real
    POST /runs/{id}/cancel route does it (src/foundry/api/routes/runs.py).
    """
    playbook = load_playbook(BUGFIX_PLAYBOOK)
    run = await store.create_run(project.id, BUGFIX_PLAYBOOK, "Investigate slow report generation")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
    await orchestrator.tick(run.id)  # get it started, a unit or two in progress

    units = await store.list_units(run.id)
    for unit in units:
        if unit.status not in ("closed", "failed", "killed", "cancelled"):
            await store.update_unit(unit.id, status="killed")
    await store.update_run(run.id, status="cancelled")


async def _seed_budget_exceeded_run(store: Store, project, project_dir: str) -> None:
    """A run whose token_budget is exhausted, producing an open human_task
    unit via the real dispatch() budget-exceeded path (tick.py) rather
    than a direct write -- this state IS reachable by construction, it
    just needs tokens_used pushed past token_budget before ticking.

    Confirmed by reading tick.py's dispatch(): it computes ready_tasks
    and slots, then checks `check_budget(run) == "exceeded"` BEFORE the
    dispatch loop that would hand work to any ready task -- so setting
    tokens_used > token_budget prior to the first tick guarantees no task
    ever dispatches; dispatch() instead appends a `budget.exceeded` event
    (once, guarded by an already-flagged scan of prior events) and creates
    exactly one `WorkUnit(step_id="_budget", type="human_task",
    status="open")`, then returns 0.

    Deviation from every other seed run in this file: this one calls
    `orchestrator.tick()` directly, ONCE, instead of going through
    `_run_to_pending_or_completion`. Verified empirically (a standalone
    script inspecting the resulting units) that ticking more than once
    changes the unit's status out from under the "open" claim: `tick()`'s
    own `unblock()` step runs `Store.get_ready_units()` first, which
    matches ANY unit with status "open" and all deps closed -- and the
    `_budget` human_task has no deps at all (it's created directly by
    dispatch(), never wired into UnitDep), so on the *second* tick,
    `unblock()` flips it from "open" straight to "ready" before dispatch()
    even runs again. `_run_to_pending_or_completion` always ticks at least
    twice (its stall check needs two equal-progress readings before it can
    break), so using it here would silently turn this into a "ready"
    human_task, not the "open" one the seed data (and its test) actually
    wants. A single `tick()` call is also all this state needs: the
    budget check runs before the dispatch loop that would hand out any
    ready task, so tokens_used > token_budget guarantees zero dispatch on
    the very first tick, same as on every later one.
    """
    playbook = load_playbook(BUGFIX_PLAYBOOK)
    run = await store.create_run(project.id, BUGFIX_PLAYBOOK, "Refactor report caching layer")
    await store.update_run(run.id, token_budget=1000, tokens_used=1500)
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
    await orchestrator.tick(run.id)


async def _seed_memory_items(store: Store, project) -> None:
    await store.create_memory_item(
        scope="project",
        kind="lesson",
        title="Paginate before you filter",
        body_md="Filtering the full result set before pagination caused a "
        "timeout on large reports. Apply filters in the SQL query, not "
        "after fetching.",
        project_id=project.id,
    )
    await store.create_memory_item(
        scope="project",
        kind="pattern",
        title="CSV export reuses the report's existing serializer",
        body_md="Don't write a second serialization path for exports -- "
        "the report view's own row formatter already handles every edge "
        "case (null fields, currency formatting).",
        project_id=project.id,
    )
    await store.create_memory_item(
        scope="project",
        kind="pitfall",
        title="Off-by-one in manual pagination math",
        body_md="`page - 1` vs `page` as the offset multiplier bit us "
        "twice in this project. Prefer the shared paginate() helper over "
        "hand-rolled offset math.",
        project_id=project.id,
    )


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

    gamma_dir = os.path.join(base_dir, "gamma-api")
    generate_toy_repo(gamma_dir, num_files=10)
    gamma = await store.create_project("gamma-api", gamma_dir)
    await _seed_rejection_rework_run(store, gamma, gamma_dir)
    await _seed_cancelled_run(store, gamma, gamma_dir)

    delta_dir = os.path.join(base_dir, "delta-billing")
    generate_toy_repo(delta_dir, num_files=8)
    delta = await store.create_project("delta-billing", delta_dir)
    await _seed_budget_exceeded_run(store, delta, delta_dir)

    epsilon_dir = os.path.join(base_dir, "epsilon-notifications")
    generate_toy_repo(epsilon_dir, num_files=9)
    epsilon = await store.create_project("epsilon-notifications", epsilon_dir)
    await _seed_closed_successful_run(store, epsilon, epsilon_dir)

    for proj in (acme, beta, gamma, delta, epsilon):
        await _seed_memory_items(store, proj)

    # Varied per-project settings so the Settings form / NewRunForm
    # pre-fill have something real to show instead of every project
    # sitting on the same defaults.
    await store.update_project(
        acme.id, default_driver="fake", default_token_budget=50000, default_playbook_path=BUGFIX_PLAYBOOK
    )
    await store.update_project(
        beta.id, default_driver="codex", default_token_budget=100000, default_playbook_path=SDLC_PLAYBOOK
    )
    await store.update_project(
        gamma.id, default_driver="claude", default_token_budget=75000, default_playbook_path=SDLC_PLAYBOOK
    )
    await store.update_project(
        delta.id, default_driver="fake", default_token_budget=1000, default_playbook_path=BUGFIX_PLAYBOOK
    )
    await store.update_project(
        epsilon.id, default_driver="codex", default_token_budget=30000, default_playbook_path=BUGFIX_PLAYBOOK
    )

    # Project lifecycle variety -- pause one, archive another, matching
    # every Project.status value the dashboard renders differently.
    await store.update_project(delta.id, status="paused")
    await store.update_project(epsilon.id, status="archived")

    # acme and epsilon only got one run each above -- give both a second
    # run so every project has 2+ runs (spec: "2-4 runs spanning every
    # state"), reusing Task 3/4's helpers as-is since neither hardcodes
    # which project it's called with.
    await _seed_active_pending_human_gate_run(store, acme, acme_dir)
    await _seed_cancelled_run(store, epsilon, epsilon_dir)
