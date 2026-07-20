# M1a — Backend: Real Gates + REST API Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace M0's CLI-only auto-approve-everything gate model with real, API-driven gates (pending until a human decides), and build the FastAPI `/api` surface — projects, runs, gates, artifacts, graph, cancel, SSE stream — so a run's full plan → approve → implement → reject → rework → approve cycle can be driven by an HTTP client instead of only `foundry run`'s one-shot CLI loop. This is the backend half of M1; M1b (a separate plan/branch) builds the React dashboard against this API.

**Architecture:** `Orchestrator.tick()` (from M0) is unchanged in its core loop shape, but two behaviors change: (1) a step's success-path gate and a derived-plan-approval gate now stay `pending` instead of auto-approving — a human decides via `POST /api/gates/{id}/decide`; (2) artifact rework increments `version` instead of always writing `version=1`. Because the API can't block an HTTP request on `run_to_completion()` (a run may sit `blocked` on a human for minutes), a new `Scheduler` owns a registry of `{run_id: Orchestrator}` and ticks all of them on a background loop — `POST /api/runs` registers, the scheduler unregisters once a run's task units are all `closed`. FastAPI routes are thin: validate input, call `Store`/`Scheduler`, return an `ApiResponse` envelope per ADR-001. `foundry run` (the M0 CLI) keeps its own auto-approve convenience loop so local FakeDriver smoke-testing doesn't regress — that auto-approve logic moves out of the orchestrator and into the CLI layer, where it belongs.

**Tech Stack:** FastAPI, Pydantic v2, sse-starlette (already a dependency), httpx (test client), everything from M0 (SQLAlchemy 2 async, aiosqlite/WAL, Typer, pytest + pytest-asyncio).

## Global Constraints

- All `/api` responses conform to ADR-001 (`docs/adrs/001-api-response-structure.md`): `{data, paging}` envelope, `{error}` envelope with `code/message/status_code/timestamp/path/details`, offset/limit pagination (default `offset=0/limit=20`, max `limit=100`, **reject with 400 above max — not FastAPI's default 422**), plain `?key=value` filters, HTTP status table from that ADR.
- `/internal` API and `ClaudeCodeDriver` are **not** in this plan — M0 already deferred them to a follow-up plan; this plan doesn't pick that debt up. Every run in this plan still executes on `FakeDriver`, consistent with the FakeDriver-first constraint (CLAUDE.md).
- Dispatch stays **sequential** inside `tick()` — no concurrency primitives. M1a doesn't touch `dispatch()`'s spawn-then-synchronously-collect shape; that's M2 scope.
- No dashboard, no React, no SSE-consuming frontend code — M1b's job. This plan proves the API with `httpx` tests only.
- No Alembic migration — no new SQLAlchemy columns are added in this plan (verified per-task below); if a task's design would need one, that's a stop-and-ask, not a workaround.
- All IDs are ULIDs (unchanged from M0); `WorkUnit.status` gains no new enum values beyond what the M0 data model already documented (`open|ready|intent|in_progress|blocked|closed|failed|killed` — `killed` is used for the first time by this plan's cancel endpoint, but it was already a documented valid value, not a new one).

---

### Task 1: Store additions — read helpers, artifact versioning, event redaction

**Files:**
- Create: `src/foundry/store/redaction.py`
- Modify: `src/foundry/store/store.py` (add methods; add one import)
- Test: `tests/store/test_store.py` (extend)
- Test: `tests/store/test_redaction.py`

**Interfaces:**
- Consumes: `Store`, `Project`, `Run`, `Artifact` from `foundry.store.models`/`foundry.store.store` (unchanged from M0).
- Produces: `redact_event_payload(payload: dict) -> dict`; `Store.list_projects() -> list[Project]`; `Store.get_project(project_id: str) -> Project | None`; `Store.get_run(run_id: str) -> Run | None`; `Store.list_runs(project_id: str | None = None, status: str | None = None) -> list[Run]`; `Store.update_run(run_id: str, **fields) -> None`; `Store.get_next_artifact_version(work_unit_id: str) -> int` (returns `1` if no prior artifact exists for that unit, else `max(existing versions) + 1`). `Store.append_event` now redacts `payload` before persisting — signature unchanged.

- [ ] **Step 1: Write the failing tests**

```python
# tests/store/test_redaction.py
from foundry.store.redaction import redact_event_payload


def test_redacts_sensitive_keys_case_insensitively():
    payload = {"api_key": "sk-abc123", "Token": "xyz", "note": "fine"}
    redacted = redact_event_payload(payload)
    assert redacted["api_key"] == "***REDACTED***"
    assert redacted["Token"] == "***REDACTED***"
    assert redacted["note"] == "fine"


def test_redacts_nested_dicts_and_lists():
    payload = {"tool_call": {"env": {"AWS_SECRET_ACCESS_KEY": "abc"}, "args": ["--password", "hunter2"]}}
    redacted = redact_event_payload(payload)
    assert redacted["tool_call"]["env"]["AWS_SECRET_ACCESS_KEY"] == "***REDACTED***"
    # list items aren't key/value pairs, so only dict keys drive redaction — the raw
    # list is passed through unless a later task adds value-pattern scanning.
    assert redacted["tool_call"]["args"] == ["--password", "hunter2"]


def test_leaves_non_sensitive_payload_untouched():
    payload = {"unit_id": "01J...", "status": "closed"}
    assert redact_event_payload(payload) == payload
```

```python
# tests/store/test_store.py — append to the existing file
async def test_list_projects_and_get_project(tmp_path):
    store = await make_store(tmp_path)
    p1 = await store.create_project("proj-a", "/tmp/a")
    p2 = await store.create_project("proj-b", "/tmp/b")

    all_projects = await store.list_projects()
    assert {p.id for p in all_projects} == {p1.id, p2.id}

    fetched = await store.get_project(p1.id)
    assert fetched.name == "proj-a"
    assert await store.get_project("does-not-exist") is None

    await store.stop()


async def test_get_run_and_list_runs_with_filters(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj", "/tmp/proj")
    run1 = await store.create_run(project.id, "pb1.toml", "run one")
    run2 = await store.create_run(project.id, "pb2.toml", "run two")
    await store.update_run(run2.id, status="closed")

    assert (await store.get_run(run1.id)).title == "run one"
    assert await store.get_run("does-not-exist") is None

    all_runs = await store.list_runs(project_id=project.id)
    assert {r.id for r in all_runs} == {run1.id, run2.id}

    active_only = await store.list_runs(project_id=project.id, status="active")
    assert [r.id for r in active_only] == [run1.id]

    await store.stop()


async def test_get_next_artifact_version_increments_per_work_unit(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj2", "/tmp/proj2")
    run = await store.create_run(project.id, "pb.toml", "run")
    units = await store.create_work_units(
        [WorkUnit(run_id=run.id, step_id="a", type="task", status="open")]
    )
    unit = units[0]

    assert await store.get_next_artifact_version(unit.id) == 1

    await store.create_artifact(
        run_id=run.id, work_unit_id=unit.id, kind="a_artifact",
        version=1, produced_by_role="planner", payload_json={},
    )
    assert await store.get_next_artifact_version(unit.id) == 2

    await store.create_artifact(
        run_id=run.id, work_unit_id=unit.id, kind="a_artifact",
        version=2, produced_by_role="planner", payload_json={},
    )
    assert await store.get_next_artifact_version(unit.id) == 3

    await store.stop()


async def test_append_event_redacts_payload_before_persisting(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj3", "/tmp/proj3")
    run = await store.create_run(project.id, "pb.toml", "run")

    seq = await store.append_event(run.id, None, "test.event", {"secret_token": "shh", "ok": True})
    events = await store.list_events(run.id, after_seq=seq - 1)
    assert events[0].payload_json["secret_token"] == "***REDACTED***"
    assert events[0].payload_json["ok"] is True

    await store.stop()
```

Note: `tests/store/test_store.py` already imports `WorkUnit` from `foundry.store.models` and defines a `make_store(tmp_path)` helper (from M0) — reuse both, don't redefine.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/store/test_redaction.py tests/store/test_store.py -v -k "redact or list_projects or get_run or list_runs or get_next_artifact_version or append_event_redacts"`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.store.redaction'` and `AttributeError: 'Store' object has no attribute 'list_projects'` (etc).

- [ ] **Step 3: Write `src/foundry/store/redaction.py`**

```python
from __future__ import annotations

import re

_SENSITIVE_KEY_PATTERN = re.compile(r"(key|token|secret|password|passwd|credential|auth)", re.IGNORECASE)
_REDACTED = "***REDACTED***"


def redact_event_payload(payload: dict) -> dict:
    return {k: _redact_value(k, v) for k, v in payload.items()}


def _redact_value(key: str, value):
    if _SENSITIVE_KEY_PATTERN.search(key):
        return _REDACTED
    if isinstance(value, dict):
        return redact_event_payload(value)
    return value
```

- [ ] **Step 4: Add the new methods to `src/foundry/store/store.py`**

Add the import at the top (extend the existing `from foundry.store.models import (...)` block to include nothing new — `Project`, `Run`, `Artifact`, `WorkUnit` are already imported) and add this import line:

```python
from foundry.store.redaction import redact_event_payload
```

Add these methods (place `list_projects`/`get_project` right after `create_project`, `get_run`/`list_runs`/`update_run` right after `create_run`, and `get_next_artifact_version` right after `list_artifacts`):

```python
    async def list_projects(self) -> list[Project]:
        async def _op(session):
            res = await session.execute(select(Project))
            return list(res.scalars())

        return await self.read(_op)

    async def get_project(self, project_id: str) -> Project | None:
        async def _op(session):
            return await session.get(Project, project_id)

        return await self.read(_op)
```

```python
    async def get_run(self, run_id: str) -> Run | None:
        async def _op(session):
            return await session.get(Run, run_id)

        return await self.read(_op)

    async def list_runs(self, project_id: str | None = None, status: str | None = None) -> list[Run]:
        async def _op(session):
            stmt = select(Run)
            if project_id is not None:
                stmt = stmt.where(Run.project_id == project_id)
            if status is not None:
                stmt = stmt.where(Run.status == status)
            res = await session.execute(stmt)
            return list(res.scalars())

        return await self.read(_op)

    async def update_run(self, run_id: str, **fields) -> None:
        async def _op(session):
            run = await session.get(Run, run_id)
            for key, value in fields.items():
                setattr(run, key, value)

        await self.write(_op)
```

```python
    async def get_next_artifact_version(self, work_unit_id: str) -> int:
        async def _op(session):
            res = await session.execute(
                select(Artifact.version)
                .where(Artifact.work_unit_id == work_unit_id)
                .order_by(Artifact.version.desc())
            )
            latest = res.scalars().first()
            return (latest or 0) + 1

        return await self.read(_op)
```

Modify `append_event`'s body to redact before constructing the `Event`:

```python
    async def append_event(
        self, run_id: str, unit_id: str | None, type_: str, payload: dict | None = None
    ) -> int:
        async def _op(session):
            ev = Event(run_id=run_id, unit_id=unit_id, type=type_, payload_json=redact_event_payload(payload or {}))
            session.add(ev)
            await session.flush()
            return ev.seq

        return await self.write(_op)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/store/ -v`
Expected: PASS (all tests, including the new ones — the full `tests/store/` directory, since redaction touches every event write)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/store/redaction.py src/foundry/store/store.py tests/store/test_redaction.py tests/store/test_store.py
git commit -m "feat(store): project/run read helpers, artifact versioning, event redaction filter"
```

---

### Task 2: Orchestrator — real pending gates, artifact versioning, cost estimate

**Files:**
- Create: `src/foundry/orchestrator/cost.py`
- Modify: `src/foundry/orchestrator/tick.py`
- Modify: `src/foundry/cli.py` (auto-approve convenience loop moves here)
- Test: `tests/orchestrator/test_cost.py`
- Test: `tests/orchestrator/test_tick.py` (modify 2 existing tests, add 1 new)
- Test: `tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `PlaybookSpec`/`StepSpec` from `foundry.playbook.schema`; `Store.get_next_artifact_version` (Task 1).
- Produces: `estimate_plan_cost(playbook: PlaybookSpec, gate_step_id: str) -> dict` (keys: `estimated_writes_steps: int`, `estimated_tokens: int`, `basis: str`). `Orchestrator._gate_derived_units` replaces `_close_derived_gates` (same call site in `tick()`, same "no-op if nothing ready" behavior, different action when something *is* ready — creates a `pending` `gate_type="derived"` `Gate` and blocks the unit, instead of auto-closing). `Orchestrator._collect`'s success path creates the gate `pending` (no more `decide_gate(..., "approved", ...)` call). Artifact `version` is `await self.store.get_next_artifact_version(task_unit.id)` instead of the literal `1`.

This task changes behavior two existing tests encoded as M0-only ("no UI, gates auto-approved") — you're updating them to prove the *new*, correct M1 behavior (gate created pending → external `decide_gate` call → run then progresses), not just making them pass.

- [ ] **Step 1: Write the failing test for cost estimation**

```python
# tests/orchestrator/test_cost.py
from foundry.orchestrator.cost import estimate_plan_cost
from foundry.playbook.schema import PlaybookSpec, StepSpec


def test_estimate_counts_only_downstream_writes_steps():
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="requirement", role="po", produces="requirement_artifact"),
            StepSpec(id="architecture", role="architect", needs=["requirement"], produces="architecture_artifact"),
            StepSpec(id="test_plan", role="qa", needs=["requirement"], produces="test_plan_artifact"),
            StepSpec(
                id="plan_approval", role="system", type="derived_gate",
                needs=["requirement", "architecture", "test_plan"],
            ),
            StepSpec(
                id="implement", role="developer", needs=["plan_approval"],
                produces="code_diff_artifact", writes=True,
            ),
            StepSpec(id="agent_review", role="reviewer", needs=["implement"], produces="review_artifact"),
        ],
    )

    result = estimate_plan_cost(playbook, "plan_approval")

    assert result["estimated_writes_steps"] == 1  # only "implement" has writes=True
    assert result["estimated_tokens"] == 30_000
    assert "basis" in result


def test_estimate_is_zero_for_a_gate_with_no_downstream_writes_steps():
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="a", role="x", type="derived_gate"),
            StepSpec(id="b", role="x", needs=["a"], produces="x_artifact"),  # writes defaults False
        ],
    )

    result = estimate_plan_cost(playbook, "a")

    assert result["estimated_writes_steps"] == 0
    assert result["estimated_tokens"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_cost.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.orchestrator.cost'`

- [ ] **Step 3: Write `src/foundry/orchestrator/cost.py`**

```python
from __future__ import annotations

from foundry.playbook.schema import PlaybookSpec

DEFAULT_TOKENS_PER_STEP = 30_000


def estimate_plan_cost(playbook: PlaybookSpec, gate_step_id: str) -> dict:
    """Heuristic cost estimate for a derived (plan-approval) gate: count of
    writes-capable steps transitively downstream of it, times a flat per-step
    token estimate. Replace with a real historical per-project rollup once M2+
    has actual session token usage to draw on (design doc §11.1)."""
    steps_by_id = {s.id: s for s in playbook.steps}
    downstream_ids = _downstream_step_ids(playbook, gate_step_id)
    writes_steps = [sid for sid in downstream_ids if steps_by_id[sid].writes]
    estimated_tokens = len(writes_steps) * DEFAULT_TOKENS_PER_STEP
    return {
        "estimated_writes_steps": len(writes_steps),
        "estimated_tokens": estimated_tokens,
        "basis": (
            "heuristic: writes-steps-downstream x default-tokens-per-step; "
            "real historical per-project rollup lands in M2+"
        ),
    }


def _downstream_step_ids(playbook: PlaybookSpec, from_step_id: str) -> set[str]:
    forward: dict[str, list[str]] = {}
    for step in playbook.steps:
        for need_id in step.needs:
            forward.setdefault(need_id, []).append(step.id)

    seen: set[str] = set()
    stack = [from_step_id]
    while stack:
        current = stack.pop()
        for nxt in forward.get(current, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_cost.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Update the two existing tests that encode M0's auto-approve behavior**

In `tests/orchestrator/test_tick.py`, replace the entire body of `test_gated_step_auto_approves_and_run_completes` with:

```python
@pytest.mark.asyncio
async def test_gated_step_creates_pending_gate_then_completes_once_decided(tmp_path):
    """M1: gates on successful steps stay pending until a human (here, the test
    standing in for the API) decides — they no longer auto-approve."""
    store = await make_store(tmp_path)
    project = await store.create_project("demo6", str(tmp_path))
    playbook = load_playbook(GATED_FIXTURE)
    run = await store.create_run(project.id, GATED_FIXTURE, "gated demo run")
    await materialize(playbook, run.id, store)

    script = {
        "a": FakeStepScript(artifact={"ok": True}),
        "b": FakeStepScript(artifact={"ok": True}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)

    result = await orchestrator.run_to_completion(run.id)
    assert result.complete is False

    gates = await store.list_gates_for_run(run.id)
    assert len(gates) == 1
    assert gates[0].decision == "pending"

    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    a_task = next(u for u in task_units if u.step_id == "a")
    b_task = next(u for u in task_units if u.step_id == "b")
    assert a_task.status == "blocked"
    assert b_task.status == "open"  # never unblocked — "a" hasn't closed yet

    await store.decide_gate(gates[0].id, "approved", decided_by="test-human")
    result = await orchestrator.run_to_completion(run.id)

    assert result.complete is True
    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    assert all(u.status == "closed" for u in task_units)

    await store.stop()
```

Replace the entire body of `test_reconcile_recovers_orphaned_gated_task_with_existing_artifact_auto_approves` (rename it too) with:

```python
@pytest.mark.asyncio
async def test_reconcile_recovers_orphaned_gated_task_with_pending_gate(tmp_path):
    """The crash-recovery path for a gated step creates the same kind of pending
    gate the normal success path does — it must not auto-approve either."""
    store = await make_store(tmp_path)
    project = await store.create_project("demo7", str(tmp_path))
    playbook = load_playbook(GATED_FIXTURE)
    run = await store.create_run(project.id, GATED_FIXTURE, "gated demo run 2")
    await materialize(playbook, run.id, store)

    units = await store.list_units(run.id)
    a_task = next(u for u in units if u.step_id == "a" and u.type == "task")

    orphan_session = (
        await store.create_work_units([WorkUnit(run_id=run.id, step_id="a", type="session", status="closed")])
    )[0]
    await store.update_unit(a_task.id, owner_session_id=orphan_session.id, status="in_progress")
    await store.create_artifact(
        run_id=run.id,
        work_unit_id=a_task.id,
        kind="a_artifact",
        version=1,
        produced_by_role="planner",
        payload_json={"ok": True},
    )

    script = {
        "a": FakeStepScript(artifact={"ok": True}),
        "b": FakeStepScript(artifact={"ok": True}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)
    result = await orchestrator.run_to_completion(run.id)

    assert result.complete is False
    a_task = await store.get_unit(a_task.id)
    assert a_task.status == "blocked"

    gates = await store.list_gates_for_run(run.id)
    assert len(gates) == 1
    assert gates[0].work_unit_id == a_task.id
    assert gates[0].decision == "pending"

    artifacts = await store.list_artifacts(run.id)
    a_artifacts = [x for x in artifacts if x.kind == "a_artifact"]
    assert len(a_artifacts) == 1  # recovery reused the existing artifact, didn't duplicate it

    events = await store.list_events(run.id)
    assert any(e.type == "gate.created" and e.payload_json.get("recovered") is True for e in events)

    await store.decide_gate(gates[0].id, "approved", decided_by="test-human")
    result = await orchestrator.run_to_completion(run.id)
    assert result.complete is True

    await store.stop()
```

- [ ] **Step 6: Write the new artifact-versioning test**

Add to `tests/orchestrator/test_tick.py`:

```python
@pytest.mark.asyncio
async def test_reject_then_rework_increments_artifact_version(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo8", str(tmp_path))
    playbook = load_playbook(GATED_FIXTURE)
    run = await store.create_run(project.id, GATED_FIXTURE, "rework demo run")
    await materialize(playbook, run.id, store)

    script = {
        "a": FakeStepScript(artifact={"round": 1}),
        "b": FakeStepScript(artifact={"ok": True}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)
    await orchestrator.run_to_completion(run.id)

    gates = await store.list_gates_for_run(run.id)
    assert len(gates) == 1
    await store.decide_gate(gates[0].id, "rejected", feedback={"note": "try again"}, decided_by="test-human")

    # rejection reopens the task; give it a fresh script for round 2 and re-run
    orchestrator.driver = FakeDriver({"a": FakeStepScript(artifact={"round": 2}), "b": FakeStepScript(artifact={"ok": True})})
    await orchestrator.run_to_completion(run.id)

    artifacts = await store.list_artifacts(run.id)
    a_artifacts = sorted([x for x in artifacts if x.kind == "a_artifact"], key=lambda a: a.version)
    assert [a.version for a in a_artifacts] == [1, 2]
    assert a_artifacts[0].payload_json == {"round": 1}
    assert a_artifacts[1].payload_json == {"round": 2}

    await store.stop()
```

- [ ] **Step 7: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_tick.py -v`
Expected: FAIL — the two modified tests fail because the current code still auto-approves (`assert result.complete is False` fails, since M0's code completes the run in one call); the new rework test fails on `assert [a.version for a in a_artifacts] == [1, 2]` (currently always `[1, 1]` — two rows both `version=1` since `_collect` hardcodes it).

- [ ] **Step 8: Modify `src/foundry/orchestrator/tick.py`**

In `tick()` (around line 31), change the call site:

```python
        await self._gate_derived_units(run_id)
```

Replace `_close_derived_gates` (the whole method) with:

```python
    async def _gate_derived_units(self, run_id: str) -> None:
        units = await self.store.list_units(run_id)
        gates = await self.store.list_gates_for_run(run_id)
        already_gated = {g.work_unit_id for g in gates}

        for unit in units:
            if unit.type != "gate" or unit.status != "ready":
                continue
            if unit.id in already_gated:
                continue
            await self.store.create_gate(work_unit_id=unit.id, gate_type="derived", decision="pending")
            await self.store.update_unit(unit.id, status="blocked")
            await self.store.append_event(run_id, unit.id, "gate.created", {"gate_type": "derived"})
```

In `reconcile()`'s orphan-recovery branch (the `if gate.decision == "pending":` block, around line 119-120), delete the auto-approve call — the surrounding structure stays, only these two lines go:

```python
                    if gate.decision == "pending":
                        await self.store.decide_gate(gate.id, "approved", decided_by="system-auto-m0")
```

(Delete both lines; the `await self.store.update_unit(unit.id, status="blocked")` line right after stays as-is.)

In `_collect()`'s success path (the `else:` branch after `if step.gate in (None, "none"):`), delete the auto-approve call and update the comment:

```python
        else:
            gate = await self.store.create_gate(
                work_unit_id=task_unit.id,
                artifact_id=artifact.id,
                gate_type=step.gate,
                decision="pending",
            )
            # M1: the gate stays pending. A human (or, for local FakeDriver smoke
            # runs, the CLI's own auto-approve convenience loop) decides via
            # Store.decide_gate — apply_gate_decisions() picks it up next tick.
            await self.store.update_unit(task_unit.id, status="blocked")
            await self.store.append_event(run_id, task_unit.id, "gate.created", {"gate_id": gate.id})
```

Finally, change the artifact version in that same method's `create_artifact` call:

```python
        artifact = await self.store.create_artifact(
            run_id=run_id,
            work_unit_id=task_unit.id,
            kind=step.produces or "artifact",
            version=await self.store.get_next_artifact_version(task_unit.id),
            produced_by_role=step.role,
            payload_json=artifact_payload,
        )
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/ -v`
Expected: PASS (all tests in the directory)

- [ ] **Step 10: Move the auto-approve convenience loop into the CLI**

Removing orchestrator-level auto-approval means `foundry run` (which always used `FakeDriver` with an all-succeed script and expected the run to finish in one call) will now report incomplete runs for any playbook with a gated step. Give the CLI its own convenience loop that approves only *real* gates (a produced-artifact gate, or a derived-plan gate) — never the failure-escalation gate (created with no `artifact_id`, since that represents a genuine repeated failure a human should look at, not routine approval).

Write the failing test first:

```python
# tests/test_cli.py — append to the existing file
def test_run_auto_approves_gated_steps_for_local_fake_driver_convenience(tmp_path):
    db_path = str(tmp_path / "foundry.db")

    result = runner.invoke(
        app, ["run", "tests/orchestrator/fixtures/gated_demo.toml", "--db", db_path]
    )

    assert result.exit_code == 0, result.output
    run_id = result.output.strip()
    assert len(run_id) == 26
```

Run: `uv run pytest tests/test_cli.py -v -k auto_approves_gated`
Expected: FAIL — exit code 1, "did not complete: ... unit(s) still pending" on stderr (the gate stays pending, nothing decides it).

Modify `src/foundry/cli.py`'s `_run` function — replace the block from `script = {step.id: ...}` through the `pending_count = 0` / `await store.stop()` / `return` lines with:

```python
    script = {step.id: FakeStepScript(artifact={"ok": True}) for step in playbook.steps}
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)

    result = await orchestrator.run_to_completion(run_row.id)
    for _ in range(20):
        if result.complete:
            break
        gates = await store.list_gates_for_run(run_row.id)
        # Only auto-approve gates that gate a produced artifact (artifact_id set)
        # or a derived plan-approval gate (gate_type == "derived"). A failure-
        # escalation gate (no artifact_id, gate_type == "human") represents a
        # step that failed max_attempts times with no output — approving that
        # would close a task that never actually produced anything, which is
        # exactly the silent-failure the escalation gate exists to prevent.
        approvable = [g for g in gates if g.decision == "pending" and (g.artifact_id is not None or g.gate_type == "derived")]
        if not approvable:
            break
        for gate in approvable:
            await store.decide_gate(gate.id, "approved", decided_by="cli-auto")
        result = await orchestrator.run_to_completion(run_row.id)

    pending_count = 0
    if not result.complete:
        units = await store.list_units(run_row.id)
        pending_count = sum(1 for u in units if u.status not in ("closed", "failed", "blocked"))

    await store.stop()
    return run_row.id, result.complete, pending_count
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS (all CLI tests, including the new one)

- [ ] **Step 12: Run the full suite**

Run: `uv run pytest -v`
Expected: PASS (every test in the repo)

- [ ] **Step 13: Commit**

```bash
git add src/foundry/orchestrator/cost.py src/foundry/orchestrator/tick.py src/foundry/cli.py \
        tests/orchestrator/test_cost.py tests/orchestrator/test_tick.py tests/test_cli.py
git commit -m "feat(orchestrator): real pending gates (no auto-approve), artifact versioning on rework, cost estimate"
```

---

### Task 3: API response envelope + error handling (ADR-001)

**Files:**
- Create: `src/foundry/api/__init__.py` (empty)
- Create: `src/foundry/api/schemas.py`
- Create: `src/foundry/api/errors.py`
- Test: `tests/api/__init__.py` (empty)
- Test: `tests/api/test_schemas.py`

**Interfaces:**
- Produces: `Paging` (fields: `offset, limit, total, total_pages, has_next, has_prev`, all `int | None`/`bool | None`) with classmethods `Paging.none()`, `Paging.for_page(offset: int, limit: int, total: int)`, `Paging.unpaginated(total: int)`; `ApiResponse[T]` generic (`data: T`, `paging: Paging`); `ApiError`/`ErrorEnvelope` Pydantic models matching ADR-001's error shape; `validate_paging(offset: int, limit: int) -> None` (raises `ValidationApiError` if `limit < 1`, `limit > 100`, or `offset < 0`); `FoundryApiError`/`NotFoundError`/`ConflictError`/`ValidationApiError` exception classes; `foundry_api_error_handler(request, exc) -> JSONResponse`.

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_schemas.py
import pytest

from foundry.api.errors import ValidationApiError, validate_paging
from foundry.api.schemas import ApiResponse, Paging


def test_paging_none_is_all_null():
    p = Paging.none()
    assert p.offset is None
    assert p.limit is None
    assert p.total is None
    assert p.total_pages is None
    assert p.has_next is None
    assert p.has_prev is None


def test_paging_for_page_computes_total_pages_and_next_prev():
    p = Paging.for_page(offset=20, limit=20, total=43)
    assert p.total_pages == 3
    assert p.has_next is True
    assert p.has_prev is True

    first_page = Paging.for_page(offset=0, limit=20, total=43)
    assert first_page.has_prev is False

    last_page = Paging.for_page(offset=40, limit=20, total=43)
    assert last_page.has_next is False


def test_paging_unpaginated_fills_only_total():
    p = Paging.unpaginated(total=2)
    assert p.total == 2
    assert p.offset is None
    assert p.limit is None


def test_api_response_envelope_roundtrips():
    resp = ApiResponse[dict](data={"id": "01J..."}, paging=Paging.none())
    dumped = resp.model_dump()
    assert dumped["data"] == {"id": "01J..."}
    assert dumped["paging"]["offset"] is None


def test_validate_paging_rejects_limit_over_max():
    with pytest.raises(ValidationApiError):
        validate_paging(offset=0, limit=101)


def test_validate_paging_rejects_negative_offset():
    with pytest.raises(ValidationApiError):
        validate_paging(offset=-1, limit=20)


def test_validate_paging_accepts_defaults():
    validate_paging(offset=0, limit=20)  # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_schemas.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.api'`

- [ ] **Step 3: Write `src/foundry/api/schemas.py`**

```python
from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Paging(BaseModel):
    offset: int | None = None
    limit: int | None = None
    total: int | None = None
    total_pages: int | None = None
    has_next: bool | None = None
    has_prev: bool | None = None

    @classmethod
    def none(cls) -> Paging:
        return cls()

    @classmethod
    def for_page(cls, offset: int, limit: int, total: int) -> Paging:
        total_pages = (total + limit - 1) // limit if limit else 0
        return cls(
            offset=offset,
            limit=limit,
            total=total,
            total_pages=total_pages,
            has_next=(offset + limit) < total,
            has_prev=offset > 0,
        )

    @classmethod
    def unpaginated(cls, total: int) -> Paging:
        return cls(total=total)


class ApiResponse(BaseModel, Generic[T]):
    data: T
    paging: Paging


class ApiError(BaseModel):
    code: str
    message: str
    status_code: int
    timestamp: str
    path: str
    details: dict | None = None


class ErrorEnvelope(BaseModel):
    error: ApiError
```

- [ ] **Step 4: Write `src/foundry/api/errors.py`**

```python
from __future__ import annotations

import datetime as dt

from fastapi import Request
from fastapi.responses import JSONResponse

from foundry.api.schemas import ApiError, ErrorEnvelope


class FoundryApiError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details


class NotFoundError(FoundryApiError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(FoundryApiError):
    status_code = 409
    code = "CONFLICT"


class ValidationApiError(FoundryApiError):
    status_code = 400
    code = "VALIDATION_ERROR"


def validate_paging(offset: int, limit: int) -> None:
    if offset < 0:
        raise ValidationApiError(f"offset must be >= 0, got {offset}")
    if limit < 1:
        raise ValidationApiError(f"limit must be >= 1, got {limit}")
    if limit > 100:
        raise ValidationApiError(f"limit must be <= 100, got {limit}")


async def foundry_api_error_handler(request: Request, exc: FoundryApiError) -> JSONResponse:
    envelope = ErrorEnvelope(
        error=ApiError(
            code=exc.code,
            message=exc.message,
            status_code=exc.status_code,
            timestamp=dt.datetime.now(dt.timezone.utc).isoformat(),
            path=str(request.url.path),
            details=exc.details,
        )
    )
    return JSONResponse(status_code=exc.status_code, content=envelope.model_dump())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_schemas.py -v`
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/__init__.py src/foundry/api/schemas.py src/foundry/api/errors.py tests/api/
git commit -m "feat(api): ADR-001 response envelope, paging, and error shape"
```

---

### Task 4: Scheduler + app factory

**Files:**
- Create: `src/foundry/api/scheduler.py`
- Create: `src/foundry/api/app.py`
- Test: `tests/api/test_scheduler.py`

**Interfaces:**
- Consumes: `Store` (M0/Task 1), `Orchestrator` (Task 2), `AgentDriver`/`PlaybookSpec`.
- Produces: `class Scheduler(store: Store, interval: float = 0.2)` with `register(run_id: str, driver: AgentDriver, playbook: PlaybookSpec) -> None`, `unregister(run_id: str) -> None`, `async tick_all_once() -> None` (ticks every registered run once; marks a run `closed` + unregisters it once every `type=="task"` unit is `closed`), `async start() -> None` / `async stop() -> None` (real background loop, for production use — not used by this plan's own tests, which call `tick_all_once()` directly for determinism). `create_app(store: Store, scheduler: Scheduler) -> FastAPI` (attaches both to `app.state`, registers the ADR-001 exception handler; routers are added by later tasks as they're written — this task's version has no routers yet, just the skeleton + `GET /api/_health` so the factory is independently testable).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_scheduler.py
import pytest

from foundry.api.scheduler import Scheduler
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store

FIXTURE = "tests/orchestrator/fixtures/linear_demo.toml"


async def make_store(tmp_path) -> Store:
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_tick_all_once_advances_registered_run_and_unregisters_on_completion(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "sched run")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    scheduler = Scheduler(store)
    scheduler.register(run.id, FakeDriver(script), playbook)

    for _ in range(10):
        await scheduler.tick_all_once()

    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    assert all(u.status == "closed" for u in task_units)

    run_row = await store.get_run(run.id)
    assert run_row.status == "closed"
    assert run_row.closed_at is not None

    assert run.id not in scheduler._orchestrators  # unregistered once finished

    await store.stop()


@pytest.mark.asyncio
async def test_tick_all_once_leaves_a_blocked_run_registered(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj2", str(tmp_path))
    playbook = load_playbook("tests/orchestrator/fixtures/gated_demo.toml")
    run = await store.create_run(project.id, "gated_demo.toml", "sched run 2")
    await materialize(playbook, run.id, store)

    script = {"a": FakeStepScript(artifact={"ok": True}), "b": FakeStepScript(artifact={"ok": True})}
    scheduler = Scheduler(store)
    scheduler.register(run.id, FakeDriver(script), playbook)

    for _ in range(5):
        await scheduler.tick_all_once()

    assert run.id in scheduler._orchestrators  # still waiting on the gate — must not unregister

    run_row = await store.get_run(run.id)
    assert run_row.status == "active"

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.api.scheduler'`

- [ ] **Step 3: Write `src/foundry/api/scheduler.py`**

```python
from __future__ import annotations

import asyncio

from foundry.drivers.base import AgentDriver
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.schema import PlaybookSpec
from foundry.store.models import utcnow
from foundry.store.store import Store


class Scheduler:
    def __init__(self, store: Store, interval: float = 0.2):
        self.store = store
        self.interval = interval
        self._orchestrators: dict[str, Orchestrator] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    def register(self, run_id: str, driver: AgentDriver, playbook: PlaybookSpec) -> None:
        self._orchestrators[run_id] = Orchestrator(self.store, driver, playbook)

    def unregister(self, run_id: str) -> None:
        self._orchestrators.pop(run_id, None)

    async def tick_all_once(self) -> None:
        for run_id, orchestrator in list(self._orchestrators.items()):
            await orchestrator.tick(run_id)
            if await self._is_finished(run_id):
                await self.store.update_run(run_id, status="closed", closed_at=utcnow())
                self.unregister(run_id)

    async def _is_finished(self, run_id: str) -> bool:
        units = await self.store.list_units(run_id)
        task_units = [u for u in units if u.type == "task"]
        return bool(task_units) and all(u.status == "closed" for u in task_units)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            await self.tick_all_once()
            await asyncio.sleep(self.interval)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_scheduler.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Write `src/foundry/api/app.py`**

```python
from __future__ import annotations

from fastapi import FastAPI

from foundry.api.errors import FoundryApiError, foundry_api_error_handler
from foundry.api.scheduler import Scheduler
from foundry.store.store import Store


def create_app(store: Store, scheduler: Scheduler) -> FastAPI:
    app = FastAPI(title="Foundry API")
    app.state.store = store
    app.state.scheduler = scheduler

    app.add_exception_handler(FoundryApiError, foundry_api_error_handler)

    @app.get("/api/_health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
```

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/scheduler.py src/foundry/api/app.py tests/api/test_scheduler.py
git commit -m "feat(api): background scheduler ticking registered runs; app factory skeleton"
```

---

### Task 5: Projects API

**Files:**
- Create: `src/foundry/api/routes/__init__.py` (empty)
- Create: `src/foundry/api/routes/projects.py`
- Modify: `src/foundry/api/app.py` (register the router)
- Test: `tests/api/conftest.py`
- Test: `tests/api/test_projects.py`

**Interfaces:**
- Consumes: `Store.create_project`, `Store.list_projects`, `Store.get_project` (M0/Task 1); `ApiResponse`, `Paging`, `validate_paging` (Task 3); `NotFoundError` (Task 3).
- Produces: shared pytest fixture `api_client(tmp_path)` (in `conftest.py`) yielding a ready-to-use `(httpx.AsyncClient, Store, Scheduler)` tuple against an isolated temp DB — every later API test file imports this. `POST /api/projects` (201), `GET /api/projects` (200, paginated), `GET /api/projects/{id}` (200 or 404).

- [ ] **Step 1: Write the shared test fixture and the failing tests**

```python
# tests/api/conftest.py
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from foundry.api.app import create_app
from foundry.api.scheduler import Scheduler
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest_asyncio.fixture
async def api_client(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)

    app = create_app(store, scheduler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, store, scheduler

    await store.stop()
```

```python
# tests/api/test_projects.py
import pytest


@pytest.mark.asyncio
async def test_create_and_get_project(api_client):
    client, _store, _scheduler = api_client

    create_resp = await client.post("/api/projects", json={"name": "acme", "path": "/repos/acme"})
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["data"]["name"] == "acme"
    assert body["paging"] == {"offset": None, "limit": None, "total": None, "total_pages": None, "has_next": None, "has_prev": None}
    project_id = body["data"]["id"]

    get_resp = await client.get(f"/api/projects/{project_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["path"] == "/repos/acme"


@pytest.mark.asyncio
async def test_get_missing_project_returns_404_envelope(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/projects/does-not-exist")

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["path"] == "/api/projects/does-not-exist"


@pytest.mark.asyncio
async def test_list_projects_is_paginated(api_client):
    client, _store, _scheduler = api_client

    for i in range(3):
        await client.post("/api/projects", json={"name": f"proj-{i}", "path": f"/tmp/{i}"})

    resp = await client.get("/api/projects?offset=0&limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["paging"]["total"] == 3
    assert body["paging"]["has_next"] is True


@pytest.mark.asyncio
async def test_list_projects_rejects_limit_over_100(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/projects?limit=101")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_projects.py -v`
Expected: FAIL — `404 Not Found` from FastAPI itself (no routes registered yet) on every request.

- [ ] **Step 3: Write `src/foundry/api/routes/projects.py`**

```python
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import NotFoundError, validate_paging
from foundry.api.schemas import ApiResponse, Paging
from foundry.store.models import Project
from foundry.store.store import Store

router = APIRouter()


def _get_store(request: Request) -> Store:
    return request.app.state.store


class ProjectCreate(BaseModel):
    name: str
    path: str


class ProjectOut(BaseModel):
    id: str
    name: str
    path: str
    kg_status: str
    created_at: str


def _to_project_out(p: Project) -> ProjectOut:
    return ProjectOut(id=p.id, name=p.name, path=p.path, kg_status=p.kg_status, created_at=p.created_at.isoformat())


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate, request: Request) -> ApiResponse[ProjectOut]:
    store = _get_store(request)
    project = await store.create_project(body.name, body.path)
    return ApiResponse[ProjectOut](data=_to_project_out(project), paging=Paging.none())


@router.get("/projects")
async def list_projects(request: Request, offset: int = 0, limit: int = 20) -> ApiResponse[list[ProjectOut]]:
    validate_paging(offset, limit)
    store = _get_store(request)
    all_projects = await store.list_projects()
    total = len(all_projects)
    page = all_projects[offset : offset + limit]
    return ApiResponse[list[ProjectOut]](
        data=[_to_project_out(p) for p in page], paging=Paging.for_page(offset, limit, total)
    )


@router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request) -> ApiResponse[ProjectOut]:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")
    return ApiResponse[ProjectOut](data=_to_project_out(project), paging=Paging.none())
```

- [ ] **Step 4: Register the router in `src/foundry/api/app.py`**

```python
from foundry.api.routes.projects import router as projects_router
```

Add right after `app.add_exception_handler(...)`:

```python
    app.include_router(projects_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/ -v`
Expected: PASS (all tests in `tests/api/`, including Tasks 3-4's)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/routes/__init__.py src/foundry/api/routes/projects.py src/foundry/api/app.py \
        tests/api/conftest.py tests/api/test_projects.py
git commit -m "feat(api): projects endpoints + shared test client fixture"
```

---

### Task 6: Runs API — create, list, detail, graph, artifacts

**Files:**
- Create: `src/foundry/api/routes/runs.py`
- Modify: `src/foundry/api/app.py` (register the router)
- Test: `tests/api/test_runs.py`

**Interfaces:**
- Consumes: `Store` methods from M0 + Task 1 (`create_run`, `list_runs`, `get_run`, `list_units`, `list_deps`, `list_gates_for_run`, `list_artifacts`); `Scheduler.register` (Task 4); `load_playbook`/`PlaybookLoadError` (`foundry.playbook.loader`), `lint_plan_first`/`PlaybookLintError` (`foundry.playbook.lint`), `materialize` (`foundry.playbook.materializer`); `estimate_plan_cost` (Task 2); `FakeDriver`/`FakeStepScript` (`foundry.drivers.fake`).
- Produces: `POST /api/runs` (201 — loads+lints+materializes a playbook from a server-local path, registers with the scheduler, returns the created run); `GET /api/runs` (200, paginated, `?project_id=`/`?status=` filters); `GET /api/runs/{id}` (200 — run + units + gates, with `cost_estimate` attached to any pending `gate_type="derived"` gate); `GET /api/runs/{id}/graph` (200 — units + dep edges, non-paginated); `GET /api/runs/{id}/artifacts` (200, non-paginated, `?latest=1` returns only the max version per `work_unit_id`).

This task's routes still create the run's `Orchestrator` against `FakeDriver` — the same M0/M1a-wide constraint (no real driver in this plan). A future plan wires role/model config to pick a real driver per run; until then, every run created via the API behaves like `foundry run`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_runs.py
import pytest


@pytest.mark.asyncio
async def test_create_run_materializes_and_registers_with_scheduler(api_client):
    client, store, scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "title": "my run",
        },
    )

    assert run_resp.status_code == 201, run_resp.text
    body = run_resp.json()["data"]
    assert body["title"] == "my run"
    assert body["status"] == "active"
    run_id = body["id"]

    assert run_id in scheduler._orchestrators
    units = await store.list_units(run_id)
    assert len(units) == 3  # plan, implement, review


@pytest.mark.asyncio
async def test_create_run_with_bad_playbook_returns_400(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    resp = await client.post(
        "/api/runs",
        json={"project_id": project_id, "playbook_path": "tests/fixtures/dangling_needs.toml", "title": "bad"},
    )

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_run_for_missing_project_returns_404(api_client):
    client, _store, _scheduler = api_client

    resp = await client.post(
        "/api/runs",
        json={"project_id": "does-not-exist", "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )

    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_run_detail_shows_units_and_gates_with_cost_estimate(api_client):
    client, store, scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]
    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/playbook/fixtures/sdlc_mini.toml",
            "title": "plan-gated run",
        },
    )
    run_id = run_resp.json()["data"]["id"]

    for _ in range(5):
        await scheduler.tick_all_once()

    detail_resp = await client.get(f"/api/runs/{run_id}")
    assert detail_resp.status_code == 200
    body = detail_resp.json()["data"]
    assert body["run"]["id"] == run_id
    assert len(body["units"]) == 5

    derived_gates = [g for g in body["gates"] if g["gate_type"] == "derived"]
    assert len(derived_gates) == 1
    assert derived_gates[0]["decision"] == "pending"
    assert derived_gates[0]["cost_estimate"]["estimated_writes_steps"] == 1


@pytest.mark.asyncio
async def test_list_runs_filters_by_project_and_status(api_client):
    client, _store, _scheduler = api_client

    proj1 = (await client.post("/api/projects", json={"name": "p1", "path": "/tmp/p1"})).json()["data"]["id"]
    proj2 = (await client.post("/api/projects", json={"name": "p2", "path": "/tmp/p2"})).json()["data"]["id"]
    await client.post(
        "/api/runs",
        json={"project_id": proj1, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )
    await client.post(
        "/api/runs",
        json={"project_id": proj2, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )

    resp = await client.get(f"/api/runs?project_id={proj1}")
    assert resp.status_code == 200
    assert len(resp.json()["data"]) == 1


@pytest.mark.asyncio
async def test_get_run_graph_returns_units_and_deps(api_client):
    client, _store, _scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
        )
    ).json()["data"]["id"]

    resp = await client.get(f"/api/runs/{run_id}/graph")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body["units"]) == 3
    assert len(body["deps"]) == 2  # implement needs plan, review needs implement


@pytest.mark.asyncio
async def test_get_run_artifacts_latest_only_returns_max_version(api_client):
    client, store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/gated_demo.toml"},
        )
    ).json()["data"]["id"]

    for _ in range(5):
        await scheduler.tick_all_once()

    gates = await store.list_gates_for_run(run_id)
    await store.decide_gate(gates[0].id, "rejected", decided_by="test")
    for _ in range(5):
        await scheduler.tick_all_once()
    gates = await store.list_gates_for_run(run_id)
    pending = [g for g in gates if g.decision == "pending"]
    if pending:
        await store.decide_gate(pending[0].id, "approved", decided_by="test")
        for _ in range(5):
            await scheduler.tick_all_once()

    resp = await client.get(f"/api/runs/{run_id}/artifacts?latest=1")
    assert resp.status_code == 200
    a_artifacts = [a for a in resp.json()["data"] if a["kind"] == "a_artifact"]
    assert len(a_artifacts) == 1
    assert a_artifacts[0]["version"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: FAIL — `404 Not Found` (no `/api/runs` routes registered yet).

- [ ] **Step 3: Write `src/foundry/api/routes/runs.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import NotFoundError, ValidationApiError, validate_paging
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.cost import estimate_plan_cost
from foundry.playbook.lint import PlaybookLintError, lint_plan_first
from foundry.playbook.loader import PlaybookLoadError, load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.models import Artifact, Gate, Run, UnitDep, WorkUnit
from foundry.store.store import Store

router = APIRouter()


def _get_scheduler(request: Request):
    return request.app.state.scheduler


class RunCreate(BaseModel):
    project_id: str
    playbook_path: str
    title: str | None = None


class RunOut(BaseModel):
    id: str
    project_id: str
    playbook_ref: str
    title: str
    status: str
    created_at: str


class WorkUnitOut(BaseModel):
    id: str
    step_id: str
    type: str
    status: str
    attempt: int
    owner_session_id: str | None


class GateOut(BaseModel):
    id: str
    work_unit_id: str
    gate_type: str
    decision: str
    artifact_id: str | None
    cost_estimate: dict | None = None


class ArtifactOut(BaseModel):
    id: str
    work_unit_id: str
    kind: str
    version: int
    produced_by_role: str
    payload_json: dict


class RunDetailOut(BaseModel):
    run: RunOut
    units: list[WorkUnitOut]
    gates: list[GateOut]


class UnitDepOut(BaseModel):
    unit_id: str
    needs_unit_id: str


class GraphOut(BaseModel):
    units: list[WorkUnitOut]
    deps: list[UnitDepOut]


def _to_run_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id, project_id=r.project_id, playbook_ref=r.playbook_ref,
        title=r.title, status=r.status, created_at=r.created_at.isoformat(),
    )


def _to_unit_out(u: WorkUnit) -> WorkUnitOut:
    return WorkUnitOut(
        id=u.id, step_id=u.step_id, type=u.type, status=u.status,
        attempt=u.attempt, owner_session_id=u.owner_session_id,
    )


def _to_artifact_out(a: Artifact) -> ArtifactOut:
    return ArtifactOut(
        id=a.id, work_unit_id=a.work_unit_id, kind=a.kind, version=a.version,
        produced_by_role=a.produced_by_role, payload_json=a.payload_json,
    )


@router.post("/runs", status_code=201)
async def create_run(body: RunCreate, request: Request) -> ApiResponse[RunOut]:
    store = _get_store(request)
    scheduler = _get_scheduler(request)

    project = await store.get_project(body.project_id)
    if project is None:
        raise NotFoundError(f"Project {body.project_id} not found")

    try:
        playbook = load_playbook(body.playbook_path)
        lint_plan_first(playbook)
    except (PlaybookLoadError, PlaybookLintError) as e:
        raise ValidationApiError(str(e)) from e

    run = await store.create_run(project.id, body.playbook_path, body.title or playbook.description or playbook.id)
    await materialize(playbook, run.id, store)

    script = {step.id: FakeStepScript(artifact={"ok": True}) for step in playbook.steps}
    scheduler.register(run.id, FakeDriver(script), playbook)

    return ApiResponse[RunOut](data=_to_run_out(run), paging=Paging.none())


@router.get("/runs")
async def list_runs(
    request: Request, project_id: str | None = None, status: str | None = None, offset: int = 0, limit: int = 20
) -> ApiResponse[list[RunOut]]:
    validate_paging(offset, limit)
    store = _get_store(request)
    all_runs = await store.list_runs(project_id=project_id, status=status)
    total = len(all_runs)
    page = all_runs[offset : offset + limit]
    return ApiResponse[list[RunOut]](data=[_to_run_out(r) for r in page], paging=Paging.for_page(offset, limit, total))


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str, request: Request) -> ApiResponse[RunDetailOut]:
    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    scheduler = _get_scheduler(request)
    orchestrator = scheduler._orchestrators.get(run_id)
    playbook = orchestrator.playbook if orchestrator is not None else None

    units = await store.list_units(run_id)
    units_by_id = {u.id: u for u in units}
    gates = await store.list_gates_for_run(run_id)

    gate_outs = []
    for g in gates:
        cost_estimate = None
        if g.gate_type == "derived" and g.decision == "pending" and playbook is not None:
            gate_step_id = units_by_id[g.work_unit_id].step_id
            cost_estimate = estimate_plan_cost(playbook, gate_step_id)
        gate_outs.append(
            GateOut(
                id=g.id, work_unit_id=g.work_unit_id, gate_type=g.gate_type,
                decision=g.decision, artifact_id=g.artifact_id, cost_estimate=cost_estimate,
            )
        )

    return ApiResponse[RunDetailOut](
        data=RunDetailOut(run=_to_run_out(run), units=[_to_unit_out(u) for u in units], gates=gate_outs),
        paging=Paging.none(),
    )


@router.get("/runs/{run_id}/graph")
async def get_run_graph(run_id: str, request: Request) -> ApiResponse[GraphOut]:
    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    units = await store.list_units(run_id)
    deps = await store.list_deps(run_id)
    graph = GraphOut(
        units=[_to_unit_out(u) for u in units],
        deps=[UnitDepOut(unit_id=d.unit_id, needs_unit_id=d.needs_unit_id) for d in deps],
    )
    return ApiResponse[GraphOut](data=graph, paging=Paging.unpaginated(len(units)))


@router.get("/runs/{run_id}/artifacts")
async def get_run_artifacts(run_id: str, request: Request, latest: int = 0) -> ApiResponse[list[ArtifactOut]]:
    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    artifacts = await store.list_artifacts(run_id)
    if latest:
        best: dict[str, Artifact] = {}
        for a in artifacts:
            current = best.get(a.work_unit_id)
            if current is None or a.version > current.version:
                best[a.work_unit_id] = a
        artifacts = list(best.values())

    return ApiResponse[list[ArtifactOut]](
        data=[_to_artifact_out(a) for a in artifacts], paging=Paging.unpaginated(len(artifacts))
    )
```

- [ ] **Step 4: Register the router in `src/foundry/api/app.py`**

```python
from foundry.api.routes.runs import router as runs_router
```

```python
    app.include_router(runs_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/ -v`
Expected: PASS (every test in `tests/api/`)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/routes/runs.py src/foundry/api/app.py tests/api/test_runs.py
git commit -m "feat(api): runs endpoints (create/list/detail/graph/artifacts) with cost-estimate on pending derived gates"
```

---

### Task 7: Gates API — the reject/rework/version-increment proof, end to end

**Files:**
- Create: `src/foundry/api/routes/gates.py`
- Modify: `src/foundry/api/app.py` (register the router)
- Test: `tests/api/test_gates.py`

**Interfaces:**
- Consumes: `Store.decide_gate`, `Store.list_gates_for_run` (M0/Task 1); `Scheduler.tick_all_once` (Task 4, test-only — a real deployment relies on `Scheduler.start()`'s background loop, tests call `tick_all_once()` directly for determinism).
- Produces: `POST /api/gates/{gate_id}/decide` (200 on success, 404 if the gate doesn't exist, 409 if already decided — decisions are one-shot, matching "reject double-cancel"-style idempotency from design doc §12 applied to gates).

- [ ] **Step 1: Write the failing tests — this is M1's actual exit-criterion proof**

```python
# tests/api/test_gates.py
import pytest


async def _create_run(client, playbook_path: str) -> tuple[str, str]:
    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]
    run_resp = await client.post(
        "/api/runs", json={"project_id": project_id, "playbook_path": playbook_path, "title": "gate test run"}
    )
    return project_id, run_resp.json()["data"]["id"]


@pytest.mark.asyncio
async def test_full_plan_approve_implement_reject_rework_approve_cycle(api_client):
    """The M1 exit criterion, driven entirely through the HTTP API (standing in
    for the browser) — no direct Store/Orchestrator calls below this line."""
    client, store, scheduler = api_client
    _project_id, run_id = await _create_run(client, "tests/orchestrator/fixtures/gated_demo.toml")

    for _ in range(5):
        await scheduler.tick_all_once()

    detail = (await client.get(f"/api/runs/{run_id}")).json()["data"]
    gate = next(g for g in detail["gates"] if g["decision"] == "pending")

    # Reject with feedback — the rework loop.
    reject_resp = await client.post(
        f"/api/gates/{gate['id']}/decide",
        json={"decision": "rejected", "feedback_chips": ["incomplete"], "feedback_text": "add more detail"},
    )
    assert reject_resp.status_code == 200

    for _ in range(5):
        await scheduler.tick_all_once()

    detail = (await client.get(f"/api/runs/{run_id}")).json()["data"]
    a_task = next(u for u in detail["units"] if u["step_id"] == "a")
    assert a_task["status"] == "blocked"  # re-dispatched, produced a second artifact, gated again
    new_gate = next(g for g in detail["gates"] if g["decision"] == "pending")
    assert new_gate["id"] != gate["id"]

    # Approve the reworked artifact.
    approve_resp = await client.post(f"/api/gates/{new_gate['id']}/decide", json={"decision": "approved"})
    assert approve_resp.status_code == 200

    for _ in range(5):
        await scheduler.tick_all_once()

    run_row = await store.get_run(run_id)
    assert run_row.status == "closed"

    artifacts_resp = await client.get(f"/api/runs/{run_id}/artifacts")
    a_artifacts = sorted(
        [a for a in artifacts_resp.json()["data"] if a["kind"] == "a_artifact"], key=lambda a: a["version"]
    )
    assert [a["version"] for a in a_artifacts] == [1, 2]  # rework really did increment the version


@pytest.mark.asyncio
async def test_decide_missing_gate_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/gates/does-not-exist/decide", json={"decision": "approved"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_decide_already_decided_gate_returns_409(api_client):
    client, store, scheduler = api_client
    _project_id, run_id = await _create_run(client, "tests/orchestrator/fixtures/gated_demo.toml")

    for _ in range(5):
        await scheduler.tick_all_once()

    gates = await store.list_gates_for_run(run_id)
    gate_id = gates[0].id

    first = await client.post(f"/api/gates/{gate_id}/decide", json={"decision": "approved"})
    assert first.status_code == 200

    second = await client.post(f"/api/gates/{gate_id}/decide", json={"decision": "approved"})
    assert second.status_code == 409
    assert second.json()["error"]["code"] == "CONFLICT"


@pytest.mark.asyncio
async def test_decide_rejects_invalid_decision_value(api_client):
    client, store, scheduler = api_client
    _project_id, run_id = await _create_run(client, "tests/orchestrator/fixtures/gated_demo.toml")
    for _ in range(5):
        await scheduler.tick_all_once()
    gates = await store.list_gates_for_run(run_id)

    resp = await client.post(f"/api/gates/{gates[0].id}/decide", json={"decision": "maybe"})

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_gates.py -v`
Expected: FAIL — `404 Not Found` from FastAPI (no `/api/gates` routes registered).

- [ ] **Step 3: Write `src/foundry/api/routes/gates.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import ConflictError, NotFoundError, ValidationApiError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.store.models import Gate

router = APIRouter()

_VALID_DECISIONS = {"approved", "rejected"}


class GateDecideIn(BaseModel):
    decision: str
    feedback_chips: list[str] = []
    feedback_text: str | None = None


class GateOut(BaseModel):
    id: str
    work_unit_id: str
    gate_type: str
    decision: str
    decided_by: str | None


def _to_gate_out(g: Gate) -> GateOut:
    return GateOut(id=g.id, work_unit_id=g.work_unit_id, gate_type=g.gate_type, decision=g.decision, decided_by=g.decided_by)


@router.post("/gates/{gate_id}/decide")
async def decide_gate(gate_id: str, body: GateDecideIn, request: Request) -> ApiResponse[GateOut]:
    if body.decision not in _VALID_DECISIONS:
        raise ValidationApiError(f"decision must be one of {sorted(_VALID_DECISIONS)}, got {body.decision!r}")

    store = _get_store(request)

    async def _fetch(session):
        return await session.get(Gate, gate_id)

    gate = await store.read(_fetch)
    if gate is None:
        raise NotFoundError(f"Gate {gate_id} not found")
    if gate.decision != "pending":
        raise ConflictError(f"Gate {gate_id} was already {gate.decision}")

    feedback = {"chips": body.feedback_chips, "text": body.feedback_text} if body.decision == "rejected" else None
    await store.decide_gate(gate_id, body.decision, feedback=feedback, decided_by="api")

    updated = await store.read(_fetch)
    return ApiResponse[GateOut](data=_to_gate_out(updated), paging=Paging.none())
```

- [ ] **Step 4: Register the router in `src/foundry/api/app.py`**

```python
from foundry.api.routes.gates import router as gates_router
```

```python
    app.include_router(gates_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/ -v`
Expected: PASS (every test in `tests/api/`)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/routes/gates.py src/foundry/api/app.py tests/api/test_gates.py
git commit -m "feat(api): gates decide endpoint — proves the full reject/rework/approve cycle over HTTP"
```

---

### Task 8: Cancel API

**Files:**
- Modify: `src/foundry/api/routes/runs.py`
- Test: `tests/api/test_runs.py` (extend)

**Interfaces:**
- Consumes: `Store.update_unit`, `Store.update_run` (M0/Task 1); `Scheduler.unregister` (Task 4).
- Produces: `POST /api/runs/{run_id}/cancel` (204 on success, 404 if the run doesn't exist, 409 if already `cancelled`/`closed`).

Dispatch is sequential within `tick()` (Global Constraints) — by the time a `POST` request reaches this handler there is never an in-flight session to tree-kill (every dispatched session is fully collected before `tick()` returns control to the scheduler). Cancel therefore only needs to flip every non-terminal unit and stop scheduling the run; "kill the process group before flipping status" becomes meaningful once M2 makes dispatch concurrent/backgrounded — noted here, not built here.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_runs.py — append to the existing file
@pytest.mark.asyncio
async def test_cancel_run_flips_non_terminal_units_and_stops_scheduling(api_client):
    client, store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/gated_demo.toml"},
        )
    ).json()["data"]["id"]

    for _ in range(5):
        await scheduler.tick_all_once()

    resp = await client.post(f"/api/runs/{run_id}/cancel")
    assert resp.status_code == 204

    units = await store.list_units(run_id)
    assert all(u.status in ("closed", "failed", "killed") for u in units)

    run_row = await store.get_run(run_id)
    assert run_row.status == "cancelled"
    assert run_id not in scheduler._orchestrators


@pytest.mark.asyncio
async def test_double_cancel_returns_409(api_client):
    client, _store, scheduler = api_client

    proj = (await client.post("/api/projects", json={"name": "p", "path": "/tmp/p"})).json()["data"]["id"]
    run_id = (
        await client.post(
            "/api/runs",
            json={"project_id": proj, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
        )
    ).json()["data"]["id"]

    first = await client.post(f"/api/runs/{run_id}/cancel")
    assert first.status_code == 204

    second = await client.post(f"/api/runs/{run_id}/cancel")
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_cancel_missing_run_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/runs/does-not-exist/cancel")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_runs.py -v -k cancel`
Expected: FAIL with `404 Not Found` (route doesn't exist yet).

- [ ] **Step 3: Add the cancel route to `src/foundry/api/routes/runs.py`**

Add this import at the top:

```python
from fastapi import Response

from foundry.store.models import utcnow
```

Add the route (place it after `create_run`, before `list_runs`):

```python
@router.post("/runs/{run_id}/cancel", status_code=204)
async def cancel_run(run_id: str, request: Request) -> Response:
    store = _get_store(request)
    scheduler = _get_scheduler(request)

    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")
    if run.status in ("cancelled", "closed"):
        raise ConflictError(f"Run {run_id} is already {run.status}")

    units = await store.list_units(run_id)
    for unit in units:
        if unit.status not in ("closed", "failed", "killed", "cancelled"):
            await store.update_unit(unit.id, status="killed")

    await store.update_run(run_id, status="cancelled", closed_at=utcnow())
    scheduler.unregister(run_id)
    await store.append_event(run_id, None, "run.cancelled", {})

    return Response(status_code=204)
```

Also add `ConflictError` to the existing `from foundry.api.errors import ...` line at the top of the file (it currently imports `NotFoundError, ValidationApiError, validate_paging` — extend it to `NotFoundError, ConflictError, ValidationApiError, validate_paging`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/ -v`
Expected: PASS (every test in `tests/api/`)

- [ ] **Step 5: Commit**

```bash
git add src/foundry/api/routes/runs.py tests/api/test_runs.py
git commit -m "feat(api): run cancel endpoint (idempotent, 409 on double-cancel)"
```

---

### Task 9: SSE event stream

**Files:**
- Create: `src/foundry/api/routes/stream.py`
- Modify: `src/foundry/api/app.py` (register the router)
- Test: `tests/api/test_stream.py`

**Interfaces:**
- Consumes: `Store.list_events` (M0).
- Produces: `GET /api/stream/{run_id}` — SSE, resumable via the `Last-Event-ID` header (falling back to `?after_seq=`), one event per `Event` row (`event:` = `Event.type`, `data:` = JSON-encoded `Event.payload_json`, `id:` = `Event.seq`).

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_stream.py
import asyncio
import json

import pytest


@pytest.mark.asyncio
async def test_stream_replays_existing_events_then_new_ones(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("proj", "/tmp/proj")
    run = await store.create_run(project.id, "pb.toml", "stream test")
    await store.append_event(run.id, None, "run.created", {"note": "first"})

    lines: list[str] = []
    async with client.stream("GET", f"/api/stream/{run.id}", headers={"Last-Event-ID": "0"}) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            lines.append(line)
            if any("run.created" in item for item in lines):
                break

    text = "\n".join(lines)
    assert "event: run.created" in text
    assert '"note": "first"' in text


@pytest.mark.asyncio
async def test_stream_resumes_from_last_event_id(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("proj2", "/tmp/proj2")
    run = await store.create_run(project.id, "pb.toml", "stream resume test")
    seq1 = await store.append_event(run.id, None, "event.one", {})
    await store.append_event(run.id, None, "event.two", {})

    lines: list[str] = []
    async with client.stream("GET", f"/api/stream/{run.id}", headers={"Last-Event-ID": str(seq1)}) as response:
        async for line in response.aiter_lines():
            lines.append(line)
            if any("event.two" in item for item in lines):
                break

    text = "\n".join(lines)
    assert "event.one" not in text  # already seen, per Last-Event-ID
    assert "event.two" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_stream.py -v --timeout=10`
Expected: FAIL — `404 Not Found` (route doesn't exist). (If `pytest-timeout` isn't installed, omit `--timeout` here — Step 3's implementation terminates promptly on client disconnect regardless, so a hang isn't expected once the route exists.)

- [ ] **Step 3: Write `src/foundry/api/routes/stream.py`**

```python
from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from foundry.api.routes.projects import _get_store

router = APIRouter()


@router.get("/stream/{run_id}")
async def stream_run(run_id: str, request: Request) -> EventSourceResponse:
    store = _get_store(request)
    last_seq = _parse_last_event_id(request)

    async def event_generator():
        seq = last_seq
        while True:
            if await request.is_disconnected():
                break
            events = await store.list_events(run_id, after_seq=seq)
            for ev in events:
                seq = ev.seq
                yield {"id": str(ev.seq), "event": ev.type, "data": json.dumps(ev.payload_json)}
            await asyncio.sleep(0.2)

    return EventSourceResponse(event_generator())


def _parse_last_event_id(request: Request) -> int:
    header = request.headers.get("last-event-id")
    if header is not None:
        try:
            return int(header)
        except ValueError:
            return 0
    param = request.query_params.get("after_seq")
    if param is not None:
        try:
            return int(param)
        except ValueError:
            return 0
    return 0
```

- [ ] **Step 4: Register the router in `src/foundry/api/app.py`**

```python
from foundry.api.routes.stream import router as stream_router
```

```python
    app.include_router(stream_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_stream.py -v`
Expected: PASS (2 tests — each exits its `async with client.stream(...)` block as soon as it sees the expected event, so no test-side timeout is needed for a passing run)

- [ ] **Step 6: Run the entire suite**

Run: `uv run pytest -v`
Expected: PASS (every test in the repo)

- [ ] **Step 7: Commit**

```bash
git add src/foundry/api/routes/stream.py src/foundry/api/app.py tests/api/test_stream.py
git commit -m "feat(api): SSE event stream with Last-Event-ID resume"
```

---

### Task 10: `foundry serve` — real entrypoint wiring

**Files:**
- Modify: `src/foundry/cli.py`
- Modify: `pyproject.toml` (add `uvicorn` — already a dependency; no change needed, verify only)

**Interfaces:**
- Consumes: `create_app` (Task 4), `Scheduler` (Task 4), `Store`/`make_engine`/`init_db`/`make_sessionmaker` (M0).
- Produces: `foundry serve [--db PATH] [--host HOST] [--port PORT]` — starts the store, the scheduler's background loop, and a real HTTP server (`uvicorn`), until interrupted.

This task has no automated test — spinning up a real listening TCP server and asserting against it is disproportionate for what's a thin wiring command over already-tested pieces (`create_app`, `Scheduler`, `Store` are each fully covered by Tasks 1-9). Verify manually per Step 3.

- [ ] **Step 1: Add the `serve` command to `src/foundry/cli.py`**

Add these imports at the top:

```python
import uvicorn

from foundry.api.app import create_app
from foundry.api.scheduler import Scheduler
```

Add the command (after the existing `events` command):

```python
@app.command()
def serve(db: str = "foundry.db", host: str = "127.0.0.1", port: int = 8000) -> None:
    asyncio.run(_serve(db, host, port))


async def _serve(db: str, host: str, port: int) -> None:
    engine = make_engine(db)
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    scheduler = Scheduler(store)
    await scheduler.start()

    api_app = create_app(store, scheduler)
    config = uvicorn.Config(api_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        await scheduler.stop()
        await store.stop()
```

- [ ] **Step 2: Run the full suite to confirm nothing broke**

Run: `uv run pytest -v`
Expected: PASS (every test — this task adds no new tests, just a CLI command)

- [ ] **Step 3: Manual verification**

```bash
uv run foundry serve --db /tmp/foundry-manual-test.db --port 8123 &
sleep 1
curl -s http://127.0.0.1:8123/api/_health
curl -s -X POST http://127.0.0.1:8123/api/projects -H 'content-type: application/json' -d '{"name":"manual","path":"/tmp/manual"}'
kill %1
rm -f /tmp/foundry-manual-test.db*
```

Expected: health check returns `{"status":"ok"}`; the project POST returns a `{data: {...}, paging: {...}}` envelope with a 26-character ULID `id`.

- [ ] **Step 4: Commit**

```bash
git add src/foundry/cli.py
git commit -m "feat(cli): foundry serve — real HTTP entrypoint wiring store, scheduler, and the API app"
```

---

## Out of scope for this plan (tracked, not forgotten)

- **`/internal` API + `ClaudeCodeDriver` + real end-to-end run** — still owed from M0's own deferred exit criterion (b); not picked up here. Every run in this plan executes on `FakeDriver`.
- **React dashboard** — M1b, a separate plan/branch, consumes this API.
- **`human_task` completion endpoint + My-queue view** — `Store.complete_human_task` exists (M0) but nothing in this plan calls it over HTTP; a run containing a `human_task` step stays registered with the scheduler forever (harmlessly re-ticking) until that lands.
- **`notes_addressed` chat contract** — no `POST /api/runs/{id}/chat` in this plan; chat-to-role is deferred (design doc lists it under M4 gate-policy/chat work, and it depends on artifact-schema validation this plan doesn't add either).
- **Artifact JSON-schema validation** — artifacts are still accepted with whatever `payload_json` a step produces; `jsonschema`-backed validation against a declared `schema_ref` is real scope this plan doesn't cover (no schema registry exists yet — that's pack content, M4).
- **Real historical cost estimation** — `estimate_plan_cost` is a documented heuristic (flat tokens-per-step); the real per-project rollup needs actual session token usage from a real driver (M2+, design doc §11.1).
- **Event redaction glob configuration** — the key-pattern regex in `redaction.py` is a fixed default, not the "configurable globs for sensitive paths" the design doc mentions; making it configurable is a small follow-up, not blocking.
- **Cancel's tree-kill-before-mark ordering** — meaningful once M2 makes dispatch concurrent; M1a's cancel is a pure status flip since dispatch is still synchronous (see Task 8).
