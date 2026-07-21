# M3a — Knowledge Graph + Memory Engine Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend capability design doc §9-10 (M3) calls for — a knowledge graph service, context minimization, cross-slice interference warnings, and a compounding memory store fed by a generic `compound` step — so implement/review steps consume a *bounded, relevant* slice of the codebase instead of everything, and a second run of a similar feature can demonstrably draw on a lesson from the first. M3b (a separate plan) builds the knowledge-view dashboard panel that visualizes what this milestone computes.

**Architecture:** Two new first-party services (`src/foundry/kg/`, memory retrieval logic alongside the existing `Memory` table from M0) consumed **in-process** by the orchestrator, not over a new HTTP surface — `Orchestrator.dispatch()` composes a context bundle (blast-radius file list + top-k memory items) directly when building `SessionSpec` for a session, and records what it composed via a new `context.composed` event for observability and the token-reduction proof (Task 7). No `/internal` HTTP endpoint is added in this plan (see Global Constraints). The memory-compounding loop reuses the exact generic-contract pattern M2a's `escalates_on` established: a step whose produced artifact matches a well-known shape triggers engine-side side effects, with zero SDLC-specific knowledge in the engine itself.

**Tech Stack:** Same as M0-M2a — Python 3.12+, SQLAlchemy 2 async + aiosqlite, Pydantic v2, pytest + pytest-asyncio, ruff. No new runtime dependencies — the knowledge graph is built with Python's stdlib `ast` module (parsing this project's own Python source is exactly the kind of codebase KGService needs to handle, and `ast` is dependency-free, precise, and already in every Python 3.12 install).

## Global Constraints

- **KGService is first-party, not a wrapper around the external `code-review-graph` package design doc §9 names.** That package is not a declared dependency of this project, is not installed, and doesn't exist anywhere on this filesystem — it's an external tool the design doc's author had access to elsewhere, not something available here. Building a lightweight, in-repo import-graph service (nodes = source files, edges = import relationships, parsed via Python's stdlib `ast` module) is a documented, necessary substitution — the same kind of honest scope adaptation M2a made for CodexDriver (real class built, real invocation deferred) and the DAG view (layered layout, not a physics-sim library). This KGService only understands Python import graphs in this iteration; extending it to other languages is future work, not silently implied here.
- **No new `/internal` HTTP API, no new authentication surface.** Design doc §7 describes a shared-secret-header `/internal` API for agents to fetch context bundles over HTTP. That surface has zero real consumers today — `FakeDriver` never makes an HTTP callback (it runs in-process), and no real provider driver (`ClaudeCodeDriver`) has been wired into this codebase in any milestone so far (still deferred, unchanged since M0). Introducing new API authentication for a capability nothing yet calls is premature, and per the project's standing directive to ask before touching security-sensitive surfaces (secrets, auth), this plan deliberately avoids the question entirely by keeping context composition in-process, inside `Orchestrator.dispatch()`, exactly where `SessionSpec` is already built today. When a real driver is eventually wired up (still not this milestone), *that* plan is the right place to decide whether context-fetching needs to cross a process boundary and, if so, design real auth for it then — not before.
- **Memory retrieval uses keyword-overlap scoring, not embeddings.** Design doc §10 describes "embedding similarity" selection. No embedding model or vector-search dependency exists in this project. A simple, deterministic keyword/token-overlap scorer (Jaccard-style overlap between the step's input-artifact text and each candidate memory item's title+body) is used instead — documented, not silently substituted. This is revisited if/when a real embedding-capable driver exists to generate them.
- **"Reviewer risk scores" (roadmap text) are represented as the `convoy.interference_warning` event's structured data (Task 6), not as text injected into a reviewer role's prompt.** Design doc §8's own prompt-rendering contract (role definition, input artifacts, KG context, memory, schema, chat notes) has never been built in any milestone so far — `SessionSpec.prompt` is still the placeholder string `f"step:{step.id}"` it's been since M0, extended only minimally by this plan (Task 5). Attaching a "risk score" to a prompt template that doesn't exist would be inventing prompt-rendering infrastructure this plan doesn't otherwise need; the interference-warning event carries the same underlying signal (overlapping blast radii between parallel slices) in a form the engine can already act on (fire an event, block nothing) and a future pack/prompt-templating milestone can surface however it wants.
- **The KG import graph only needs to be built from a project's own Python source tree** (this repo's own `src/foundry/` is the realistic fixture for the token-reduction benchmark in Task 7 — a real, non-trivial, already-available codebase, not a synthetic fixture invented for this plan alone).
- **No changes to `frontend/`.** This plan is backend-only, same split pattern as M2a/M2b.
- Every new/changed file lives under `src/foundry/` or `tests/`.

---

### Task 1: KGService — import-graph builder + blast radius

**Files:**
- Create: `src/foundry/kg/__init__.py`
- Create: `src/foundry/kg/service.py`
- Test: `tests/kg/__init__.py`, `tests/kg/test_service.py`
- Test fixture: `tests/kg/fixtures/sample_project/` (a tiny synthetic Python package for isolated, fast unit tests — Task 7's benchmark uses the real `src/foundry/` tree separately)

**Interfaces:**
- Produces: `KGSnapshot` (dataclass: `nodes: set[str]` — relative file paths; `imports: dict[str, set[str]]` — file → set of files it imports (intra-project only, external/stdlib imports dropped)). `build_kg(project_root: str) -> KGSnapshot` — walks all `.py` files under `project_root`, parses each with `ast.parse`, resolves `import`/`from ... import` statements to project-relative file paths where possible (module `foo.bar` → `foo/bar.py` or `foo/bar/__init__.py`, tried relative to every directory containing an `__init__.py` ancestor chain — simplified single-root resolution, not a full `sys.path` emulation). `blast_radius(snapshot: KGSnapshot, changed_files: list[str], depth: int = 2) -> set[str]` — BFS over both forward (`imports`) and reverse (files that import a changed file) edges, up to `depth` hops, unioned across all `changed_files`, always including the `changed_files` themselves.

- [ ] **Step 1: Write the fixture package and failing tests**

```python
# tests/kg/fixtures/sample_project/__init__.py
```

```python
# tests/kg/fixtures/sample_project/a.py
from sample_project import b

VALUE = b.helper()
```

```python
# tests/kg/fixtures/sample_project/b.py
from sample_project import c


def helper():
    return c.CONST
```

```python
# tests/kg/fixtures/sample_project/c.py
CONST = 42
```

```python
# tests/kg/fixtures/sample_project/isolated.py
import os

VALUE = os.getcwd()
```

```python
# tests/kg/test_service.py
from pathlib import Path

from foundry.kg.service import blast_radius, build_kg

FIXTURE_ROOT = str(Path(__file__).parent / "fixtures")


def test_build_kg_finds_all_python_files():
    snapshot = build_kg(FIXTURE_ROOT)
    assert "sample_project/a.py" in snapshot.nodes
    assert "sample_project/b.py" in snapshot.nodes
    assert "sample_project/c.py" in snapshot.nodes
    assert "sample_project/isolated.py" in snapshot.nodes


def test_build_kg_resolves_intra_project_imports():
    snapshot = build_kg(FIXTURE_ROOT)
    assert "sample_project/b.py" in snapshot.imports["sample_project/a.py"]
    assert "sample_project/c.py" in snapshot.imports["sample_project/b.py"]


def test_build_kg_drops_external_stdlib_imports():
    snapshot = build_kg(FIXTURE_ROOT)
    # "os" has no project-relative resolution; isolated.py's import edge set
    # for an unresolvable module must simply not appear, not crash.
    assert snapshot.imports.get("sample_project/isolated.py", set()) == set()


def test_blast_radius_direct_hit_is_included():
    snapshot = build_kg(FIXTURE_ROOT)
    radius = blast_radius(snapshot, ["sample_project/c.py"], depth=1)
    assert "sample_project/c.py" in radius


def test_blast_radius_follows_reverse_edges_within_depth():
    snapshot = build_kg(FIXTURE_ROOT)
    # c.py changed; b.py imports c.py (1 hop reverse); a.py imports b.py (2 hops reverse).
    radius = blast_radius(snapshot, ["sample_project/c.py"], depth=2)
    assert "sample_project/b.py" in radius
    assert "sample_project/a.py" in radius


def test_blast_radius_respects_depth_cutoff():
    snapshot = build_kg(FIXTURE_ROOT)
    radius = blast_radius(snapshot, ["sample_project/c.py"], depth=1)
    assert "sample_project/b.py" in radius  # 1 hop
    assert "sample_project/a.py" not in radius  # 2 hops — excluded at depth=1


def test_blast_radius_isolated_file_has_no_neighbors():
    snapshot = build_kg(FIXTURE_ROOT)
    radius = blast_radius(snapshot, ["sample_project/isolated.py"], depth=2)
    assert radius == {"sample_project/isolated.py"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kg/test_service.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.kg'`

- [ ] **Step 3: Write `src/foundry/kg/service.py`**

```python
from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class KGSnapshot:
    nodes: set[str] = field(default_factory=set)
    imports: dict[str, set[str]] = field(default_factory=dict)


def build_kg(project_root: str) -> KGSnapshot:
    root = Path(project_root)
    py_files = sorted(root.rglob("*.py"))
    rel_paths = {str(p.relative_to(root)) for p in py_files}

    snapshot = KGSnapshot(nodes=rel_paths)
    for path in py_files:
        rel = str(path.relative_to(root))
        snapshot.imports[rel] = _resolve_imports(path, root, rel_paths)
    return snapshot


def _resolve_imports(path: Path, root: Path, known_files: set[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return set()

    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_names.add(node.module)

    resolved: set[str] = set()
    for module_name in module_names:
        candidate = _module_to_relpath(module_name, known_files)
        if candidate is not None:
            resolved.add(candidate)
    return resolved


def _module_to_relpath(module_name: str, known_files: set[str]) -> str | None:
    as_path = module_name.replace(".", "/")
    for candidate in (f"{as_path}.py", f"{as_path}/__init__.py"):
        if candidate in known_files:
            return candidate
    # Also try treating the module name as rooted one level below any known
    # top-level package (handles fixtures/tests laid out under a subdir).
    for known in known_files:
        if known.endswith(f"/{as_path}.py") or known.endswith(f"/{as_path}/__init__.py"):
            return known
    return None


def blast_radius(snapshot: KGSnapshot, changed_files: list[str], depth: int = 2) -> set[str]:
    reverse: dict[str, set[str]] = {}
    for src, targets in snapshot.imports.items():
        for target in targets:
            reverse.setdefault(target, set()).add(src)

    visited: set[str] = set(changed_files)
    frontier: deque[tuple[str, int]] = deque((f, 0) for f in changed_files)
    while frontier:
        current, dist = frontier.popleft()
        if dist >= depth:
            continue
        neighbors = snapshot.imports.get(current, set()) | reverse.get(current, set())
        for neighbor in neighbors:
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append((neighbor, dist + 1))
    return visited
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kg/test_service.py -v`
Expected: PASS (7 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/foundry/kg/ tests/kg/
git commit -m "feat(kg): first-party Python import-graph builder + blast-radius query"
```

---

### Task 2: Memory store

**Files:**
- Modify: `src/foundry/store/models.py` (add `project_id` to `Memory`)
- Modify: `src/foundry/store/store.py`
- Test: `tests/store/test_memory.py`

**Interfaces:**
- Produces: `Memory.project_id: str | None` (new column — the existing `scope: str` field already distinguishes `pack`/`project`/`role`, but nothing recorded *which* project for `scope="project"` items; without this, project-scoped memory is unfilterable). `Store.create_memory_item(scope, kind, title, body_md, project_id=None, pack_id=None, source_run_id=None) -> Memory`. `Store.list_memory_items(scope=None, project_id=None, pack_id=None, kind=None) -> list[Memory]` — all filters optional and combined with AND when provided.

- [ ] **Step 1: Write the failing tests**

```python
# tests/store/test_memory.py
import pytest

from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def _store(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_create_and_list_memory_item(tmp_path):
    store = await _store(tmp_path)
    item = await store.create_memory_item(
        scope="project", kind="lesson", title="Watch the budget",
        body_md="Token budgets pause dispatch, not kill in-flight work.",
        project_id="proj1", source_run_id="run1",
    )
    assert item.id

    items = await store.list_memory_items(project_id="proj1")
    assert len(items) == 1
    assert items[0].title == "Watch the budget"
    await store.stop()


@pytest.mark.asyncio
async def test_list_memory_items_filters_by_project(tmp_path):
    store = await _store(tmp_path)
    await store.create_memory_item(scope="project", kind="lesson", title="A", body_md="x", project_id="p1")
    await store.create_memory_item(scope="project", kind="lesson", title="B", body_md="x", project_id="p2")

    items = await store.list_memory_items(project_id="p1")
    assert [i.title for i in items] == ["A"]
    await store.stop()


@pytest.mark.asyncio
async def test_list_memory_items_filters_by_kind_and_scope(tmp_path):
    store = await _store(tmp_path)
    await store.create_memory_item(scope="project", kind="lesson", title="L", body_md="x", project_id="p1")
    await store.create_memory_item(scope="project", kind="pattern", title="P", body_md="x", project_id="p1")

    items = await store.list_memory_items(project_id="p1", kind="pattern")
    assert [i.title for i in items] == ["P"]
    await store.stop()


@pytest.mark.asyncio
async def test_list_memory_items_with_no_filters_returns_all(tmp_path):
    store = await _store(tmp_path)
    await store.create_memory_item(scope="pack", kind="pattern", title="X", body_md="x", pack_id="pk1")
    items = await store.list_memory_items()
    assert len(items) == 1
    await store.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/store/test_memory.py -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'create_memory_item'`

- [ ] **Step 3: Add `project_id` to the `Memory` model**

In `src/foundry/store/models.py`, in the `Memory` class, add (place after `pack_id`):

```python
    project_id: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Add the two `Store` methods**

In `src/foundry/store/store.py`, near the existing CRUD sections (add a new `# --- memory ---` section, e.g. after `# --- sessions ---`):

```python
    # --- memory ---

    async def create_memory_item(
        self,
        scope: str,
        kind: str,
        title: str,
        body_md: str,
        project_id: str | None = None,
        pack_id: str | None = None,
        source_run_id: str | None = None,
    ) -> Memory:
        async def _op(session):
            item = Memory(
                scope=scope,
                kind=kind,
                title=title,
                body_md=body_md,
                project_id=project_id,
                pack_id=pack_id,
                source_run_id=source_run_id,
            )
            session.add(item)
            await session.flush()
            return item

        return await self.write(_op)

    async def list_memory_items(
        self,
        scope: str | None = None,
        project_id: str | None = None,
        pack_id: str | None = None,
        kind: str | None = None,
    ) -> list[Memory]:
        async def _op(session):
            stmt = select(Memory)
            if scope is not None:
                stmt = stmt.where(Memory.scope == scope)
            if project_id is not None:
                stmt = stmt.where(Memory.project_id == project_id)
            if pack_id is not None:
                stmt = stmt.where(Memory.pack_id == pack_id)
            if kind is not None:
                stmt = stmt.where(Memory.kind == kind)
            res = await session.execute(stmt)
            return list(res.scalars())

        return await self.read(_op)
```

Add `Memory` to the existing `from foundry.store.models import (...)` block at the top of the file.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/store/test_memory.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 7: Commit**

```bash
git add src/foundry/store/models.py src/foundry/store/store.py tests/store/test_memory.py
git commit -m "feat(store): project_id on Memory + create/list_memory_items"
```

---

### Task 3: Compound step contract

**Files:**
- Modify: `src/foundry/orchestrator/tick.py`
- Test: `tests/orchestrator/test_compound.py`

**Interfaces:**
- Consumes: `Store.create_memory_item` (Task 2).
- Produces: extends `_collect()`'s success path (alongside the existing `escalates_on` check from M2a) — when `step.produces == "memory_items_artifact"`, the engine reads `artifact_payload["items"]` (a list of `{"kind": "lesson"|"pattern"|"pitfall", "title": str, "body_md": str}` dicts) and writes one `Memory` row per item via `store.create_memory_item(scope="project", project_id=<project id of the run>, source_run_id=run_id, ...)`, then closes the unit normally (this is deliberately an *ungated* step per design doc §10 — "Every playbook ends with an ungated compound step" — so it always follows the ordinary `step.gate in (None, "none")` closing path once memory items are written, never the gated branch). This is a generic contract keyed on the artifact `kind` string, exactly like `escalates_on` is keyed on a field name — the engine has no idea what "compound" or "lesson" mean semantically, only that this specific artifact shape triggers a specific store write.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestrator/test_compound.py
import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_compound_step_writes_memory_items(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(
        id="p",
        steps=[StepSpec(id="compound", role="reviewer", produces="memory_items_artifact", gate="none")],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    script = {
        "compound": FakeStepScript(
            artifact={
                "items": [
                    {"kind": "lesson", "title": "Watch budgets", "body_md": "Pause, don't kill."},
                    {"kind": "pattern", "title": "Retry with backoff", "body_md": "Reuse the cap logic."},
                ]
            }
        )
    }
    orch = Orchestrator(store, FakeDriver(script), playbook)
    await orch.tick(run.id)

    items = await store.list_memory_items(project_id=project.id)
    assert {i.title for i in items} == {"Watch budgets", "Retry with backoff"}
    assert {i.kind for i in items} == {"lesson", "pattern"}
    assert all(i.source_run_id == run.id for i in items)

    units = await store.list_units(run.id)
    compound_unit = next(u for u in units if u.step_id == "compound")
    assert compound_unit.status == "closed"


@pytest.mark.asyncio
async def test_non_compound_step_does_not_write_memory(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(id="p", steps=[StepSpec(id="plain", role="dev", produces="x", gate="none")])
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    orch = Orchestrator(store, FakeDriver({"plain": FakeStepScript(artifact={"items": [{"kind": "lesson"}]})}), playbook)
    await orch.tick(run.id)

    items = await store.list_memory_items(project_id=project.id)
    assert items == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_compound.py -v`
Expected: FAIL — first test fails (`items == []`, no memory rows written); second test passes trivially already.

- [ ] **Step 3: Add the compound-step check to `_collect()` in `src/foundry/orchestrator/tick.py`**

Read the current `_collect()` success-path block first (it already has the `escalated = artifact_payload.get(step.escalates_on)...` check from M2a Task 5). Add a compound check as a new branch, evaluated after the escalation check (an artifact can't be both an escalation source and a compound source in practice, but ordering escalation first preserves that if it ever were, escalation wins — matching the existing pattern where the engine handles one well-known shape at a time):

```python
        escalated = artifact_payload.get(step.escalates_on) if step.escalates_on else None
        if escalated:
            ...  # unchanged, from M2a Task 5
        elif step.produces == "memory_items_artifact":
            run = await self.store.get_run(run_id)
            project_id = run.project_id if run is not None else None
            for item in artifact_payload.get("items", []):
                await self.store.create_memory_item(
                    scope="project",
                    kind=item["kind"],
                    title=item["title"],
                    body_md=item["body_md"],
                    project_id=project_id,
                    source_run_id=run_id,
                )
            await self.store.update_unit(task_unit.id, status="closed")
            await self.store.append_event(
                run_id, task_unit.id, "unit.closed", {"memory_items_written": len(artifact_payload.get("items", []))}
            )
            self._cleanup_worktree(task_unit.id)
        elif step.gate in (None, "none"):
            ...  # unchanged
        else:
            ...  # unchanged
```

Write out the actual full replacement block in the file (don't leave `...` placeholders in the committed code — this snippet is showing you where the new `elif` branch slots in relative to the existing branches; copy the existing unchanged branches' real bodies from the current file into your edit).

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_compound.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/foundry/orchestrator/tick.py tests/orchestrator/test_compound.py
git commit -m "feat(orchestrator): generic memory_items_artifact contract writes compound-step output to Memory"
```

---

### Task 4: Memory retrieval (keyword-overlap scoring)

**Files:**
- Create: `src/foundry/kg/memory_retrieval.py`
- Test: `tests/kg/test_memory_retrieval.py`

**Interfaces:**
- Consumes: `Memory` (Task 2/M0 model).
- Produces: `score_memory_item(item: Memory, query_text: str) -> float` — Jaccard-style overlap between the lowercased, whitespace-tokenized word sets of `query_text` and `item.title + " " + item.body_md`; returns `0.0` for no overlap, up to `1.0` for identical token sets. `select_relevant_memory(items: list[Memory], query_text: str, k: int = 5, max_chars: int = 2000) -> list[Memory]` — scores every item, sorts descending by score (ties broken by `created_at` descending — newer wins), drops zero-score items, then greedily includes items up to `k` count **and** `max_chars` cumulative `body_md` length (whichever limit hits first) — the `max_chars` is the concrete stand-in for design doc §10's "~1-2k token budget" (character count as a cheap, dependency-free proxy for token count, documented as such).

- [ ] **Step 1: Write the failing tests**

```python
# tests/kg/test_memory_retrieval.py
import datetime as dt

from foundry.kg.memory_retrieval import score_memory_item, select_relevant_memory
from foundry.store.models import Memory


def _item(title, body, created_offset=0):
    return Memory(
        id=f"m-{title}", scope="project", kind="lesson", title=title, body_md=body,
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(minutes=created_offset),
    )


def test_score_is_zero_for_disjoint_text():
    item = _item("budget pause", "token budgets pause dispatch")
    assert score_memory_item(item, "completely unrelated topic here") == 0.0


def test_score_is_higher_for_more_overlap():
    item_a = _item("budget pause", "token budgets pause dispatch never kill")
    item_b = _item("unrelated", "some other lesson entirely about drivers")
    query = "token budget pause dispatch"
    assert score_memory_item(item_a, query) > score_memory_item(item_b, query)


def test_select_relevant_memory_drops_zero_score_items():
    items = [_item("a", "token budget pause"), _item("b", "completely unrelated")]
    selected = select_relevant_memory(items, "token budget dispatch", k=5)
    assert [i.title for i in selected] == ["a"]


def test_select_relevant_memory_respects_k():
    items = [_item(f"item{i}", "token budget pause dispatch") for i in range(10)]
    selected = select_relevant_memory(items, "token budget pause dispatch", k=3)
    assert len(selected) == 3


def test_select_relevant_memory_respects_max_chars():
    items = [_item(f"item{i}", "token budget pause dispatch " * 50) for i in range(5)]
    selected = select_relevant_memory(items, "token budget pause dispatch", k=10, max_chars=200)
    total_chars = sum(len(i.body_md) for i in selected)
    assert total_chars <= 200 + len(items[0].body_md)  # allows the item that crosses the boundary to be included whole
    assert len(selected) < 5


def test_select_relevant_memory_breaks_ties_by_newest():
    older = _item("older", "token budget pause", created_offset=0)
    newer = _item("newer", "token budget pause", created_offset=10)
    selected = select_relevant_memory([older, newer], "token budget pause", k=1)
    assert selected == [newer]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kg/test_memory_retrieval.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.kg.memory_retrieval'`

- [ ] **Step 3: Write `src/foundry/kg/memory_retrieval.py`**

```python
from __future__ import annotations

import re

from foundry.store.models import Memory

_WORD_RE = re.compile(r"[a-z0-9]+")


def _tokenize(text: str) -> set[str]:
    return set(_WORD_RE.findall(text.lower()))


def score_memory_item(item: Memory, query_text: str) -> float:
    query_tokens = _tokenize(query_text)
    item_tokens = _tokenize(f"{item.title} {item.body_md}")
    if not query_tokens or not item_tokens:
        return 0.0
    intersection = query_tokens & item_tokens
    union = query_tokens | item_tokens
    return len(intersection) / len(union) if union else 0.0


def select_relevant_memory(items: list[Memory], query_text: str, k: int = 5, max_chars: int = 2000) -> list[Memory]:
    scored = [(item, score_memory_item(item, query_text)) for item in items]
    scored = [(item, score) for item, score in scored if score > 0.0]
    scored.sort(key=lambda pair: (pair[1], pair[0].created_at), reverse=True)

    selected: list[Memory] = []
    total_chars = 0
    for item, _score in scored:
        if len(selected) >= k:
            break
        if selected and total_chars >= max_chars:
            break
        selected.append(item)
        total_chars += len(item.body_md)
    return selected
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kg/test_memory_retrieval.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/foundry/kg/memory_retrieval.py tests/kg/test_memory_retrieval.py
git commit -m "feat(kg): keyword-overlap memory retrieval (select_relevant_memory), documented substitute for embedding similarity"
```

---

### Task 5: Context bundle composition in `dispatch()`

**Files:**
- Modify: `src/foundry/orchestrator/tick.py`
- Test: `tests/orchestrator/test_context_bundle.py`

**Interfaces:**
- Consumes: `build_kg`, `blast_radius` (Task 1), `select_relevant_memory` (Task 4), `Store.list_memory_items` (Task 2).
- Produces: `Orchestrator.__init__` gains an optional `kg_snapshot: KGSnapshot | None = None` parameter (built once per orchestrator instance, not per-dispatch — rebuilding the whole project's import graph on every tick would be wasteful; a future task can add cache invalidation on worktree merge per design doc §9, out of scope here). `dispatch()` composes a context bundle for each dispatched unit *before* building `SessionSpec`: resolves the unit's step's declared input file list (from upstream artifacts' `payload_json.get("files", [])` — the only convention this plan defines for "which files did this artifact touch"; artifacts without a `files` field contribute nothing to the blast radius, which is fine, not every artifact kind needs to), computes `blast_radius` if `kg_snapshot` is set, retrieves top relevant memory via `select_relevant_memory` scoped to the run's project, and appends a compact summary onto `SessionSpec.prompt` (extending the existing `f"step:{step.id}"` placeholder convention — real prompt templating doesn't exist yet in this codebase, this plan doesn't invent it either). Emits a new `context.composed` event per dispatch with `{"files_in_bundle": N, "memory_items": M, "bundle_chars": C}` — this is the observability hook Task 7's benchmark reads.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestrator/test_context_bundle.py
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
            StepSpec(id="implement", role="dev", needs=["architecture"], produces="code_diff_artifact", gate="none"),
        ],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    kg_snapshot = build_kg(str((tmp_path / "fixture_project")))
    # Build a minimal on-disk project matching the KG so blast_radius has real data to work with.
    (tmp_path / "fixture_project").mkdir()
    (tmp_path / "fixture_project" / "a.py").write_text("from fixture_project import b\n")
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
        scope="project", kind="lesson", title="implement step lesson",
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_context_bundle.py -v`
Expected: FAIL — `Orchestrator.__init__() got an unexpected keyword argument 'kg_snapshot'`, and no `context.composed` events exist.

- [ ] **Step 3: Wire context bundle composition into `Orchestrator`**

In `src/foundry/orchestrator/tick.py`, extend `__init__`:

```python
    def __init__(
        self,
        store: Store,
        driver: AgentDriver,
        playbook: PlaybookSpec,
        concurrency: int = 5,
        worktree_manager: "WorktreeManager | None" = None,
        project_path: str = ".",
        kg_snapshot: "KGSnapshot | None" = None,
    ):
        self.store = store
        self.driver = driver
        self.playbook = playbook
        self.concurrency = concurrency
        self.worktree_manager = worktree_manager
        self.project_path = project_path
        self.kg_snapshot = kg_snapshot
        self._steps_by_id: dict[str, StepSpec] = {s.id: s for s in playbook.steps}
        self._unit_worktrees: dict[str, str] = {}
```

Add the imports: `from foundry.kg.memory_retrieval import select_relevant_memory` and `from foundry.kg.service import KGSnapshot, blast_radius`.

Add a new private helper method:

```python
    async def _compose_context_bundle(self, run_id: str, task_unit: WorkUnit) -> tuple[list[str], list, int]:
        deps = await self.store.list_deps(run_id)
        needed_ids = {d.needs_unit_id for d in deps if d.unit_id == task_unit.id}
        artifacts = await self.store.list_artifacts(run_id)
        input_files: list[str] = []
        for artifact in artifacts:
            if artifact.work_unit_id in needed_ids:
                input_files.extend(artifact.payload_json.get("files", []))

        bundle_files: set[str] = set(input_files)
        if self.kg_snapshot is not None and input_files:
            bundle_files = blast_radius(self.kg_snapshot, input_files)

        run = await self.store.get_run(run_id)
        memory_items = []
        if run is not None:
            candidates = await self.store.list_memory_items(project_id=run.project_id)
            query_text = " ".join(input_files) + " " + task_unit.step_id
            memory_items = select_relevant_memory(candidates, query_text)

        bundle_chars = sum(len(f) for f in bundle_files) + sum(len(m.body_md) for m in memory_items)
        return sorted(bundle_files), memory_items, bundle_chars
```

In `dispatch()`, right before `spec = SessionSpec(...)` is built, add:

```python
            bundle_files, memory_items, bundle_chars = await self._compose_context_bundle(run_id, task_unit)
            await self.store.append_event(
                run_id,
                session_unit.id,
                "context.composed",
                {
                    "files_in_bundle": len(bundle_files),
                    "memory_items": len(memory_items),
                    "bundle_chars": bundle_chars,
                },
            )
```

Extend the `prompt` field of the existing `SessionSpec(...)` construction (keep every other field exactly as-is):

```python
                prompt=f"step:{step.id} files:{len(bundle_files)} memory:{len(memory_items)}",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_context_bundle.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions (existing tests never pass `kg_snapshot`, so it defaults to `None` and `_compose_context_bundle` degrades to `bundle_files = set(input_files)` with no KG expansion, matching prior behavior for the `context.composed` event's existence without changing anything else)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/orchestrator/tick.py tests/orchestrator/test_context_bundle.py
git commit -m "feat(orchestrator): compose blast-radius + relevant-memory context bundle in dispatch(), emit context.composed"
```

---

### Task 6: Cross-slice interference warning

**Files:**
- Modify: `src/foundry/orchestrator/tick.py`
- Test: `tests/orchestrator/test_interference.py`

**Interfaces:**
- Consumes: `blast_radius` (Task 1), convoy grouping (`WorkUnit.convoy_id`, M2a).
- Produces: a new tick phase `_check_convoy_interference(run_id)` (called once per tick, after `_fan_out`/`_close_convoys`, alongside the other post-fan-out checks) — for each open convoy with 2+ sibling slice units that have each produced an artifact declaring `files`, computes each slice's blast radius (via `self.kg_snapshot`, when set) and checks pairwise overlaps; on any overlap, fires one `convoy.interference_warning` event per convoy (idempotent — only once per convoy, tracked the same way `_dispatch_agent_reviews`/budget events already dedupe via an events-log scan) with `{"convoy_id": ..., "overlapping_slices": [[slice_a_unit_id, slice_b_unit_id], ...], "overlapping_files": [...]}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/orchestrator/test_interference.py
import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.kg.service import build_kg
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.loader import load_playbook
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_interference_warning_fires_when_slices_touch_overlapping_files(tmp_path):
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "shared.py").write_text("X = 1\n")
    (tmp_path / "proj" / "auth.py").write_text("from proj import shared\n")
    (tmp_path / "proj" / "billing.py").write_text("from proj import shared\n")
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_interference.py -v`
Expected: FAIL — no `convoy.interference_warning` event ever fires.

- [ ] **Step 3: Implement `_check_convoy_interference` in `src/foundry/orchestrator/tick.py`**

Wire into `tick()`, after `_close_convoys`:

```python
    async def tick(self, run_id: str) -> TickResult:
        await self.reconcile(run_id)
        await self.apply_gate_decisions(run_id)
        await self.unblock(run_id)
        await self._gate_derived_units(run_id)
        await self._fan_out(run_id)
        await self._close_convoys(run_id)
        await self._check_convoy_interference(run_id)
        dispatched = await self.dispatch(run_id)
        await self._dispatch_agent_reviews(run_id)
        ...  # rest unchanged
```

Add the method:

```python
    async def _check_convoy_interference(self, run_id: str) -> None:
        if self.kg_snapshot is None:
            return

        units = await self.store.list_units(run_id)
        convoys = [u for u in units if u.type == "convoy"]
        events = await self.store.list_events(run_id)
        already_warned = {
            e.payload_json.get("convoy_id") for e in events if e.type == "convoy.interference_warning"
        }
        artifacts = await self.store.list_artifacts(run_id)
        artifacts_by_unit: dict[str, list] = {}
        for a in artifacts:
            artifacts_by_unit.setdefault(a.work_unit_id, []).append(a)

        for convoy in convoys:
            if convoy.id in already_warned:
                continue
            slice_units = [u for u in units if u.convoy_id == convoy.id and u.type == "task"]
            slice_radii: dict[str, set[str]] = {}
            for slice_unit in slice_units:
                slice_artifacts = artifacts_by_unit.get(slice_unit.id, [])
                files: list[str] = []
                for a in slice_artifacts:
                    files.extend(a.payload_json.get("files", []))
                if files:
                    slice_radii[slice_unit.id] = blast_radius(self.kg_snapshot, files)

            overlaps: list[list[str]] = []
            overlapping_files: set[str] = set()
            slice_ids = list(slice_radii.keys())
            for i in range(len(slice_ids)):
                for j in range(i + 1, len(slice_ids)):
                    shared = slice_radii[slice_ids[i]] & slice_radii[slice_ids[j]]
                    if shared:
                        overlaps.append([slice_ids[i], slice_ids[j]])
                        overlapping_files |= shared

            if overlaps:
                await self.store.append_event(
                    run_id,
                    convoy.id,
                    "convoy.interference_warning",
                    {
                        "convoy_id": convoy.id,
                        "overlapping_slices": overlaps,
                        "overlapping_files": sorted(overlapping_files),
                    },
                )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_interference.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/foundry/orchestrator/tick.py tests/orchestrator/test_interference.py
git commit -m "feat(orchestrator): cross-slice blast-radius interference warning for fan-out convoys"
```

---

### Task 7: Token-reduction benchmark

**Files:**
- Test: `tests/kg/test_context_reduction_benchmark.py`

**Interfaces:**
- No new production code — this task is a measurement proving M3's exit criterion (a): "measured token reduction on implement/review steps vs. M2 baseline." Uses this repo's own `src/foundry/` tree as the benchmark corpus (a real, non-trivial, already-available codebase — not a fixture invented for this plan) and a real file from it as the "changed file" input, comparing blast-radius bundle size against "everything" (the pre-M3 baseline behavior, where context composition had no KG and no bound — every file was implicitly in scope since nothing filtered it).

- [ ] **Step 1: Write the benchmark test**

```python
# tests/kg/test_context_reduction_benchmark.py
from pathlib import Path

from foundry.kg.service import blast_radius, build_kg

REPO_ROOT = str(Path(__file__).parent.parent.parent / "src" / "foundry")


def test_blast_radius_context_is_meaningfully_smaller_than_the_whole_tree():
    snapshot = build_kg(REPO_ROOT)
    total_files = len(snapshot.nodes)
    assert total_files > 20, "benchmark corpus (src/foundry) is expected to have grown past a trivial size"

    # orchestrator/tick.py is one of the most central, highest-fan-in files in
    # this codebase (materializer, playbook schema, store, drivers, worktrees,
    # budget, kg all feed into it) — if blast radius stays meaningfully smaller
    # than the whole tree even for this worst-case-central file, it's a
    # representative, non-cherry-picked proof.
    changed = ["orchestrator/tick.py"]
    radius = blast_radius(snapshot, changed, depth=2)

    reduction_ratio = 1 - (len(radius) / total_files)
    assert reduction_ratio > 0.15, (
        f"expected blast radius ({len(radius)} files) to be at least 15% smaller than "
        f"the whole tree ({total_files} files) even for a high-fan-in file; got {reduction_ratio:.2%}"
    )


def test_blast_radius_context_is_much_smaller_for_a_leaf_file():
    snapshot = build_kg(REPO_ROOT)
    total_files = len(snapshot.nodes)

    # orchestrator/budget.py is a small, low-fan-in leaf module (pure function,
    # nothing depends on internal details beyond one check_budget import) —
    # this is the common case a real implement/review step's context should
    # look like: most files are NOT in scope.
    changed = ["orchestrator/budget.py"]
    radius = blast_radius(snapshot, changed, depth=2)

    reduction_ratio = 1 - (len(radius) / total_files)
    assert reduction_ratio > 0.7, (
        f"expected a leaf module's blast radius ({len(radius)} files) to be well under "
        f"30% of the whole tree ({total_files} files); got {reduction_ratio:.2%} reduction"
    )
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/kg/test_context_reduction_benchmark.py -v`
Expected: PASS. If either assertion fails, that's a real, meaningful finding about this repo's actual import coupling — don't lower the threshold to force a pass; investigate whether `blast_radius`'s depth or the resolver in `build_kg` has a bug first (cross-check against Task 1's own tests, which are still the ground truth for correctness), and only adjust the threshold if the measured ratio is genuinely, defensibly different from this plan's assumption after confirming the mechanism itself is correct.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 4: Commit**

```bash
git add tests/kg/test_context_reduction_benchmark.py
git commit -m "test(kg): benchmark proving blast-radius context is meaningfully smaller than the whole tree (M3 exit criterion a)"
```

---

### Task 8: End-to-end memory-compounding proof

**Files:**
- Create: `tests/orchestrator/fixtures/compounding_demo.toml`
- Test: `tests/orchestrator/test_memory_compounding_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1-6. No new production code — proves M3's exit criterion (b): "second run of a similar feature demonstrably references a lesson from the first."

- [ ] **Step 1: Write the fixture playbook**

```toml
# tests/orchestrator/fixtures/compounding_demo.toml
[playbook]
id = "compounding_demo"
description = "implement -> compound: a minimal playbook that writes a lesson every run"

[[step]]
id = "implement"
role = "developer"
produces = "code_diff_artifact"
gate = "none"

[[step]]
id = "compound"
role = "reviewer"
needs = ["implement"]
produces = "memory_items_artifact"
gate = "none"
```

- [ ] **Step 2: Write the end-to-end test**

```python
# tests/orchestrator/test_memory_compounding_e2e.py
import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_second_run_context_bundle_includes_lesson_from_first_run(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/orchestrator/fixtures/compounding_demo.toml")

    # Run 1: implement, then compound distills a lesson about this project's
    # implement step into the Memory table.
    run1 = await store.create_run(project.id, "compounding_demo.toml", "run 1")
    await materialize(playbook, run1.id, store)
    driver1 = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"files": ["auth.py"]}),
            "compound": FakeStepScript(
                artifact={
                    "items": [
                        {
                            "kind": "lesson",
                            "title": "auth.py implement lesson",
                            "body_md": "implement steps touching auth.py must handle token expiry edge cases",
                        }
                    ]
                }
            ),
        }
    )
    orch1 = Orchestrator(store, driver1, playbook)
    for _ in range(4):
        await orch1.tick(run1.id)

    memory_after_run1 = await store.list_memory_items(project_id=project.id)
    assert len(memory_after_run1) == 1

    # Run 2: a similar feature (same project, same playbook, implement again
    # touches auth.py) — its context bundle for the implement dispatch must
    # surface the lesson written by run 1.
    run2 = await store.create_run(project.id, "compounding_demo.toml", "run 2")
    await materialize(playbook, run2.id, store)
    driver2 = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"files": ["auth.py"]}),
            "compound": FakeStepScript(artifact={"items": []}),
        }
    )
    orch2 = Orchestrator(store, driver2, playbook)
    await orch2.tick(run2.id)  # dispatches "implement" — this is the tick whose context.composed we check

    events = await store.list_events(run2.id)
    composed = [e for e in events if e.type == "context.composed"]
    implement_composed = composed[0]
    assert implement_composed.payload_json["memory_items"] >= 1, (
        "run 2's implement dispatch should have surfaced run 1's lesson via project-scoped memory retrieval"
    )
```

- [ ] **Step 3: Run the test**

Run: `uv run pytest tests/orchestrator/test_memory_compounding_e2e.py -v`
Expected: PASS. As with M2a's own Task 10, treat any failure as a real signal to debug against Tasks 1-6's actual implementation, not a reason to weaken the assertion — if `memory_items` is `0`, trace whether `select_relevant_memory`'s scoring genuinely finds no overlap between "implement" (the query text) and the lesson's title/body (which do share real words: "implement", "auth.py" isn't tokenized as one word by the `[a-z0-9]+` regex — note this precisely, since "auth.py" splits into "auth"/"py" tokens, and "implement" itself must appear in both the query and the item text for a nonzero score; if the query text construction in `_compose_context_bundle` doesn't naturally produce that overlap, this is exactly the kind of integration gap Task 10-style tests exist to catch).

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, full suite green

- [ ] **Step 5: Commit**

```bash
git add tests/orchestrator/fixtures/compounding_demo.toml tests/orchestrator/test_memory_compounding_e2e.py
git commit -m "test(orchestrator): end-to-end memory-compounding proof — second run references first run's lesson (M3 exit criterion b)"
```

---

## Out of scope for this plan (tracked, not forgotten)

- **M3b — knowledge view dashboard panel.** A separate plan, written after M3a merges, embedding a KG graph view + memory browser (design doc §11), consuming `context.composed`/`convoy.interference_warning` events and `GET`-style read access to memory this plan produces (M3b, like M2b, may need one or two small new backend read endpoints for memory/KG data the dashboard wants to show — scoped when that plan is written, same pattern as M2b's Task 1).
- **Wrapping the real external `code-review-graph` package.** Not available in this environment; the first-party `src/foundry/kg/` substitute is the permanent v1 implementation, not a placeholder — revisit only if that package becomes available and its capabilities are genuinely needed beyond what this plan's import-graph approach provides.
- **`/internal` HTTP API + shared-secret auth.** Deliberately not built (Global Constraints) — no real consumer exists yet since real driver wiring (`ClaudeCodeDriver`) is still deferred from M0. Build this when a real driver is actually wired up, as part of that milestone's own security-conscious design, not improvised here.
- **KG cache invalidation on worktree merge.** `Orchestrator.kg_snapshot` is built once at orchestrator-construction time and never refreshed mid-run. Design doc §9's "incremental update hooked to worktree merges" is real future work, not silently implied by this plan.
- **Non-Python codebases.** `build_kg` only understands Python `import`/`from` statements via `ast`. Extending to other languages is a natural but unbuilt follow-up.
- **Consolidate/prune job for stale or duplicate memory items** (design doc §10's "periodic `consolidate` job... mirrors rejected-feedback themes into role prompt improvements"). Out of scope — this plan only writes and reads memory, it doesn't curate it.
