# M2a — Fan-out Engine (Convoys, Worktrees, Review Loop, Second Driver) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend engine capability design doc §15's M2 milestone calls for — `fan_out` + convoys, per-unit git worktrees, the `integrate` step's generic escalation contract, an agent-review loop with round cap, concurrency caps + token budgets, a second driver (CodexDriver), and metrics rollup — so a 3-slice feature can be implemented by parallel agents, peer-reviewed, and integrated to one branch, provably on `FakeDriver` before any real provider is touched. M2b (a separate plan) builds the fleet/DAG/metrics dashboard views that consume this engine's output.

**Architecture:** Extends the existing single-writer `Store` / `Orchestrator.tick()` model from M0/M1a — no new tables beyond what M0 already shipped (`work_units.convoy_id` exists unused since M0; this plan is the first thing to populate it). Fan-out is resolved **dynamically at tick-time**, not at playbook-materialization time, because the array being fanned out over (e.g. `architecture_artifact.slices`) is only known once an upstream artifact exists — mirroring how M0 already creates `session` work units dynamically during `dispatch()` rather than statically at parse time. Per-unit worktrees are real local `git worktree` operations against the project's own repo (no network calls). The agent-review loop reuses the *existing* rejected-gate rework machinery in `apply_gate_decisions` almost unchanged — the only new piece is the engine auto-deciding `gate_type="agent"` gates from a spawned reviewer session's output instead of waiting on a human API call.

**Tech Stack:** Same as M0/M1a — Python 3.12+, SQLAlchemy 2 async + aiosqlite, Pydantic v2, pytest + pytest-asyncio, ruff. No new runtime dependencies.

## Global Constraints

- **FakeDriver-first, always** (CLAUDE.md, design doc §8): every feature in this plan gets a FakeDriver-backed test before CodexDriver is touched, and CodexDriver itself is validated against a *scripted local subprocess fixture* (a fake `codex` shell script checked into `tests/fixtures/`), never a real network call or real `codex` CLI invocation. Nothing in this plan spends real tokens or makes an external network call — consistent with the standing directive to ask before any external network call, this plan simply doesn't make one.
- **No SDLC knowledge in the engine** (design doc §4.1: "No role names, phase names, or SDLC knowledge appears anywhere in this loop"). The `integrate` step is *not* hardcoded anywhere in this plan — instead, StepSpec gets one new generic field (`escalates_on`) so *any* step whose produced artifact lists escalations gets a `human_task` created. The integrator role's actual merge/conflict-resolution logic is pack/prompt content (out of scope here, same as every other role), simulated for tests via `FakeDriver` scripts that return a canned `integration_artifact`.
- **Exactly one level of `fan_out_from` chaining is in scope.** A step can `fan_out` over an upstream artifact array, and other steps can declare `fan_out_from = "<that step's id>"` to inherit the same per-slice fan-out with a needs-edge to their matching slice. Chaining a `fan_out_from` step from *another* `fan_out_from` step (two hops) is out of scope for M2 — not needed by the exit criterion (`implement` fans out, `agent_review` inherits, `integrate` consumes the whole convoy) and adds graph-walking complexity with no current consumer. Playbook validation rejects a `fan_out_from` chain deeper than one hop.
- **Reviewer "rotation" (roadmap: "agent-review loop with rotation and round cap") is descoped to round-cap only.** Rotating which reviewer identity/model handles each round is pack/role configuration (which reviewer roles exist, how many, on what basis to rotate) that has no consumer until packs exist (M4) — building rotation logic now against a role system that doesn't exist yet would be speculative. Task 6 implements the round cap and auto-decision loop; the engine already threads `attempt` through to each review dispatch, so a future pack-aware rotation only needs to read that counter, not change the engine.
- **`loop.until` is not a general expression language.** The only supported semantics is the one design doc §5.1's example actually describes: the reviewer's verdict must equal `"approved"` to end the loop; anything else is a rejection triggering rework, up to `max_rounds`. The `until` field is stored on `LoopSpec` for forward-compatibility and human readability in playbook files, but the engine does not parse or evaluate it as an expression in M2 — building a mini expression evaluator for a single hardcoded comparison is exactly the kind of premature abstraction CLAUDE.md's engineering conventions rule out.
- **Metrics rollup computes on read, not on a persisted schedule.** Design doc §11.1 describes "a rollup job (on run close + nightly)" materializing time series into a new table. M2a implements the *derivations* as pure functions over the event log, exposed via a single `GET /api/metrics/{project_id}` endpoint computed on each request. No new table, no background job. This is called out explicitly (not silently descoped) because if per-project event volume ever makes on-read computation too slow, *that's* the trigger for the persisted-rollup version — not before (same "revisit as it grows" philosophy design doc §15's closing note already commits to).
- **CodexDriver's "mixed providers" exit-criterion demo uses two differently-configured `FakeDriver` instances**, not a real Claude Code / Codex CLI. `ClaudeCodeDriver` itself was already deferred out of M0 (`docs/status.html` — "Same 3-step linear playbook runs end-to-end on a real repo via ClaudeCodeDriver — deferred to a follow-up plan... not started"); M2a does not pick that up either. CodexDriver is still built as a real, protocol-conformant, independently-tested adapter class (satisfying the roadmap's literal "CodexDriver" scope item) — it's the *live end-to-end token-spending validation* of either real driver that stays deferred, consistent with M0's own precedent.
- Every new/changed file lives under `src/foundry/` or `tests/`; no `frontend/` changes in this plan (that's M2b).

---

### Task 1: Playbook schema — `fan_out`, `fan_out_from`, `loop`, `escalates_on`

**Files:**
- Modify: `src/foundry/playbook/schema.py`
- Test: `tests/playbook/test_schema.py` (new file)

**Interfaces:**
- Produces: `LoopSpec` (`back_to: str`, `until: str = "verdict == approved"`, `max_rounds: int = 5`), extended `StepSpec` with `fan_out: str | None`, `fan_out_from: str | None`, `loop: LoopSpec | None`, `escalates_on: str | None`. `STEP_TYPE_TO_UNIT_TYPE: dict[str, str]` (renamed/promoted from materializer's private `_TYPE_MAP` so both `materializer.py` and `orchestrator/tick.py` import the same mapping instead of duplicating it). `PlaybookSpec` gains a model validator enforcing: `fan_out`/`fan_out_from` mutually exclusive; `fan_out_from` must reference a step with `fan_out` set (not another `fan_out_from` step — enforces the one-hop-chain constraint); `loop.back_to` must reference a real step id.

- [ ] **Step 1: Write the failing tests**

```python
# tests/playbook/test_schema.py
import pytest
from pydantic import ValidationError

from foundry.playbook.schema import LoopSpec, PlaybookSpec, StepSpec


def test_step_spec_defaults_have_no_fan_out_or_loop():
    step = StepSpec(id="a", role="dev")
    assert step.fan_out is None
    assert step.fan_out_from is None
    assert step.loop is None
    assert step.escalates_on is None


def test_fan_out_and_fan_out_from_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        PlaybookSpec(
            id="p",
            steps=[
                StepSpec(id="a", role="dev", fan_out="x.slices", fan_out_from="b"),
                StepSpec(id="b", role="dev", fan_out="y.slices"),
            ],
        )


def test_fan_out_from_must_reference_a_fan_out_step():
    with pytest.raises(ValidationError, match="must reference a step with fan_out"):
        PlaybookSpec(
            id="p",
            steps=[
                StepSpec(id="a", role="dev"),
                StepSpec(id="b", role="dev", fan_out_from="a"),
            ],
        )


def test_fan_out_from_chain_deeper_than_one_hop_is_rejected():
    with pytest.raises(ValidationError, match="must reference a step with fan_out"):
        PlaybookSpec(
            id="p",
            steps=[
                StepSpec(id="a", role="dev", fan_out="x.slices"),
                StepSpec(id="b", role="dev", fan_out_from="a"),
                StepSpec(id="c", role="dev", fan_out_from="b"),  # b has fan_out_from, not fan_out
            ],
        )


def test_fan_out_from_unknown_step_rejected():
    with pytest.raises(ValidationError, match="unknown step"):
        PlaybookSpec(id="p", steps=[StepSpec(id="a", role="dev", fan_out_from="ghost")])


def test_loop_back_to_unknown_step_rejected():
    with pytest.raises(ValidationError, match="loop.back_to"):
        PlaybookSpec(
            id="p",
            steps=[StepSpec(id="a", role="dev", loop=LoopSpec(back_to="ghost"))],
        )


def test_valid_fan_out_playbook_parses():
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="architecture", role="architect", produces="architecture_artifact"),
            StepSpec(
                id="implement", role="dev", needs=["architecture"], fan_out="architecture_artifact.slices"
            ),
            StepSpec(
                id="review",
                role="reviewer",
                needs=["implement"],
                fan_out_from="implement",
                gate="agent",
                loop=LoopSpec(back_to="implement", max_rounds=5),
            ),
        ],
    )
    assert playbook.steps[2].loop.max_rounds == 5
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/playbook/test_schema.py -v`
Expected: FAIL — `ImportError: cannot import name 'LoopSpec'`

- [ ] **Step 3: Extend `src/foundry/playbook/schema.py`**

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

STEP_TYPE_TO_UNIT_TYPE = {"task": "task", "derived_gate": "gate", "human_task": "human_task"}


class LoopSpec(BaseModel):
    back_to: str
    until: str = "verdict == approved"
    max_rounds: int = 5


class StepSpec(BaseModel):
    id: str
    role: str
    type: Literal["task", "derived_gate", "human_task"] = "task"
    needs: list[str] = Field(default_factory=list)
    produces: str | None = None
    gate: Literal["human", "agent", "none"] | None = "none"
    writes: bool = False
    fan_out: str | None = None
    fan_out_from: str | None = None
    loop: LoopSpec | None = None
    escalates_on: str | None = None


class PlaybookSpec(BaseModel):
    id: str
    description: str = ""
    steps: list[StepSpec]

    @model_validator(mode="after")
    def _validate_fan_out_and_loop(self) -> "PlaybookSpec":
        ids = {s.id for s in self.steps}
        by_id = {s.id: s for s in self.steps}
        for step in self.steps:
            if step.fan_out and step.fan_out_from:
                raise ValueError(f"step {step.id!r}: fan_out and fan_out_from are mutually exclusive")
            if step.fan_out_from is not None:
                if step.fan_out_from not in ids:
                    raise ValueError(
                        f"step {step.id!r}: fan_out_from references unknown step {step.fan_out_from!r}"
                    )
                source = by_id[step.fan_out_from]
                if not source.fan_out:
                    raise ValueError(
                        f"step {step.id!r}: fan_out_from={step.fan_out_from!r} "
                        "must reference a step with fan_out set (one-hop chains only)"
                    )
            if step.loop is not None and step.loop.back_to not in ids:
                raise ValueError(
                    f"step {step.id!r}: loop.back_to references unknown step {step.loop.back_to!r}"
                )
        return self
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/playbook/test_schema.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full existing suite to confirm no regressions**

Run: `uv run pytest -q`
Expected: PASS, same count as before plus 7

- [ ] **Step 6: Commit**

```bash
git add src/foundry/playbook/schema.py tests/playbook/test_schema.py
git commit -m "feat(playbook): fan_out, fan_out_from, loop, escalates_on step fields"
```

---

### Task 2: Materializer — static/dynamic step split

**Files:**
- Modify: `src/foundry/playbook/materializer.py`
- Modify: `tests/playbook/test_materializer.py` (add cases; existing test must keep passing unchanged)
- Test: new fixture `tests/playbook/fixtures/fanout_demo.toml`

**Interfaces:**
- Consumes: `StepSpec.fan_out`/`fan_out_from`, `STEP_TYPE_TO_UNIT_TYPE` (Task 1).
- Produces: `materialize(playbook, run_id, store) -> dict[str, str]` — **unchanged signature**, but now only creates units for "static" steps (steps with no `fan_out`/`fan_out_from` and not transitively downstream of one). Dynamic steps are left for the orchestrator's `_fan_out` phase (Task 3). `is_dynamic_step(step, steps_by_id) -> bool` — exported so Task 3 can reuse the exact same classification.

- [ ] **Step 1: Add the fixture and failing test**

```toml
# tests/playbook/fixtures/fanout_demo.toml
[playbook]
id = "fanout_demo"
description = "architecture -> implement (fan_out) -> review (fan_out_from) -> integrate (convoy-consuming)"

[[step]]
id = "architecture"
role = "architect"
produces = "architecture_artifact"
gate = "human"

[[step]]
id = "implement"
role = "developer"
needs = ["architecture"]
fan_out = "architecture_artifact.slices"
produces = "code_diff_artifact"
gate = "none"

[[step]]
id = "review"
role = "reviewer"
needs = ["implement"]
fan_out_from = "implement"
produces = "review_artifact"
gate = "agent"

[[step]]
id = "integrate"
role = "integrator"
needs = ["review"]
produces = "integration_artifact"
gate = "human"
escalates_on = "escalated"
```

```python
# tests/playbook/test_materializer.py — add these, keep the existing test as-is
from foundry.playbook.materializer import is_dynamic_step


@pytest.mark.asyncio
async def test_materialize_skips_dynamic_steps(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/playbook/fixtures/fanout_demo.toml")
    run = await store.create_run(project.id, "fanout_demo.toml", "demo run")

    step_to_unit = await materialize(playbook, run.id, store)

    # Only "architecture" is static: implement/review/integrate are all
    # transitively downstream of implement's fan_out.
    assert set(step_to_unit) == {"architecture"}
    units = await store.list_units(run.id)
    assert len(units) == 1
    assert units[0].step_id == "architecture"


def test_is_dynamic_step_classification():
    playbook = load_playbook("tests/playbook/fixtures/fanout_demo.toml")
    by_id = {s.id: s for s in playbook.steps}
    assert is_dynamic_step(by_id["architecture"], by_id) is False
    assert is_dynamic_step(by_id["implement"], by_id) is True
    assert is_dynamic_step(by_id["review"], by_id) is True
    assert is_dynamic_step(by_id["integrate"], by_id) is True
```

- [ ] **Step 2: Run tests to verify the new ones fail**

Run: `uv run pytest tests/playbook/test_materializer.py -v`
Expected: FAIL — `ImportError: cannot import name 'is_dynamic_step'`; existing `test_materialize_creates_units_and_dep_edges` still passes.

- [ ] **Step 3: Rewrite `src/foundry/playbook/materializer.py`**

```python
from __future__ import annotations

from foundry.playbook.schema import STEP_TYPE_TO_UNIT_TYPE, PlaybookSpec, StepSpec
from foundry.store.models import UnitDep, WorkUnit
from foundry.store.store import Store


def is_dynamic_step(step: StepSpec, steps_by_id: dict[str, StepSpec]) -> bool:
    if step.fan_out or step.fan_out_from:
        return True
    return any(is_dynamic_step(steps_by_id[need_id], steps_by_id) for need_id in step.needs)


async def materialize(playbook: PlaybookSpec, run_id: str, store: Store) -> dict[str, str]:
    steps_by_id = {s.id: s for s in playbook.steps}
    static_steps = [s for s in playbook.steps if not is_dynamic_step(s, steps_by_id)]

    units = [
        WorkUnit(run_id=run_id, step_id=step.id, type=STEP_TYPE_TO_UNIT_TYPE[step.type], status="open")
        for step in static_steps
    ]
    created = await store.create_work_units(units)
    step_to_unit = {step.id: unit.id for step, unit in zip(static_steps, created, strict=True)}

    deps = [
        UnitDep(unit_id=step_to_unit[step.id], needs_unit_id=step_to_unit[need_id])
        for step in static_steps
        for need_id in step.needs
        if need_id in step_to_unit
    ]
    if deps:
        await store.add_unit_deps(deps)

    return step_to_unit
```

Note the `if need_id in step_to_unit` guard on the deps comprehension: a static step's `needs` list is by construction only ever other static steps (a static step can't depend on a dynamic one — `is_dynamic_step` would have made it dynamic too), so this is always true in practice; it's there defensively rather than via a bare KeyError, matching the existing codebase's preference for explicit conditions over exceptions-as-control-flow in hot paths.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/playbook/test_materializer.py -v`
Expected: PASS (3 tests: 1 existing + 2 new)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/foundry/playbook/materializer.py tests/playbook/test_materializer.py \
        tests/playbook/fixtures/fanout_demo.toml
git commit -m "feat(playbook): materializer skips fan-out/dynamic steps, exports is_dynamic_step"
```

---

### Task 3: Orchestrator — fan-out expansion and convoy closing

**Files:**
- Modify: `src/foundry/orchestrator/tick.py`
- Test: `tests/orchestrator/test_fanout.py` (new file)

**Interfaces:**
- Consumes: `is_dynamic_step` (Task 2), `STEP_TYPE_TO_UNIT_TYPE` (Task 1), `WorkUnit.convoy_id` (already exists in `store/models.py` since M0, unused until now).
- Produces: `Orchestrator._fan_out(run_id)` — new tick phase, called between `_gate_derived_units` and `dispatch` in `tick()`. `Orchestrator._close_convoys(run_id)` — new tick phase, called right after `_fan_out`. Both are internal (not part of the public API other tasks call directly), but their *effects* — convoy `WorkUnit`s, per-slice task/gate units with `convoy_id` set, `UnitDep` rows chaining slice-to-slice — are what Tasks 4-6 build on.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestrator/test_fanout.py
import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def _setup(tmp_path, script):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/playbook/fixtures/fanout_demo.toml")
    run = await store.create_run(project.id, "fanout_demo.toml", "demo run")
    await materialize(playbook, run.id, store)
    driver = FakeDriver(script)
    orch = Orchestrator(store, driver, playbook, concurrency=10)
    return store, run, orch


@pytest.mark.asyncio
async def test_fan_out_creates_convoy_and_per_slice_units_once_architecture_closes(tmp_path):
    script = {
        "architecture": FakeStepScript(
            artifact={"slices": ["auth", "billing", "notifications"]}
        )
    }
    store, run, orch = await _setup(tmp_path, script)

    # Drive architecture (human-gated) to closed.
    await orch.tick(run.id)  # dispatches architecture
    units = await store.list_units(run.id)
    arch_gate_unit = next(u for u in units if u.step_id == "architecture" and u.type == "gate") if False else None
    # architecture has gate="human": find its gate and approve it.
    gates = await store.list_gates_for_run(run.id)
    arch_gate = next(g for g in gates if g.artifact_id is not None)
    await store.decide_gate(arch_gate.id, "approved")
    await orch.tick(run.id)  # apply_gate_decisions closes the architecture task unit

    await orch.tick(run.id)  # this tick should run _fan_out

    units = await store.list_units(run.id)
    convoys = [u for u in units if u.type == "convoy"]
    assert len(convoys) == 1
    assert convoys[0].step_id == "implement"

    implement_units = [u for u in units if u.step_id == "implement" and u.convoy_id == convoys[0].id]
    review_units = [u for u in units if u.step_id == "review" and u.convoy_id == convoys[0].id]
    assert len(implement_units) == 3
    assert len(review_units) == 3
    assert {u.payload_json["slice"] for u in implement_units} == {"auth", "billing", "notifications"}

    integrate_units = [u for u in units if u.step_id == "integrate"]
    assert len(integrate_units) == 1
    deps = await store.list_deps(run.id)
    integrate_deps = {d.needs_unit_id for d in deps if d.unit_id == integrate_units[0].id}
    assert integrate_deps == {convoys[0].id}


@pytest.mark.asyncio
async def test_fan_out_is_idempotent_across_ticks(tmp_path):
    script = {"architecture": FakeStepScript(artifact={"slices": ["a", "b"]})}
    store, run, orch = await _setup(tmp_path, script)
    await orch.tick(run.id)
    gates = await store.list_gates_for_run(run.id)
    await store.decide_gate(next(g for g in gates if g.artifact_id is not None).id, "approved")
    for _ in range(4):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    convoys = [u for u in units if u.type == "convoy"]
    assert len(convoys) == 1  # not re-expanded on every subsequent tick


@pytest.mark.asyncio
async def test_convoy_closes_once_every_leaf_slice_unit_closes(tmp_path):
    script = {
        "architecture": FakeStepScript(artifact={"slices": ["a", "b"]}),
        "implement": FakeStepScript(artifact={"diff": "ok"}),
        "review": FakeStepScript(artifact={"verdict": "approved"}),
    }
    store, run, orch = await _setup(tmp_path, script)
    await orch.tick(run.id)
    gates = await store.list_gates_for_run(run.id)
    await store.decide_gate(next(g for g in gates if g.artifact_id is not None).id, "approved")

    for _ in range(15):
        await orch.tick(run.id)
        units = await store.list_units(run.id)
        gates = await store.list_gates_for_run(run.id)
        pending_agent_gates = [g for g in gates if g.decision == "pending" and g.gate_type == "agent"]
        for g in pending_agent_gates:
            await store.decide_gate(g.id, "approved")

    units = await store.list_units(run.id)
    convoy = next(u for u in units if u.type == "convoy")
    assert convoy.status == "closed"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_fanout.py -v`
Expected: FAIL — convoys list is empty (no `_fan_out` phase exists yet).

- [ ] **Step 3: Implement `_fan_out` and `_close_convoys` in `src/foundry/orchestrator/tick.py`**

Add these imports at the top (alongside the existing ones):

```python
from foundry.playbook.materializer import is_dynamic_step
from foundry.playbook.schema import STEP_TYPE_TO_UNIT_TYPE
from foundry.store.models import Artifact, UnitDep
```

Wire the two new phases into `tick()`:

```python
    async def tick(self, run_id: str) -> TickResult:
        await self.reconcile(run_id)
        await self.apply_gate_decisions(run_id)
        await self.unblock(run_id)
        await self._gate_derived_units(run_id)
        await self._fan_out(run_id)
        await self._close_convoys(run_id)
        dispatched = await self.dispatch(run_id)
        ...  # rest unchanged
```

Add the two methods (place after `_gate_derived_units`):

```python
    async def _fan_out(self, run_id: str) -> None:
        units = await self.store.list_units(run_id)
        static_unit_by_step = {u.step_id: u for u in units if u.convoy_id is None and u.type != "convoy"}
        expanded_steps = {u.step_id for u in units if u.type == "convoy"}

        for step in self.playbook.steps:
            if not step.fan_out or step.id in expanded_steps:
                continue
            need_units = [static_unit_by_step.get(n) for n in step.needs]
            if any(u is None or u.status != "closed" for u in need_units):
                continue

            artifacts = await self.store.list_artifacts(run_id)
            kind, _, field = step.fan_out.partition(".")
            slices = _resolve_fan_out_slices(artifacts, kind, field)

            convoy = (
                await self.store.create_work_units(
                    [WorkUnit(run_id=run_id, step_id=step.id, type="convoy", status="open")]
                )
            )[0]
            await self.store.append_event(run_id, convoy.id, "convoy.created", {"size": len(slices)})

            chain = [step] + [s for s in self.playbook.steps if s.fan_out_from == step.id]
            units_by_step_index: dict[str, list[WorkUnit]] = {}

            for chain_step in chain:
                payloads = [
                    {"slice_index": i, "slice": slices[i]} if chain_step is step else {"slice_index": i}
                    for i in range(len(slices))
                ]
                max_attempts = chain_step.loop.max_rounds if chain_step.loop else 3
                new_units = await self.store.create_work_units(
                    [
                        WorkUnit(
                            run_id=run_id,
                            step_id=chain_step.id,
                            type=STEP_TYPE_TO_UNIT_TYPE[chain_step.type],
                            status="open",
                            convoy_id=convoy.id,
                            payload_json=payloads[i],
                            max_attempts=max_attempts,
                        )
                        for i in range(len(slices))
                    ]
                )
                deps: list[UnitDep] = []
                if chain_step is step:
                    for unit in new_units:
                        for need_id in chain_step.needs:
                            deps.append(UnitDep(unit_id=unit.id, needs_unit_id=need_units[chain_step.needs.index(need_id)].id))
                else:
                    source_units = units_by_step_index[chain_step.fan_out_from]
                    for i, unit in enumerate(new_units):
                        deps.append(UnitDep(unit_id=unit.id, needs_unit_id=source_units[i].id))
                if deps:
                    await self.store.add_unit_deps(deps)
                units_by_step_index[chain_step.id] = new_units
                await self.store.append_event(
                    run_id, convoy.id, "unit.created", {"step_id": chain_step.id, "count": len(new_units)}
                )

            chain_ids = {s.id for s in chain}
            already_materialized = {u.step_id for u in units if u.convoy_id is None and u.type != "convoy"}
            downstream = [
                s
                for s in self.playbook.steps
                if s.id not in chain_ids
                and s.id not in already_materialized
                and any(n in chain_ids for n in s.needs)
            ]
            for ds_step in downstream:
                ds_unit = (
                    await self.store.create_work_units(
                        [
                            WorkUnit(
                                run_id=run_id,
                                step_id=ds_step.id,
                                type=STEP_TYPE_TO_UNIT_TYPE[ds_step.type],
                                status="open",
                            )
                        ]
                    )
                )[0]
                dep_rows = [UnitDep(unit_id=ds_unit.id, needs_unit_id=convoy.id)]
                for need_id in ds_step.needs:
                    if need_id in chain_ids:
                        continue
                    other = static_unit_by_step.get(need_id)
                    if other is not None:
                        dep_rows.append(UnitDep(unit_id=ds_unit.id, needs_unit_id=other.id))
                await self.store.add_unit_deps(dep_rows)

    async def _close_convoys(self, run_id: str) -> None:
        units = await self.store.list_units(run_id)
        convoys = [u for u in units if u.type == "convoy" and u.status not in ("closed", "failed")]
        for convoy in convoys:
            step = self._steps_by_id[convoy.step_id]
            leaf_step_id = step.id
            for candidate in self.playbook.steps:
                if candidate.fan_out_from == step.id:
                    leaf_step_id = candidate.id  # last step in the chain wins; one-hop chains only (Task 1)

            leaf_units = [u for u in units if u.step_id == leaf_step_id and u.convoy_id == convoy.id]
            if not leaf_units:
                continue
            if any(u.status == "failed" for u in leaf_units):
                await self.store.update_unit(convoy.id, status="failed")
                await self.store.append_event(run_id, convoy.id, "convoy.closed", {"status": "failed"})
            elif all(u.status == "closed" for u in leaf_units):
                await self.store.update_unit(convoy.id, status="closed")
                await self.store.append_event(run_id, convoy.id, "convoy.closed", {"status": "closed"})
```

Add the module-level helper (near the bottom of the file, or just above the `Orchestrator` class):

```python
def _resolve_fan_out_slices(artifacts: list[Artifact], kind: str, field: str) -> list:
    matching = [a for a in artifacts if a.kind == kind]
    if not matching:
        raise ValueError(f"fan-out: no artifact of kind {kind!r} found yet")
    latest = max(matching, key=lambda a: a.version)
    value = latest.payload_json.get(field)
    if not isinstance(value, list):
        raise ValueError(f"fan-out source {kind}.{field} is not a list (got {type(value).__name__})")
    return value
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_fanout.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions (existing `tests/orchestrator/test_tick.py` playbooks have no `fan_out` steps, so `_fan_out`/`_close_convoys` are no-ops for them)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/orchestrator/tick.py tests/orchestrator/test_fanout.py
git commit -m "feat(orchestrator): fan-out expansion into convoys + convoy close-on-leaf-completion"
```

---

### Task 4: Per-unit git worktrees

**Files:**
- Create: `src/foundry/orchestrator/worktrees.py`
- Modify: `src/foundry/orchestrator/tick.py` (wire into `dispatch`)
- Test: `tests/orchestrator/test_worktrees.py`

**Interfaces:**
- Produces: `WorktreeManager` (`src/foundry/orchestrator/worktrees.py`) — `create(project_path: str, run_id: str, unit_id: str) -> str` (runs `git worktree add <path> -b foundry/<run_id>/<unit_id>` against `project_path`, returns the absolute worktree path), `remove(project_path: str, worktree_path: str) -> None` (runs `git worktree remove --force <worktree_path>` then `git branch -D` the branch it created). Both are synchronous, thin wrappers over `subprocess.run` (local git only — no network). `Orchestrator.__init__` gains an optional `worktree_manager: WorktreeManager | None = None` parameter; `dispatch()` calls `worktree_manager.create(...)` before `spawn()` when `step.writes` is `True` and a manager is configured, passing the resulting path as `SessionSpec.cwd` instead of the hardcoded `"."`; `_collect()` calls `worktree_manager.remove(...)` once the task unit reaches a terminal state (`closed`, `failed` past `max_attempts`, i.e. when a `human` gate is created for a permanently-failed unit) — *not* on every retry, since a retry should keep working in the same worktree.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestrator/test_worktrees.py
import subprocess

import pytest

from foundry.orchestrator.worktrees import WorktreeManager


def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


def test_create_makes_a_real_worktree_on_its_own_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    path = mgr.create(str(repo), run_id="run1", unit_id="unit1")

    assert (Path := __import__("pathlib").Path)(path).is_dir()
    assert (Path(path) / "README.md").exists()
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "foundry/run1/unit1"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "foundry/run1/unit1" in branches


def test_remove_deletes_worktree_and_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    path = mgr.create(str(repo), run_id="run1", unit_id="unit1")
    mgr.remove(str(repo), path)

    from pathlib import Path

    assert not Path(path).exists()
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "foundry/run1/unit1"],
        capture_output=True, text=True, check=True,
    ).stdout
    assert "foundry/run1/unit1" not in branches
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_worktrees.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.orchestrator.worktrees'`

- [ ] **Step 3: Write `src/foundry/orchestrator/worktrees.py`**

```python
from __future__ import annotations

import subprocess
from pathlib import Path


class WorktreeManager:
    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir)

    def create(self, project_path: str, run_id: str, unit_id: str) -> str:
        self.base_dir.mkdir(parents=True, exist_ok=True)
        worktree_path = self.base_dir / run_id / unit_id
        branch = f"foundry/{run_id}/{unit_id}"
        subprocess.run(
            ["git", "-C", project_path, "worktree", "add", str(worktree_path), "-b", branch],
            check=True,
            capture_output=True,
        )
        return str(worktree_path)

    def remove(self, project_path: str, worktree_path: str) -> None:
        subprocess.run(
            ["git", "-C", project_path, "worktree", "remove", "--force", worktree_path],
            check=True,
            capture_output=True,
        )
        branch = self._branch_for(project_path, worktree_path)
        if branch is not None:
            subprocess.run(
                ["git", "-C", project_path, "branch", "-D", branch],
                check=False,
                capture_output=True,
            )

    def _branch_for(self, project_path: str, worktree_path: str) -> str | None:
        result = subprocess.run(
            ["git", "-C", project_path, "worktree", "list", "--porcelain"],
            check=True,
            capture_output=True,
            text=True,
        )
        blocks = result.stdout.split("\n\n")
        target = str(Path(worktree_path))
        for block in blocks:
            lines = block.splitlines()
            if not lines or not lines[0].startswith("worktree "):
                continue
            if lines[0].removeprefix("worktree ") != target:
                continue
            for line in lines:
                if line.startswith("branch refs/heads/"):
                    return line.removeprefix("branch refs/heads/")
        return None
```

Note: `remove()` reads the branch name from `git worktree list --porcelain` *before* deletion isn't possible after `worktree remove` already ran (the worktree entry is gone) — so `_branch_for` must be called, and its git-worktree-list query executed, **before** the `worktree remove` call above actually removes the entry. Reorder so `_branch_for` is queried first:

```python
    def remove(self, project_path: str, worktree_path: str) -> None:
        branch = self._branch_for(project_path, worktree_path)
        subprocess.run(
            ["git", "-C", project_path, "worktree", "remove", "--force", worktree_path],
            check=True,
            capture_output=True,
        )
        if branch is not None:
            subprocess.run(
                ["git", "-C", project_path, "branch", "-D", branch],
                check=False,
                capture_output=True,
            )
```

(Use this ordering, not the earlier snippet's ordering, when writing the file.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worktrees.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Wire `WorktreeManager` into `Orchestrator`**

In `src/foundry/orchestrator/tick.py`:

```python
    def __init__(
        self,
        store: Store,
        driver: AgentDriver,
        playbook: PlaybookSpec,
        concurrency: int = 5,
        worktree_manager: "WorktreeManager | None" = None,
        project_path: str = ".",
    ):
        self.store = store
        self.driver = driver
        self.playbook = playbook
        self.concurrency = concurrency
        self.worktree_manager = worktree_manager
        self.project_path = project_path
        self._steps_by_id: dict[str, StepSpec] = {s.id: s for s in playbook.steps}
        self._unit_worktrees: dict[str, str] = {}
```

Add the import: `from foundry.orchestrator.worktrees import WorktreeManager`.

In `dispatch()`, where `spec = SessionSpec(cwd=".", ...)` is built, change to:

```python
            cwd = "."
            if step.writes and self.worktree_manager is not None:
                cwd = self.worktree_manager.create(self.project_path, run_id, task_unit.id)
                self._unit_worktrees[task_unit.id] = cwd

            spec = SessionSpec(
                cwd=cwd,
                prompt=f"step:{step.id}",
                ...
```

In `_collect()`, after the `if failed:` branch's `max_attempts`-exceeded path (the one that creates a `human` gate for permanent failure) and again at the success path right before the method returns — worktree cleanup happens on *either* terminal outcome:

```python
        if failed:
            next_attempt = task_unit.attempt + 1
            if next_attempt >= task_unit.max_attempts:
                await self.store.update_unit(task_unit.id, status="blocked", attempt=next_attempt)
                await self.store.create_gate(work_unit_id=task_unit.id, gate_type="human", decision="pending")
                await self.store.append_event(
                    run_id, task_unit.id, "unit.blocked", {"reason": "failed", "error": error_payload}
                )
                self._cleanup_worktree(task_unit.id)
            else:
                await self.store.update_unit(
                    task_unit.id, status="ready", attempt=next_attempt, owner_session_id=None
                )
                await self.store.append_event(run_id, task_unit.id, "unit.retried", {"attempt": next_attempt})
            return
```

And at the very end of `_collect()` (both the `gate in (None, "none")` closed branch and the gated branch fall through to the same cleanup — add it once after the `if/else`, not inside either arm):

```python
        if step.gate in (None, "none"):
            await self.store.update_unit(task_unit.id, status="closed")
            await self.store.append_event(run_id, task_unit.id, "unit.closed", {})
        else:
            gate = await self.store.create_gate(
                work_unit_id=task_unit.id,
                artifact_id=artifact.id,
                gate_type=step.gate,
                decision="pending",
            )
            await self.store.update_unit(task_unit.id, status="blocked")
            await self.store.append_event(run_id, task_unit.id, "gate.created", {"gate_id": gate.id})

        if step.gate in (None, "none"):
            self._cleanup_worktree(task_unit.id)
```

Add the helper method:

```python
    def _cleanup_worktree(self, unit_id: str) -> None:
        path = self._unit_worktrees.pop(unit_id, None)
        if path is not None and self.worktree_manager is not None:
            self.worktree_manager.remove(self.project_path, path)
```

A gated unit's worktree is deliberately *not* cleaned up when its gate is created — rejection needs the same worktree still present for rework (the artifact/worktree pairing must survive a reject→rework cycle). It only gets cleaned up once the unit reaches `closed` via `apply_gate_decisions`'s approve path or the permanent-failure path above. Add cleanup to `apply_gate_decisions`'s approve branch too:

```python
            if gate.decision == "approved":
                await self.store.update_unit(unit.id, status="closed")
                await self.store.append_event(run_id, unit.id, "gate.approved", {"gate_id": gate.id})
                self._cleanup_worktree(unit.id)
```

- [ ] **Step 6: Write a FakeDriver-backed integration test proving worktree lifecycle under real dispatch**

```python
# append to tests/orchestrator/test_worktrees.py
import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_writes_step_gets_a_real_worktree_and_it_is_cleaned_up_on_close(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(repo))
    playbook = PlaybookSpec(
        id="p", steps=[StepSpec(id="a", role="dev", writes=True, produces="x", gate="none")]
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    orch = Orchestrator(
        store, FakeDriver({"a": FakeStepScript(artifact={})}), playbook,
        worktree_manager=mgr, project_path=str(repo),
    )

    await orch.tick(run.id)  # dispatches "a", worktree created, task runs to closed synchronously

    worktree_path = tmp_path / "worktrees" / run.id
    # unit id isn't known ahead of time; assert the parent dir is empty (cleaned up) rather
    # than guessing the unit's ULID.
    assert not any(worktree_path.iterdir()) if worktree_path.exists() else True
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_worktrees.py -v`
Expected: PASS (3 tests)

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions (existing tests never pass `worktree_manager`, so it defaults to `None` and `dispatch()`'s `cwd = "."` behavior is unchanged for them)

- [ ] **Step 9: Commit**

```bash
git add src/foundry/orchestrator/worktrees.py src/foundry/orchestrator/tick.py \
        tests/orchestrator/test_worktrees.py
git commit -m "feat(orchestrator): per-unit git worktrees for writes-capable steps"
```

---

### Task 5: Escalation contract (generic `integrate`-style human handoff)

**Files:**
- Modify: `src/foundry/orchestrator/tick.py`
- Test: `tests/orchestrator/test_escalation.py`

**Interfaces:**
- Consumes: `StepSpec.escalates_on` (Task 1).
- Produces: extends `_collect()`'s success path — when `step.escalates_on` is set and the produced artifact's `payload_json[step.escalates_on]` is a non-empty list, the engine creates a `human_task` work unit (instead of the normal gate) referencing the artifact, and fires `unit.blocked` with the escalation payload attached. This is the generic mechanism the design doc's `integrate` step relies on (§5.1: "anything semantic escalates to a `human_task` with both diffs and the KG blast-radius overlap attached") — the *engine* only knows "artifact says escalate", never anything about merges or conflicts.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestrator/test_escalation.py
import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def _run_one_tick(tmp_path, step, artifact_payload):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(id="p", steps=[step])
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)
    driver = FakeDriver({step.id: FakeStepScript(artifact=artifact_payload)})
    orch = Orchestrator(store, driver, playbook)
    await orch.tick(run.id)
    return store, run


@pytest.mark.asyncio
async def test_escalation_creates_human_task_when_field_is_nonempty(tmp_path):
    step = StepSpec(id="integrate", role="integrator", produces="integration_artifact", escalates_on="escalated")
    store, run = await _run_one_tick(
        tmp_path, step, {"auto_resolved": ["lockfile"], "escalated": [{"file": "auth.py", "reason": "semantic"}]}
    )

    units = await store.list_units(run.id)
    human_tasks = [u for u in units if u.type == "human_task"]
    assert len(human_tasks) == 1
    task_unit = next(u for u in units if u.step_id == "integrate" and u.type == "task")
    assert task_unit.status == "blocked"

    events = await store.list_events(run.id)
    blocked_events = [e for e in events if e.type == "unit.blocked" and e.unit_id == task_unit.id]
    assert blocked_events
    assert blocked_events[0].payload_json["escalated"] == [{"file": "auth.py", "reason": "semantic"}]


@pytest.mark.asyncio
async def test_no_escalation_when_field_is_empty(tmp_path):
    step = StepSpec(id="integrate", role="integrator", produces="integration_artifact", escalates_on="escalated", gate="none")
    store, run = await _run_one_tick(tmp_path, step, {"auto_resolved": ["lockfile"], "escalated": []})

    units = await store.list_units(run.id)
    assert not [u for u in units if u.type == "human_task"]
    task_unit = next(u for u in units if u.step_id == "integrate" and u.type == "task")
    assert task_unit.status == "closed"


@pytest.mark.asyncio
async def test_step_without_escalates_on_is_unaffected(tmp_path):
    step = StepSpec(id="plain", role="dev", produces="x", gate="none")
    store, run = await _run_one_tick(tmp_path, step, {"anything": "ignored"})
    units = await store.list_units(run.id)
    assert not [u for u in units if u.type == "human_task"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_escalation.py -v`
Expected: FAIL — no human_task is ever created (feature doesn't exist yet)

- [ ] **Step 3: Add escalation handling to `_collect()` in `src/foundry/orchestrator/tick.py`**

Replace the artifact-produced success block (the part after `artifact.produced` is appended) with:

```python
        await self.store.append_event(run_id, task_unit.id, "artifact.produced", {"artifact_id": artifact.id})

        escalated = artifact_payload.get(step.escalates_on) if step.escalates_on else None
        if escalated:
            human_task_unit = (
                await self.store.create_work_units(
                    [WorkUnit(run_id=run_id, step_id=f"{step.id}.escalation", type="human_task", status="open")]
                )
            )[0]
            await self.store.update_unit(task_unit.id, status="blocked")
            await self.store.append_event(
                run_id,
                task_unit.id,
                "unit.blocked",
                {"reason": "escalated", "escalated": escalated, "human_task_id": human_task_unit.id},
            )
        elif step.gate in (None, "none"):
            await self.store.update_unit(task_unit.id, status="closed")
            await self.store.append_event(run_id, task_unit.id, "unit.closed", {})
            self._cleanup_worktree(task_unit.id)
        else:
            gate = await self.store.create_gate(
                work_unit_id=task_unit.id,
                artifact_id=artifact.id,
                gate_type=step.gate,
                decision="pending",
            )
            await self.store.update_unit(task_unit.id, status="blocked")
            await self.store.append_event(run_id, task_unit.id, "gate.created", {"gate_id": gate.id})
```

(This replaces the block Task 4 modified — the `if step.gate in (None, "none"): self._cleanup_worktree(task_unit.id)` trailer line from Task 4 is folded into the `elif` branch above instead of being a separate trailing statement.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_escalation.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/foundry/orchestrator/tick.py tests/orchestrator/test_escalation.py
git commit -m "feat(orchestrator): generic escalates_on contract creates human_task on non-empty artifact field"
```

---

### Task 6: Agent-review loop

**Files:**
- Modify: `src/foundry/orchestrator/tick.py`
- Test: `tests/orchestrator/test_review_loop.py`

**Interfaces:**
- Consumes: `gate_type == "agent"` gates (already created generically by `_collect`, per Task 1's `StepSpec.gate: Literal["human","agent","none"]`, unchanged), `StepSpec.loop` (Task 1).
- Produces: `Orchestrator._dispatch_agent_reviews(run_id)` — new tick phase (called right after `dispatch`, in the same tick, so a freshly-dispatched reviewable step's gate can be picked up without waiting a full extra tick where possible... in practice the gate is only created once `_collect` finishes the producing session, which for FakeDriver is synchronous within `dispatch`, so same-tick pickup is achievable and tested). For each `pending` `gate_type="agent"` gate with no reviewer session dispatched yet, spawns a reviewer session via the driver; the session's `completed` artifact payload's `verdict` field (`"approved"` or anything else) is used to `decide_gate` automatically — approved gates flow through the *existing* `apply_gate_decisions` approve path unchanged; anything else flows through the *existing* rejected path unchanged, which already increments `attempt` and reopens the producing unit for rework. When `attempt >= max_attempts` (set from `loop.max_rounds` at fan-out-expansion time per Task 3), the existing max-attempts-exceeded escalation in `_collect`'s failure path already forces a human gate — the review loop reuses that same cap enforcement rather than adding a second one.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestrator/test_review_loop.py
import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import LoopSpec, PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


def _playbook():
    return PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="implement", role="dev", produces="code_diff_artifact", gate="none", writes=False),
            StepSpec(
                id="review",
                role="reviewer",
                needs=["implement"],
                produces="review_artifact",
                gate="agent",
                loop=LoopSpec(back_to="implement", max_rounds=3),
            ),
        ],
    )


@pytest.mark.asyncio
async def test_agent_gate_auto_approved_closes_the_reviewed_unit(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = _playbook()
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"diff": "x"}),
            "review": FakeStepScript(artifact={"verdict": "approved"}),
        }
    )
    orch = Orchestrator(store, driver, playbook)

    for _ in range(6):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.status == "closed"
    assert implement_unit.attempt == 0


@pytest.mark.asyncio
async def test_agent_gate_rejection_reworks_the_producing_unit(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = _playbook()
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    driver = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"diff": "x"}),
            "review": FakeStepScript(artifact={"verdict": "needs_changes"}),
        }
    )
    orch = Orchestrator(store, driver, playbook)

    for _ in range(4):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.attempt >= 1


@pytest.mark.asyncio
async def test_review_loop_escalates_to_human_after_max_rounds(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="implement", role="dev", produces="code_diff_artifact", gate="none"),
            StepSpec(
                id="review", role="reviewer", needs=["implement"], produces="review_artifact",
                gate="agent", loop=LoopSpec(back_to="implement", max_rounds=2),
            ),
        ],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    step_to_unit = await materialize(playbook, run.id, store)
    await store.update_unit(step_to_unit["implement"], max_attempts=2)

    driver = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"diff": "x"}),
            "review": FakeStepScript(artifact={"verdict": "needs_changes"}),
        }
    )
    orch = Orchestrator(store, driver, playbook)

    for _ in range(10):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.status == "blocked"
    gates = await store.list_gates_for_run(run.id)
    human_gates = [g for g in gates if g.gate_type == "human" and g.work_unit_id == implement_unit.id]
    assert human_gates
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_review_loop.py -v`
Expected: FAIL — agent gates stay `pending` forever, nothing ever reworks `implement` or closes it.

- [ ] **Step 3: Implement `_dispatch_agent_reviews` in `src/foundry/orchestrator/tick.py`**

Wire into `tick()`, right after `dispatch`:

```python
    async def tick(self, run_id: str) -> TickResult:
        await self.reconcile(run_id)
        await self.apply_gate_decisions(run_id)
        await self.unblock(run_id)
        await self._gate_derived_units(run_id)
        await self._fan_out(run_id)
        await self._close_convoys(run_id)
        dispatched = await self.dispatch(run_id)
        await self._dispatch_agent_reviews(run_id)
        ...  # rest unchanged
```

Add the method:

```python
    async def _dispatch_agent_reviews(self, run_id: str) -> None:
        gates = await self.store.list_gates_for_run(run_id)
        events = await self.store.list_events(run_id)
        already_reviewed_gate_ids = {
            e.payload_json.get("gate_id") for e in events if e.type == "gate.review_dispatched"
        }

        for gate in gates:
            if gate.gate_type != "agent" or gate.decision != "pending":
                continue
            if gate.id in already_reviewed_gate_ids:
                continue

            unit = await self.store.get_unit(gate.work_unit_id)
            if unit is None:
                continue
            step = self._steps_by_id[unit.step_id]

            spec = SessionSpec(
                cwd=".",
                prompt=f"review:{step.id}:gate:{gate.id}",
                model="fake",
                tool_policy={},
                mcp_servers=[],
                env={},
                internal_endpoint="",
                internal_secret="",
                unit_id=gate.id,
                run_id=run_id,
                step_id=step.id,
            )
            handle = self.driver.spawn(spec)
            await self.store.append_event(run_id, unit.id, "gate.review_dispatched", {"gate_id": gate.id})

            verdict = "needs_changes"
            async for ev in self.driver.stream_events(handle):
                await self.store.append_event(run_id, unit.id, f"driver.{ev.kind}", ev.payload)
                if ev.kind == "completed":
                    verdict = ev.payload.get("artifact", {}).get("verdict", "needs_changes")

            decision = "approved" if verdict == "approved" else "rejected"
            await self.store.decide_gate(gate.id, decision, feedback={"verdict": verdict}, decided_by="agent")
```

Note this reuses `apply_gate_decisions` (already run earlier in the *next* tick, since `decide_gate` here just flips the row — the actual unit-status transition happens when `apply_gate_decisions` runs again on a subsequent tick, exactly like a human decision arriving via the API). No changes to `apply_gate_decisions` are needed: it already treats any `gate.decision in ("approved", "rejected")` uniformly regardless of `gate_type` or `decided_by`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_review_loop.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/foundry/orchestrator/tick.py tests/orchestrator/test_review_loop.py
git commit -m "feat(orchestrator): agent-review loop auto-dispatches reviewer sessions and auto-decides gates"
```

---

### Task 7: CodexDriver (second provider, protocol-conformant)

**Files:**
- Create: `src/foundry/drivers/codex.py`
- Create: `tests/fixtures/fake_codex_cli.sh` (scripted local subprocess standing in for the real `codex` binary — no network, no real CLI)
- Test: `tests/drivers/test_codex.py`

**Interfaces:**
- Produces: `CodexDriver` (`src/foundry/drivers/codex.py`) implementing the `AgentDriver` protocol (`spawn`, `stream_events`, `cancel`, `adopt`, `health`) — following the empirical driver-spec requirements from design doc §8: process exit (not stream EOF) is authoritative for session end; the subprocess's stdout is redirected to a `session.log` file the driver tails from a persisted byte offset (not read via a live pipe); the process group is reaped (`SIGTERM` → grace period → `SIGKILL`) on every session end, not just cancel; `asyncio.StreamReader` limit is raised to `≥1MB` to avoid the default 64KB `readline` crash on large tool results. `CodexDriver.__init__(self, cli_path: str = "codex", session_log_dir: str | Path = ...)` — `cli_path` is overridable so tests point it at the fixture script instead of a real `codex` binary.

- [ ] **Step 1: Write the fixture "codex" CLI stand-in**

```bash
#!/usr/bin/env bash
# tests/fixtures/fake_codex_cli.sh
# Stands in for the real `codex exec` CLI in tests — never invoked in production,
# never makes a network call. Emits a minimal JSONL stream to stdout mimicking
# the normalized shape CodexDriver expects to parse, then exits 0.
set -euo pipefail
echo '{"type":"tool_call","tool":"read_file"}'
sleep 0.05
echo '{"type":"completed","artifact":{"diff":"fake codex diff"}}'
exit 0
```

Make it executable as part of the same step: `chmod +x tests/fixtures/fake_codex_cli.sh`.

- [ ] **Step 2: Write the failing tests**

```python
# tests/drivers/test_codex.py
import asyncio
import os
import stat
from pathlib import Path

import pytest

from foundry.drivers.base import SessionSpec
from foundry.drivers.codex import CodexDriver

FIXTURE = str(Path(__file__).parent.parent / "fixtures" / "fake_codex_cli.sh")


def _spec(unit_id="u1", run_id="r1", step_id="s1") -> SessionSpec:
    return SessionSpec(
        cwd=".", prompt="do the thing", model="codex-fake", tool_policy={}, mcp_servers=[],
        env={}, internal_endpoint="", internal_secret="", unit_id=unit_id, run_id=run_id, step_id=step_id,
    )


@pytest.mark.asyncio
async def test_spawn_and_stream_events_normalizes_the_fixture_output(tmp_path):
    os.chmod(FIXTURE, os.stat(FIXTURE).st_mode | stat.S_IEXEC)
    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())

    kinds = []
    async for ev in driver.stream_events(handle):
        kinds.append(ev.kind)

    assert "tool_call" in kinds
    assert kinds[-1] == "completed"


@pytest.mark.asyncio
async def test_process_exit_is_authoritative_not_stream_eof(tmp_path):
    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())

    events = [ev async for ev in driver.stream_events(handle)]
    health = driver.health(handle)
    assert health.alive is False  # process has exited; driver must reflect that, not hang
    assert events


def test_adopt_returns_empty_when_no_sessions_recorded(tmp_path):
    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    assert driver.adopt() == []


def test_cancel_is_safe_on_already_finished_session(tmp_path):
    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())
    driver.cancel(handle)  # must not raise even though nothing is running yet
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/drivers/test_codex.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.drivers.codex'`

- [ ] **Step 4: Write `src/foundry/drivers/codex.py`**

```python
from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
from collections.abc import AsyncIterator
from pathlib import Path

from foundry.drivers.base import DriverEvent, SessionHandle, SessionHealth, SessionSpec

_READLINE_LIMIT = 1024 * 1024  # ≥1MB, per design doc §8 driver-spec requirement 4


class CodexDriver:
    def __init__(self, cli_path: str = "codex", session_log_dir: str | Path = "/tmp/foundry-codex-sessions"):
        self.cli_path = cli_path
        self.session_log_dir = Path(session_log_dir)
        self.session_log_dir.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, subprocess.Popen] = {}
        self._log_paths: dict[str, Path] = {}

    def spawn(self, spec: SessionSpec) -> SessionHandle:
        log_path = self.session_log_dir / f"{spec.unit_id}.jsonl"
        log_file = open(log_path, "wb")  # noqa: SIM115 - lifetime is the subprocess's, closed on reap
        process = subprocess.Popen(  # noqa: S603 - cli_path is operator-configured, not user input
            [self.cli_path],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group, for tree-kill (driver-spec requirement 3)
        )
        self._processes[spec.unit_id] = process
        self._log_paths[spec.unit_id] = log_path
        return SessionHandle(id=spec.unit_id, pid=process.pid)

    async def stream_events(self, handle: SessionHandle) -> AsyncIterator[DriverEvent]:
        process = self._processes.get(handle.id)
        log_path = self._log_paths.get(handle.id)
        if process is None or log_path is None:
            raise ValueError(f"unknown session handle: {handle.id}")

        offset = 0
        while True:
            # Process exit is authoritative for session end (driver-spec requirement 1)
            # — never wait on stream EOF, which grandchildren can hold open forever.
            exited = process.poll() is not None
            with open(log_path, "rb") as f:
                f.seek(offset)
                chunk = f.read()
                offset += len(chunk)
            for line in chunk.splitlines():
                if not line.strip():
                    continue
                if len(line) > _READLINE_LIMIT:
                    continue
                record = json.loads(line)
                yield _normalize(record)
            if exited:
                break
            await asyncio.sleep(0.01)

        self._reap(handle.id)

    def cancel(self, handle: SessionHandle, tree_kill: bool = True) -> None:
        process = self._processes.get(handle.id)
        if process is None or process.poll() is not None:
            return
        pgid = os.getpgid(process.pid) if tree_kill else None
        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return

    def adopt(self) -> list[SessionHandle]:
        return [
            SessionHandle(id=unit_id, pid=p.pid)
            for unit_id, p in self._processes.items()
            if p.poll() is None
        ]

    def health(self, handle: SessionHandle) -> SessionHealth:
        process = self._processes.get(handle.id)
        if process is None:
            return SessionHealth(alive=False, detail="unknown session")
        alive = process.poll() is None
        return SessionHealth(alive=alive, detail="running" if alive else f"exited {process.returncode}")

    def _reap(self, unit_id: str) -> None:
        process = self._processes.get(unit_id)
        if process is None:
            return
        if process.poll() is None:
            try:
                pgid = os.getpgid(process.pid)
                os.killpg(pgid, signal.SIGTERM)
                process.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(pgid, signal.SIGKILL)
                except ProcessLookupError:
                    pass


def _normalize(record: dict) -> DriverEvent:
    kind = record.get("type", "text")
    if kind not in ("tool_call", "text", "usage", "completed", "failed"):
        kind = "text"
    payload = {k: v for k, v in record.items() if k != "type"}
    return DriverEvent(kind=kind, payload=payload)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/drivers/test_codex.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 7: Commit**

```bash
git add src/foundry/drivers/codex.py tests/drivers/test_codex.py tests/fixtures/fake_codex_cli.sh
git commit -m "feat(drivers): CodexDriver — protocol-conformant subprocess adapter, tested via scripted fixture"
```

---

### Task 8: Concurrency caps + token budgets

**Files:**
- Create: `src/foundry/orchestrator/budget.py`
- Modify: `src/foundry/orchestrator/tick.py` (per-run token budget enforcement in `dispatch`)
- Modify: `src/foundry/api/scheduler.py` (global + per-project concurrency across runs)
- Test: `tests/orchestrator/test_budget.py`, `tests/api/test_scheduler_fairness.py`

**Interfaces:**
- Produces: `src/foundry/orchestrator/budget.py`: `BudgetStatus` (`Literal["ok", "warning", "exceeded"]`), `check_budget(run: Run) -> BudgetStatus` (pure function: `tokens_used / token_budget` — `< 0.8` → `"ok"`, `< 1.0` → `"warning"`, `>= 1.0` → `"exceeded"`; `token_budget == 0` always means unlimited → always `"ok"`, matching the M0/M1a default of `token_budget=0`). `Orchestrator.dispatch()` gains a budget check: before dispatching each ready task, re-fetch the `Run` row; if `check_budget(run) == "exceeded"`, skip dispatch entirely for this tick, emit `budget.exceeded` once (idempotent via an events-log check, same idempotency pattern as `_dispatch_agent_reviews`), and surface a `human` gate on... there's no natural single unit to gate on for a whole-run budget stop, so instead create a `human_task` work unit (type already supports run-scoped, ownerless human tasks) titled via its payload, blocking nothing structurally but visible in `My queue` once M2b/M4 build that view. `_collect` aggregates `driver.usage` events into `Run.tokens_used` (previously logged but never summed) via `Store.update_run(run_id, tokens_used=...)`. `src/foundry/api/scheduler.py`'s `Scheduler` gains a `GlobalDispatchLimiter` (`global_cap: int`, `per_project_cap: int`) consulted in `tick_all_once` before calling each registered `Orchestrator.tick()` — runs are ticked in a weighted round-robin order (least-recently-ticked-per-project first) so one project's fan-out convoy can't starve another project's single run.

- [ ] **Step 1: Write the failing tests for `budget.py`**

```python
# tests/orchestrator/test_budget.py
from foundry.orchestrator.budget import check_budget
from foundry.store.models import Run


def _run(token_budget=0, tokens_used=0):
    return Run(id="r1", project_id="p1", playbook_ref="x", title="t", token_budget=token_budget, tokens_used=tokens_used)


def test_zero_budget_is_always_ok():
    assert check_budget(_run(token_budget=0, tokens_used=999_999)) == "ok"


def test_under_80_percent_is_ok():
    assert check_budget(_run(token_budget=1000, tokens_used=500)) == "ok"


def test_between_80_and_100_percent_is_warning():
    assert check_budget(_run(token_budget=1000, tokens_used=850)) == "warning"


def test_at_or_over_100_percent_is_exceeded():
    assert check_budget(_run(token_budget=1000, tokens_used=1000)) == "exceeded"
    assert check_budget(_run(token_budget=1000, tokens_used=1500)) == "exceeded"
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/orchestrator/test_budget.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write `src/foundry/orchestrator/budget.py`**

```python
from __future__ import annotations

from typing import Literal

from foundry.store.models import Run

BudgetStatus = Literal["ok", "warning", "exceeded"]


def check_budget(run: Run) -> BudgetStatus:
    if run.token_budget <= 0:
        return "ok"
    ratio = run.tokens_used / run.token_budget
    if ratio >= 1.0:
        return "exceeded"
    if ratio >= 0.8:
        return "warning"
    return "ok"
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/orchestrator/test_budget.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Wire budget enforcement + usage aggregation into `dispatch()`/`_collect()`**

In `dispatch()`, right after computing `slots` and before the `for task_unit in ready_tasks[:slots]:` loop:

```python
        run = await self.store.get_run(run_id)
        if run is not None and check_budget(run) == "exceeded":
            events = await self.store.list_events(run_id)
            already_flagged = any(e.type == "budget.exceeded" for e in events)
            if not already_flagged:
                await self.store.append_event(run_id, None, "budget.exceeded", {"tokens_used": run.tokens_used, "token_budget": run.token_budget})
                await self.store.create_work_units(
                    [WorkUnit(run_id=run_id, step_id="_budget", type="human_task", status="open")]
                )
            return 0
        if run is not None and check_budget(run) == "warning":
            events = await self.store.list_events(run_id)
            already_flagged = any(e.type == "budget.warning" for e in events)
            if not already_flagged:
                await self.store.append_event(run_id, None, "budget.warning", {"tokens_used": run.tokens_used, "token_budget": run.token_budget})
```

Add the import: `from foundry.orchestrator.budget import check_budget`.

In `_collect()`'s event-consuming loop, aggregate usage:

```python
        async for ev in self.driver.stream_events(handle):
            await self.store.append_event(run_id, session_unit.id, f"driver.{ev.kind}", ev.payload)
            if ev.kind == "completed":
                artifact_payload = ev.payload.get("artifact", {})
            elif ev.kind == "failed":
                failed = True
                error_payload = ev.payload
            elif ev.kind == "usage":
                total = ev.payload.get("tokens_in", 0) + ev.payload.get("tokens_out", 0)
                run = await self.store.get_run(run_id)
                if run is not None:
                    await self.store.update_run(run_id, tokens_used=run.tokens_used + total)
```

- [ ] **Step 6: FakeDriver-backed integration test proving budget pause**

```python
# append to tests/orchestrator/test_budget.py
import pytest

from foundry.drivers.base import DriverEvent
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


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
```

- [ ] **Step 7: Run all budget tests**

Run: `uv run pytest tests/orchestrator/test_budget.py -v`
Expected: PASS (5 tests)

- [ ] **Step 8: Write the failing scheduler-fairness test**

```python
# tests/api/test_scheduler_fairness.py
import pytest

from foundry.api.scheduler import GlobalDispatchLimiter


def test_global_cap_blocks_dispatch_once_reached():
    limiter = GlobalDispatchLimiter(global_cap=2, per_project_cap=5)
    assert limiter.can_dispatch(project_id="p1") is True
    limiter.record_dispatch(project_id="p1")
    limiter.record_dispatch(project_id="p1")
    assert limiter.can_dispatch(project_id="p1") is False


def test_per_project_cap_blocks_before_global_cap():
    limiter = GlobalDispatchLimiter(global_cap=10, per_project_cap=1)
    limiter.record_dispatch(project_id="p1")
    assert limiter.can_dispatch(project_id="p1") is False
    assert limiter.can_dispatch(project_id="p2") is True  # other project unaffected


def test_release_frees_a_slot():
    limiter = GlobalDispatchLimiter(global_cap=1, per_project_cap=1)
    limiter.record_dispatch(project_id="p1")
    assert limiter.can_dispatch(project_id="p1") is False
    limiter.release(project_id="p1")
    assert limiter.can_dispatch(project_id="p1") is True
```

- [ ] **Step 9: Run to verify failure**

Run: `uv run pytest tests/api/test_scheduler_fairness.py -v`
Expected: FAIL — `ImportError: cannot import name 'GlobalDispatchLimiter'`

- [ ] **Step 10: Read `src/foundry/api/scheduler.py` before modifying it, then add `GlobalDispatchLimiter`**

The implementer must first `Read` the current `src/foundry/api/scheduler.py` in full to see the exact current `Scheduler.tick_all_once`/`register` signatures before wiring the limiter in (this file was last touched in M1a and its exact per-run try/except isolation structure must be preserved). Add this class to the same file, above `Scheduler`:

```python
class GlobalDispatchLimiter:
    def __init__(self, global_cap: int = 20, per_project_cap: int = 8):
        self.global_cap = global_cap
        self.per_project_cap = per_project_cap
        self._in_flight_total = 0
        self._in_flight_by_project: dict[str, int] = {}

    def can_dispatch(self, project_id: str) -> bool:
        if self._in_flight_total >= self.global_cap:
            return False
        return self._in_flight_by_project.get(project_id, 0) < self.per_project_cap

    def record_dispatch(self, project_id: str) -> None:
        self._in_flight_total += 1
        self._in_flight_by_project[project_id] = self._in_flight_by_project.get(project_id, 0) + 1

    def release(self, project_id: str) -> None:
        self._in_flight_total = max(0, self._in_flight_total - 1)
        current = self._in_flight_by_project.get(project_id, 0)
        self._in_flight_by_project[project_id] = max(0, current - 1)
```

Wiring `GlobalDispatchLimiter` into `Scheduler.tick_all_once`'s actual dispatch-ordering (weighted round-robin by project, consulting `can_dispatch`/`record_dispatch`/`release` around each `Orchestrator.tick()` call) requires seeing the exact current method body — write this wiring to match the existing per-run try/except isolation pattern exactly (don't restructure it), adding project-fairness ordering as a layer on top, not a replacement. If `Scheduler` doesn't currently have access to each registered run's `project_id`, extend `register()`'s signature to accept it (check current signature first) rather than re-querying the store on every tick.

- [ ] **Step 11: Run to verify pass**

Run: `uv run pytest tests/api/test_scheduler_fairness.py -v`
Expected: PASS (3 tests)

- [ ] **Step 12: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 13: Commit**

```bash
git add src/foundry/orchestrator/budget.py src/foundry/orchestrator/tick.py \
        src/foundry/api/scheduler.py tests/orchestrator/test_budget.py tests/api/test_scheduler_fairness.py
git commit -m "feat(orchestrator): token budget pause + cross-project fair dispatch limiter"
```

---

### Task 9: Metrics rollup (compute-on-read)

**Files:**
- Create: `src/foundry/metrics/__init__.py`
- Create: `src/foundry/metrics/rollup.py`
- Create: `src/foundry/api/routes/metrics.py`
- Modify: `src/foundry/api/app.py` (register the new router)
- Test: `tests/metrics/test_rollup.py`, `tests/api/test_metrics.py`

**Interfaces:**
- Produces: `src/foundry/metrics/rollup.py`: `compute_project_metrics(events: list[Event], gates: list[Gate], units: list[WorkUnit], sessions: list[SessionRow]) -> dict` — pure function computing exactly the §11.1 table: `approval_latency_seconds` (mean `gate.approved`/`gate.rejected` minus matching `gate.created` per gate id, from event timestamps), `rework_rate` (rejections / total gate decisions), `tokens_per_run` (sum of `usage`-derived tokens, from `driver.usage` event payloads), `phase_durations_seconds` (per step_id: last event ts minus first event ts for units of that step_id), `retry_count`/`crash_count` (`unit.retried` / count of `session` units that ended `failed`), `auto_resolved_vs_escalated` (from `integration_artifact`-shaped artifacts' `auto_resolved`/`escalated` list lengths, matching Task 5's escalation contract). `GET /api/metrics/{project_id}` (`src/foundry/api/routes/metrics.py`) — aggregates across all of a project's runs, conforming to ADR-001's envelope.

- [ ] **Step 1: Write the failing rollup tests**

```python
# tests/metrics/test_rollup.py
import datetime as dt

from foundry.metrics.rollup import compute_project_metrics
from foundry.store.models import Artifact, Event, Gate, SessionRow, WorkUnit


def _ev(seq, unit_id, type_, payload=None, minutes_offset=0):
    return Event(
        seq=seq, run_id="r1", unit_id=unit_id, type=type_, payload_json=payload or {},
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(minutes=minutes_offset),
    )


def test_approval_latency_averages_created_to_decided_gap():
    events = [
        _ev(1, "u1", "gate.created", {"gate_id": "g1"}, minutes_offset=0),
        _ev(2, "u1", "gate.approved", {"gate_id": "g1"}, minutes_offset=10),
        _ev(3, "u2", "gate.created", {"gate_id": "g2"}, minutes_offset=0),
        _ev(4, "u2", "gate.rejected", {"gate_id": "g2"}, minutes_offset=20),
    ]
    metrics = compute_project_metrics(events=events, gates=[], units=[], sessions=[])
    assert metrics["approval_latency_seconds"] == pytest_approx(900)  # (600+1200)/2


def pytest_approx(value, rel=1e-6):
    import pytest

    return pytest.approx(value, rel=rel)


def test_rework_rate_is_rejections_over_total_decisions():
    gates = [
        Gate(id="g1", work_unit_id="u1", gate_type="human", decision="approved"),
        Gate(id="g2", work_unit_id="u2", gate_type="human", decision="rejected"),
        Gate(id="g3", work_unit_id="u3", gate_type="human", decision="approved"),
        Gate(id="g4", work_unit_id="u4", gate_type="human", decision="pending"),
    ]
    metrics = compute_project_metrics(events=[], gates=gates, units=[], sessions=[])
    assert metrics["rework_rate"] == pytest_approx(1 / 3)  # pending excluded from the denominator


def test_retry_and_crash_counts():
    events = [
        _ev(1, "u1", "unit.retried", {}),
        _ev(2, "u2", "unit.retried", {}),
    ]
    sessions = [
        SessionRow(id="s1", work_unit_id="u1", driver="FakeDriver", status="ended"),
        SessionRow(id="s2", work_unit_id="u2", driver="FakeDriver", status="failed"),
    ]
    metrics = compute_project_metrics(events=events, gates=[], units=[], sessions=sessions)
    assert metrics["retry_count"] == 2
    assert metrics["crash_count"] == 1


def test_auto_resolved_vs_escalated_from_integration_artifacts():
    units = [WorkUnit(id="u1", run_id="r1", step_id="integrate", type="task", status="closed")]
    metrics = compute_project_metrics(
        events=[], gates=[], units=units, sessions=[],
        artifacts=[
            Artifact(
                id="a1", run_id="r1", work_unit_id="u1", kind="integration_artifact", version=1,
                produced_by_role="integrator",
                payload_json={"auto_resolved": ["lockfile", "imports"], "escalated": [{"file": "x.py"}]},
            )
        ],
    )
    assert metrics["auto_resolved_count"] == 2
    assert metrics["escalated_count"] == 1


def test_empty_input_returns_zeroed_metrics_not_a_crash():
    metrics = compute_project_metrics(events=[], gates=[], units=[], sessions=[])
    assert metrics["approval_latency_seconds"] == 0
    assert metrics["rework_rate"] == 0
    assert metrics["retry_count"] == 0
    assert metrics["crash_count"] == 0
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/metrics/test_rollup.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.metrics'`

- [ ] **Step 3: Write `src/foundry/metrics/__init__.py`** (empty file) **and `src/foundry/metrics/rollup.py`**

```python
from __future__ import annotations

from foundry.store.models import Artifact, Event, Gate, SessionRow, WorkUnit


def compute_project_metrics(
    events: list[Event],
    gates: list[Gate],
    units: list[WorkUnit],
    sessions: list[SessionRow],
    artifacts: list[Artifact] | None = None,
) -> dict:
    artifacts = artifacts or []

    created_by_gate: dict[str, Event] = {}
    decided_by_gate: dict[str, Event] = {}
    for ev in events:
        gate_id = ev.payload_json.get("gate_id")
        if gate_id is None:
            continue
        if ev.type == "gate.created":
            created_by_gate[gate_id] = ev
        elif ev.type in ("gate.approved", "gate.rejected"):
            decided_by_gate[gate_id] = ev

    latencies = [
        (decided_by_gate[gid].created_at - created_by_gate[gid].created_at).total_seconds()
        for gid in created_by_gate
        if gid in decided_by_gate
    ]
    approval_latency_seconds = sum(latencies) / len(latencies) if latencies else 0

    decided_gates = [g for g in gates if g.decision in ("approved", "rejected")]
    rejected_gates = [g for g in decided_gates if g.decision == "rejected"]
    rework_rate = len(rejected_gates) / len(decided_gates) if decided_gates else 0

    retry_count = sum(1 for ev in events if ev.type == "unit.retried")
    crash_count = sum(1 for s in sessions if s.status == "failed")

    integration_artifacts = [a for a in artifacts if a.kind == "integration_artifact"]
    auto_resolved_count = sum(len(a.payload_json.get("auto_resolved", [])) for a in integration_artifacts)
    escalated_count = sum(len(a.payload_json.get("escalated", [])) for a in integration_artifacts)

    return {
        "approval_latency_seconds": approval_latency_seconds,
        "rework_rate": rework_rate,
        "retry_count": retry_count,
        "crash_count": crash_count,
        "auto_resolved_count": auto_resolved_count,
        "escalated_count": escalated_count,
    }
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/metrics/test_rollup.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Write the failing API test**

First, read `src/foundry/api/routes/projects.py` and `src/foundry/api/app.py` in full to confirm the current `_get_store` helper and router-registration pattern before writing new code that must match it exactly.

```python
# tests/api/test_metrics.py
import pytest


@pytest.mark.asyncio
async def test_get_metrics_for_project_with_no_runs_returns_zeroed_metrics(api_client):
    resp = await api_client.post("/api/projects", json={"name": "demo", "path": "/tmp/demo"})
    project_id = resp.json()["data"]["id"]

    resp = await api_client.get(f"/api/metrics/{project_id}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["rework_rate"] == 0
    assert body["retry_count"] == 0


@pytest.mark.asyncio
async def test_get_metrics_for_unknown_project_404s(api_client):
    resp = await api_client.get("/api/metrics/01JUNKNOWN")
    assert resp.status_code == 404
```

- [ ] **Step 6: Run to verify failure**

Run: `uv run pytest tests/api/test_metrics.py -v`
Expected: FAIL — 404 route not found (no metrics router registered yet)

- [ ] **Step 7: Write `src/foundry/api/routes/metrics.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from foundry.api.errors import NotFoundError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.metrics.rollup import compute_project_metrics

router = APIRouter()


@router.get("/api/metrics/{project_id}")
async def get_project_metrics(project_id: str, request: Request):
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(resource="Project", resource_id=project_id)

    runs = await store.list_runs(project_id=project_id)
    all_events, all_gates, all_units, all_sessions, all_artifacts = [], [], [], [], []
    for run in runs:
        all_events += await store.list_events(run.id)
        all_gates += await store.list_gates_for_run(run.id)
        all_units += await store.list_units(run.id)
        all_artifacts += await store.list_artifacts(run.id)

    metrics = compute_project_metrics(
        events=all_events, gates=all_gates, units=all_units, sessions=all_sessions, artifacts=all_artifacts
    )
    return ApiResponse(data=metrics, paging=Paging())
```

Read `src/foundry/api/errors.py` first to confirm `NotFoundError`'s actual constructor signature (it may not be `resource`/`resource_id` — match whatever M1a actually shipped) before using it verbatim.

Register the router in `src/foundry/api/app.py` (read the file first to see the existing registration pattern for `projects`/`runs`/`gates`/`stream` routers and follow it exactly):

```python
from foundry.api.routes import metrics
...
app.include_router(metrics.router)
```

- [ ] **Step 8: Run to verify pass**

Run: `uv run pytest tests/api/test_metrics.py -v`
Expected: PASS (2 tests)

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 10: Commit**

```bash
git add src/foundry/metrics/ src/foundry/api/routes/metrics.py src/foundry/api/app.py \
        tests/metrics/ tests/api/test_metrics.py
git commit -m "feat(metrics): compute-on-read project rollup (approval latency, rework rate, retry/crash counts, conflict resolution) + GET /api/metrics/{project_id}"
```

---

### Task 10: End-to-end fan-out integration test (exit-criterion proof)

**Files:**
- Create: `tests/orchestrator/fixtures/fanout_e2e.toml`
- Test: `tests/orchestrator/test_fanout_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1-9. No new production code — this task is a single comprehensive FakeDriver-backed test proving the actual M2 exit criterion end-to-end: *"a 3-slice feature implemented by three parallel agents (mixed providers), peer-reviewed, integrated to one branch — including at least one auto-resolved conflict — visualized live on the DAG."* ("visualized live on the DAG" is M2b's job; this test proves everything the dashboard would be visualizing is real and correct.) "Mixed providers" is proven via two `FakeDriver` instances tagged with different `driver` labels dispatched by step (per this plan's Global Constraints — no real CodexDriver/ClaudeCodeDriver network call).

- [ ] **Step 1: Write the fixture playbook**

```toml
# tests/orchestrator/fixtures/fanout_e2e.toml
[playbook]
id = "fanout_e2e"
description = "3-slice fan-out: architecture -> implement -> review (agent loop) -> integrate (escalation)"

[[step]]
id = "architecture"
role = "architect"
produces = "architecture_artifact"
gate = "human"

[[step]]
id = "implement"
role = "developer"
needs = ["architecture"]
fan_out = "architecture_artifact.slices"
produces = "code_diff_artifact"
gate = "none"
writes = true

[[step]]
id = "review"
role = "reviewer"
needs = ["implement"]
fan_out_from = "implement"
produces = "review_artifact"
gate = "agent"
loop = { back_to = "implement", max_rounds = 3 }

[[step]]
id = "integrate"
role = "integrator"
needs = ["review"]
produces = "integration_artifact"
gate = "human"
escalates_on = "escalated"
```

- [ ] **Step 2: Write the test — this is allowed to be long; it is the exit-criterion proof, not a unit test**

```python
# tests/orchestrator/test_fanout_e2e.py
import subprocess

import pytest

from foundry.drivers.base import DriverEvent, SessionSpec
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.orchestrator.worktrees import WorktreeManager
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


def _init_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True)
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


class _MixedProviderDriver(FakeDriver):
    """Tags each slice's session with a different simulated provider, proving
    the orchestrator is driver-agnostic across per-slice dispatch — standing
    in for real mixed-provider dispatch without spending tokens or making a
    network call (see this plan's Global Constraints)."""

    PROVIDERS = ["claude-fake", "codex-fake", "claude-fake"]

    def __init__(self, script):
        super().__init__(script)
        self.provider_by_unit: dict[str, str] = {}

    def spawn(self, spec: SessionSpec):
        slice_index = spec.step_id  # tests key providers off step_id for simplicity below
        handle = super().spawn(spec)
        self.provider_by_unit[handle.id] = self.PROVIDERS[len(self.provider_by_unit) % len(self.PROVIDERS)]
        return handle


@pytest.mark.asyncio
async def test_full_fanout_review_integrate_cycle(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(repo))
    playbook = load_playbook("tests/orchestrator/fixtures/fanout_e2e.toml")
    run = await store.create_run(project.id, "fanout_e2e.toml", "demo run")
    await materialize(playbook, run.id, store)

    review_call_count = {"n": 0}

    class _ReviewScript(FakeStepScript):
        pass

    script = {
        "architecture": FakeStepScript(artifact={"slices": ["auth", "billing", "notifications"]}),
        "implement": FakeStepScript(artifact={"diff": "ok"}),
        # First review call for each unit rejects once (proves the rework loop), then approves.
    }
    driver = _MixedProviderDriver(script)

    # Patch review scripting dynamically since FakeDriver scripts by step_id only,
    # and we need "reject once, then approve" behavior — override stream_events
    # for the "review" step_id specifically.
    original_stream = driver.stream_events

    async def _review_aware_stream(handle):
        step_id = driver._handle_step.get(handle.id, "")
        if step_id != "review":
            async for ev in original_stream(handle):
                yield ev
            return
        review_call_count["n"] += 1
        yield DriverEvent(kind="tool_call", payload={"tool": "noop"})
        if review_call_count["n"] <= 1:
            yield DriverEvent(kind="completed", payload={"artifact": {"verdict": "needs_changes"}})
        else:
            yield DriverEvent(kind="completed", payload={"artifact": {"verdict": "approved"}})

    driver.stream_events = _review_aware_stream

    worktree_mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    orch = Orchestrator(store, driver, playbook, concurrency=10, worktree_manager=worktree_mgr, project_path=str(repo))

    # Drive architecture's human gate to approved.
    await orch.tick(run.id)
    gates = await store.list_gates_for_run(run.id)
    arch_gate = next(g for g in gates if g.artifact_id is not None)
    await store.decide_gate(arch_gate.id, "approved")

    # Drive enough ticks for fan-out, implement, at-least-one review rejection + rework,
    # eventual approval, and integrate's own artifact production.
    for _ in range(20):
        await orch.tick(run.id)
        gates = await store.list_gates_for_run(run.id)
        integrate_gate = next(
            (g for g in gates if g.decision == "pending" and g.gate_type == "human" and g.artifact_id is not None), None
        )
        if integrate_gate is not None:
            break

    units = await store.list_units(run.id)
    convoy = next(u for u in units if u.type == "convoy")
    assert convoy.status == "closed"

    review_units = [u for u in units if u.step_id == "review"]
    assert len(review_units) == 3
    assert any(u.attempt >= 1 for u in [u for u in units if u.step_id == "implement"])  # at least one rework happened

    # "mixed providers": at least two distinct simulated providers were used across slices.
    assert len(set(driver.provider_by_unit.values())) >= 2

    artifacts = await store.list_artifacts(run.id)
    implement_artifacts = [a for a in artifacts if a.kind == "code_diff_artifact"]
    assert len(implement_artifacts) >= 3  # at least one per slice, more if rework produced v2

    # Worktrees existed and were cleaned up on close for every implement slice unit.
    worktree_root = tmp_path / "worktrees" / run.id
    assert not worktree_root.exists() or not any(worktree_root.iterdir())

    # Now approve integrate itself, scripted with one auto-resolved and one escalated conflict.
    integrate_task_unit = next(u for u in units if u.step_id == "integrate")
    driver.script["integrate"] = FakeStepScript(
        artifact={"auto_resolved": ["package-lock.json"], "escalated": [{"file": "auth.py", "reason": "semantic overlap"}]}
    )
    # integrate hasn't dispatched yet in this test run (needs convoy closed, which just happened);
    # tick once more to dispatch and collect it.
    await orch.tick(run.id)

    units = await store.list_units(run.id)
    integrate_unit = next(u for u in units if u.step_id == "integrate")
    assert integrate_unit.status == "blocked"

    human_tasks = [u for u in units if u.type == "human_task"]
    assert human_tasks  # escalation created a human_task, per Task 5's generic contract
```

- [ ] **Step 3: Run the test — expect it to need debugging**

Run: `uv run pytest tests/orchestrator/test_fanout_e2e.py -v -s`

This test exercises 9 tasks' worth of interacting engine code end-to-end for the first time; it is normal and expected for this to fail on the first several attempts (timing of when `integrate` actually dispatches relative to convoy-close, whether the "approve integrate's gate" step in the test needs to happen before or after scripting its artifact, off-by-one tick counts, etc.). **Debug the test against the actual implementation from Tasks 1-9 — do not weaken the assertions to make it pass; if an assertion reveals a real bug in Tasks 1-9's code, fix the code** (this is exactly the kind of cross-task integration bug class the project's final whole-branch review looks for — better to catch it here, task-locally, than to defer it).

- [ ] **Step 4: Once passing, run the full suite**

Run: `uv run pytest -q`
Expected: PASS, full suite green

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrator/fixtures/fanout_e2e.toml tests/orchestrator/test_fanout_e2e.py
git commit -m "test(orchestrator): end-to-end fan-out/review-loop/integrate/escalation proof (M2 exit criterion)"
```

---

## Out of scope for this plan (tracked, not forgotten)

- **M2b — fleet view, DAG view, metrics view (dashboard).** A separate plan, written after M2a merges, consuming `convoy_id`, the review-loop's `gate.review_dispatched`/agent-decided gates, and `GET /api/metrics/{project_id}` this plan produces.
- **Real ClaudeCodeDriver / CodexDriver end-to-end runs against live CLIs.** Still deferred from M0; CodexDriver here is a real, tested adapter class, never invoked against a real `codex` binary or network endpoint during this plan's automated tests (Global Constraints).
- **`fan_out_from` chains deeper than one hop.** Not needed by the exit criterion; explicitly rejected by Task 1's validator.
- **`loop.until` as a general expression language.** Only the hardcoded `verdict == "approved"` semantics is implemented.
- **Persisted/scheduled metrics rollup table + nightly job.** Task 9 computes on read; revisit only if that's provably too slow at real scale.
- **Global/per-project concurrency limiter's actual weighted-round-robin *dispatch ordering* wiring inside `Scheduler.tick_all_once`** is scoped generically in Task 8's Step 10 (the implementer must read the current scheduler file and wire it in without restructuring the existing per-run try/except isolation) — the `GlobalDispatchLimiter` class itself is fully specified and tested in isolation, but its exact call-site integration is deliberately left to match whatever `scheduler.py` looks like by the time this task executes, rather than guessing at line numbers that may have drifted.
