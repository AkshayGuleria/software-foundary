# Demo Mode Seed Data Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A `foundry demo-seed` CLI command that populates a fresh SQLite db
with realistic, varied demo data — closing the "seed data" half of
`docs/superpowers/specs/2026-07-25-demo-mode-design.md` (the hot-swap API +
UI toggle half is a separate follow-up plan, since it depends on this one's
seeding function being importable).

**Architecture:** A new `src/foundry/demo/` package: a toy-repo generator
(pure filesystem function), a seed module driving real `Orchestrator`
runs on `FakeDriver` for the common-path states plus targeted direct
`Store` writes for states unreachable by construction (cancelled runs,
paused/archived projects, backdated timestamps, varied settings), and a
thin CLI command wiring it together. Every seeding function is built to be
called from either the CLI or (in the follow-up plan) an API route — no
CLI-only logic.

**Tech Stack:** Python 3.12+, existing `Orchestrator`/`Store`/`FakeDriver`
stack, Typer.

## Global Constraints

- No new dependencies.
- Runs entirely offline — `FakeDriver` only, never `CodexDriver`/`ClaudeCodeDriver`.
- Not a replacement for `tests/fixtures/` — those stay untouched.
- Seeding logic must be an importable function (`run_demo_seed`), not a
  CLI-command-only script — the follow-up hot-swap plan calls it directly.
- The toy on-disk repo is generated fresh each run (not committed to this
  repo) into a directory under the demo db's own base directory.
- `demo-seed` must never silently touch a real `foundry.db` — require an
  explicit `--db` path, default it to something obviously demo-named.

---

### Task 1: Toy repo generator

**Files:**
- Create: `src/foundry/demo/__init__.py`
- Create: `src/foundry/demo/toy_repo.py`
- Test: `tests/demo/__init__.py`, `tests/demo/test_toy_repo.py`

**Interfaces:**
- Produces: `generate_toy_repo(dest_dir: str, num_files: int = 12) -> None`
  — creates `dest_dir` if needed, writes `num_files` Python modules with
  real import relationships plus an `__init__.py`. Task 2+ calls this once
  per demo project, pointing `dest_dir` at that project's `path`.

- [ ] **Step 1: Write the failing test**

Create `tests/demo/__init__.py` (empty file) and `tests/demo/test_toy_repo.py`:

```python
from foundry.demo.toy_repo import generate_toy_repo
from foundry.kg.service import build_kg


def test_generate_toy_repo_creates_the_requested_number_of_modules(tmp_path):
    dest = tmp_path / "toy_repo"
    generate_toy_repo(str(dest), num_files=10)

    module_files = sorted(p.name for p in dest.iterdir() if p.name.startswith("module_"))
    assert module_files == [f"module_{i}.py" for i in range(10)]
    assert (dest / "__init__.py").exists()


def test_generate_toy_repo_produces_a_real_resolvable_import_graph(tmp_path):
    dest = tmp_path / "toy_repo"
    generate_toy_repo(str(dest), num_files=10)

    snapshot = build_kg(str(dest))

    # Every module_i (except the last) imports module_{i+1} -- confirm at
    # least the first link resolves to a real edge, not an unresolvable
    # import build_kg silently drops.
    assert "module_1.py" in snapshot.imports.get("module_0.py", set())
    # A genuinely non-trivial graph: more than just the linear chain (the
    # diamond edge described in Step 3), so build_kg has something more
    # interesting than "one big line" to render.
    total_edges = sum(len(targets) for targets in snapshot.imports.values())
    assert total_edges > 9  # linear chain alone is 9 edges for 10 files; the diamond adds one more
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/demo/test_toy_repo.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.demo'`.

- [ ] **Step 3: Implement the generator**

Create `src/foundry/demo/__init__.py` (empty file).

Create `src/foundry/demo/toy_repo.py`:

```python
from __future__ import annotations

import os


def generate_toy_repo(dest_dir: str, num_files: int = 12) -> None:
    """Generate a small synthetic Python package with real import edges.

    Uses plain `import module_N` statements (not `from . import module_N`)
    because `foundry.kg.service.build_kg`'s import resolver only follows
    `ast.Import` nodes and `ast.ImportFrom` nodes with a non-empty `module`
    -- a pure relative `from . import X` has `node.module is None` and is
    silently skipped, which would make every generated file look edge-less
    to the knowledge graph despite genuinely importing its neighbor.
    """
    os.makedirs(dest_dir, exist_ok=True)

    for i in range(num_files):
        lines = []
        if i < num_files - 1:
            lines.append(f"import module_{i + 1}")
        # One diamond edge partway through the chain, so the graph isn't
        # purely linear -- gives the Knowledge view something more
        # interesting to render than a single straight line.
        if i == 2 and num_files > 5:
            lines.append(f"import module_{num_files - 1}")
        lines.append("")
        lines.append("")
        lines.append(f"def demo_function_{i}():")
        lines.append(f"    return {i}")
        lines.append("")

        with open(os.path.join(dest_dir, f"module_{i}.py"), "w") as f:
            f.write("\n".join(lines))

    with open(os.path.join(dest_dir, "__init__.py"), "w") as f:
        f.write("")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/demo/test_toy_repo.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/foundry/demo/__init__.py src/foundry/demo/toy_repo.py \
        tests/demo/__init__.py tests/demo/test_toy_repo.py
git commit -m "feat(demo): add toy repo generator for demo-mode knowledge graphs

Plain import module_N statements, not from . import -- build_kg's
resolver only follows ast.Import and non-empty-module ast.ImportFrom
nodes, so relative imports would silently produce an edge-less graph."
```

---

### Task 2: Seed module core + one closed-successful run

**Files:**
- Create: `src/foundry/demo/seed.py`
- Test: `tests/demo/test_seed.py`

**Interfaces:**
- Consumes: `generate_toy_repo` (Task 1).
- Produces: `_run_to_pending_or_completion(store, run_id, orchestrator, max_ticks=30) -> TickResult`
  — ticks repeatedly until the run either completes or every unit is
  blocked on something that won't resolve itself (a pending gate, an open
  human_task). Tasks 3-5 reuse this instead of a fixed tick count, since
  the exact number of ticks needed depends on playbook shape.
- Produces: `_auto_approve_and_complete(store, run_id, orchestrator) -> None`
  — ticks and auto-approves every approvable gate (mirroring `cli.py`'s
  `_run` polling loop) until the run completes. Used for the
  closed-successful and closed-with-rejection-rework runs.
- Produces: `run_demo_seed(store: Store, base_dir: str) -> None` — the
  top-level entry point. This task builds it with exactly ONE project/run
  (closed-successful); Tasks 3-5 extend the same function with more.

- [ ] **Step 1: Write the failing test**

Create `tests/demo/test_seed.py`:

```python
import pytest

from foundry.demo.seed import run_demo_seed
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def _make_store(tmp_path) -> Store:
    engine = make_engine(str(tmp_path / "demo.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_seed_creates_at_least_one_closed_successful_run(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    projects = await store.list_projects()
    assert len(projects) >= 1

    all_runs = await store.list_runs()
    closed_runs = [r for r in all_runs if r.status == "closed"]
    assert len(closed_runs) >= 1

    closed_run = closed_runs[0]
    units = await store.list_units(closed_run.id)
    task_units = [u for u in units if u.type == "task"]
    assert task_units
    assert all(u.status == "closed" for u in task_units)

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/demo/test_seed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.demo.seed'`.

- [ ] **Step 3: Implement the seed module core + one run**

Create `src/foundry/demo/seed.py`:

```python
from __future__ import annotations

import os

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
    previous_closed = -1
    for _ in range(max_ticks):
        result = await orchestrator.tick(run_id)
        if result.complete:
            return result
        if result.closed == previous_closed:
            break
        previous_closed = result.closed
    return result


async def _auto_approve_and_complete(store: Store, run_id: str, orchestrator: Orchestrator) -> None:
    """Tick, auto-approving every approvable gate, until the run completes.

    Mirrors cli.py's `_run` polling loop exactly (same approvable-gate
    filter: only gates with a produced artifact, or a derived plan-approval
    gate -- never blind-approve a no-artifact failure-escalation gate).
    """
    result = await _run_to_pending_or_completion(store, run_id, orchestrator)
    for _ in range(20):
        if result.complete:
            return
        gates = await store.list_gates_for_run(run_id)
        approvable = [
            g for g in gates if g.decision == "pending" and (g.artifact_id is not None or g.gate_type == "derived")
        ]
        if not approvable:
            return
        for gate in approvable:
            await store.decide_gate(gate.id, "approved", decided_by="demo-seed")
        result = await _run_to_pending_or_completion(store, run_id, orchestrator)


async def _seed_closed_successful_run(store: Store, project, project_dir: str) -> None:
    playbook = load_playbook(BUGFIX_PLAYBOOK)
    run = await store.create_run(project.id, BUGFIX_PLAYBOOK, "Fix pagination off-by-one")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
    await _auto_approve_and_complete(store, run.id, orchestrator)


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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/demo/test_seed.py -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/foundry/demo/seed.py tests/demo/test_seed.py
git commit -m "feat(demo): add seed module core + one closed-successful run

_run_to_pending_or_completion ticks until either the run completes or
stops making forward progress (robust to playbook shape, not a fixed
tick count). _auto_approve_and_complete mirrors cli.py's own _run
polling loop exactly. run_demo_seed is the importable entry point
both the CLI command and the follow-up hot-swap API route will call."
```

---

### Task 3: Active runs with a pending gate

**Files:**
- Modify: `src/foundry/demo/seed.py`
- Test: `tests/demo/test_seed.py`

**Interfaces:**
- Consumes: `_run_to_pending_or_completion`, `_HAPPY_PATH_SCRIPT`, `SDLC_PLAYBOOK`,
  `BUGFIX_PLAYBOOK` (Task 2).
- Produces: `_seed_active_pending_human_gate_run(store, project, project_dir) -> None`,
  `_seed_active_pending_agent_gate_run(store, project, project_dir) -> None`.
  `run_demo_seed` calls both on a second project.

- [ ] **Step 1: Write the failing test**

Add to `tests/demo/test_seed.py`:

```python
@pytest.mark.asyncio
async def test_seed_creates_runs_with_pending_human_and_agent_gates(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    all_gates = []
    for run in await store.list_runs():
        all_gates.extend(await store.list_gates_for_run(run.id))

    pending_human = [g for g in all_gates if g.gate_type == "human" and g.decision == "pending"]
    pending_agent = [g for g in all_gates if g.gate_type == "agent" and g.decision == "pending"]
    assert pending_human, "expected at least one pending human gate in the seed data"
    assert pending_agent, "expected at least one pending agent gate in the seed data"

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/demo/test_seed.py -k pending_human_and_agent -v`
Expected: FAIL — no pending gates exist yet (Task 2 only seeded a fully-closed run).

- [ ] **Step 3: Implement both pending-gate runs**

In `src/foundry/demo/seed.py`, add these two functions (after
`_seed_closed_successful_run`):

```python
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
    """
    playbook = load_playbook(SDLC_PLAYBOOK)
    run = await store.create_run(project.id, SDLC_PLAYBOOK, "Add CSV export to the reports page")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
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
```

Update `run_demo_seed` to add a second project and call both new functions:

```python
async def run_demo_seed(store: Store, base_dir: str) -> None:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/demo/test_seed.py -v`
Expected: PASS (all tests in the file, including Task 2's).

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/foundry/demo/seed.py tests/demo/test_seed.py
git commit -m "feat(demo): add active runs with a pending human gate and a pending agent gate

Second demo project (beta-dashboard) gets a bugfix run stopped at its
diagnose human gate, and an sdlc_story run with its upstream human/
derived gates approved but the agent-type review gate left pending."
```

---

### Task 4: Rejection→rework run + cancelled run

**Files:**
- Modify: `src/foundry/demo/seed.py`
- Test: `tests/demo/test_seed.py`

**Interfaces:**
- Consumes: `_run_to_pending_or_completion`, `_auto_approve_and_complete`,
  `_HAPPY_PATH_SCRIPT`, `SDLC_PLAYBOOK` (Tasks 2-3).
- Produces: `_seed_rejection_rework_run(store, project, project_dir) -> None`,
  `_seed_cancelled_run(store, project, project_dir) -> None`. `run_demo_seed`
  calls both on a third project.

- [ ] **Step 1: Write the failing test**

Add to `tests/demo/test_seed.py`:

```python
@pytest.mark.asyncio
async def test_seed_creates_a_rejection_rework_run_and_a_cancelled_run(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    all_gates = []
    for run in await store.list_runs():
        all_gates.extend(await store.list_gates_for_run(run.id))
    rejected_gates = [g for g in all_gates if g.decision == "rejected"]
    assert rejected_gates, "expected at least one rejected gate in the seed data's history"

    all_runs = await store.list_runs()
    cancelled_runs = [r for r in all_runs if r.status == "cancelled"]
    assert cancelled_runs, "expected at least one cancelled run"

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/demo/test_seed.py -k rejection_rework -v`
Expected: FAIL — no rejected gate or cancelled run exists yet.

- [ ] **Step 3: Implement both**

In `src/foundry/demo/seed.py`, add these two functions (after
`_seed_active_pending_agent_gate_run`):

```python
async def _seed_rejection_rework_run(store: Store, project, project_dir: str) -> None:
    """SDLC run whose review gate is rejected once, then approved on rework.

    FakeStepScript is static per step_id -- a single scripted "review"
    step always returns the same verdict, so a real orchestrator run alone
    can't produce a genuine reject-then-approve sequence. The fix: let
    ticking bring the review gate to pending naturally, directly reject it
    with store.decide_gate() BEFORE the orchestrator's own
    _dispatch_agent_reviews would have auto-decided it (once a gate is no
    longer "pending", _dispatch_agent_reviews skips it entirely -- see
    tick.py -- so this preempts the driver rather than fighting it), then
    let the rework loop continue: the implement step re-dispatches, a new
    review gate opens for round 2, and THIS time the still-"approved"
    script drives the normal agent-auto-decide path. Only the round-1
    decision needed a direct write; everything else is the real engine.
    """
    playbook = load_playbook(SDLC_PLAYBOOK)
    run = await store.create_run(project.id, SDLC_PLAYBOOK, "Add bulk delete to the reports page")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
    await _run_to_pending_or_completion(store, run.id, orchestrator)

    # Approve every human/derived gate so implement -> review can proceed,
    # same pattern as the pending-agent-gate seed run.
    for _ in range(10):
        gates = await store.list_gates_for_run(run.id)
        pending = [g for g in gates if g.decision == "pending"]
        review_pending = [g for g in pending if g.gate_type == "agent"]
        if review_pending:
            # Force round 1's rejection directly -- preempts the driver.
            await store.decide_gate(
                review_pending[0].id,
                "rejected",
                feedback={"chips": ["missing tests"], "text": "Needs a test for the empty-selection case"},
                decided_by="demo-seed",
            )
            break
        approvable = [g for g in pending if g.artifact_id is not None or g.gate_type == "derived"]
        if not approvable:
            break
        for gate in approvable:
            await store.decide_gate(gate.id, "approved", decided_by="demo-seed")
        await _run_to_pending_or_completion(store, run.id, orchestrator)

    # Round 2: implement re-dispatches, a fresh review gate opens, and this
    # time the driver's own "approved" script drives the normal
    # agent-auto-decide path via _dispatch_agent_reviews.
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
```

Update `run_demo_seed` to add a third project and call both:

```python
    gamma_dir = os.path.join(base_dir, "gamma-api")
    generate_toy_repo(gamma_dir, num_files=10)
    gamma = await store.create_project("gamma-api", gamma_dir)
    await _seed_rejection_rework_run(store, gamma, gamma_dir)
    await _seed_cancelled_run(store, gamma, gamma_dir)
```

(Add this block to the end of `run_demo_seed`, after the `beta` block from
Task 3.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/demo/test_seed.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/foundry/demo/seed.py tests/demo/test_seed.py
git commit -m "feat(demo): add rejection-then-rework run and a cancelled run

Third demo project (gamma-api). The rejection-rework run's round-1
decision is a direct store.decide_gate() call timed to preempt
_dispatch_agent_reviews before it auto-decides the gate; round 2
proceeds through the real agent-review path normally. The cancelled
run mirrors POST /runs/{id}/cancel's own direct-write approach."
```

---

### Task 5: Budget-exceeded human task, memory items, varied settings, project lifecycle states

**Files:**
- Modify: `src/foundry/demo/seed.py`
- Test: `tests/demo/test_seed.py`

**Interfaces:**
- Consumes: everything from Tasks 2-4.
- Produces: `_seed_budget_exceeded_run(store, project, project_dir) -> None`,
  `_seed_memory_items(store, project) -> None`. `run_demo_seed` gains a
  fourth and fifth project, varied `default_driver`/`default_token_budget`/
  `default_playbook_path` on every project, and one paused + one archived
  project.

- [ ] **Step 1: Write the failing test**

Add to `tests/demo/test_seed.py`:

```python
@pytest.mark.asyncio
async def test_seed_creates_an_open_human_task_and_memory_items(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    open_human_tasks = []
    for run in await store.list_runs():
        units = await store.list_units(run.id)
        open_human_tasks.extend(u for u in units if u.type == "human_task" and u.status == "open")
    assert open_human_tasks, "expected at least one open human_task unit (budget-exceeded escalation)"

    memory_items = await store.list_memory_items()
    assert len(memory_items) >= 3
    assert {m.kind for m in memory_items} >= {"lesson", "pattern", "pitfall"}

    await store.stop()


@pytest.mark.asyncio
async def test_seed_varies_project_settings_and_lifecycle_states(tmp_path):
    store = await _make_store(tmp_path)

    await run_demo_seed(store, str(tmp_path / "demo-repos"))

    projects = await store.list_projects()
    assert len(projects) >= 5

    drivers = {p.default_driver for p in projects}
    assert len(drivers) > 1, "expected varied default_driver across demo projects, not all identical"

    statuses = {p.status for p in projects}
    assert "paused" in statuses
    assert "archived" in statuses

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/demo/test_seed.py -k "human_task and memory or varies_project" -v`
Expected: FAIL — neither exists yet.

- [ ] **Step 3: Implement the budget-exceeded run, memory items, and settings/lifecycle variety**

In `src/foundry/demo/seed.py`, add:

```python
async def _seed_budget_exceeded_run(store: Store, project, project_dir: str) -> None:
    """A run whose token_budget is exhausted, producing an open human_task
    unit via the real dispatch() budget-exceeded path (tick.py) rather
    than a direct write -- this state IS reachable by construction, it
    just needs tokens_used pushed past token_budget before ticking.
    """
    playbook = load_playbook(BUGFIX_PLAYBOOK)
    run = await store.create_run(project.id, BUGFIX_PLAYBOOK, "Refactor report caching layer")
    await store.update_run(run.id, token_budget=1000, tokens_used=1500)
    await materialize(playbook, run.id, store)

    driver = FakeDriver(_HAPPY_PATH_SCRIPT)
    orchestrator = Orchestrator(store, driver, playbook, project_path=project_dir)
    await _run_to_pending_or_completion(store, run.id, orchestrator)


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
```

Update `run_demo_seed` to add the fourth/fifth projects, memory items,
varied settings, and lifecycle states:

```python
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
    await store.update_project(acme.id, default_driver="fake", default_token_budget=50000, default_playbook_path=BUGFIX_PLAYBOOK)
    await store.update_project(beta.id, default_driver="codex", default_token_budget=100000, default_playbook_path=SDLC_PLAYBOOK)
    await store.update_project(gamma.id, default_driver="claude", default_token_budget=75000, default_playbook_path=SDLC_PLAYBOOK)
    await store.update_project(delta.id, default_driver="fake", default_token_budget=1000, default_playbook_path=BUGFIX_PLAYBOOK)
    await store.update_project(epsilon.id, default_driver="codex", default_token_budget=30000, default_playbook_path=BUGFIX_PLAYBOOK)

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
```

(Add this block to the end of `run_demo_seed`, after Task 4's `gamma` block.
Note `acme`, `beta`, `gamma` are the variables already assigned earlier in
the function from Tasks 2-4 -- reuse them, don't recreate those projects.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/demo/test_seed.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/foundry/demo/seed.py tests/demo/test_seed.py
git commit -m "feat(demo): add budget-exceeded human task, memory items, and settings/lifecycle variety

Fourth and fifth demo projects. Budget-exceeded state is reached by
construction (tokens_used pushed past token_budget before ticking,
same real dispatch() path production code uses), not a direct
human_task write. Every project gets different default_driver/
default_token_budget/default_playbook_path, and one is paused, one
archived, covering every Project.status the dashboard renders
differently."
```

---

### Task 6: `foundry demo-seed` CLI command

**Files:**
- Modify: `src/foundry/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `run_demo_seed` (Task 2, extended through Task 5).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_cli.py`:

```python
def test_demo_seed_command_populates_a_fresh_db(tmp_path):
    db_path = str(tmp_path / "demo.db")
    repos_dir = str(tmp_path / "demo-repos")

    result = runner.invoke(app, ["demo-seed", "--db", db_path, "--repos-dir", repos_dir])

    assert result.exit_code == 0, result.output
    assert "seeded" in result.output.lower()


def test_demo_seed_refuses_to_run_without_an_explicit_db_path():
    result = runner.invoke(app, ["demo-seed"])

    # Typer's own missing-required-option handling is enough here -- no
    # default that could silently point at a real foundry.db.
    assert result.exit_code != 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -k demo_seed -v`
Expected: FAIL — no such command.

- [ ] **Step 3: Add the command**

In `src/foundry/cli.py`, add the import:

```python
from foundry.demo.seed import run_demo_seed
```

Add the command (after the `serve` command, before `_recover_active_runs`):

```python
@app.command("demo-seed")
def demo_seed(
    db: str = typer.Option(..., "--db", help="Path to the demo SQLite db (required, no default)"),
    repos_dir: str = ".foundry-demo",
) -> None:
    asyncio.run(_demo_seed(db, repos_dir))
    typer.echo(f"seeded {db}")


async def _demo_seed(db: str, repos_dir: str) -> None:
    engine = make_engine(db)
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    await run_demo_seed(store, repos_dir)

    await store.stop()
```

`db` uses `typer.Option(..., "--db")` — the `...` (Ellipsis) is Typer's
"required, no default" sentinel. A plain `db: str` parameter with no
default at all would make Typer treat it as a required *positional*
argument instead of a `--db` flag (Typer only generates `--flag` options
for parameters that have a default, unless explicitly wrapped in
`typer.Option`/`typer.Argument`) — this matters because the test above
invokes it as `--db <path>`, and every other command in this file already
uses the `--flag` style, so `demo-seed` needs to stay consistent with that
even though its value is required rather than defaulted. This is
deliberate — matching the plan's "never silently touch a real foundry.db"
constraint via requiredness, not via a default value.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -k demo_seed -v`
Expected: PASS

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Manually verify end to end**

Run: `uv run foundry demo-seed --db /tmp/foundry-demo-manual-check.db --repos-dir /tmp/foundry-demo-manual-check-repos`
Expected: prints `seeded /tmp/foundry-demo-manual-check.db`, exits 0. Then:
`uv run foundry serve --db /tmp/foundry-demo-manual-check.db` and confirm
in a browser (or `curl http://127.0.0.1:8000/api/portfolio`) that 5
projects show up with varied health signals. Clean up both paths
afterward: `rm -rf /tmp/foundry-demo-manual-check.db /tmp/foundry-demo-manual-check-repos`.

- [ ] **Step 7: Commit**

```bash
git add src/foundry/cli.py tests/test_cli.py
git commit -m "feat(cli): add foundry demo-seed command

No default --db value, unlike every other command here -- deliberate,
so it's never possible to accidentally reseed a real foundry.db by
omission. Thin wrapper around run_demo_seed(), which the follow-up
hot-swap plan's API routes will call directly (not this CLI command)."
```

---

## Final verification

- [ ] Run: `uv run pytest -q`
  Expected: all tests pass.
- [ ] Confirm `run_demo_seed` is genuinely reusable, not CLI-coupled:
  `grep -n "def run_demo_seed" src/foundry/demo/seed.py` — signature should
  be `(store: Store, base_dir: str) -> None`, no Typer/CLI-specific types
  anywhere in its parameter list.
- [ ] Confirm the seeded data covers everything the spec's scope section
  lists: 5 projects (`active`×3, `paused`×1, `archived`×1), runs spanning
  active-pending-human-gate / active-pending-agent-gate / closed-successful /
  closed-with-rejection-rework / cancelled, an open human_task, memory
  items of all three kinds, varied settings, and a real on-disk toy repo
  per project.
