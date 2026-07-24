# Deviation Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close six gaps between `docs/software-foundary-design.md` and the shipped
codebase, cataloged in `docs/design-deviations.md` and scoped in
`docs/superpowers/specs/2026-07-24-deviation-fixes-design.md`: two dormant
mechanisms that are built-but-never-wired (worktree isolation, KG interference
warnings), one unused dependency, a fully stubbed prompt-rendering path, missing
driver-selection plumbing, and a missing `ClaudeCodeDriver`.

**Architecture:** No new subsystems. Every task either (a) wires an already-built,
already-tested mechanism into the two/three production entry points that currently
skip it (`cli.py`'s `run` and `_recover_active_runs`, `api/routes/runs.py`'s
`create_run`, `api/scheduler.py`'s `register`), or (b) fills in content (role
descriptions, prompt text) that the engine already has the machinery to consume but
never had real data for.

**Tech Stack:** Python 3.12+, SQLAlchemy 2 async, Pydantic v2, Typer, pytest +
pytest-asyncio. No new dependencies.

## Global Constraints

- FakeDriver-backed test before any orchestrator-facing change touches a real
  driver path (per `CLAUDE.md`).
- No task requires live network/API access to test — driver tests use fixture
  scripts standing in for real CLIs, exactly like `tests/drivers/test_codex.py` +
  `tests/fixtures/fake_codex_cli.sh`.
- Conventional commits, one commit per task.
- Out of scope (see spec for full list, do not touch): `/internal` HTTP API,
  per-role multi-driver dispatch, chat/notes system, KG-via-`code-review-graph`,
  embedding-based memory retrieval, OpenAPI→TS codegen.

---

### Task 1: Wire WorktreeManager + KGSnapshot into production entry points

Both mechanisms are fully built and tested but never constructed at the three
places that create a real `Orchestrator`/register a run with the `Scheduler`:
`cli.py:57` (`run` command), `cli.py`'s `_recover_active_runs`, and
`api/routes/runs.py:154` (`create_run`). `Orchestrator` already accepts
`worktree_manager` and `kg_snapshot` as optional constructor kwargs
(`src/foundry/orchestrator/tick.py:38-44`) and already *uses* them when present
(`tick.py:547` worktree creation, `tick.py:406-460` `_check_convoy_interference`,
`tick.py:487-488` blast-radius bundle expansion) — this task only supplies real
values instead of `None`.

**Files:**
- Modify: `src/foundry/api/scheduler.py:66-79` (`Scheduler.register`)
- Modify: `src/foundry/api/routes/runs.py:128-156` (`create_run`)
- Modify: `src/foundry/cli.py:34-57` (`_run`), `src/foundry/cli.py:140-166`
  (`_recover_active_runs`)
- Create: `tests/fixtures/writes_demo.toml`
- Test: `tests/test_cli.py`, `tests/api/test_scheduler.py`

**Interfaces:**
- Consumes: `WorktreeManager(base_dir: str | Path)` and `.create(project_path, run_id, unit_id) -> str`
  (`src/foundry/orchestrator/worktrees.py`); `build_kg(project_root: str) -> KGSnapshot`
  (`src/foundry/kg/service.py`); `Orchestrator.__init__(..., worktree_manager=, project_path=, kg_snapshot=)`
  (already exists, unchanged).
- Produces: `Scheduler.register(run_id, driver, playbook, project_id=None, gate_overrides=None, project_path=".", worktree_manager=None, kg_snapshot=None)`
  — two new optional kwargs, defaulting to `None`/`"."` so every existing caller
  (including all current tests) keeps working unchanged.

- [ ] **Step 1: Write the failing fixture + test for CLI wiring**

Create `tests/fixtures/writes_demo.toml`:

```toml
[playbook]
id = "writes_demo"
description = "single writes=true task behind a derived gate, for worktree-wiring test"

[[step]]
id = "req"
role = "product_owner"
produces = "requirement_artifact"
gate = "none"

[[step]]
id = "approval"
role = "system"
type = "derived_gate"
needs = ["req"]

[[step]]
id = "code"
role = "developer"
needs = ["approval"]
produces = "code_diff_artifact"
gate = "none"
writes = true
```

Add to `tests/test_cli.py`:

```python
import os
import subprocess


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


def test_run_wires_a_real_worktree_manager_for_writes_true_steps(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    db_path = str(tmp_path / "foundry.db")

    result = runner.invoke(
        app,
        ["run", "tests/fixtures/writes_demo.toml", "--project-path", str(repo), "--db", db_path],
    )

    assert result.exit_code == 0, result.output
    assert os.path.isdir(repo / ".foundry" / "worktrees")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py::test_run_wires_a_real_worktree_manager_for_writes_true_steps -v`
Expected: FAIL — `.foundry/worktrees` never created (worktree_manager is `None` in
production today, `tick.py:547` falls through to `cwd = "."`).

- [ ] **Step 3: Wire worktree_manager + kg_snapshot into `cli.py`'s `_run`**

In `src/foundry/cli.py`, add imports and update `_run`:

```python
from foundry.kg.service import build_kg
from foundry.orchestrator.worktrees import WorktreeManager
```

Replace the `Orchestrator(store, FakeDriver(script), playbook)` line
(`cli.py:57`) with:

```python
    worktree_manager = WorktreeManager(base_dir=os.path.join(project_path, ".foundry", "worktrees"))
    kg_snapshot = build_kg(project_path)
    orchestrator = Orchestrator(
        store,
        FakeDriver(script),
        playbook,
        worktree_manager=worktree_manager,
        project_path=project_path,
        kg_snapshot=kg_snapshot,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py::test_run_wires_a_real_worktree_manager_for_writes_true_steps -v`
Expected: PASS

- [ ] **Step 5: Run the full existing CLI suite to check for regressions**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all PASS — none of the existing CLI fixtures (`cli_demo.toml`,
`gated_demo.toml`, `linear_demo.toml`, `stuck_human_task.toml`,
`dangling_needs.toml`) have `writes = true` steps, so `worktree_manager.create()`
is never actually invoked by them; `build_kg(project_path)` on the pytest cwd
(`project_path` defaults to `"."` when not passed) must not raise even though
that's this repo itself — `build_kg` only reads `*.py` files, never writes.

- [ ] **Step 6: Write the failing test for Scheduler/API wiring**

Add to `tests/api/test_scheduler.py` (it already defines `make_store(tmp_path)`
and imports `Scheduler`, `FakeDriver`, `FakeStepScript` — reuse those, add one
new import):

```python
from foundry.orchestrator.worktrees import WorktreeManager
from foundry.playbook.schema import PlaybookSpec


@pytest.mark.asyncio
async def test_register_wires_worktree_manager_and_kg_snapshot_through(tmp_path):
    store = await make_store(tmp_path)
    wtm = WorktreeManager(base_dir=tmp_path / "worktrees")

    scheduler = Scheduler(store)
    scheduler.register(
        "run1",
        FakeDriver({}),
        PlaybookSpec(id="x", steps=[]),
        project_path=str(tmp_path),
        worktree_manager=wtm,
    )

    orchestrator = scheduler._orchestrators["run1"]
    assert orchestrator.worktree_manager is wtm
    assert orchestrator.kg_snapshot is None  # only passed if caller supplies one — this call didn't

    await store.stop()
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/api/test_scheduler.py::test_register_wires_worktree_manager_and_kg_snapshot_through -v`
Expected: FAIL — `TypeError: register() got an unexpected keyword argument 'worktree_manager'`

- [ ] **Step 8: Add the two kwargs to `Scheduler.register`**

In `src/foundry/api/scheduler.py`, update the import and method:

```python
from foundry.kg.service import KGSnapshot
from foundry.orchestrator.worktrees import WorktreeManager
```

```python
    def register(
        self,
        run_id: str,
        driver: AgentDriver,
        playbook: PlaybookSpec,
        project_id: str | None = None,
        gate_overrides: dict[str, str] | None = None,
        project_path: str = ".",
        worktree_manager: WorktreeManager | None = None,
        kg_snapshot: KGSnapshot | None = None,
    ) -> None:
        self._orchestrators[run_id] = Orchestrator(
            self.store,
            driver,
            playbook,
            gate_overrides=gate_overrides,
            project_path=project_path,
            worktree_manager=worktree_manager,
            kg_snapshot=kg_snapshot,
        )
        if project_id is not None:
            self._project_by_run[run_id] = project_id
```

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run pytest tests/api/test_scheduler.py::test_register_wires_worktree_manager_and_kg_snapshot_through -v`
Expected: PASS

- [ ] **Step 10: Write the failing test for the actual API call site**

Add to `tests/api/test_runs.py` (it already uses the `api_client` fixture,
yielding `(client, store, scheduler)` as an async `httpx.AsyncClient` — see
`tests/api/conftest.py`):

```python
import subprocess


def _init_git_repo(path):
    subprocess.run(["git", "init", "-q", str(path)], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True)
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True)


@pytest.mark.asyncio
async def test_create_run_wires_a_real_worktree_manager(api_client, tmp_path):
    client, _store, scheduler = api_client
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": str(repo)})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={"project_id": project_id, "playbook_path": "tests/fixtures/writes_demo.toml"},
    )
    assert run_resp.status_code == 201, run_resp.text
    run_id = run_resp.json()["data"]["id"]

    orchestrator = scheduler._orchestrators[run_id]
    assert orchestrator.worktree_manager is not None
```

- [ ] **Step 11: Run test to verify it fails**

Run: `uv run pytest tests/api/test_runs.py::test_create_run_wires_a_real_worktree_manager -v`
Expected: FAIL — `orchestrator.worktree_manager is None`

- [ ] **Step 12: Wire it into `routes/runs.py`'s `create_run`**

In `src/foundry/api/routes/runs.py`, add imports and update the `scheduler.register(...)` call at line 154:

```python
from foundry.kg.service import build_kg
from foundry.orchestrator.worktrees import WorktreeManager
```

```python
    worktree_manager = WorktreeManager(base_dir=f"{project.path}/.foundry/worktrees")
    kg_snapshot = build_kg(project.path)
    scheduler.register(
        run.id,
        FakeDriver(script),
        playbook,
        project_id=project.id,
        gate_overrides=body.gate_overrides,
        project_path=project.path,
        worktree_manager=worktree_manager,
        kg_snapshot=kg_snapshot,
    )
```

- [ ] **Step 13: Run test to verify it passes**

Run: `uv run pytest tests/api/test_runs.py::test_create_run_wires_a_real_worktree_manager -v`
Expected: PASS

- [ ] **Step 14: Wire the same into `cli.py`'s `_recover_active_runs`**

In `src/foundry/cli.py`, update `_recover_active_runs` (around line 140-166) —
it currently only has `active_run`, needs the owning project's path:

```python
async def _recover_active_runs(store: Store, scheduler: Scheduler) -> None:
    active_runs = await store.list_runs(status="active")
    for active_run in active_runs:
        try:
            playbook = load_playbook(active_run.playbook_ref)
        except (PlaybookLoadError, PlaybookLintError):
            continue
        project = await store.get_project(active_run.project_id)
        project_path = project.path if project is not None else "."
        script = {step.id: FakeStepScript(artifact={"ok": True}) for step in playbook.steps}
        scheduler.register(
            active_run.id,
            FakeDriver(script),
            playbook,
            gate_overrides=active_run.gate_overrides_json or None,
            project_path=project_path,
            worktree_manager=WorktreeManager(base_dir=os.path.join(project_path, ".foundry", "worktrees")),
            kg_snapshot=build_kg(project_path),
        )
```

- [ ] **Step 15: Run the recovery + full suite**

Run: `uv run pytest tests/test_cli_recovery.py tests/api/test_scheduler.py tests/api/test_runs.py tests/test_cli.py -v`
Expected: all PASS

- [ ] **Step 16: Run full test suite**

Run: `uv run pytest -q`
Expected: all PASS, no regressions elsewhere.

- [ ] **Step 17: Commit**

```bash
git add tests/fixtures/writes_demo.toml tests/test_cli.py tests/api/test_scheduler.py \
        tests/api/test_runs.py src/foundry/api/scheduler.py src/foundry/api/routes/runs.py \
        src/foundry/cli.py
git commit -m "fix(orchestrator): wire WorktreeManager and KGSnapshot into production entry points

Both were fully built and tested (M2b, M3a) but never constructed at any
real call site -- cli.py's run/_recover_active_runs and the API's
create_run always passed None, so per-unit worktree isolation and
KG blast-radius/interference warnings never actually ran outside their
own test suites."
```

---

### Task 2: Drop unused Alembic dependency

Every schema change since M0 has shipped as a direct SQLAlchemy model edit.
`alembic.ini` and a `versions/` directory have never existed. This dependency has
no consumer.

**Files:**
- Modify: `pyproject.toml:13` (remove `"alembic>=1.13",`)
- Modify: `uv.lock` (regenerated)

**Interfaces:** None — this task removes a dependency, nothing to consume or
produce for other tasks.

- [ ] **Step 1: Remove the dependency line**

In `pyproject.toml`, delete the line `    "alembic>=1.13",` from the
`dependencies` list.

- [ ] **Step 2: Regenerate the lockfile**

Run: `uv lock`
Expected: `uv.lock` updates, `alembic` and its transitive deps (`Mako`, etc., if
not needed elsewhere) drop out.

- [ ] **Step 3: Reinstall and run full suite**

Run: `uv sync && uv run pytest -q`
Expected: all PASS — nothing in `src/` or `tests/` imports `alembic`
(confirmed: `grep -rn "alembic" src/ tests/` returns nothing before this change).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: drop unused alembic dependency

No migration has ever been written -- every schema change since M0 has
shipped as a direct model edit. Revisit when M5's Postgres migration
actually needs it."
```

---

### Task 3: Role definitions — schema field, pack content, Orchestrator wiring

`RoleSpec` (`src/foundry/packs/schema.py`) currently has only `id` and `model` —
no description/prompt content exists for any role, including `integrator`, whose
missing merge/conflict-resolution instructions is deviation E1. `Orchestrator`
also has no reference to `PackManifest`/`RoleSpec` at all today, so
`step.role`'s configured `model` (e.g. eventually `"sonnet-latest"`) is never
threaded into `SessionSpec.model` — both spawn sites hardcode `model="fake"`.

**Files:**
- Modify: `src/foundry/packs/schema.py` (`RoleSpec`)
- Modify: `packs/default/pack.toml` (add `description` to all 7 roles)
- Modify: `src/foundry/orchestrator/tick.py` (`Orchestrator.__init__`, both spawn sites)
- Create: `src/foundry/packs/resolve.py` addition: `resolve_pack_manifest`
- Test: `tests/packs/test_loader.py`, `tests/orchestrator/test_tick.py`

**Interfaces:**
- Produces: `RoleSpec.description: str = ""` (new field, backward compatible —
  existing `pack.toml` fixtures without it still parse, default `""`).
- Produces: `Orchestrator.__init__(..., pack: PackManifest | None = None)` — new
  kwarg; `self._roles_by_id: dict[str, RoleSpec]` built from it, empty dict if
  `pack is None`.
- Produces: `resolve_pack_manifest(playbook_path: str) -> PackManifest | None` in
  `src/foundry/packs/resolve.py`, alongside the existing `resolve_pack_version`.
  This task wires it into all 3 production entry points itself (Step 15) — it is
  not left for a later task, to avoid landing another dormant mechanism. Task 4
  and Task 5 consume `self._roles_by_id` directly (Orchestrator-internal); Task 5's
  full-block rewrites of `_run` and `_recover_active_runs` (Steps 12, 14) must
  preserve the `pack=resolve_pack_manifest(...)` line this task adds.

- [ ] **Step 1: Write the failing test for the schema field**

Add to `tests/packs/test_loader.py`:

```python
def test_role_spec_carries_an_optional_description():
    from foundry.packs.schema import RoleSpec

    role = RoleSpec(id="developer", model="fake", description="Implement the assigned slice.")
    assert role.description == "Implement the assigned slice."

    bare = RoleSpec(id="developer")
    assert bare.description == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/packs/test_loader.py::test_role_spec_carries_an_optional_description -v`
Expected: FAIL — `TypeError: RoleSpec.__init__() got an unexpected keyword argument 'description'`

- [ ] **Step 3: Add the field**

In `src/foundry/packs/schema.py`:

```python
class RoleSpec(BaseModel):
    id: str
    model: str = "fake"
    description: str = ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/packs/test_loader.py::test_role_spec_carries_an_optional_description -v`
Expected: PASS

- [ ] **Step 5: Populate `packs/default/pack.toml` with real role content**

Replace the `[[role]]` blocks in `packs/default/pack.toml` with:

```toml
[[role]]
id = "product_owner"
model = "fake"
description = "Turn the raw request into a clear requirement: goals, acceptance criteria, explicit out-of-scope. Do not write code or propose an implementation."

[[role]]
id = "architect"
model = "fake"
description = "Design the technical approach for the requirement. Slice the work into independently implementable pieces and list them under architecture_artifact.slices -- the implement step fans out one unit per slice."

[[role]]
id = "qa"
model = "fake"
description = "Write the test plan: what must be verified before this story is considered done, including edge cases the requirement doesn't spell out."

[[role]]
id = "system"
model = "fake"
description = "Automated plan-approval checkpoint. No agent session runs for this role; the engine derives the decision from upstream gate outcomes."

[[role]]
id = "developer"
model = "fake"
description = "Implement the assigned slice. Produce a code_diff_artifact touching only files necessary for this slice. Follow existing patterns in the codebase; do not restructure unrelated code."

[[role]]
id = "reviewer"
model = "fake"
description = "Review the code_diff_artifact against the architecture and test plan. Verdict must be 'approved' or 'needs_changes', with specific, actionable feedback when rejecting."

[[role]]
id = "integrator"
model = "fake"
description = "Merge the reviewed slices. Auto-resolve changes that don't overlap. If two slices conflict on the same lines or logic, do not guess a resolution -- set verdict to 'escalated' and describe the conflict precisely so a human can resolve it."
```

- [ ] **Step 6: Run the pack loader + default-pack test suites**

Run: `uv run pytest tests/packs/ -v`
Expected: all PASS — `load_pack`/`list_packs` ignore unknown-to-them extra
fields normally, and `description` is now a declared field so this is not even
an "unknown field" case.

- [ ] **Step 7: Write the failing test for Orchestrator pack wiring**

Add to `tests/orchestrator/test_tick.py`:

```python
def test_orchestrator_builds_role_lookup_from_pack():
    from foundry.packs.schema import PackManifest, RoleSpec

    pack = PackManifest(
        id="default",
        version="0.1.0",
        roles=[RoleSpec(id="developer", model="sonnet-latest", description="Implement things.")],
        playbooks=[],
    )
    orch = Orchestrator(store=None, driver=None, playbook=PlaybookSpec(id="x", steps=[]), pack=pack)
    assert orch._roles_by_id["developer"].model == "sonnet-latest"


def test_orchestrator_role_lookup_empty_without_a_pack():
    orch = Orchestrator(store=None, driver=None, playbook=PlaybookSpec(id="x", steps=[]))
    assert orch._roles_by_id == {}
```

(`store=None, driver=None` is fine here — the constructor only stores them,
doesn't touch either.)

- [ ] **Step 8: Run test to verify it fails**

Run: `uv run pytest tests/orchestrator/test_tick.py -k role_lookup -v`
Expected: FAIL — `TypeError: __init__() got an unexpected keyword argument 'pack'`

- [ ] **Step 9: Add `pack` param to `Orchestrator.__init__`**

In `src/foundry/orchestrator/tick.py`, add the import and update `__init__`:

```python
from foundry.packs.schema import PackManifest, RoleSpec
```

```python
    def __init__(
        self,
        store: Store,
        driver: AgentDriver,
        playbook: PlaybookSpec,
        concurrency: int = 5,
        worktree_manager: WorktreeManager | None = None,
        project_path: str = ".",
        kg_snapshot: KGSnapshot | None = None,
        gate_overrides: dict[str, str] | None = None,
        pack: PackManifest | None = None,
    ):
        self.store = store
        self.driver = driver
        self.playbook = playbook
        self.concurrency = concurrency
        self.worktree_manager = worktree_manager
        self.project_path = project_path
        self.kg_snapshot = kg_snapshot
        self.gate_overrides = gate_overrides or {}
        self.pack = pack
        self._steps_by_id: dict[str, StepSpec] = {s.id: s for s in playbook.steps}
        self._roles_by_id: dict[str, RoleSpec] = {r.id: r for r in pack.roles} if pack else {}
        self._unit_worktrees: dict[str, str] = {}
```

- [ ] **Step 10: Run test to verify it passes**

Run: `uv run pytest tests/orchestrator/test_tick.py -k role_lookup -v`
Expected: PASS

- [ ] **Step 11: Thread `role.model` into both `SessionSpec.model` sites**

In `src/foundry/orchestrator/tick.py`, replace `model="fake"` at the task-dispatch
spawn site (around line 566-575, right before `spec = SessionSpec(`) with:

```python
            role_spec = self._roles_by_id.get(step.role)
            model = role_spec.model if role_spec is not None else "fake"
```

and change `model="fake",` in that `SessionSpec(...)` call to `model=model,`.

Do the same at the review-gate spawn site (around line 761-763 in
`_dispatch_agent_reviews`):

```python
            role_spec = self._roles_by_id.get(step.role)
            model = role_spec.model if role_spec is not None else "fake"
```

and change that `SessionSpec(...)` call's `model="fake",` to `model=model,`.

- [ ] **Step 12: Add `resolve_pack_manifest` alongside `resolve_pack_version`**

In `src/foundry/packs/resolve.py`, add:

```python
def resolve_pack_manifest(playbook_path: str) -> PackManifest | None:
    try:
        current = Path(playbook_path).resolve().parent
    except OSError:
        return None

    for _ in range(_MAX_PARENT_WALK):
        if (current / "pack.toml").exists():
            try:
                return load_pack(str(current))
            except PackLoadError:
                return None
        if current.parent == current:
            break
        current = current.parent

    return None
```

(Note: `PackManifest` needs importing alongside the existing `PackLoadError, load_pack` import.)

- [ ] **Step 13: Write the failing test for `resolve_pack_manifest`**

Add to `tests/packs/test_resolve.py`:

```python
def test_resolve_pack_manifest_returns_the_manifest_for_a_pack_playbook():
    manifest = resolve_pack_manifest("packs/default/playbooks/sdlc_story.toml")
    assert manifest is not None
    assert manifest.id == "default"


def test_resolve_pack_manifest_returns_none_outside_any_pack():
    assert resolve_pack_manifest("tests/fixtures/cli_demo.toml") is None
```

- [ ] **Step 14: Run test to verify it fails, then implement, then verify it passes**

Run: `uv run pytest tests/packs/test_resolve.py -v`
Expected: fails first (function doesn't exist / not imported), passes after
Step 12's implementation is in place and imported in the test file.

- [ ] **Step 15: Wire `pack=resolve_pack_manifest(...)` into all 3 production entry points**

Without this step, role descriptions only ever apply to hand-built `Orchestrator`
instances in tests — production would still always see `pack=None`, `_roles_by_id`
would always be `{}`, and this task's content would be exactly as dormant as
`WorktreeManager`/`KGSnapshot` were before Task 1. Wire it the same way.

First, add `pack` as a fourth pass-through kwarg on `Scheduler.register`, in
`src/foundry/api/scheduler.py` (extending Task 1 Step 8's version):

```python
from foundry.packs.schema import PackManifest
```

```python
    def register(
        self,
        run_id: str,
        driver: AgentDriver,
        playbook: PlaybookSpec,
        project_id: str | None = None,
        gate_overrides: dict[str, str] | None = None,
        project_path: str = ".",
        worktree_manager: WorktreeManager | None = None,
        kg_snapshot: KGSnapshot | None = None,
        pack: PackManifest | None = None,
    ) -> None:
        self._orchestrators[run_id] = Orchestrator(
            self.store,
            driver,
            playbook,
            gate_overrides=gate_overrides,
            project_path=project_path,
            worktree_manager=worktree_manager,
            kg_snapshot=kg_snapshot,
            pack=pack,
        )
        if project_id is not None:
            self._project_by_run[run_id] = project_id
```

Then in `src/foundry/api/routes/runs.py`, add the import and pass `pack=` in the
`scheduler.register(...)` call built in Task 1 Step 12:

```python
from foundry.packs.resolve import resolve_pack_manifest
```

```python
    scheduler.register(
        run.id,
        FakeDriver(script),
        playbook,
        project_id=project.id,
        gate_overrides=body.gate_overrides,
        project_path=project.path,
        worktree_manager=worktree_manager,
        kg_snapshot=kg_snapshot,
        pack=resolve_pack_manifest(body.playbook_path),
    )
```

Then in `src/foundry/cli.py`, add the import and pass `pack=` at both places:
`_run`'s direct `Orchestrator(...)` construction (Task 1 Step 3) and
`_recover_active_runs`'s `scheduler.register(...)` call (Task 1 Step 14):

```python
from foundry.packs.resolve import resolve_pack_manifest
```

```python
    orchestrator = Orchestrator(
        store,
        FakeDriver(script),
        playbook,
        worktree_manager=worktree_manager,
        project_path=project_path,
        kg_snapshot=kg_snapshot,
        pack=resolve_pack_manifest(playbook_path),
    )
```

```python
        scheduler.register(
            active_run.id,
            FakeDriver(script),
            playbook,
            gate_overrides=active_run.gate_overrides_json or None,
            project_path=project_path,
            worktree_manager=WorktreeManager(base_dir=os.path.join(project_path, ".foundry", "worktrees")),
            kg_snapshot=build_kg(project_path),
            pack=resolve_pack_manifest(active_run.playbook_ref),
        )
```

- [ ] **Step 16: Write the regression test proving the wiring reaches production**

Add to `tests/test_cli.py`:

```python
def test_run_wires_the_default_pack_when_playbook_lives_inside_one(tmp_path):
    db_path = str(tmp_path / "foundry.db")

    result = runner.invoke(
        app,
        ["run", "packs/default/playbooks/sdlc_story.toml", "--db", db_path, "--project-path", "."],
    )

    assert result.exit_code == 0, result.output
```

This doesn't assert on prompt content directly (that's Task 4's regression test);
it only proves `resolve_pack_manifest("packs/default/playbooks/sdlc_story.toml")`
resolving to a real `PackManifest` and being passed through doesn't break a real
run — `sdlc_story.toml` is the fixture with the fullest step/gate shape in the
repo, good enough to catch anything Step 15's wiring gets wrong.

- [ ] **Step 17: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -k wires_the_default_pack -v`
Expected: PASS

- [ ] **Step 18: Run the full orchestrator + packs suites**

Run: `uv run pytest tests/orchestrator/ tests/packs/ tests/test_cli.py tests/test_cli_recovery.py tests/api/ -q`
Expected: all PASS — `model` defaulting to `"fake"` when no pack/role is found
(the case for every existing test that doesn't pass `pack=`) preserves current
behavior exactly.

- [ ] **Step 19: Commit**

```bash
git add src/foundry/packs/schema.py src/foundry/packs/resolve.py packs/default/pack.toml \
        src/foundry/orchestrator/tick.py src/foundry/api/scheduler.py src/foundry/api/routes/runs.py \
        src/foundry/cli.py tests/packs/test_loader.py tests/packs/test_resolve.py \
        tests/orchestrator/test_tick.py tests/test_cli.py
git commit -m "feat(packs): add role description field, wire PackManifest into Orchestrator

RoleSpec gained an optional description field, populated for all 7
default-pack roles (integrator's covers merge/conflict-resolution
instructions -- deviation E1). Orchestrator now accepts a pack and
threads role.model into SessionSpec.model instead of hardcoding 'fake'.
pack=resolve_pack_manifest(...) is wired into all 3 production entry
points -- without this, role descriptions would be exactly as dormant
as WorktreeManager/KGSnapshot were before Task 1."
```

---

### Task 4: Real prompt rendering

Both spawn sites in `tick.py` build a stub prompt string
(`f"step:{step.id} files:{len(bundle_files)} memory:{len(memory_items)}"` and
`f"review:{step.id}:gate:{gate.id}"`) even though `_compose_context_bundle`
already computes real `bundle_files`/`memory_items` content one line above. This
task replaces both with real rendered prompts using Task 3's role lookup.

**Files:**
- Create: `src/foundry/orchestrator/prompt.py`
- Modify: `src/foundry/orchestrator/tick.py` (both spawn sites)
- Test: `tests/orchestrator/test_prompt.py` (new), `tests/orchestrator/test_tick.py`

**Interfaces:**
- Produces: `render_prompt(role: RoleSpec | None, step_id: str, produces: str | None, input_files: list[str], memory_items: list[Memory]) -> str`
- Produces: `render_review_prompt(role: RoleSpec | None, step_id: str, gate_id: str, artifact_kind: str | None, artifact_payload: dict) -> str`

- [ ] **Step 1: Write the failing tests for `render_prompt`**

Create `tests/orchestrator/test_prompt.py`:

```python
from foundry.orchestrator.prompt import render_prompt, render_review_prompt
from foundry.packs.schema import RoleSpec
from foundry.store.models import Memory


def test_render_prompt_includes_role_description():
    role = RoleSpec(id="developer", model="fake", description="Implement the assigned slice.")
    prompt = render_prompt(role, "code", "code_diff_artifact", [], [])
    assert "developer" in prompt
    assert "Implement the assigned slice." in prompt


def test_render_prompt_includes_input_files_and_memory():
    role = RoleSpec(id="developer", model="fake", description="Implement.")
    memory = Memory(
        id="m1", scope="project", kind="lesson", title="Watch the pgid",
        body_md="Always capture the pgid at spawn time.",
    )
    prompt = render_prompt(role, "code", "code_diff_artifact", ["src/foo.py"], [memory])
    assert "src/foo.py" in prompt
    assert "Watch the pgid" in prompt
    assert "Always capture the pgid at spawn time." in prompt


def test_render_prompt_handles_no_role():
    prompt = render_prompt(None, "code", "code_diff_artifact", [], [])
    assert "code" in prompt


def test_render_review_prompt_includes_role_and_artifact():
    role = RoleSpec(id="reviewer", model="fake", description="Review the diff.")
    prompt = render_review_prompt(role, "review", "gate1", "code_diff_artifact", {"diff": "x"})
    assert "reviewer" in prompt
    assert "Review the diff." in prompt
    assert "code_diff_artifact" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.orchestrator.prompt'`

- [ ] **Step 3: Implement `render_prompt` and `render_review_prompt`**

Create `src/foundry/orchestrator/prompt.py`:

```python
from __future__ import annotations

from foundry.packs.schema import RoleSpec
from foundry.store.models import Memory


def _role_header(role: RoleSpec | None, fallback_id: str) -> str:
    if role is not None and role.description:
        return f"# Role: {role.id}\n{role.description}"
    return f"# Role: {role.id if role is not None else fallback_id}"


def render_prompt(
    role: RoleSpec | None,
    step_id: str,
    produces: str | None,
    input_files: list[str],
    memory_items: list[Memory],
) -> str:
    lines = [_role_header(role, "unknown"), f"\n# Step: {step_id}"]
    if produces:
        lines.append(f"Produce an artifact of kind: {produces}")
    if input_files:
        lines.append("\n# Input files in context:")
        lines.extend(f"- {f}" for f in input_files)
    if memory_items:
        lines.append("\n# Relevant memory:")
        for m in memory_items:
            lines.append(f"## {m.title}\n{m.body_md}")
    return "\n".join(lines)


def render_review_prompt(
    role: RoleSpec | None,
    step_id: str,
    gate_id: str,
    artifact_kind: str | None,
    artifact_payload: dict,
) -> str:
    lines = [_role_header(role, "reviewer"), f"\n# Review step: {step_id} (gate {gate_id})"]
    if artifact_kind:
        lines.append(f"Artifact under review (kind: {artifact_kind}):")
    lines.append(str(artifact_payload))
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_prompt.py -v`
Expected: PASS

- [ ] **Step 5: Wire `render_prompt` into the task-dispatch spawn site**

In `src/foundry/orchestrator/tick.py`, add the import:

```python
from foundry.orchestrator.prompt import render_prompt, render_review_prompt
```

Replace the stub prompt line at the task-dispatch spawn site (the one right
after `role_spec = self._roles_by_id.get(step.role)` from Task 3 Step 11) with:

```python
            prompt = render_prompt(role_spec, step.id, step.produces, bundle_files, memory_items)
```

and change `prompt=f"step:{step.id} files:{len(bundle_files)} memory:{len(memory_items)}",`
in that `SessionSpec(...)` call to `prompt=prompt,`.

- [ ] **Step 6: Wire `render_review_prompt` into the review spawn site**

In `_dispatch_agent_reviews`, right after the `role_spec = ...` / `model = ...`
lines added in Task 3 Step 11, fetch the artifact under review and render:

```python
            artifacts = await self.store.list_artifacts(run_id)
            reviewed_artifact = next((a for a in artifacts if a.id == gate.artifact_id), None)
            artifact_kind = reviewed_artifact.kind if reviewed_artifact is not None else None
            artifact_payload = reviewed_artifact.payload_json if reviewed_artifact is not None else {}
            prompt = render_review_prompt(role_spec, step.id, gate.id, artifact_kind, artifact_payload)
```

and change `prompt=f"review:{step.id}:gate:{gate.id}",` in that `SessionSpec(...)`
call to `prompt=prompt,`.

- [ ] **Step 7: Write a regression test that a real prompt reaches the driver**

Add to `tests/orchestrator/test_tick.py` (it already defines `make_store` and
uses `FIXTURE = "tests/orchestrator/fixtures/linear_demo.toml"`, whose
`implement` step has `role = "developer"`):

```python
from foundry.drivers.base import SessionHandle, SessionSpec
from foundry.packs.schema import PackManifest, RoleSpec


class CapturingDriver(FakeDriver):
    def __init__(self, script):
        super().__init__(script)
        self.captured_specs: list[SessionSpec] = []

    def spawn(self, spec: SessionSpec) -> SessionHandle:
        self.captured_specs.append(spec)
        return super().spawn(spec)


@pytest.mark.asyncio
async def test_dispatch_sends_a_real_rendered_prompt_not_a_stub(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo3", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run 3")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a", "b"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    driver = CapturingDriver(script)
    pack = PackManifest(
        id="test",
        version="0.1.0",
        roles=[RoleSpec(id="developer", model="fake", description="Implement the assigned slice.")],
        playbooks=[],
    )
    orchestrator = Orchestrator(store, driver, playbook, pack=pack)

    await orchestrator.run_to_completion(run.id)

    assert any("Implement the assigned slice." in s.prompt for s in driver.captured_specs)
    assert not any(s.prompt.startswith("step:") and "files:" in s.prompt for s in driver.captured_specs)

    await store.stop()
```

- [ ] **Step 8: Run test to verify it fails, then passes**

Run: `uv run pytest tests/orchestrator/test_tick.py -k real_rendered_prompt -v`
Expected: fails before Step 5/6's wiring, passes after.

- [ ] **Step 9: Run full orchestrator suite**

Run: `uv run pytest tests/orchestrator/ -q`
Expected: all PASS — every existing test constructs `Orchestrator` without
`pack=`, so `role_spec` is always `None` and `render_prompt`/`render_review_prompt`
fall back to the "unknown"/"reviewer" header, still producing a non-empty
string `FakeDriver` doesn't care about the content of.

- [ ] **Step 10: Run full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add src/foundry/orchestrator/prompt.py src/foundry/orchestrator/tick.py \
        tests/orchestrator/test_prompt.py tests/orchestrator/test_tick.py
git commit -m "feat(orchestrator): render real prompts instead of stub strings

Both spawn sites built a stub prompt (step id + file/memory counts)
even though the real bundle_files/memory_items content was already
computed one line above. render_prompt/render_review_prompt now build
the design doc's §8 prompt contract (role definition, input files,
memory content, artifact kind) minus the chat-notes section, which
stays deferred (no chat subsystem exists -- deviation A4)."
```

---

### Task 5: Driver selection plumbing

Neither `foundry run` nor `POST /api/runs` can select any driver but
`FakeDriver` — there is no flag, no field, nothing. `CodexDriver` has been fully
built and tested since M2 with zero non-test references anywhere in the
codebase. This task adds a shared driver factory, a persisted `driver` field on
`Run` (same pattern as the existing `pack_version_pin`/`gate_overrides_json`
columns) so a restart-recovered run keeps using the driver it was created with,
and wires selection into both the CLI and the API.

**Files:**
- Create: `src/foundry/drivers/factory.py`
- Modify: `src/foundry/store/models.py` (`Run.driver` column)
- Modify: `src/foundry/store/store.py` (`create_run`)
- Modify: `src/foundry/api/routes/runs.py` (`RunCreate`, `RunOut`, `_to_run_out`, `create_run`)
- Modify: `src/foundry/cli.py` (`run` command, `_run`, `_recover_active_runs`)
- Test: `tests/drivers/test_factory.py` (new), `tests/store/test_store.py` or
  equivalent, `tests/api/test_runs.py`, `tests/test_cli.py`, `tests/test_cli_recovery.py`

**Interfaces:**
- Produces: `make_driver(name: str, playbook: PlaybookSpec | None = None) -> AgentDriver`,
  `name` one of `"fake" | "codex" | "claude"`, raises `ValueError` otherwise.
- Produces: `Store.create_run(..., driver: str = "fake")`; `Run.driver: str`
  column, default `"fake"`.
- Task 6 (`ClaudeCodeDriver`) is selected via `make_driver("claude", ...)` — this
  task's factory must import it, so Task 6 must land its driver class file before
  this task's factory import will resolve. **Do this task's Steps 1-3 (factory
  skeleton) before Task 6, then come back and wire the `"claude"` branch in after
  Task 6 lands** — or reorder execution so Task 6 runs before this task. Either
  order is fine; the two are listed in spec order, not execution order.

- [ ] **Step 1: Write the failing test for the factory**

Create `tests/drivers/test_factory.py`:

```python
import pytest

from foundry.drivers.factory import make_driver
from foundry.drivers.fake import FakeDriver
from foundry.drivers.codex import CodexDriver
from foundry.playbook.schema import PlaybookSpec, StepSpec


def test_make_driver_fake_builds_a_scripted_fake_driver():
    playbook = PlaybookSpec(id="x", steps=[StepSpec(id="a", role="developer")])
    driver = make_driver("fake", playbook)
    assert isinstance(driver, FakeDriver)


def test_make_driver_codex_builds_a_codex_driver():
    driver = make_driver("codex")
    assert isinstance(driver, CodexDriver)


def test_make_driver_rejects_unknown_names():
    with pytest.raises(ValueError, match="unknown driver"):
        make_driver("not-a-real-driver")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/drivers/test_factory.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement the factory (fake + codex branches only for now)**

Create `src/foundry/drivers/factory.py`:

```python
from __future__ import annotations

from foundry.drivers.base import AgentDriver
from foundry.drivers.codex import CodexDriver
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.playbook.schema import PlaybookSpec

VALID_DRIVER_NAMES = ("fake", "codex", "claude")


def make_driver(name: str, playbook: PlaybookSpec | None = None) -> AgentDriver:
    if name == "fake":
        steps = playbook.steps if playbook is not None else []
        script = {step.id: FakeStepScript(artifact={"ok": True}) for step in steps}
        return FakeDriver(script)
    if name == "codex":
        return CodexDriver()
    if name == "claude":
        from foundry.drivers.claude_code import ClaudeCodeDriver  # deferred: see Task 6

        return ClaudeCodeDriver()
    raise ValueError(f"unknown driver {name!r}, expected one of {VALID_DRIVER_NAMES}")
```

(The `claude` branch's import is deferred/local so this file imports cleanly
even before Task 6's `claude_code.py` exists — `make_driver("claude", ...)`
just isn't callable yet until Task 6 lands. If Task 6 is done first, this can be
a normal top-level import instead.)

- [ ] **Step 4: Run test to verify fake/codex pass, claude test deferred**

Run: `uv run pytest tests/drivers/test_factory.py -v`
Expected: `test_make_driver_fake_builds_a_scripted_fake_driver` and
`test_make_driver_codex_builds_a_codex_driver` and
`test_make_driver_rejects_unknown_names` PASS. (No `claude` test yet — added in
Task 6.)

- [ ] **Step 5: Write the failing test for `Run.driver` persistence**

Add to `tests/store/test_store.py` (it already defines `make_store(tmp_path)`
and has multiple `store.create_run(project.id, "pb.toml", "...")` calls to
match the style of):

```python
@pytest.mark.asyncio
async def test_create_run_persists_driver_name(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("p", str(tmp_path))

    run = await store.create_run(project.id, "playbook.toml", "title", driver="codex")
    assert run.driver == "codex"

    fetched = await store.get_run(run.id)
    assert fetched.driver == "codex"

    default_run = await store.create_run(project.id, "playbook2.toml", "title2")
    assert default_run.driver == "fake"

    await store.stop()
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest -k test_create_run_persists_driver_name -v`
Expected: FAIL — `TypeError: create_run() got an unexpected keyword argument 'driver'`

- [ ] **Step 7: Add the column and thread it through `create_run`**

In `src/foundry/store/models.py`, add to `Run` (near `pack_version_pin`):

```python
    driver: Mapped[str] = mapped_column(String, default="fake")
```

In `src/foundry/store/store.py`, update `create_run`:

```python
    async def create_run(
        self, project_id: str, playbook_ref: str, title: str, pack_version_pin: str = "local", driver: str = "fake"
    ) -> Run:
        async def _op(session):
            run = Run(
                project_id=project_id,
                playbook_ref=playbook_ref,
                title=title,
                pack_version_pin=pack_version_pin,
                driver=driver,
            )
            session.add(run)
            await session.flush()
            return run

        return await self.write(_op)
```

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest -k test_create_run_persists_driver_name -v`
Expected: PASS

- [ ] **Step 9: Wire `driver` through the API — request/response schema**

In `src/foundry/api/routes/runs.py`, update imports and models:

```python
from foundry.drivers.factory import make_driver
```

```python
class RunCreate(BaseModel):
    project_id: str
    playbook_path: str
    title: str | None = None
    gate_overrides: dict[str, Literal["approved", "rejected"]] | None = None
    driver: Literal["fake", "codex", "claude"] = "fake"


class RunOut(BaseModel):
    id: str
    project_id: str
    playbook_ref: str
    title: str
    status: str
    created_at: str
    pack_version_pin: str
    gate_overrides: dict[str, str]
    token_budget: int
    tokens_used: int
    driver: str
```

Update `_to_run_out`:

```python
def _to_run_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id,
        project_id=r.project_id,
        playbook_ref=r.playbook_ref,
        title=r.title,
        status=r.status,
        created_at=r.created_at.isoformat(),
        pack_version_pin=r.pack_version_pin,
        gate_overrides=r.gate_overrides_json,
        token_budget=r.token_budget,
        tokens_used=r.tokens_used,
        driver=r.driver,
    )
```

Update `create_run` (the route function): pass `driver=body.driver` to
`store.create_run(...)`, and replace `FakeDriver(script)` in the
`scheduler.register(...)` call with `make_driver(body.driver, playbook)` (drop
the now-unused `script = {...}` line and the `FakeDriver`/`FakeStepScript`
import if nothing else in the file needs them — check first with
`grep -n "FakeDriver\|FakeStepScript" src/foundry/api/routes/runs.py`).

- [ ] **Step 10: Write the failing API test**

Add to `tests/api/test_runs.py`, matching the existing
`test_create_run_materializes_and_registers_with_scheduler` pattern exactly:

```python
@pytest.mark.asyncio
async def test_create_run_accepts_and_persists_a_driver_choice(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "driver": "codex",
        },
    )
    assert run_resp.status_code == 201, run_resp.text
    assert run_resp.json()["data"]["driver"] == "codex"
```

- [ ] **Step 11: Run test, verify fail then pass**

Run: `uv run pytest tests/api/test_runs.py -k driver_choice -v`
Expected: fails before Step 9, passes after.

- [ ] **Step 12: Wire `--driver` into `foundry run`**

In `src/foundry/cli.py`, add the import and update the `run` command + `_run`:

```python
from foundry.drivers.factory import make_driver
```

```python
@app.command()
def run(
    playbook_path: str, project_path: str = ".", db: str = "foundry.db", driver: str = "fake"
) -> None:
    run_id, complete, pending_count = asyncio.run(_run(playbook_path, project_path, db, driver))
    ...


async def _run(playbook_path: str, project_path: str, db: str, driver_name: str = "fake") -> tuple[str, bool, int]:
    ...
    run_row = await store.create_run(
        project.id, playbook_path, playbook.description or playbook.id,
        pack_version_pin=pack_version_pin, driver=driver_name,
    )
    await materialize(playbook, run_row.id, store)

    worktree_manager = WorktreeManager(base_dir=os.path.join(project_path, ".foundry", "worktrees"))
    kg_snapshot = build_kg(project_path)
    orchestrator = Orchestrator(
        store,
        make_driver(driver_name, playbook),
        playbook,
        worktree_manager=worktree_manager,
        project_path=project_path,
        kg_snapshot=kg_snapshot,
        pack=resolve_pack_manifest(playbook_path),
    )
    ...
```

(Remove the now-unused `script = {...}` line and `FakeDriver`/`FakeStepScript`
import from this function if nothing else in `cli.py` needs them — check with
`grep -n "FakeDriver\|FakeStepScript" src/foundry/cli.py` first, since
`_recover_active_runs` also uses them today and this step changes that too, in
Step 14 below.)

- [ ] **Step 13: Run existing + new CLI tests**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all PASS — default `driver="fake"` on both the Typer option and
`_run`'s parameter preserves current behavior for every test that doesn't pass
`--driver`.

- [ ] **Step 14: Wire `driver` into `_recover_active_runs`**

In `src/foundry/cli.py`, update `_recover_active_runs` (building on Task 1
Step 14's version):

```python
        scheduler.register(
            active_run.id,
            make_driver(active_run.driver, playbook),
            playbook,
            gate_overrides=active_run.gate_overrides_json or None,
            project_path=project_path,
            worktree_manager=WorktreeManager(base_dir=os.path.join(project_path, ".foundry", "worktrees")),
            kg_snapshot=build_kg(project_path),
            pack=resolve_pack_manifest(active_run.playbook_ref),
        )
```

- [ ] **Step 15: Write the failing recovery test**

Add to `tests/test_cli_recovery.py`:

```python
@pytest.mark.asyncio
async def test_recover_active_runs_reconstructs_the_persisted_driver(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj", str(tmp_path))
    run = await store.create_run(project.id, FIXTURE, "recovered run", driver="codex")

    scheduler = Scheduler(store)
    await _recover_active_runs(store, scheduler)

    orchestrator = scheduler._orchestrators[run.id]
    from foundry.drivers.codex import CodexDriver
    assert isinstance(orchestrator.driver, CodexDriver)

    await store.stop()
```

- [ ] **Step 16: Run test, verify fail then pass**

Run: `uv run pytest tests/test_cli_recovery.py -k persisted_driver -v`
Expected: fails before Step 14, passes after.

- [ ] **Step 17: Run full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 18: Commit**

```bash
git add src/foundry/drivers/factory.py src/foundry/store/models.py src/foundry/store/store.py \
        src/foundry/api/routes/runs.py src/foundry/cli.py \
        tests/drivers/test_factory.py tests/api/test_runs.py tests/test_cli.py tests/test_cli_recovery.py \
        tests/store/
git commit -m "feat(drivers): add driver-selection plumbing (factory, --driver flag, Run.driver persistence)

CodexDriver has been fully built and tested since M2 with zero
non-test references anywhere -- foundry run and POST /api/runs could
only ever construct FakeDriver, with no flag or field to choose
otherwise. make_driver() centralizes the choice; Run.driver persists
it (same pattern as pack_version_pin) so restart-recovery reconstructs
the same driver instead of silently reverting to fake."
```

---

### Task 6: ClaudeCodeDriver

Mirrors `CodexDriver` exactly in shape and in every driver-spec requirement from
design doc §8 (process exit authoritative, log-file tailing from a persisted
offset, process-group reap on every session end, ≥1MB readline limit) — the
only real difference is the CLI invocation and normalization function.

**Files:**
- Create: `src/foundry/drivers/claude_code.py`
- Create: `tests/fixtures/fake_claude_cli.sh`
- Create: `tests/drivers/test_claude_code.py`
- Modify: `src/foundry/drivers/factory.py` (uncomment/finalize the `claude` branch — no-op if Task 5 already left it as a local import, otherwise add it)

**Interfaces:**
- Produces: `ClaudeCodeDriver(cli_path: str = "claude", session_log_dir: str | Path = "/tmp/foundry-claude-sessions")`
  implementing the `AgentDriver` protocol (`spawn`, `stream_events`, `cancel`,
  `adopt`, `health`) — identical method surface to `CodexDriver`.

- [ ] **Step 1: Create the fixture CLI**

Create `tests/fixtures/fake_claude_cli.sh`:

```bash
#!/usr/bin/env bash
# tests/fixtures/fake_claude_cli.sh
# Stands in for `claude -p --output-format stream-json` in tests -- never
# invoked in production, never makes a network call. Emits a minimal JSONL
# stream to stdout mimicking the normalized shape ClaudeCodeDriver expects,
# then exits 0.
set -euo pipefail
echo '{"type":"tool_call","tool":"read_file"}'
sleep 0.05

if [[ -n "${CLAUDE_TEST_GRANDCHILD_PID_FILE:-}" ]]; then
  sleep 30 &
  echo $! > "$CLAUDE_TEST_GRANDCHILD_PID_FILE"
fi

echo '{"type":"completed","artifact":{"diff":"fake claude diff"}}'
exit 0
```

- [ ] **Step 2: Write the failing driver tests (mirror `test_codex.py` exactly)**

Create `tests/drivers/test_claude_code.py` — copy the structure of
`tests/drivers/test_codex.py` wholesale, replacing `CodexDriver` with
`ClaudeCodeDriver`, `fake_codex_cli.sh` with `fake_claude_cli.sh`, and
`CODEX_TEST_GRANDCHILD_PID_FILE` with `CLAUDE_TEST_GRANDCHILD_PID_FILE`:

```python
import os
import stat
import subprocess
from pathlib import Path

import pytest

from foundry.drivers.base import SessionSpec
from foundry.drivers.claude_code import ClaudeCodeDriver

FIXTURE = str(Path(__file__).parent.parent / "fixtures" / "fake_claude_cli.sh")


def _spec(unit_id="u1", run_id="r1", step_id="s1") -> SessionSpec:
    return SessionSpec(
        cwd=".",
        prompt="do the thing",
        model="claude-fake",
        tool_policy={},
        mcp_servers=[],
        env={},
        internal_endpoint="",
        internal_secret="",
        unit_id=unit_id,
        run_id=run_id,
        step_id=step_id,
    )


@pytest.mark.asyncio
async def test_spawn_and_stream_events_normalizes_the_fixture_output(tmp_path):
    os.chmod(FIXTURE, os.stat(FIXTURE).st_mode | stat.S_IEXEC)
    driver = ClaudeCodeDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())

    kinds = []
    async for ev in driver.stream_events(handle):
        kinds.append(ev.kind)

    assert "tool_call" in kinds
    assert kinds[-1] == "completed"


@pytest.mark.asyncio
async def test_process_exit_is_authoritative_not_stream_eof(tmp_path):
    driver = ClaudeCodeDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())

    events = [ev async for ev in driver.stream_events(handle)]
    health = driver.health(handle)
    assert health.alive is False
    assert events


def test_adopt_returns_empty_when_no_sessions_recorded(tmp_path):
    driver = ClaudeCodeDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    assert driver.adopt() == []


def test_cancel_is_safe_on_already_finished_session(tmp_path):
    driver = ClaudeCodeDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())
    driver.cancel(handle)


def _pid_alive(pid: int) -> bool:
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    state = result.stdout.strip()
    return bool(state) and "Z" not in state


@pytest.mark.asyncio
async def test_reap_sweeps_the_whole_process_group_not_just_the_leader(tmp_path, monkeypatch):
    marker = tmp_path / "grandchild.pid"
    monkeypatch.setenv("CLAUDE_TEST_GRANDCHILD_PID_FILE", str(marker))

    driver = ClaudeCodeDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())

    async for _ in driver.stream_events(handle):
        pass

    assert marker.exists(), "fixture never wrote the grandchild pid marker"
    grandchild_pid = int(marker.read_text().strip())
    assert not _pid_alive(grandchild_pid), (
        "grandchild survived stream_events()'s _reap() call -- process group was not swept"
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/drivers/test_claude_code.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.drivers.claude_code'`

- [ ] **Step 4: Implement `ClaudeCodeDriver` (copy `codex.py`, change CLI invocation)**

Create `src/foundry/drivers/claude_code.py` as a structural copy of
`src/foundry/drivers/codex.py`: same imports, same `_READLINE_LIMIT`, and every
method (`spawn`, `stream_events`, `cancel`, `adopt`, `health`, `_reap`) copied
verbatim except:

1. Class name `CodexDriver` → `ClaudeCodeDriver`.
2. `__init__`'s default `cli_path: str = "codex"` → `"claude"`, default
   `session_log_dir` → `"/tmp/foundry-claude-sessions"`.
3. `spawn`'s subprocess invocation — per design doc §8, the real CLI needs
   `-p --output-format stream-json` flags:

   ```python
       process = subprocess.Popen(  # noqa: S603 - cli_path is operator-configured, not user input
           [self.cli_path, "-p", "--output-format", "stream-json"],
           stdout=log_file,
           stderr=subprocess.STDOUT,
           start_new_session=True,
       )
   ```

4. The module-level `_normalize(record)` function is copied unchanged — it
   already only depends on the `type` key being one of
   `tool_call | text | usage | completed | failed`, which is exactly the shape
   both `codex.py`'s and this driver's own test fixtures emit. (If a real
   `claude -p --output-format stream-json` session is exercised manually during
   review and its actual field names differ, adjust `_normalize` then — the
   fixture-driven test suite is the source of truth for CI either way, per the
   Global Constraints' "no live API access to test.")

Every comment explaining *why* (the driver-spec requirements 1-4, the pgid
capture-at-spawn-time reasoning, the `_reap` dead-code-bug history) should be
copied along with the code it documents — those reasons apply identically here.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/drivers/test_claude_code.py -v`
Expected: PASS — all 5 tests (mirroring all 5 in `test_codex.py`).

- [ ] **Step 6: Finalize the factory's `claude` branch and its test**

If Task 5 already landed with the local-import version in
`src/foundry/drivers/factory.py`, no change needed — it now resolves. Add to
`tests/drivers/test_factory.py`:

```python
def test_make_driver_claude_builds_a_claude_code_driver():
    from foundry.drivers.claude_code import ClaudeCodeDriver

    driver = make_driver("claude")
    assert isinstance(driver, ClaudeCodeDriver)
```

- [ ] **Step 7: Run test to verify it passes**

Run: `uv run pytest tests/drivers/test_factory.py -v`
Expected: all PASS, including the new `claude` case.

- [ ] **Step 8: Run full suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add src/foundry/drivers/claude_code.py tests/fixtures/fake_claude_cli.sh \
        tests/drivers/test_claude_code.py tests/drivers/test_factory.py \
        src/foundry/drivers/factory.py
git commit -m "feat(drivers): add ClaudeCodeDriver

Mirrors CodexDriver's shape and every driver-spec requirement from
design doc §8 (process-exit-authoritative, log-file tailing, pgid
reap, readline limit) -- M0 exit criterion (b), never met until now.
Fixture-script-driven tests only, no live API calls, same pattern as
the existing Codex test suite."
```

---

## Final verification (after all 6 tasks)

- [ ] Run: `uv run ruff check . && uv run ruff format --check . && uv run pytest -q`
  Expected: all clean, all tests pass.
- [ ] Confirm no unintended production-path drift: `grep -rn "model=\"fake\"" src/foundry/orchestrator/tick.py`
  Expected: no matches (both hardcoded sites replaced in Task 3).
- [ ] Confirm `CodexDriver`/`ClaudeCodeDriver` are now reachable outside tests:
  `grep -rln "CodexDriver\|ClaudeCodeDriver" src/foundry/ | grep -v /tests/`
  Expected: `src/foundry/drivers/factory.py` (plus the driver files themselves).
