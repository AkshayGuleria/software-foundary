# M4a — Packs, Gate Overrides, Project Lifecycle, Event Archival Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend capability design doc §15's M4 milestone calls for — a real pack manifest/loader, the built-in SDLC playbook extracted into shipped pack content (not a test fixture), per-run gate-policy overrides, project lifecycle (pause/archive), and event archival — so a second, genuinely different playbook can be added as pure pack content with zero engine changes (M4's exit criterion a), and a project can be paused/archived. M4b (a separate plan) builds the portfolio-home and pack-viewer dashboard views that consume this milestone's output.

**Architecture:** `src/foundry/packs/` is new (mirrors `src/foundry/kg/`'s M3a precedent — first-party, stdlib-only, no new dependencies). A pack is a directory with a `pack.toml` manifest declaring roles (id + default model — pure config, no prompt templating invented here since none exists anywhere in this codebase yet) and a list of playbook file paths; `load_pack` validates every step across every declared playbook resolves its `role` against a manifest-declared role id, giving packs real validation teeth rather than being purely decorative. Critically, **the existing `load_playbook(path)` / `POST /api/runs` / `foundry run` mechanism is completely unmodified** — a playbook that happens to live inside a pack directory loads exactly the same way any other playbook file always has. This is what makes exit criterion (a)'s "zero engine changes" claim literally true rather than aspirational: the pack system is additive validation/versioning tooling around playbook files, not a new required indirection layer the engine must understand to run one.

**Tech Stack:** Same as M0-M3b — Python 3.12+, stdlib `tomllib` (already used by `playbook/loader.py`), SQLAlchemy 2 async, Pydantic v2, pytest + pytest-asyncio, ruff, Typer (for the new CLI command). No new runtime dependencies.

## Global Constraints

- **No prompt templating is invented.** Design doc §3 describes a `Role` as "prompt template + provider + model + tool scope," but no milestone so far has built real prompt rendering — `SessionSpec.prompt` is still the placeholder string convention established in M0 and lightly extended in M3a (`f"step:{step.id} files:{N} memory:{M}"`). This plan's `RoleSpec` is deliberately minimal (`id`, `model`) — enough for `load_pack` to validate that every step's `role` resolves to something real, without inventing a prompt-template format nothing consumes yet. Extending `RoleSpec` with actual prompt templates is real future work for whenever prompt rendering itself gets built.
- **"Chat-to-role" is not built.** Design doc's M4 roadmap text mentions it, but it depends on the `notes_addressed`/chat contract design doc §8 describes — already explicitly deferred since M1a ("no `POST /api/runs/{id}/chat` exists yet... deferred it") and never picked up in M1b, M2b, or M3b either. This plan doesn't pick it up now; still tracked as a standing deferral, not silently dropped.
- **Project pause/archive only gates NEW run creation for that project; it does not reach into already-registered/ticking runs.** Design doc §3 says a project has a lifecycle (`active → paused → archived`), but doesn't specify what happens to a run already in flight when its project pauses mid-run. Rather than guess at that design (kill it? let it finish? block new dispatch only?), this plan scopes pause/archive to exactly what's unambiguous: `POST /api/runs` refuses to create a new run for a non-active project (`ConflictError`), and that's the whole behavioral contract for now. What an in-flight run should do when its project pauses is flagged as a real follow-up question, not answered here.
- **Cross-project fair scheduling is already covered by M2a's `GlobalDispatchLimiter`+`Scheduler.tick_all_once` ordering** (least-recently-ticked-project-first). M2a's own final review already found and documented that this limiter is fairness-*ordering*-only, not a real concurrency ceiling, because `Orchestrator.dispatch()` is fully synchronous end-to-end — there's no actual concurrent overlap for a cap to prevent yet. That finding is unchanged by this plan; M4 doesn't need to build a second fairness mechanism on top of an already-correct-for-today one.
- **Event archival writes gzip-compressed JSONL and prunes the hot table — no scheduled/cron execution.** Design doc §6 describes "events for closed runs are archived... after N days (default 30) and pruned from the hot table." This plan builds the archival OPERATION (a `Store` method + a CLI command an operator or an external cron can invoke), not a background scheduler that runs it automatically — matching this project's existing "CLI-only surface where nothing requires a live daemon" pattern (`foundry serve`'s own background scheduler is the one exception, and it's explicitly for run dispatch, not archival).
- Every new/changed backend file lives under `src/foundry/` (new `src/foundry/packs/` module) or the new top-level `packs/` content directory (sibling to `src/`, matching `frontend/`'s precedent of a top-level non-`src` directory for a distinct concern) or `tests/`.

---

### Task 1: Pack schema + loader

**Files:**
- Create: `src/foundry/packs/__init__.py`
- Create: `src/foundry/packs/schema.py`
- Create: `src/foundry/packs/loader.py`
- Test: `tests/packs/__init__.py`, `tests/packs/test_loader.py`
- Test fixtures: `tests/packs/fixtures/valid_pack/` (small synthetic pack for isolated unit tests)

**Interfaces:**
- Produces: `RoleSpec` (Pydantic: `id: str`, `model: str = "fake"`). `PackManifest` (Pydantic: `id: str`, `version: str`, `roles: list[RoleSpec]`, `playbooks: list[str]` — paths relative to the pack directory). `class PackLoadError(Exception)`. `load_pack(pack_dir: str) -> PackManifest` — reads `pack.toml` from `pack_dir`, parses it into `PackManifest`, then loads every playbook file it references (via the existing, unmodified `foundry.playbook.loader.load_playbook`) and validates every step's `role` field resolves against a role id declared in `manifest.roles`; raises `PackLoadError` on any missing file, malformed manifest, or unresolved role reference.

- [ ] **Step 1: Write the fixture pack and failing tests**

```toml
# tests/packs/fixtures/valid_pack/pack.toml
[pack]
id = "test_pack"
version = "0.1.0"

[[role]]
id = "dev"
model = "fake"

[[role]]
id = "reviewer"
model = "fake"

playbooks = ["playbooks/simple.toml"]
```

```toml
# tests/packs/fixtures/valid_pack/playbooks/simple.toml
[playbook]
id = "simple"
description = "a trivial playbook for pack-loader tests"

[[step]]
id = "implement"
role = "dev"
produces = "code_diff_artifact"
gate = "none"

[[step]]
id = "review"
role = "reviewer"
needs = ["implement"]
produces = "review_artifact"
gate = "none"
```

```toml
# tests/packs/fixtures/invalid_role_pack/pack.toml
[pack]
id = "bad_pack"
version = "0.1.0"

[[role]]
id = "dev"
model = "fake"

playbooks = ["playbooks/unresolved.toml"]
```

```toml
# tests/packs/fixtures/invalid_role_pack/playbooks/unresolved.toml
[playbook]
id = "unresolved"

[[step]]
id = "a"
role = "nonexistent_role"
produces = "x"
gate = "none"
```

```python
# tests/packs/test_loader.py
from pathlib import Path

import pytest

from foundry.packs.loader import PackLoadError, load_pack

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_pack_parses_manifest_and_playbooks():
    manifest = load_pack(str(FIXTURES / "valid_pack"))
    assert manifest.id == "test_pack"
    assert manifest.version == "0.1.0"
    assert {r.id for r in manifest.roles} == {"dev", "reviewer"}
    assert manifest.playbooks == ["playbooks/simple.toml"]


def test_load_pack_rejects_unresolved_role():
    with pytest.raises(PackLoadError, match="nonexistent_role"):
        load_pack(str(FIXTURES / "invalid_role_pack"))


def test_load_pack_missing_manifest_raises():
    with pytest.raises(PackLoadError, match="pack.toml"):
        load_pack(str(FIXTURES / "does_not_exist"))


def test_load_pack_missing_referenced_playbook_raises(tmp_path):
    (tmp_path / "pack.toml").write_text(
        '[pack]\nid = "p"\nversion = "0.1.0"\n\n[[role]]\nid = "dev"\n\nplaybooks = ["playbooks/missing.toml"]\n'
    )
    with pytest.raises(PackLoadError, match="missing.toml"):
        load_pack(str(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/packs/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.packs'`

- [ ] **Step 3: Write `src/foundry/packs/schema.py`**

```python
from __future__ import annotations

from pydantic import BaseModel


class RoleSpec(BaseModel):
    id: str
    model: str = "fake"


class PackManifest(BaseModel):
    id: str
    version: str
    roles: list[RoleSpec]
    playbooks: list[str]
```

- [ ] **Step 4: Write `src/foundry/packs/loader.py`**

```python
from __future__ import annotations

import tomllib
from pathlib import Path

from foundry.packs.schema import PackManifest, RoleSpec
from foundry.playbook.loader import PlaybookLoadError, load_playbook


class PackLoadError(Exception):
    pass


def load_pack(pack_dir: str) -> PackManifest:
    root = Path(pack_dir)
    manifest_path = root / "pack.toml"
    if not manifest_path.exists():
        raise PackLoadError(f"pack.toml not found under {pack_dir!r}")

    with open(manifest_path, "rb") as f:
        data = tomllib.load(f)

    pack_meta = data.get("pack", {})
    if "id" not in pack_meta or "version" not in pack_meta:
        raise PackLoadError(f"pack.toml at {manifest_path} must declare [pack] id and version")

    roles = [RoleSpec(**raw_role) for raw_role in data.get("role", [])]
    playbooks = data.get("playbooks", [])

    manifest = PackManifest(id=pack_meta["id"], version=pack_meta["version"], roles=roles, playbooks=playbooks)

    role_ids = {r.id for r in manifest.roles}
    for rel_path in manifest.playbooks:
        playbook_path = root / rel_path
        if not playbook_path.exists():
            raise PackLoadError(f"pack {manifest.id!r} references missing playbook file: {rel_path!r}")
        try:
            playbook = load_playbook(str(playbook_path))
        except PlaybookLoadError as e:
            raise PackLoadError(f"pack {manifest.id!r}: playbook {rel_path!r} failed to load: {e}") from e

        for step in playbook.steps:
            if step.role not in role_ids:
                raise PackLoadError(
                    f"pack {manifest.id!r}: playbook {rel_path!r} step {step.id!r} references "
                    f"undeclared role {step.role!r} (declared roles: {sorted(role_ids)})"
                )

    return manifest
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/packs/test_loader.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 7: Commit**

```bash
git add src/foundry/packs/ tests/packs/
git commit -m "feat(packs): pack manifest schema + loader with role-reference validation"
```

---

### Task 2: Default pack — extract the built-in SDLC playbook

**Files:**
- Create: `packs/default/pack.toml`
- Create: `packs/default/playbooks/sdlc_story.toml`
- Test: `tests/packs/test_default_pack.py`

**Interfaces:**
- Consumes: `load_pack` (Task 1).
- Produces: `packs/default/` — the first real, shipped (non-test-fixture) pack content in this repo, at the top level (sibling to `src/`, `frontend/`, `tests/`), matching design doc §3's framing of "the deployment's root pack is the 'factory'." Contains a real SDLC-shaped playbook (requirement → architecture + test_plan → plan_approval → implement (fan_out) → review (agent-review loop) → integrate) adapted from design doc §5.1's own sketch, using every engine capability already built (fan-out, agent-review loop, escalation) rather than a simplified toy — this is deliberately the most complete, realistic playbook in the whole repo, not another minimal test fixture.

- [ ] **Step 1: Write the failing test**

```python
# tests/packs/test_default_pack.py
from foundry.packs.loader import load_pack


def test_default_pack_loads_without_error():
    manifest = load_pack("packs/default")
    assert manifest.id == "default"
    assert "playbooks/sdlc_story.toml" in manifest.playbooks


def test_default_pack_sdlc_story_uses_fan_out_and_review_loop():
    from foundry.playbook.loader import load_playbook

    playbook = load_playbook("packs/default/playbooks/sdlc_story.toml")
    steps_by_id = {s.id: s for s in playbook.steps}
    assert steps_by_id["implement"].fan_out is not None
    assert steps_by_id["review"].fan_out_from == "implement"
    assert steps_by_id["review"].loop is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/packs/test_default_pack.py -v`
Expected: FAIL — `packs/default` doesn't exist yet.

- [ ] **Step 3: Write `packs/default/pack.toml`**

```toml
[pack]
id = "default"
version = "0.1.0"

[[role]]
id = "product_owner"
model = "fake"

[[role]]
id = "architect"
model = "fake"

[[role]]
id = "qa"
model = "fake"

[[role]]
id = "developer"
model = "fake"

[[role]]
id = "reviewer"
model = "fake"

[[role]]
id = "integrator"
model = "fake"

playbooks = ["playbooks/sdlc_story.toml"]
```

- [ ] **Step 4: Write `packs/default/playbooks/sdlc_story.toml`**

```toml
[playbook]
id = "sdlc_story"
description = "Story: requirement -> plan -> sliced implementation -> review -> integrate"

[[step]]
id = "requirement"
role = "product_owner"
produces = "requirement_artifact"
gate = "human"

[[step]]
id = "architecture"
role = "architect"
needs = ["requirement"]
produces = "architecture_artifact"
gate = "human"

[[step]]
id = "test_plan"
role = "qa"
needs = ["requirement"]
produces = "test_plan_artifact"
gate = "human"

[[step]]
id = "plan_approval"
type = "derived_gate"
needs = ["requirement", "architecture", "test_plan"]

[[step]]
id = "implement"
role = "developer"
needs = ["plan_approval"]
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
loop = { back_to = "implement", max_rounds = 5 }

[[step]]
id = "integrate"
role = "integrator"
needs = ["review"]
produces = "integration_artifact"
gate = "human"
escalates_on = "escalated"
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/packs/test_default_pack.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Run the full suite (also confirms `lint_plan_first` accepts this real playbook)**

Run: `uv run pytest -q`
Expected: PASS. Additionally run `uv run python -c "from foundry.playbook.loader import load_playbook; from foundry.playbook.lint import lint_plan_first; lint_plan_first(load_playbook('packs/default/playbooks/sdlc_story.toml')); print('lint OK')"` to confirm the shipped playbook itself passes the plan-first lint (every `writes=true` step downstream of a `derived_gate`) — `implement` has `writes = true` and is downstream of `plan_approval`, so this should print `lint OK` with no exception.

- [ ] **Step 7: Commit**

```bash
git add packs/ tests/packs/test_default_pack.py
git commit -m "feat(packs): extract the built-in SDLC playbook into a real, shipped default pack"
```

---

### Task 3: Second pack playbook (bug-fix) — proves exit criterion (a)

**Files:**
- Create: `packs/default/playbooks/bugfix.toml`
- Modify: `packs/default/pack.toml` (add the new playbook to the `playbooks` list)
- Test: `tests/packs/test_default_pack.py` (extend)

**Interfaces:**
- Consumes: nothing new — this task adds pure pack content plus one line in the manifest's `playbooks` list. It touches **zero files under `src/foundry/`**, which is the literal proof of M4's exit criterion (a): "a second, different playbook... added purely as pack content — zero engine changes."
- Produces: `packs/default/playbooks/bugfix.toml` — a genuinely different playbook shape from `sdlc_story.toml` (design doc's own example: "a 'bug fix' with a diagnose step"), no fan-out, a linear diagnose → fix → review chain, ungated except the final review, proving the pack/engine boundary holds for a structurally different playbook, not just a copy of the first one.

- [ ] **Step 1: Add the failing test**

```python
# append to tests/packs/test_default_pack.py
from foundry.playbook.loader import load_playbook


def test_default_pack_includes_bugfix_playbook():
    manifest = load_pack("packs/default")
    assert "playbooks/bugfix.toml" in manifest.playbooks


def test_bugfix_playbook_has_a_diagnose_step_and_no_fan_out():
    playbook = load_playbook("packs/default/playbooks/bugfix.toml")
    steps_by_id = {s.id: s for s in playbook.steps}
    assert "diagnose" in steps_by_id
    assert all(s.fan_out is None for s in playbook.steps)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/packs/test_default_pack.py -v`
Expected: FAIL — `bugfix.toml` doesn't exist, and it's not yet in the manifest's `playbooks` list.

- [ ] **Step 3: Write `packs/default/playbooks/bugfix.toml`**

The final file's dependency chain must be `diagnose` → `diagnose_approval` (`derived_gate`) → `fix` (`writes = true`) → `review`, not a chain where `fix` depends directly on `diagnose`'s `human` gate — a bare `human` gate does not satisfy the plan-first invariant (`src/foundry/playbook/lint.py`'s `lint_plan_first` requires every `writes=true` step be transitively downstream of a `derived_gate`), so a `derived_gate` step is required to make this playbook actually runnable, not just loadable:

```toml
[playbook]
id = "bugfix"
description = "Bug fix: diagnose -> fix -> review, no fan-out, a structurally different shape from sdlc_story"

[[step]]
id = "diagnose"
role = "developer"
produces = "diagnosis_artifact"
gate = "human"

[[step]]
id = "diagnose_approval"
type = "derived_gate"
needs = ["diagnose"]

[[step]]
id = "fix"
role = "developer"
needs = ["diagnose_approval"]
produces = "code_diff_artifact"
gate = "none"
writes = true

[[step]]
id = "review"
role = "reviewer"
needs = ["fix"]
produces = "review_artifact"
gate = "human"
```

- [ ] **Step 4: Update `packs/default/pack.toml`'s `playbooks` list**

```toml
playbooks = ["playbooks/sdlc_story.toml", "playbooks/bugfix.toml"]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/packs/test_default_pack.py -v`
Expected: PASS (4 tests total: 2 from Task 2 + 2 new)

- [ ] **Step 6: Confirm the plan-first lint passes on the file**

Run: `uv run python -c "from foundry.playbook.loader import load_playbook; from foundry.playbook.lint import lint_plan_first; lint_plan_first(load_playbook('packs/default/playbooks/bugfix.toml')); print('lint OK')"`
Expected: prints `lint OK`

- [ ] **Step 7: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git add packs/default/pack.toml packs/default/playbooks/bugfix.toml tests/packs/test_default_pack.py
git commit -m "feat(packs): add bugfix playbook as pure pack content (M4 exit criterion a)"
```

---

### Task 4: Wire `pack_version_pin` into run creation

**Files:**
- Create: `src/foundry/packs/resolve.py`
- Modify: `src/foundry/api/routes/runs.py`
- Modify: `src/foundry/cli.py` (`run` command)
- Test: `tests/packs/test_resolve.py`, extend `tests/api/test_runs.py`

**Interfaces:**
- Produces: `resolve_pack_version(playbook_path: str) -> str` (`src/foundry/packs/resolve.py`) — walks up from `playbook_path`'s directory looking for a `pack.toml`; if found, loads it via `load_pack` and returns `f"{manifest.id}@{manifest.version}"`; if no `pack.toml` is found within a bounded number of parent directories (cap at 5 to avoid walking to filesystem root on a path with no pack), returns the literal string `"local"` (matching `Run.pack_version_pin`'s existing default). `POST /api/runs` and `foundry run` both call this and pass the result to `Store.create_run`, which gains a new optional `pack_version_pin: str = "local"` parameter.

- [ ] **Step 1: Write the failing tests**

```python
# tests/packs/test_resolve.py
from foundry.packs.resolve import resolve_pack_version


def test_resolve_pack_version_finds_pack_toml_in_parent_dir():
    pin = resolve_pack_version("packs/default/playbooks/sdlc_story.toml")
    assert pin == "default@0.1.0"


def test_resolve_pack_version_returns_local_when_no_pack_toml(tmp_path):
    playbook_file = tmp_path / "standalone.toml"
    playbook_file.write_text('[playbook]\nid = "x"\n')
    assert resolve_pack_version(str(playbook_file)) == "local"


def test_resolve_pack_version_returns_local_for_nonexistent_path():
    assert resolve_pack_version("/does/not/exist.toml") == "local"
```

First read `src/foundry/api/routes/runs.py`'s current `RunOut` model and `create_run` handler in full (both already known from prior research this session: `RunOut` has no `pack_version_pin` field yet; the handler does `title = body.title or playbook.description or playbook.id` then `run = await store.create_run(project.id, body.playbook_path, title)`), then add ONE new test appended to `tests/api/test_runs.py`:

```python
# append to tests/api/test_runs.py
import pytest


@pytest.mark.asyncio
async def test_create_run_pins_pack_version_when_playbook_is_pack_content(api_client):
    client, store, _scheduler = api_client
    project = await store.create_project("demo", ".")
    resp = await client.post(
        "/api/runs",
        json={"project_id": project.id, "playbook_path": "packs/default/playbooks/sdlc_story.toml"},
    )
    assert resp.status_code == 201
    assert resp.json()["data"]["pack_version_pin"] == "default@0.1.0"
```

(If `tests/api/test_runs.py` does not already have an `api_client` fixture with this exact shape, read the file's existing tests first and match whatever fixture name/shape they actually use instead of inventing a new one.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/packs/test_resolve.py tests/api/test_runs.py -v`
Expected: FAIL — `ModuleNotFoundError` for `resolve.py`, and a `KeyError`/`None` mismatch for the new API test.

- [ ] **Step 3: Write `src/foundry/packs/resolve.py`**

```python
from __future__ import annotations

from pathlib import Path

from foundry.packs.loader import PackLoadError, load_pack

_MAX_PARENT_WALK = 5


def resolve_pack_version(playbook_path: str) -> str:
    try:
        current = Path(playbook_path).resolve().parent
    except OSError:
        return "local"

    for _ in range(_MAX_PARENT_WALK):
        if (current / "pack.toml").exists():
            try:
                manifest = load_pack(str(current))
            except PackLoadError:
                return "local"
            return f"{manifest.id}@{manifest.version}"
        if current.parent == current:
            break
        current = current.parent

    return "local"
```

- [ ] **Step 4: Wire it into `Store.create_run`, `POST /api/runs`, and `foundry run`**

In `src/foundry/store/store.py`, extend `create_run`:

```python
    async def create_run(self, project_id: str, playbook_ref: str, title: str, pack_version_pin: str = "local") -> Run:
        async def _op(session):
            run = Run(project_id=project_id, playbook_ref=playbook_ref, title=title, pack_version_pin=pack_version_pin)
            session.add(run)
            await session.flush()
            return run

        return await self.write(_op)
```

In `src/foundry/api/routes/runs.py`, add `pack_version_pin: str` to `RunOut`, update `_to_run_out` (or whatever the file's existing serialization helper is named — read it first) to include `pack_version_pin=r.pack_version_pin`, import `resolve_pack_version` from `foundry.packs.resolve`, and update `create_run`'s handler:

```python
    pack_version_pin = resolve_pack_version(body.playbook_path)
    run = await store.create_run(project.id, body.playbook_path, title, pack_version_pin=pack_version_pin)
```

In `src/foundry/cli.py`'s `_run` function: add `from foundry.packs.resolve import resolve_pack_version` to the file's top-level imports (alongside the existing imports, matching this file's existing style — not an inline import inside the function), then inside `_run`:

```python
    pack_version_pin = resolve_pack_version(playbook_path)
    project = await store.create_project(playbook.id, project_path)
    run_row = await store.create_run(project.id, playbook_path, playbook.description or playbook.id, pack_version_pin=pack_version_pin)
```

(Match this to `_run`'s actual existing variable names for `project`/`run_row` — read the current function body first since this plan's earlier research summarized its shape but did not capture every local variable name verbatim.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/packs/test_resolve.py tests/api/test_runs.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions (existing runs created against non-pack playbook paths get `pack_version_pin="local"`, matching the pre-existing default — no behavior change for any existing test)

- [ ] **Step 7: Commit**

```bash
git add src/foundry/packs/resolve.py src/foundry/store/store.py src/foundry/api/routes/runs.py src/foundry/cli.py \
        tests/packs/test_resolve.py tests/api/test_runs.py
git commit -m "feat(packs): resolve and pin a run's pack version at creation time"
```

---

### Task 5: Per-run gate-policy overrides

**Files:**
- Modify: `src/foundry/store/models.py` (add `Run.gate_overrides_json`)
- Modify: `src/foundry/orchestrator/tick.py`
- Modify: `src/foundry/api/routes/runs.py`
- Modify: `src/foundry/api/scheduler.py`
- Test: `tests/orchestrator/test_gate_overrides.py`, extend `tests/api/test_runs.py`

**Interfaces:**
- Produces: `Run.gate_overrides_json: dict[str, str]` (new column, default `{}`) — maps `step_id -> "approved"|"rejected"`, recorded at run creation for audit per design doc §5.3 ("recorded in the event log for audit"). `Orchestrator.__init__` gains `gate_overrides: dict[str, str] | None = None` (alongside the existing `kg_snapshot`/`worktree_manager` params from M3a — read the current constructor signature first). In `_collect()`'s gated-artifact branch, right after a gate is created for a step whose id is in `gate_overrides`, the engine immediately calls `store.decide_gate(gate.id, gate_overrides[step.id], decided_by="run_override")` and fires a `gate.policy_overridden` event — the gate still exists (visible in the dashboard, auditable), it's just pre-decided instead of left pending. `POST /api/runs`'s `RunCreate` gains an optional `gate_overrides: dict[str, str] | None = None` field, persisted onto the `Run` row and passed through `Scheduler.register` to the `Orchestrator`.

- [ ] **Step 1: Read the current `_collect()` gated-artifact branch and `Orchestrator.__init__` verbatim**

Read `src/foundry/orchestrator/tick.py` in full before editing — the M3a/M3b work added `kg_snapshot` and `worktree_manager` params and this task must match their exact existing pattern (constructor param name, storage as `self.x = x`, defaulting) rather than guessing at it.

- [ ] **Step 2: Write the failing tests**

```python
# tests/orchestrator/test_gate_overrides.py
import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.materializer import materialize
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_gate_override_auto_approves_without_leaving_gate_pending(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(id="p", steps=[StepSpec(id="test_plan", role="qa", produces="test_plan_artifact", gate="human")])
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    orch = Orchestrator(
        store, FakeDriver({"test_plan": FakeStepScript(artifact={})}), playbook,
        gate_overrides={"test_plan": "approved"},
    )
    await orch.tick(run.id)
    await orch.tick(run.id)  # apply_gate_decisions picks up the pre-decided gate

    units = await store.list_units(run.id)
    unit = next(u for u in units if u.step_id == "test_plan")
    assert unit.status == "closed"

    gates = await store.list_gates_for_run(run.id)
    gate = next(g for g in gates if g.work_unit_id == unit.id)
    assert gate.decision == "approved"
    assert gate.decided_by == "run_override"

    events = await store.list_events(run.id)
    assert any(e.type == "gate.policy_overridden" for e in events)


@pytest.mark.asyncio
async def test_no_override_leaves_gate_pending_as_before(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = PlaybookSpec(id="p", steps=[StepSpec(id="test_plan", role="qa", produces="test_plan_artifact", gate="human")])
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    orch = Orchestrator(store, FakeDriver({"test_plan": FakeStepScript(artifact={})}), playbook)
    await orch.tick(run.id)

    gates = await store.list_gates_for_run(run.id)
    assert gates[0].decision == "pending"
```

(If `PlaybookSpec`/`StepSpec` field names differ slightly from what's shown here, match whatever `src/foundry/playbook/schema.py` actually declares — read it if unsure rather than guessing.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_gate_overrides.py -v`
Expected: FAIL — `Orchestrator.__init__() got an unexpected keyword argument 'gate_overrides'`

- [ ] **Step 4: Add `gate_overrides_json` to the `Run` model**

In `src/foundry/store/models.py`'s `Run` class, add (matching the column style of the file's existing `JSON`-typed columns, e.g. `manifest_json` on `Pack`):

```python
    gate_overrides_json: Mapped[dict] = mapped_column(JSON, default=dict)
```

- [ ] **Step 5: Wire `gate_overrides` into `Orchestrator`**

Extend `__init__` with `gate_overrides: dict[str, str] | None = None`, storing `self.gate_overrides = gate_overrides or {}`. In `_collect()`, immediately after the existing gate-creation code (`gate = await self.store.create_gate(...)`, `await self.store.update_unit(task_unit.id, status="blocked")`, `await self.store.append_event(run_id, task_unit.id, "gate.created", ...)`), add:

```python
            if step.id in self.gate_overrides:
                override_decision = self.gate_overrides[step.id]
                await self.store.decide_gate(gate.id, override_decision, decided_by="run_override")
                await self.store.append_event(
                    run_id, task_unit.id, "gate.policy_overridden",
                    {"gate_id": gate.id, "decision": override_decision},
                )
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_gate_overrides.py -v`
Expected: PASS (2 tests)

- [ ] **Step 7: Wire `gate_overrides` through the API**

Read `src/foundry/api/scheduler.py`'s current `Scheduler.register` signature in full first (it already accepts extra params from M2a/M3a — match its existing pattern exactly). Add `gate_overrides: dict[str, str] | None = None`, passed through to the `Orchestrator` it constructs.

In `src/foundry/api/routes/runs.py`: add `gate_overrides: dict[str, str] | None = None` to `RunCreate`; after `run = await store.create_run(...)`, if `body.gate_overrides` is set, call `await store.update_run(run.id, gate_overrides_json=body.gate_overrides)`. Update `create_run`'s handler to pass `body.gate_overrides` into `scheduler.register(...)`.

```python
# append to tests/api/test_runs.py
@pytest.mark.asyncio
async def test_create_run_with_gate_overrides_persists_and_applies_them(api_client):
    client, store, _scheduler = api_client
    project = await store.create_project("demo2", ".")
    resp = await client.post(
        "/api/runs",
        json={
            "project_id": project.id,
            "playbook_path": "packs/default/playbooks/bugfix.toml",
            "gate_overrides": {"diagnose": "approved"},
        },
    )
    assert resp.status_code == 201
    run_id = resp.json()["data"]["id"]
    run_row = await store.get_run(run_id)
    assert run_row.gate_overrides_json == {"diagnose": "approved"}
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 9: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 10: Commit**

```bash
git add src/foundry/store/models.py src/foundry/orchestrator/tick.py src/foundry/api/routes/runs.py \
        src/foundry/api/scheduler.py tests/orchestrator/test_gate_overrides.py tests/api/test_runs.py
git commit -m "feat(orchestrator): per-run gate-policy overrides, recorded for audit"
```

---

### Task 6: Project lifecycle (pause/archive)

**Files:**
- Modify: `src/foundry/store/models.py` (add `Project.status`)
- Modify: `src/foundry/store/store.py` (add `update_project`)
- Modify: `src/foundry/api/routes/projects.py`
- Modify: `src/foundry/api/routes/runs.py` (refuse run creation for non-active projects)
- Test: `tests/api/test_projects.py` (extend)

**Interfaces:**
- Produces: `Project.status: str = "active"` (new column — `active`/`paused`/`archived`). `Store.update_project(project_id, **fields) -> None` (mirrors the existing `update_run`'s kwargs-based-updater pattern exactly — read `update_run` first and match its structure, including its `ValueError` guard for a missing row). `POST /api/projects/{id}/pause`, `POST /api/projects/{id}/archive`, `POST /api/projects/{id}/activate` — each validates the transition is meaningful (`ConflictError` if already in the target state) and returns the updated `ProjectOut` (which gains a `status` field). `POST /api/runs` gains a check: if the target project's `status != "active"`, raise `ConflictError` before creating anything.

- [ ] **Step 1: Read `src/foundry/api/routes/projects.py` and `Store.update_run` in full**

Confirm the exact existing `ProjectOut` shape, the file's serialization helper name, its `ApiResponse[...]`/`Paging` import pattern, and `update_run`'s exact body, before writing new code that must match them.

- [ ] **Step 2: Write the failing tests**

```python
# append to tests/api/test_projects.py
import pytest


@pytest.mark.asyncio
async def test_pause_then_activate_project(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo", "path": "."})
    project_id = resp.json()["data"]["id"]

    resp = await client.post(f"/api/projects/{project_id}/pause")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "paused"

    resp = await client.post(f"/api/projects/{project_id}/activate")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_pausing_an_already_paused_project_409s(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo2", "path": "."})
    project_id = resp.json()["data"]["id"]
    await client.post(f"/api/projects/{project_id}/pause")

    resp = await client.post(f"/api/projects/{project_id}/pause")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_archive_project(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo3", "path": "."})
    project_id = resp.json()["data"]["id"]

    resp = await client.post(f"/api/projects/{project_id}/archive")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "archived"


@pytest.mark.asyncio
async def test_creating_a_run_for_a_paused_project_409s(api_client):
    client, store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo4", "path": "."})
    project_id = resp.json()["data"]["id"]
    await client.post(f"/api/projects/{project_id}/pause")

    resp = await client.post(
        "/api/runs", json={"project_id": project_id, "playbook_path": "packs/default/playbooks/bugfix.toml"}
    )
    assert resp.status_code == 409
```

(Match `api_client`, request/response JSON shapes to whatever `tests/api/test_projects.py` already uses — read it first.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_projects.py -v`
Expected: FAIL — 404s for the new routes, which don't exist yet.

- [ ] **Step 4: Add `Project.status` and `Store.update_project`**

In `src/foundry/store/models.py`'s `Project` class:

```python
    status: Mapped[str] = mapped_column(String, default="active")
```

In `src/foundry/store/store.py`, matching `update_run`'s exact existing structure:

```python
    async def update_project(self, project_id: str, **fields) -> None:
        async def _op(session):
            project = await session.get(Project, project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            for key, value in fields.items():
                setattr(project, key, value)

        await self.write(_op)
```

- [ ] **Step 5: Add the lifecycle routes to `src/foundry/api/routes/projects.py`**

Add `status: str` to `ProjectOut`, update its serialization helper to include `status=p.status`. Add (matching the file's actual existing imports/error-class names — confirm `ConflictError`'s import path from Step 1's read; it is already used in `runs.py`):

```python
async def _transition_project(request: Request, project_id: str, target_status: str) -> ApiResponse[ProjectOut]:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")
    if project.status == target_status:
        raise ConflictError(f"Project {project_id} is already {target_status}")
    await store.update_project(project_id, status=target_status)
    project = await store.get_project(project_id)
    return ApiResponse[ProjectOut](data=_to_project_out(project), paging=Paging.none())


@router.post("/projects/{project_id}/pause")
async def pause_project(project_id: str, request: Request) -> ApiResponse[ProjectOut]:
    return await _transition_project(request, project_id, "paused")


@router.post("/projects/{project_id}/archive")
async def archive_project(project_id: str, request: Request) -> ApiResponse[ProjectOut]:
    return await _transition_project(request, project_id, "archived")


@router.post("/projects/{project_id}/activate")
async def activate_project(project_id: str, request: Request) -> ApiResponse[ProjectOut]:
    return await _transition_project(request, project_id, "active")
```

(`_get_store`/`_to_project_out`/`Paging.none()` are placeholder names for whatever this file's actual existing helpers are called — use the real ones found in Step 1's read, not these literal names if they differ.)

- [ ] **Step 6: Wire the active-project check into `POST /api/runs`**

In `src/foundry/api/routes/runs.py`'s `create_run` handler, right after the existing `project is None` check:

```python
    if project.status != "active":
        raise ConflictError(f"Project {body.project_id} is not active (status: {project.status})")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_projects.py -v`
Expected: PASS (all tests, including the 4 new ones)

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions (every existing test creates projects that stay `active` by default, so the new run-creation check never fires for them)

- [ ] **Step 9: Commit**

```bash
git add src/foundry/store/models.py src/foundry/store/store.py src/foundry/api/routes/projects.py \
        src/foundry/api/routes/runs.py tests/api/test_projects.py
git commit -m "feat(projects): pause/archive/activate lifecycle, refuse new runs for non-active projects"
```

---

### Task 7: Event archival + compaction

**Files:**
- Modify: `src/foundry/store/store.py`
- Modify: `src/foundry/cli.py`
- Test: `tests/store/test_archival.py`, `tests/test_cli.py` (extend)

**Interfaces:**
- Produces: `Store.list_closed_runs_older_than(days: int) -> list[Run]` — runs with `status in ("closed", "cancelled", "failed")` and `closed_at` older than `days` ago. `Store.archive_run_events(run_id: str, archive_dir: str) -> str` — writes all of a run's events to a gzip-compressed JSONL file at `{archive_dir}/{run_id}.jsonl.gz` (one JSON object per line, same field shape as `Event`), then deletes those rows from the hot `events` table; returns the archive file's path. `foundry archive-events --db ... --archive-dir ... --older-than-days 30` (Typer command) — finds eligible runs via `list_closed_runs_older_than`, archives each, prints one line per archived run.

- [ ] **Step 1: Read `Event`'s model fields and any existing `closed_at`-setting call site (e.g. `cancel_run`) in full**

Confirms exact `Event` column names for the JSONL serialization, and confirms which terminal-status transitions actually set `closed_at` today (needed so `list_closed_runs_older_than` filters correctly against real data, not assumed data).

- [ ] **Step 2: Write the failing tests**

```python
# tests/store/test_archival.py
import datetime
import gzip
import json

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
async def test_archive_run_events_writes_gzip_jsonl_and_prunes_hot_table(tmp_path):
    store = await _store(tmp_path)
    project = await store.create_project("demo", str(tmp_path))
    run = await store.create_run(project.id, "p.toml", "demo")
    await store.append_event(run.id, None, "run.created", {"x": 1})
    await store.append_event(run.id, None, "run.closed", {"y": 2})

    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    path = await store.archive_run_events(run.id, str(archive_dir))

    assert path.endswith(f"{run.id}.jsonl.gz")
    with gzip.open(path, "rt") as f:
        lines = [json.loads(line) for line in f]
    assert len(lines) == 2
    assert {line["type"] for line in lines} == {"run.created", "run.closed"}

    remaining = await store.list_events(run.id)
    assert remaining == []
    await store.stop()


@pytest.mark.asyncio
async def test_list_closed_runs_older_than_excludes_recent_and_active_runs(tmp_path):
    store = await _store(tmp_path)
    project = await store.create_project("demo", str(tmp_path))

    recent_closed = await store.create_run(project.id, "p.toml", "recent")
    await store.update_run(recent_closed.id, status="closed", closed_at=datetime.datetime.now(datetime.UTC))

    still_active = await store.create_run(project.id, "p.toml", "active")
    await store.update_run(still_active.id, status="active")

    old_closed = await store.create_run(project.id, "p.toml", "old")
    old_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=45)
    await store.update_run(old_closed.id, status="closed", closed_at=old_time)

    eligible = await store.list_closed_runs_older_than(30)
    assert [r.id for r in eligible] == [old_closed.id]
    await store.stop()
```

(If Step 1's read shows `closed_at` is not reliably set for every terminal status, adapt `list_closed_runs_older_than`'s filter and this test's setup accordingly — falling back to `created_at` for runs where `closed_at` is `None`, matching whatever the codebase's real current behavior is, not this plan's assumption.)

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/store/test_archival.py -v`
Expected: FAIL — `AttributeError: 'Store' object has no attribute 'archive_run_events'`

- [ ] **Step 4: Add the two `Store` methods**

In `src/foundry/store/store.py`, add near the events section (add `import gzip`, `import json`, `from datetime import timedelta`, `from pathlib import Path` to the top-level imports, and add `delete` to the existing `from sqlalchemy import select` line):

```python
    async def list_closed_runs_older_than(self, days: int) -> list[Run]:
        async def _op(session):
            cutoff = utcnow() - timedelta(days=days)
            stmt = select(Run).where(
                Run.status.in_(("closed", "cancelled", "failed")),
                Run.closed_at.is_not(None),
                Run.closed_at < cutoff,
            )
            res = await session.execute(stmt)
            return list(res.scalars())

        return await self.read(_op)

    async def archive_run_events(self, run_id: str, archive_dir: str) -> str:
        events = await self.list_events(run_id)
        archive_path = Path(archive_dir) / f"{run_id}.jsonl.gz"
        with gzip.open(archive_path, "wt") as f:
            for ev in events:
                f.write(
                    json.dumps(
                        {
                            "seq": ev.seq,
                            "run_id": ev.run_id,
                            "unit_id": ev.unit_id,
                            "type": ev.type,
                            "payload_json": ev.payload_json,
                            "created_at": ev.created_at.isoformat(),
                        }
                    )
                    + "\n"
                )

        async def _op(session):
            await session.execute(delete(Event).where(Event.run_id == run_id))

        await self.write(_op)
        return str(archive_path)
```

(`utcnow` — use whatever this file's existing helper for the current UTC timestamp is; `store.py` already has one given `Run`/`Event` timestamp columns elsewhere in the codebase. If none exists, use `datetime.datetime.now(datetime.UTC)` inline instead of inventing a new helper.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/store/test_archival.py -v`
Expected: PASS (2 tests)

- [ ] **Step 6: Add the `foundry archive-events` CLI command**

Read `src/foundry/cli.py`'s existing command structure first (its `run`/`events`/`serve` commands and their `async def _x` helper pattern), then add, matching that exact pattern:

```python
@app.command("archive-events")
def archive_events(db: str = "foundry.db", archive_dir: str = "./archive", older_than_days: int = 30) -> None:
    asyncio.run(_archive_events(db, archive_dir, older_than_days))


async def _archive_events(db: str, archive_dir: str, older_than_days: int) -> None:
    os.makedirs(archive_dir, exist_ok=True)
    engine = make_engine(db)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    eligible = await store.list_closed_runs_older_than(older_than_days)
    for run in eligible:
        path = await store.archive_run_events(run.id, archive_dir)
        typer.echo(f"archived {run.id} -> {path}")

    if not eligible:
        typer.echo("no eligible runs to archive")

    await store.stop()
```

(Add `import os` to the file's top-level imports, matching its existing style — not inline inside the function.)

- [ ] **Step 7: Write a CLI test**

Read `tests/test_cli.py`'s existing imports/fixtures first (does it already import `CliRunner`/`app` at module level?) and match that, rather than re-importing inline:

```python
def test_archive_events_command_runs_without_error(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    archive_dir = str(tmp_path / "archive")
    result = runner.invoke(app, ["archive-events", "--db", db_path, "--archive-dir", archive_dir, "--older-than-days", "30"])
    assert result.exit_code == 0
```

(`runner`/`app` — use whatever names the file's existing tests already reference.)

- [ ] **Step 8: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 9: Commit**

```bash
git add src/foundry/store/store.py src/foundry/cli.py tests/store/test_archival.py tests/test_cli.py
git commit -m "feat(store): event archival to gzip JSONL + foundry archive-events CLI command"
```

---

### Task 8: End-to-end proof — a pack playbook runs to completion with zero engine changes

**Files:**
- Test: `tests/packs/test_pack_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1-7. No new production code — this task proves M4's exit criterion (a) by actually RUNNING the second pack playbook (`bugfix.toml`, added in Task 3 as pure content) to completion via the real `Orchestrator`/`Store`/`materialize`/`load_playbook` stack, on `FakeDriver`, with gate overrides exercised too (tying Task 3's content together with Task 5's engine feature) — and confirms it via the same mechanism `foundry run`/`POST /api/runs` already use, unmodified.

- [ ] **Step 1: Write the end-to-end test**

```python
# tests/packs/test_pack_e2e.py
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
    run = await store.create_run(project.id, playbook_path, playbook.description or playbook.id, pack_version_pin=pin)
    await materialize(playbook, run.id, store)

    script = {step.id: FakeStepScript(artifact={"ok": True}) for step in playbook.steps}
    driver = FakeDriver(script)
    orch = Orchestrator(store, driver, playbook, gate_overrides={"diagnose": "approved"})

    complete = False
    for _ in range(10):
        result = await orch.tick(run.id)
        gates = await store.list_gates_for_run(run.id)
        # "review" is a human gate with no override in this test — approve it
        # manually, same as any dashboard user would, to reach completion.
        pending_human = [g for g in gates if g.decision == "pending" and g.gate_type == "human"]
        for g in pending_human:
            await store.decide_gate(g.id, "approved", decided_by="test")
        if getattr(result, "complete", False):
            complete = True
            break

    units = await store.list_units(run.id)
    task_units = [u for u in units if u.type == "task"]
    assert task_units
    assert all(u.status == "closed" for u in task_units)

    events = await store.list_events(run.id)
    assert any(e.type == "gate.policy_overridden" for e in events)

    await store.stop()
```

(`result.complete` — read `Orchestrator.tick`'s actual return type/shape first, since this plan's earlier research did not pin down its exact fields; adjust the loop's completion check to whatever `tick` actually returns, e.g. checking run status via `store.get_run(run.id)` instead if `tick` doesn't return a `complete` flag directly.)

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/packs/test_pack_e2e.py -v`
Expected: PASS. As with every prior milestone's own end-to-end proof task, treat any failure as a real signal to debug against Tasks 1-7's actual implementation, not a reason to weaken the assertions.

- [ ] **Step 3: Run the full suite one more time**

Run: `uv run pytest -q`
Expected: PASS, full suite green

- [ ] **Step 4: Commit**

```bash
git add tests/packs/test_pack_e2e.py
git commit -m "test(packs): end-to-end proof - bugfix pack playbook runs to completion, gate override applied, zero engine changes (M4 exit criterion a)"
```

---

## Out of scope for this plan (tracked, not forgotten)

- **M4b — pack viewer + portfolio home + project view dashboard.** A separate plan, written after M4a merges, consuming `GET /api/projects` (now with `status`), the pack manifest data this plan produces, and whatever small new read endpoints M4b's own plan decides it needs (same pattern as every prior `*b` plan's own Task 1).
- **What happens to an in-flight run when its project pauses mid-run.** Deliberately left ambiguous per Global Constraints — pause/archive only gate NEW run creation.
- **Chat-to-role.** Still deferred, unchanged since M1a.
- **Real prompt templates for `RoleSpec`.** `RoleSpec` is intentionally minimal (`id`, `model`) — no prompt-template format invented here.
- **Scheduled/cron execution of event archival.** The `foundry archive-events` CLI command is built; wiring it into an actual periodic job (external cron, or a new background loop in `foundry serve`) is not.
- **Five-projects/three-concurrent-runs exit criterion (b).** That's fundamentally a dashboard/portfolio-home demonstration (visualizing attention-ranked health across projects) — M4b's job, not M4a's. M4a's own job is making sure the underlying primitives (project status, pack pinning, gate overrides) exist and are correct; M4a doesn't attempt to demonstrate criterion (b) itself.
