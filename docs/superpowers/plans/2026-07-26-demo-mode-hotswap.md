# Demo Mode Hot-Swap (Part 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a running `foundry serve` process hot-swap its live database between the operator's real db and a throwaway demo db, at runtime, via a UI toggle — seeding the demo db automatically on first activation, with a "Reseed" action while active.

**Architecture:** A shared `build_store_and_scheduler(db_path)` helper (extracted from `foundry serve`'s own startup code, since both `serve` and the swap routes need to do the identical stop-old/build-new/recover-runs sequence) backs four new `/api/demo/*` FastAPI routes. Each mutating route stops the current `Scheduler`/`Store`, disposes the old engine, builds a fresh engine/`Store`/`Scheduler` for the target db (recovering any active runs into it), seeds it if empty, and reassigns `app.state.store`/`app.state.scheduler` in place — under an `asyncio.Lock` so concurrent swap requests can't race. `_get_store`-style route handlers already read `request.app.state.store` fresh per request, so no ASGI app restart is needed. The frontend adds a nav-header toggle that calls these routes and, on any successful swap, clears the whole TanStack Query cache and navigates to `/` (a deep-linked run/project id from before the swap won't exist against the new db).

**Tech Stack:** FastAPI, SQLAlchemy 2 async + aiosqlite (existing `Store`/`Scheduler`), React/Vite/TS + `@tanstack/react-query` + `react-router-dom` (existing frontend stack). Consumes Part 1's `foundry.demo.seed.run_demo_seed(store, base_dir)` (merged to `master` at `7135cc4`).

## Global Constraints

- No new dependencies (spec: "No new dependencies").
- Must never silently touch a real `foundry.db` by accident — deactivation always swaps back to the exact `original_db_path` the server was started with; the demo db lives at its own dedicated, non-overlapping path.
- All writes funnel through `Store`'s single-writer `write()`/`read()` methods (`CLAUDE.md`: "all writes funnel through one single-writer asyncio task") — no route or helper opens a second engine/session/connection directly; `engine.dispose()` (pool teardown, not a write) is the one exception, used only on the engine being retired.
- SQLite WAL mandatory (already the default via `make_engine`'s connect-time `PRAGMA journal_mode=WAL` — unchanged by this plan).
- Runs entirely offline; `FakeDriver`-first for anything that touches the orchestrator (unchanged — this plan seeds/serves data, it doesn't add new orchestrator behavior).
- Conventional commits (`feat:`, `fix:`, `test:`), one commit per task.
- Frontend: match existing patterns exactly — `apiFetch<T>` from `frontend/src/api/client.ts`, `ApiResponse<T>`/`Paging` shapes, Tailwind classes matching sibling nav/button elements, `useQuery`/`useMutation` from `@tanstack/react-query`.

---

### Task 1: Extract shared store/scheduler bootstrap

**Files:**
- Create: `src/foundry/api/bootstrap.py`
- Modify: `src/foundry/cli.py`
- Modify: `tests/test_cli_recovery.py`

**Interfaces:**
- Consumes: nothing new (moves existing `Store`/`Scheduler`/`make_engine`/`init_db`/`make_sessionmaker` usage already in `cli.py`).
- Produces: `recover_active_runs(store: Store, scheduler: Scheduler) -> None` (renamed, public version of `cli.py`'s former `_recover_active_runs`, identical behavior), `build_store_and_scheduler(db_path: str) -> tuple[AsyncEngine, Store, Scheduler]` (stands up a fresh engine/Store/Scheduler for `db_path`, recovers active runs, starts the scheduler), `reset_sqlite_db(db_path: str, repos_dir: str | None = None) -> None` (deletes a sqlite db file + WAL/SHM sidecars and optionally a repos dir — used by both `foundry demo-seed --reset` and the future `POST /api/demo/reseed` route). Tasks 2-4 consume `build_store_and_scheduler` and `reset_sqlite_db`.

- [ ] **Step 1: Write the failing test**

The existing recovery tests already exercise the behavior this task moves — they just import from the wrong place after the move. Update `tests/test_cli_recovery.py` to import from the new location (this IS the failing-test step: the import will fail until Step 3 creates the module):

```python
import pytest

from foundry.api.bootstrap import recover_active_runs
from foundry.api.scheduler import Scheduler
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
async def test_recover_active_runs_rehydrates_persisted_gate_overrides(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj", str(tmp_path))
    run = await store.create_run(project.id, FIXTURE, "recovered run")
    await store.update_run(run.id, gate_overrides_json={"implement": "approved"})

    assert run.status == "active"  # sanity: the recovery loop only picks up active runs

    scheduler = Scheduler(store)
    await recover_active_runs(store, scheduler)

    orchestrator = scheduler._orchestrators[run.id]
    assert orchestrator.gate_overrides == {"implement": "approved"}

    await store.stop()


@pytest.mark.asyncio
async def test_recover_active_runs_with_no_overrides_registers_with_none(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj2", str(tmp_path))
    run = await store.create_run(project.id, FIXTURE, "recovered run 2")
    # gate_overrides_json defaults to {} -- must normalize to an empty dict on
    # the Orchestrator, not crash or leave it None-vs-{} inconsistent.

    scheduler = Scheduler(store)
    await recover_active_runs(store, scheduler)

    orchestrator = scheduler._orchestrators[run.id]
    assert orchestrator.gate_overrides == {}

    await store.stop()


@pytest.mark.asyncio
async def test_recover_active_runs_skips_non_active_runs(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj3", str(tmp_path))
    run = await store.create_run(project.id, FIXTURE, "closed run")
    await store.update_run(run.id, status="closed")

    scheduler = Scheduler(store)
    await recover_active_runs(store, scheduler)

    assert run.id not in scheduler._orchestrators

    await store.stop()


@pytest.mark.asyncio
async def test_recover_active_runs_reconstructs_the_persisted_driver(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("proj", str(tmp_path))
    run = await store.create_run(project.id, FIXTURE, "recovered run", driver="codex")

    scheduler = Scheduler(store)
    await recover_active_runs(store, scheduler)

    orchestrator = scheduler._orchestrators[run.id]
    from foundry.drivers.codex import CodexDriver

    assert isinstance(orchestrator.driver, CodexDriver)

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_recovery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.api.bootstrap'`.

- [ ] **Step 3: Create `src/foundry/api/bootstrap.py`**

```python
from __future__ import annotations

import asyncio
import os
import shutil

from sqlalchemy.ext.asyncio import AsyncEngine

from foundry.api.scheduler import Scheduler
from foundry.drivers.factory import make_driver
from foundry.kg.service import build_kg
from foundry.orchestrator.worktrees import WorktreeManager
from foundry.packs.resolve import resolve_pack_manifest
from foundry.playbook.lint import PlaybookLintError
from foundry.playbook.loader import PlaybookLoadError, load_playbook
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def recover_active_runs(store: Store, scheduler: Scheduler) -> None:
    """Re-register every `status="active"` run with the scheduler on startup.

    This is the code path responsible for rehydrating each run's persisted
    `gate_overrides_json` back into its Orchestrator (via `Scheduler.register`'s
    `gate_overrides` kwarg) after a restart or a database hot-swap -- without
    it, a run created with gate overrides would silently lose them and any
    gate for a step created after the restart would revert to requiring
    manual approval.
    """
    active_runs = await store.list_runs(status="active")
    for active_run in active_runs:
        try:
            playbook = load_playbook(active_run.playbook_ref)
        except (PlaybookLoadError, PlaybookLintError):
            continue  # playbook file moved/changed since the run started; skip, don't crash startup
        project = await store.get_project(active_run.project_id)
        project_path = project.path if project is not None else "."
        scheduler.register(
            active_run.id,
            make_driver(active_run.driver, playbook),
            playbook,
            gate_overrides=active_run.gate_overrides_json or None,
            project_path=project_path,
            worktree_manager=WorktreeManager(base_dir=os.path.join(project_path, ".foundry", "worktrees")),
            kg_snapshot=await asyncio.to_thread(build_kg, project_path),
            pack=resolve_pack_manifest(active_run.playbook_ref),
        )


async def build_store_and_scheduler(db_path: str) -> tuple[AsyncEngine, Store, Scheduler]:
    """Stand up a fresh engine/Store/Scheduler for `db_path`, recovering any
    active runs and starting the scheduler's tick loop.

    Shared by `foundry serve`'s startup and the demo-mode hot-swap routes
    (`src/foundry/api/routes/demo.py`) so both paths recover runs identically.
    Auto-creates `db_path`'s parent directory if missing (e.g. the demo db's
    default `.foundry-demo/demo.db` won't exist on first activation).
    """
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    engine = make_engine(db_path)
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    scheduler = Scheduler(store)
    await recover_active_runs(store, scheduler)
    await scheduler.start()

    return engine, store, scheduler


def reset_sqlite_db(db_path: str, repos_dir: str | None = None) -> None:
    """Delete a sqlite db file (and its WAL/SHM sidecars) and, if given, a
    repos directory tree -- for idempotent re-seeding. Shared by `foundry
    demo-seed --reset` and `POST /api/demo/reseed`.
    """
    for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
        if os.path.exists(path):
            os.remove(path)
    if repos_dir is not None:
        shutil.rmtree(repos_dir, ignore_errors=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli_recovery.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Update `src/foundry/cli.py` to use the extracted module**

Replace the import block (lines 1-22) with:

```python
from __future__ import annotations

import asyncio
import os

import typer
import uvicorn

from foundry.api.app import create_app
from foundry.api.bootstrap import build_store_and_scheduler, reset_sqlite_db
from foundry.demo.seed import run_demo_seed
from foundry.drivers.factory import make_driver
from foundry.kg.service import build_kg
from foundry.orchestrator.tick import Orchestrator
from foundry.orchestrator.worktrees import WorktreeManager
from foundry.packs.resolve import resolve_pack_manifest, resolve_pack_version
from foundry.playbook.lint import PlaybookLintError, lint_plan_first
from foundry.playbook.loader import PlaybookLoadError, load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store
```

(Removed: `import shutil` — now only used inside `reset_sqlite_db`, which lives in `bootstrap.py`; `from foundry.api.scheduler import Scheduler` — no longer referenced directly in `cli.py` once `_serve` is updated below and `_recover_active_runs` is removed. Added: `from foundry.api.bootstrap import build_store_and_scheduler, reset_sqlite_db`.)

Replace the `_demo_seed` function (previously using inline WAL/SHM deletion) with:

```python
async def _demo_seed(db: str, repos_dir: str, reset: bool = False) -> None:
    if reset:
        reset_sqlite_db(db, repos_dir)

    engine = make_engine(db)
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    await run_demo_seed(store, repos_dir)

    await store.stop()
```

Delete the `_recover_active_runs` function entirely (its body moved to `bootstrap.py`'s `recover_active_runs` in Step 3).

Replace `_serve`'s prelude (the engine/store/scheduler construction + recovery + scheduler start) with a call to the new helper:

```python
async def _serve(db: str, host: str, port: int) -> None:
    engine, store, scheduler = await build_store_and_scheduler(db)

    api_app = create_app(store, scheduler)
    config = uvicorn.Config(api_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        await scheduler.stop()
        await store.stop()
```

- [ ] **Step 6: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS (254 before this task).

- [ ] **Step 7: Commit**

```bash
git add src/foundry/api/bootstrap.py src/foundry/cli.py tests/test_cli_recovery.py
git commit -m "refactor(api): extract store/scheduler bootstrap into a shared module

recover_active_runs and a new build_store_and_scheduler() (used by both
foundry serve and the upcoming demo-mode hot-swap routes) now live in
src/foundry/api/bootstrap.py instead of being cli.py-private. Also
extracts reset_sqlite_db(), reused by foundry demo-seed --reset and the
upcoming POST /api/demo/reseed route -- same wipe-then-reseed logic,
one implementation."
```

---

### Task 2: `create_app` gains hot-swap state

**Files:**
- Modify: `src/foundry/api/app.py`
- Modify: `src/foundry/cli.py`
- Modify: `tests/api/conftest.py`

**Interfaces:**
- Consumes: `build_store_and_scheduler` (Task 1).
- Produces: `create_app(store, scheduler, engine=None, original_db_path=None, demo_db_path=".foundry-demo/demo.db", demo_repos_dir=".foundry-demo/repos") -> FastAPI` (all four new params optional, defaults preserve current behavior for every existing caller). App state gains: `app.state.engine`, `app.state.original_db_path`, `app.state.current_db_path` (initialized to `original_db_path`), `app.state.demo_db_path`, `app.state.demo_repos_dir`, `app.state.demo_swap_lock` (`asyncio.Lock`). A new pytest fixture `demo_api_client(tmp_path)` yielding `(client, app)` — Tasks 3-4 consume this fixture.

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_app.py` (create the file if it doesn't already exist — check first with `ls tests/api/test_app.py`; if it exists, append to it):

```python
import pytest

from foundry.api.app import create_app
from foundry.api.scheduler import Scheduler
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_create_app_defaults_current_db_path_to_original_db_path(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)

    app = create_app(store, scheduler, engine=engine, original_db_path=str(tmp_path / "foundry.db"))

    assert app.state.current_db_path == str(tmp_path / "foundry.db")
    assert app.state.demo_db_path == ".foundry-demo/demo.db"
    assert app.state.demo_repos_dir == ".foundry-demo/repos"
    assert app.state.demo_swap_lock is not None

    await store.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_app_without_original_db_path_defaults_to_none(tmp_path):
    # Every existing caller that doesn't care about demo mode (most test
    # fixtures) keeps working unchanged -- engine/original_db_path default
    # to None, current_db_path follows original_db_path (also None).
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)

    app = create_app(store, scheduler)

    assert app.state.engine is None
    assert app.state.original_db_path is None
    assert app.state.current_db_path is None

    await store.stop()
    await engine.dispose()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_app.py -v`
Expected: FAIL — `AttributeError: 'State' object has no attribute 'current_db_path'`.

- [ ] **Step 3: Update `src/foundry/api/app.py`**

Replace the full file with:

```python
from __future__ import annotations

import asyncio

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncEngine

from foundry.api.errors import (
    FoundryApiError,
    foundry_api_error_handler,
    request_validation_error_handler,
)
from foundry.api.routes.gates import router as gates_router
from foundry.api.routes.knowledge import router as knowledge_router
from foundry.api.routes.memory import router as memory_router
from foundry.api.routes.metrics import router as metrics_router
from foundry.api.routes.packs import router as packs_router
from foundry.api.routes.portfolio import router as portfolio_router
from foundry.api.routes.projects import router as projects_router
from foundry.api.routes.queue import router as queue_router
from foundry.api.routes.runs import router as runs_router
from foundry.api.routes.sessions import router as sessions_router
from foundry.api.routes.stream import router as stream_router
from foundry.api.scheduler import Scheduler
from foundry.store.store import Store


def create_app(
    store: Store,
    scheduler: Scheduler,
    engine: AsyncEngine | None = None,
    original_db_path: str | None = None,
    demo_db_path: str = ".foundry-demo/demo.db",
    demo_repos_dir: str = ".foundry-demo/repos",
) -> FastAPI:
    app = FastAPI(title="Foundry API")
    app.state.store = store
    app.state.scheduler = scheduler
    app.state.engine = engine
    app.state.original_db_path = original_db_path
    app.state.current_db_path = original_db_path
    app.state.demo_db_path = demo_db_path
    app.state.demo_repos_dir = demo_repos_dir
    app.state.demo_swap_lock = asyncio.Lock()

    app.add_exception_handler(FoundryApiError, foundry_api_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)

    app.include_router(projects_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(gates_router, prefix="/api")
    app.include_router(stream_router, prefix="/api")
    app.include_router(metrics_router, prefix="/api")
    app.include_router(portfolio_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")
    app.include_router(memory_router, prefix="/api")
    app.include_router(knowledge_router, prefix="/api")
    app.include_router(packs_router, prefix="/api")
    app.include_router(queue_router, prefix="/api")

    @app.get("/api/_health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
```

(The demo router isn't registered yet — Task 3 adds `from foundry.api.routes.demo import router as demo_router` and its `include_router` call, since the module doesn't exist until then.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_app.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Wire `original_db_path`/`engine` into `foundry serve`, and fix a latent shutdown-safety gap**

In `src/foundry/cli.py`, update `_serve` (from Task 1's version):

```python
async def _serve(db: str, host: str, port: int) -> None:
    engine, store, scheduler = await build_store_and_scheduler(db)

    api_app = create_app(store, scheduler, engine=engine, original_db_path=db)
    config = uvicorn.Config(api_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        # Read from api_app.state, not the `scheduler`/`store` locals above:
        # once the demo-mode hot-swap routes exist (Task 3-4), a swap
        # reassigns app.state.store/scheduler to brand-new instances built
        # for a different db. Stopping the *original* local-variable
        # instances at shutdown would leave whichever instances are
        # actually live (and holding the real writer task / tick loop) never
        # cleanly stopped.
        await api_app.state.scheduler.stop()
        await api_app.state.store.stop()
```

- [ ] **Step 6: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Add the `demo_api_client` fixture**

In `tests/api/conftest.py`, add this fixture after the existing `api_client` fixture (don't modify `_make_store_scheduler_app` or `api_client` — this is a new, separate fixture so existing tests are unaffected):

```python
@pytest_asyncio.fixture
async def demo_api_client(tmp_path):
    """Like `api_client`, but wired for demo-mode hot-swap testing: a real
    `original_db_path`/`engine`, and demo db/repos paths under `tmp_path`
    (never the real `.foundry-demo/` default -- that would pollute the repo
    working directory when tests run from the repo root).
    """
    original_db = str(tmp_path / "foundry.db")
    demo_db = str(tmp_path / "demo" / "demo.db")
    demo_repos = str(tmp_path / "demo" / "repos")

    engine = make_engine(original_db)
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)
    app = create_app(
        store,
        scheduler,
        engine=engine,
        original_db_path=original_db,
        demo_db_path=demo_db,
        demo_repos_dir=demo_repos,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, app

    # Read from app.state, not the `store`/`engine` locals -- same reasoning
    # as _serve's shutdown fix: a swap during the test replaces these.
    await app.state.store.stop()
    if app.state.engine is not None:
        await app.state.engine.dispose()
```

- [ ] **Step 8: Run the full backend suite once more**

Run: `uv run pytest -q`
Expected: all PASS (the new fixture isn't used by any test yet, so this just confirms nothing broke).

- [ ] **Step 9: Commit**

```bash
git add src/foundry/api/app.py src/foundry/cli.py tests/api/test_app.py tests/api/conftest.py
git commit -m "feat(api): thread engine/original-db-path/demo-path state through create_app

create_app() gains four optional params (engine, original_db_path,
demo_db_path, demo_repos_dir) plus a demo_swap_lock -- all defaulted so
every existing caller is unaffected. foundry serve now passes its real
engine/db path through. _serve's shutdown now reads app.state.store/
scheduler instead of closed-over locals, since the upcoming hot-swap
routes will reassign those references at runtime."
```

---

### Task 3: Demo status + activate routes

**Files:**
- Create: `src/foundry/api/routes/demo.py`
- Modify: `src/foundry/api/app.py`
- Test: `tests/api/test_demo.py`

**Interfaces:**
- Consumes: `build_store_and_scheduler`, `reset_sqlite_db` (Task 1); `demo_api_client` fixture (Task 2); `run_demo_seed` (Part 1, `foundry.demo.seed`).
- Produces: `DemoStatusOut` (pydantic: `active: bool`, `db_path: str`), `_status_out(app: FastAPI) -> DemoStatusOut`, `_swap_database(app: FastAPI, target_db_path: str, *, reset: bool, seed_if_empty: bool, repos_dir: str | None = None) -> None`, `GET /api/demo/status`, `POST /api/demo/activate`. Task 4 extends this same file with `POST /api/demo/deactivate` and `POST /api/demo/reseed`, reusing `_swap_database`/`_status_out`.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_demo.py`:

```python
import pytest


@pytest.mark.asyncio
async def test_demo_status_reports_inactive_on_original_db(demo_api_client):
    client, app = demo_api_client

    resp = await client.get("/api/demo/status")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["active"] is False
    assert body["db_path"] == app.state.original_db_path


@pytest.mark.asyncio
async def test_demo_activate_swaps_to_demo_db_and_seeds_when_empty(demo_api_client):
    client, app = demo_api_client

    resp = await client.post("/api/demo/activate")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["active"] is True
    assert body["db_path"] == app.state.demo_db_path

    projects = await app.state.store.list_projects()
    assert len(projects) == 5


@pytest.mark.asyncio
async def test_demo_activate_does_not_reseed_when_already_seeded(demo_api_client):
    client, app = demo_api_client

    await client.post("/api/demo/activate")
    first_count = len(await app.state.store.list_projects())

    resp = await client.post("/api/demo/activate")

    assert resp.status_code == 200
    second_count = len(await app.state.store.list_projects())
    assert first_count == second_count == 5


@pytest.mark.asyncio
async def test_demo_activate_recovers_active_runs_into_the_new_scheduler(demo_api_client):
    client, app = demo_api_client

    await client.post("/api/demo/activate")

    # The seeded dataset always includes runs left in status="active" (e.g.
    # the pending-human-gate and pending-agent-gate scenarios). Activation's
    # swap must recover them into the freshly built scheduler, not just seed
    # the rows -- otherwise those runs would sit inert, never ticked again.
    active_runs = await app.state.store.list_runs(status="active")
    assert active_runs
    registered_ids = set(app.state.scheduler._orchestrators.keys())
    assert {r.id for r in active_runs} <= registered_ids
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_demo.py -v`
Expected: FAIL — `ModuleNotFoundError` (no `demo` route module) and `fixture 'demo_api_client' not found` resolves fine (Task 2 already added it), but the routes don't exist yet so requests 404.

- [ ] **Step 3: Create `src/foundry/api/routes/demo.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel

from foundry.api.bootstrap import build_store_and_scheduler, reset_sqlite_db
from foundry.api.errors import ConflictError
from foundry.api.schemas import ApiResponse, Paging
from foundry.demo.seed import run_demo_seed

router = APIRouter()


class DemoStatusOut(BaseModel):
    active: bool
    db_path: str


def _status_out(app: FastAPI) -> DemoStatusOut:
    current = app.state.current_db_path
    original = app.state.original_db_path
    return DemoStatusOut(active=current != original, db_path=current)


async def _swap_database(
    app: FastAPI, target_db_path: str, *, reset: bool, seed_if_empty: bool, repos_dir: str | None = None
) -> None:
    """Stop the current Store/Scheduler, dispose the old engine, build a
    fresh engine/Store/Scheduler for `target_db_path` (recovering any active
    runs into it), seed it if empty, and reassign app.state -- all under a
    lock so two swap requests in flight at once can't race each other.
    """
    async with app.state.demo_swap_lock:
        await app.state.scheduler.stop()
        await app.state.store.stop()
        if app.state.engine is not None:
            await app.state.engine.dispose()

        if reset:
            reset_sqlite_db(target_db_path, repos_dir)

        engine, store, scheduler = await build_store_and_scheduler(target_db_path)

        if seed_if_empty:
            projects = await store.list_projects()
            if not projects:
                await run_demo_seed(store, repos_dir)

        app.state.engine = engine
        app.state.store = store
        app.state.scheduler = scheduler
        app.state.current_db_path = target_db_path


@router.get("/demo/status")
async def demo_status(request: Request) -> ApiResponse[DemoStatusOut]:
    return ApiResponse[DemoStatusOut](data=_status_out(request.app), paging=Paging.none())


@router.post("/demo/activate")
async def activate_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    await _swap_database(
        app, app.state.demo_db_path, reset=False, seed_if_empty=True, repos_dir=app.state.demo_repos_dir
    )
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())
```

- [ ] **Step 4: Register the router**

In `src/foundry/api/app.py`, insert the import in alphabetical position — between the `from foundry.api.errors import (...)` block and `from foundry.api.routes.gates import router as gates_router` (`routes.demo` sorts before `routes.gates`; ruff's import-sort check runs in the pre-commit hook and will reject it out of order):

```python
from foundry.api.routes.demo import router as demo_router
from foundry.api.routes.gates import router as gates_router
```

And register it alongside the other `include_router` calls — add it as the last one, after `queue_router` (registration order doesn't affect routing here since none of these prefixes overlap, so appending is simplest and matches this file's existing append-at-the-end pattern for `queue_router` itself):

```python
    app.include_router(queue_router, prefix="/api")
    app.include_router(demo_router, prefix="/api")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_demo.py -v`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add src/foundry/api/routes/demo.py src/foundry/api/app.py tests/api/test_demo.py
git commit -m "feat(api): add demo mode status + activate routes

GET /api/demo/status reports whether the server is currently on its
demo db. POST /api/demo/activate hot-swaps to it, seeding automatically
on first activation (detected via an empty project list, not file
existence) via the same run_demo_seed() the CLI's demo-seed command
uses. The swap itself (stop scheduler/store, dispose old engine, build
fresh ones with active-run recovery, reassign app.state) is wrapped in
a lock so concurrent swap requests can't race."
```

---

### Task 4: Demo deactivate + reseed routes

**Files:**
- Modify: `src/foundry/api/routes/demo.py`
- Test: `tests/api/test_demo.py`

**Interfaces:**
- Consumes: `_swap_database`, `_status_out`, `DemoStatusOut` (Task 3).
- Produces: `POST /api/demo/deactivate`, `POST /api/demo/reseed`. Nothing further consumes these — this is the last backend task.

- [ ] **Step 1: Write the failing test**

Add `import asyncio` to the top of `tests/api/test_demo.py` (alongside the existing `import pytest`, not at the bottom — ruff's import-order check runs in this repo's pre-commit hook and will reject a mid-file import):

```python
import asyncio

import pytest
```

Then append these test functions at the end of the file:

```python
@pytest.mark.asyncio
async def test_demo_deactivate_swaps_back_to_original_db(demo_api_client):
    client, app = demo_api_client
    await app.state.store.create_project("pre-existing", "/tmp/pre-existing")

    await client.post("/api/demo/activate")
    resp = await client.post("/api/demo/deactivate")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["active"] is False
    assert body["db_path"] == app.state.original_db_path

    projects = await app.state.store.list_projects()
    assert [p.name for p in projects] == ["pre-existing"]


@pytest.mark.asyncio
async def test_demo_deactivate_when_already_inactive_does_not_crash(demo_api_client):
    client, _app = demo_api_client

    resp = await client.post("/api/demo/deactivate")

    assert resp.status_code == 200
    assert resp.json()["data"]["active"] is False


@pytest.mark.asyncio
async def test_demo_reseed_wipes_and_reseeds_in_place(demo_api_client):
    client, app = demo_api_client
    await client.post("/api/demo/activate")
    await app.state.store.create_project("manually-added", "/tmp/manual")
    assert len(await app.state.store.list_projects()) == 6

    resp = await client.post("/api/demo/reseed")

    assert resp.status_code == 200
    projects = await app.state.store.list_projects()
    assert len(projects) == 5
    assert "manually-added" not in [p.name for p in projects]


@pytest.mark.asyncio
async def test_demo_reseed_409_when_not_active(demo_api_client):
    client, _app = demo_api_client

    resp = await client.post("/api/demo/reseed")

    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_concurrent_activate_requests_do_not_double_seed(demo_api_client):
    client, app = demo_api_client

    responses = await asyncio.gather(
        client.post("/api/demo/activate"),
        client.post("/api/demo/activate"),
    )

    assert all(r.status_code == 200 for r in responses)
    projects = await app.state.store.list_projects()
    assert len(projects) == 5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_demo.py -v`
Expected: FAIL — the 5 new tests 404 (no deactivate/reseed routes yet).

- [ ] **Step 3: Add the routes**

Append to `src/foundry/api/routes/demo.py` (after `activate_demo`):

```python
@router.post("/demo/deactivate")
async def deactivate_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    if app.state.original_db_path is None:
        raise ConflictError("no original database configured for this server")
    await _swap_database(app, app.state.original_db_path, reset=False, seed_if_empty=False)
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())


@router.post("/demo/reseed")
async def reseed_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    if app.state.current_db_path != app.state.demo_db_path:
        raise ConflictError("demo mode is not active")
    await _swap_database(
        app, app.state.demo_db_path, reset=True, seed_if_empty=True, repos_dir=app.state.demo_repos_dir
    )
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/api/test_demo.py -v`
Expected: PASS (9 tests total).

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/routes/demo.py tests/api/test_demo.py
git commit -m "feat(api): add demo mode deactivate + reseed routes

POST /api/demo/deactivate swaps back to the server's original db.
POST /api/demo/reseed 409s if demo mode isn't active (reseeding only
makes sense for the db you're currently on), otherwise wipes and
reseeds the demo db in place via reset_sqlite_db + run_demo_seed. Both
reuse Task 3's _swap_database, so concurrent activate/deactivate/reseed
calls all serialize on the same lock."
```

---

### Task 5: Frontend demo API client

**Files:**
- Create: `frontend/src/api/demo.ts`
- Test: `frontend/src/api/demo.test.ts`
- Modify: `frontend/src/api/types.ts`

**Interfaces:**
- Consumes: `apiFetch` (`frontend/src/api/client.ts`).
- Produces: `DemoStatus` type (`{ active: boolean; db_path: string }`), `getDemoStatus()`, `activateDemo()`, `deactivateDemo()`, `reseedDemo()` — all `Promise<DemoStatus>`. Task 6 consumes all four.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/api/demo.test.ts`:

```ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { activateDemo, deactivateDemo, getDemoStatus, reseedDemo } from "./demo";

describe("demo API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("getDemoStatus GETs /api/demo/status", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { active: false, db_path: "/tmp/foundry.db" }, paging: {} }),
    });

    const status = await getDemoStatus();

    expect(fetch).toHaveBeenCalledWith("/api/demo/status", undefined);
    expect(status.active).toBe(false);
  });

  it("activateDemo POSTs to /api/demo/activate", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { active: true, db_path: ".foundry-demo/demo.db" }, paging: {} }),
    });

    const status = await activateDemo();

    expect(fetch).toHaveBeenCalledWith("/api/demo/activate", { method: "POST" });
    expect(status.active).toBe(true);
  });

  it("deactivateDemo POSTs to /api/demo/deactivate", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { active: false, db_path: "/tmp/foundry.db" }, paging: {} }),
    });

    const status = await deactivateDemo();

    expect(fetch).toHaveBeenCalledWith("/api/demo/deactivate", { method: "POST" });
    expect(status.active).toBe(false);
  });

  it("reseedDemo POSTs to /api/demo/reseed", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { active: true, db_path: ".foundry-demo/demo.db" }, paging: {} }),
    });

    const status = await reseedDemo();

    expect(fetch).toHaveBeenCalledWith("/api/demo/reseed", { method: "POST" });
    expect(status.active).toBe(true);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/demo.test.ts`
Expected: FAIL — `Cannot find module './demo'`.

- [ ] **Step 3: Add the `DemoStatus` type**

Append to `frontend/src/api/types.ts`:

```ts
export interface DemoStatus {
  active: boolean;
  db_path: string;
}
```

- [ ] **Step 4: Create `frontend/src/api/demo.ts`**

```ts
import { apiFetch } from "./client";
import type { DemoStatus } from "./types";

export async function getDemoStatus(): Promise<DemoStatus> {
  const res = await apiFetch<DemoStatus>("/api/demo/status");
  return res.data;
}

export async function activateDemo(): Promise<DemoStatus> {
  const res = await apiFetch<DemoStatus>("/api/demo/activate", { method: "POST" });
  return res.data;
}

export async function deactivateDemo(): Promise<DemoStatus> {
  const res = await apiFetch<DemoStatus>("/api/demo/deactivate", { method: "POST" });
  return res.data;
}

export async function reseedDemo(): Promise<DemoStatus> {
  const res = await apiFetch<DemoStatus>("/api/demo/reseed", { method: "POST" });
  return res.data;
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/demo.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS (254 before this task — check actual current count in output, don't assume).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/demo.ts frontend/src/api/demo.test.ts frontend/src/api/types.ts
git commit -m "feat(frontend): add demo mode API client

getDemoStatus/activateDemo/deactivateDemo/reseedDemo wrap the four
new /api/demo/* backend routes, matching every other api/*.ts
module's apiFetch<T> + ApiResponse<T> pattern."
```

---

### Task 6: Demo mode toggle UI

**Files:**
- Create: `frontend/src/components/DemoModeToggle.tsx`
- Test: `frontend/src/components/DemoModeToggle.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getDemoStatus`, `activateDemo`, `deactivateDemo`, `reseedDemo`, `DemoStatus` (Task 5).
- Produces: `DemoModeToggle` (default export, no props) — rendered once in `App.tsx`'s header. Nothing further consumes it — this is the last task.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/DemoModeToggle.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import DemoModeToggle from "./DemoModeToggle";

function LocationMarker() {
  const location = useLocation();
  return <div data-testid="location">{location.pathname}</div>;
}

function renderWithProviders(initialPath = "/queue") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <LocationMarker />
        <Routes>
          <Route path="*" element={<DemoModeToggle />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("DemoModeToggle", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("shows a 'Demo mode' button when inactive, no Reseed button", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true, status: 200,
        json: async () => ({ data: { active: false, db_path: "/tmp/foundry.db" }, paging: {} }),
      }),
    );

    renderWithProviders();

    await waitFor(() => expect(screen.getByRole("button", { name: /demo mode/i })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: /reseed/i })).not.toBeInTheDocument();
  });

  it("shows 'Exit demo mode' and a Reseed button when active", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true, status: 200,
        json: async () => ({ data: { active: true, db_path: ".foundry-demo/demo.db" }, paging: {} }),
      }),
    );

    renderWithProviders();

    await waitFor(() => expect(screen.getByRole("button", { name: /exit demo mode/i })).toBeInTheDocument());
    expect(screen.getByRole("button", { name: /reseed/i })).toBeInTheDocument();
  });

  it("activating clears the cache (triggering a status refetch) and navigates to /", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/demo/status" && !init) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { active: false, db_path: "/tmp/foundry.db" }, paging: {} }),
        });
      }
      if (url === "/api/demo/activate") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { active: true, db_path: ".foundry-demo/demo.db" }, paging: {} }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderWithProviders("/queue");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole("button", { name: /^demo mode$/i })).toBeInTheDocument());
    expect(screen.getByTestId("location")).toHaveTextContent("/queue");

    await user.click(screen.getByRole("button", { name: /^demo mode$/i }));

    await waitFor(() => expect(screen.getByTestId("location")).toHaveTextContent("/"));
    // Cache clear -> the toggle's own status query loses its cached data and
    // refetches; the mock's status branch now needs to have been hit again
    // (activate response) with an updated status reflected in the button.
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /exit demo mode/i })).toBeInTheDocument(),
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/DemoModeToggle.test.tsx`
Expected: FAIL — `Cannot find module './DemoModeToggle'`.

- [ ] **Step 3: Create `frontend/src/components/DemoModeToggle.tsx`**

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { activateDemo, deactivateDemo, getDemoStatus, reseedDemo } from "../api/demo";

export default function DemoModeToggle() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { data: status } = useQuery({ queryKey: ["demo-status"], queryFn: getDemoStatus });

  const afterSwap = () => {
    // The entire database underneath the app just changed -- everything is
    // potentially stale, not just one query key. A deep-linked run/project
    // id from before the swap won't exist against the new db, so send the
    // user back to a page that doesn't depend on one.
    queryClient.clear();
    navigate("/");
  };

  const activateMutation = useMutation({ mutationFn: activateDemo, onSuccess: afterSwap });
  const deactivateMutation = useMutation({ mutationFn: deactivateDemo, onSuccess: afterSwap });
  const reseedMutation = useMutation({ mutationFn: reseedDemo, onSuccess: afterSwap });

  if (!status) {
    return null;
  }

  const pending = activateMutation.isPending || deactivateMutation.isPending || reseedMutation.isPending;

  return (
    <div className="ml-auto flex items-center gap-2">
      <button
        type="button"
        disabled={pending}
        onClick={() => (status.active ? deactivateMutation.mutate() : activateMutation.mutate())}
        className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500 disabled:opacity-50"
      >
        {status.active ? "Exit demo mode" : "Demo mode"}
      </button>
      {status.active && (
        <button
          type="button"
          disabled={pending}
          onClick={() => reseedMutation.mutate()}
          className="rounded border border-slate-700 px-3 py-1.5 text-sm text-slate-300 hover:border-orange-400 disabled:opacity-50"
        >
          Reseed
        </button>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/DemoModeToggle.test.tsx`
Expected: PASS (3 tests).

- [ ] **Step 5: Wire into `App.tsx`**

In `frontend/src/App.tsx`, add the import:

```tsx
import DemoModeToggle from "./components/DemoModeToggle";
```

Add `<DemoModeToggle />` inside the `<header>`, after the `<nav>` (the header is already `flex items-center gap-4`, and `DemoModeToggle`'s own `ml-auto` pushes it to the right edge):

```tsx
      <header className="flex items-center gap-4 border-b border-slate-800 px-6 py-4">
        <h1 className="text-lg font-semibold">Foundry</h1>
        <nav className="flex gap-3 text-sm">
          <NavLink to="/" end className="text-slate-400 hover:text-orange-400">
            Portfolio
          </NavLink>
          <NavLink to="/queue" className="text-slate-400 hover:text-orange-400">
            Queue
          </NavLink>
          <NavLink to="/projects" className="text-slate-400 hover:text-orange-400">
            Projects
          </NavLink>
          <NavLink to="/runs" className="text-slate-400 hover:text-orange-400">
            Runs
          </NavLink>
          <NavLink to="/knowledge" className="text-slate-400 hover:text-orange-400">
            Knowledge
          </NavLink>
          <NavLink to="/fleet" className="text-slate-400 hover:text-orange-400">
            Fleet
          </NavLink>
          <NavLink to="/metrics" className="text-slate-400 hover:text-orange-400">
            Metrics
          </NavLink>
          <NavLink to="/packs" className="text-slate-400 hover:text-orange-400">
            Packs
          </NavLink>
        </nav>
        <DemoModeToggle />
      </header>
```

- [ ] **Step 6: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 7: Manually verify end to end**

```bash
uv run foundry serve --db /tmp/foundry-hotswap-check.db
```

In a browser at `http://127.0.0.1:8000` (or wherever the frontend dev server proxies to — check `frontend/vite.config.ts` for the existing proxy setup if the frontend isn't served from the same origin): confirm the "Demo mode" button appears in the header, click it, confirm the page navigates to `/` and now shows 5 seeded projects on the portfolio view, confirm the button now reads "Exit demo mode" with a "Reseed" button beside it, click "Reseed" and confirm the data refreshes (still 5 projects, not 10), click "Exit demo mode" and confirm it navigates back to `/` showing the original (empty) db's portfolio view. Stop the server (Ctrl-C) and clean up: `rm -rf /tmp/foundry-hotswap-check.db .foundry-demo`.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/DemoModeToggle.tsx frontend/src/components/DemoModeToggle.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): add demo mode toggle to the nav header

Calls GET /api/demo/status on mount, POST /api/demo/activate or
/deactivate on toggle, POST /api/demo/reseed via a second button shown
only while active. Any successful swap clears the whole query cache
and navigates to / -- the database underneath the app just changed,
and a deep-linked run/project id from before the swap won't resolve
against the new one."
```

---

## Final verification

- [ ] Run: `uv run pytest -q` — expect all backend tests passing (254 before this plan, plus this plan's new tests).
- [ ] Run: `cd frontend && npx vitest run` — expect all frontend tests passing.
- [ ] Confirm the shared bootstrap actually is shared, not duplicated: `grep -n "def build_store_and_scheduler\|def recover_active_runs\|def reset_sqlite_db" src/foundry/api/bootstrap.py` should show exactly one definition of each, and `grep -rn "build_store_and_scheduler(" src/foundry/` should show it called from both `cli.py`'s `_serve` and `routes/demo.py`'s `_swap_database`.
- [ ] Confirm the spec's swap-mechanics list (stop scheduler → stop store → dispose engine → build fresh engine/store/scheduler with recovery → seed if needed → reassign `app.state` under a lock) is fully present in `_swap_database` — read `src/foundry/api/routes/demo.py` once end to end.
- [ ] Confirm no route or helper opens a second engine/session directly outside `Store`'s own `write()`/`read()` — `grep -n "sessionmaker()\|create_async_engine" src/foundry/api/routes/demo.py` should return nothing.
