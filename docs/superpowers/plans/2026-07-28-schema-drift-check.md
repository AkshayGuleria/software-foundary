# Schema Drift Check Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catch a stale db file (tables missing columns the current SQLAlchemy models declare) at the point it's opened, with a clear message, instead of a cryptic `sqlite3.OperationalError: no such column` 500 from an unrelated query later.

**Architecture:** One detection function folded into `init_db` (the single function every db-opening code path already calls) reflects each table's actual columns via `sqlalchemy.inspect` and compares against `Base.metadata`'s declared columns, raising `SchemaDriftError` if anything's missing. CLI commands catch it and exit 1 with a clear stderr message; demo hot-swap routes catch it and return a proper API error, relying on the swap mechanism's already-existing failure-recovery to leave the server on its last-known-good db.

**Tech Stack:** SQLAlchemy 2 async (existing `sqlalchemy.inspect`, no new dependency), Python 3.12+, pytest + pytest-asyncio, Typer, FastAPI.

## Global Constraints

- No new dependencies — `sqlalchemy.inspect` is already available.
- No schema changes — this check only reads schema, never writes it.
- No migration tooling added — deliberately out of scope, deferred to M5 per `docs/design-deviations.md`'s D1. This plan makes the *failure* clear, it does not fix the underlying db file automatically.
- Only missing *columns* on existing tables are drift. Missing *tables* are already handled correctly by `create_all` (unaffected by this plan). Extra/unexpected columns and type mismatches are explicitly ignored — not the failure mode being fixed, and SQLite's dynamic typing makes type-checking unreliable.
- `init_db`'s signature change (`db_path: str | None = None` added) must be backward compatible — every existing call site that doesn't pass it keeps working.

---

### Task 1: Detection mechanism in `store/db.py`

**Files:**
- Modify: `src/foundry/store/db.py`
- Test: `tests/store/test_db.py`

**Interfaces:**
- Consumes: `Base.metadata` (existing, from `foundry.store.models`).
- Produces: `class SchemaDriftError(Exception)`, `init_db(engine: AsyncEngine, db_path: str | None = None) -> None` (signature change — `db_path` is new and optional). Tasks 2-3 consume `SchemaDriftError` and update every `init_db` call site to pass `db_path`.

- [ ] **Step 1: Write the failing tests**

Add to `tests/store/test_db.py` (the file already has one test, `test_init_db_creates_tables_and_roundtrips_a_row` — leave it as-is, add these two after it):

```python
@pytest.mark.asyncio
async def test_init_db_raises_schema_drift_error_for_a_table_missing_columns(tmp_path):
    import sqlite3

    db_path = str(tmp_path / "stale.db")
    # Hand-craft a `projects` table matching the OLD schema (pre-G4 --
    # missing default_driver/default_token_budget/default_playbook_path),
    # bypassing create_all entirely so it's NOT the current shape -- this
    # simulates exactly the real incident: a db file whose table already
    # exists, just with fewer columns than the current model declares.
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute(
        """
        CREATE TABLE projects (
            id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            path VARCHAR NOT NULL,
            kg_status VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (name)
        )
        """
    )
    raw_conn.commit()
    raw_conn.close()

    engine = make_engine(db_path)

    with pytest.raises(SchemaDriftError) as exc_info:
        await init_db(engine, db_path)

    message = str(exc_info.value)
    assert "projects.default_driver" in message
    assert "projects.default_token_budget" in message
    assert "projects.default_playbook_path" in message
    assert db_path in message


@pytest.mark.asyncio
async def test_init_db_does_not_raise_on_a_second_call_against_an_up_to_date_db(tmp_path):
    db_path = str(tmp_path / "current.db")
    engine = make_engine(db_path)

    await init_db(engine, db_path)
    # Second call against the same, now-existing, fully-current db --
    # every table already exists with every column the model declares.
    # This must NOT raise: the check only flags MISSING columns, it
    # should never flag a table that's already fully up to date.
    await init_db(engine, db_path)
```

Add `SchemaDriftError` to this test file's existing import line: `from foundry.store.db import init_db, make_engine, make_sessionmaker` becomes `from foundry.store.db import SchemaDriftError, init_db, make_engine, make_sessionmaker`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/store/test_db.py -v`
Expected: FAIL — `ImportError: cannot import name 'SchemaDriftError'` (and the pre-existing test still passes, since `init_db(engine)` with no second argument is still valid at this point — the signature hasn't changed yet).

- [ ] **Step 3: Implement the check**

Replace `src/foundry/store/db.py` entirely with:

```python
from __future__ import annotations

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from foundry.store.models import Base


class SchemaDriftError(Exception):
    """Raised when an existing db file's tables are missing columns the
    current SQLAlchemy models declare.

    `Base.metadata.create_all` only creates missing *tables* -- it never
    adds missing *columns* to a table that already exists. A db file
    created before a later model change (e.g. a new column added to
    `Project`) stays permanently out of date until this is caught. There
    is no migration tooling yet (see docs/design-deviations.md's D1,
    deliberately deferred to M5) -- this exists to make that failure
    mode a clear message instead of a cryptic `sqlite3.OperationalError:
    no such column` surfacing later from an unrelated query.
    """


def make_engine(db_path: str) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _find_schema_drift(sync_conn) -> list[str]:
    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    missing: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue  # create_all just created it fresh -- can't be missing columns
        actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in actual_columns:
                missing.append(f"{table_name}.{column.name}")
    return missing


async def init_db(engine: AsyncEngine, db_path: str | None = None) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        missing = await conn.run_sync(_find_schema_drift)
    if missing:
        raise SchemaDriftError(
            f"Schema drift in {db_path or '<unknown>'}: {', '.join(missing)} missing. "
            "Delete the db file and restart, or add the missing columns "
            "manually (no migration tooling yet)."
        )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/store/test_db.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS (273 before this task — every other call site still calls `init_db(engine)` with no second argument, which remains valid).

- [ ] **Step 6: Commit**

```bash
git add src/foundry/store/db.py tests/store/test_db.py
git commit -m "feat(store): detect schema drift in init_db

Base.metadata.create_all only creates missing tables, never adds
missing columns to ones that already exist -- so a db file created
before a later model change stays permanently out of date, silently,
until some unrelated query 500s with a cryptic 'no such column' error
deep in a SQLAlchemy traceback. init_db now reflects each table's
actual columns via sqlalchemy.inspect and compares against what
Base.metadata declares, raising SchemaDriftError with every missing
column named (not just the first) plus the db path and a suggested
fix, the moment the db is opened."
```

---

### Task 2: Wire `db_path` through every call site, CLI failure handling

**Files:**
- Modify: `src/foundry/cli.py`
- Modify: `src/foundry/api/bootstrap.py`
- Modify: `tests/api/conftest.py`
- Test: `tests/test_cli_recovery.py` (verify no regression — this file already tests `build_store_and_scheduler`-adjacent recovery behavior; no new tests needed here, see Step 5)
- Test: `tests/test_cli_schema_drift.py` (new)

**Interfaces:**
- Consumes: `SchemaDriftError`, `init_db(engine, db_path=None)` (Task 1).
- Produces: every `init_db` call site now passes its `db_path`; `foundry serve`/`run`/`demo-seed`/`archive-events` all exit 1 with a clear stderr message on drift instead of crashing with a raw traceback. `build_store_and_scheduler` (bootstrap.py) passes `db_path` through but does NOT catch `SchemaDriftError` itself — it propagates to whichever caller wraps it (Task 2's `_serve`, or Task 3's demo routes).

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_schema_drift.py`:

```python
import sqlite3

import pytest
import typer

from foundry.cli import _run, _serve


def _write_stale_projects_table(db_path: str) -> None:
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute(
        """
        CREATE TABLE projects (
            id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            path VARCHAR NOT NULL,
            kg_status VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (name)
        )
        """
    )
    raw_conn.commit()
    raw_conn.close()


@pytest.mark.asyncio
async def test_run_command_exits_cleanly_on_schema_drift(tmp_path):
    db_path = str(tmp_path / "stale.db")
    _write_stale_projects_table(db_path)

    fixture = "tests/orchestrator/fixtures/linear_demo.toml"
    with pytest.raises(typer.Exit) as exc_info:
        await _run(fixture, ".", db_path, "fake")

    assert exc_info.value.exit_code == 1


@pytest.mark.asyncio
async def test_serve_exits_cleanly_on_schema_drift(tmp_path):
    db_path = str(tmp_path / "stale.db")
    _write_stale_projects_table(db_path)

    with pytest.raises(typer.Exit) as exc_info:
        await _serve(db_path, "127.0.0.1", 0)

    assert exc_info.value.exit_code == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_schema_drift.py -v`
Expected: FAIL — `_run` currently lets `SchemaDriftError` propagate uncaught (not wrapped in `typer.Exit`), and `_serve` calls `build_store_and_scheduler` with no try/except at all around it, so both tests fail with an unhandled `SchemaDriftError` instead of the expected `typer.Exit`.

- [ ] **Step 3: Update `src/foundry/api/bootstrap.py`**

Change the import and pass `db_path` through in `build_store_and_scheduler`:

```python
from foundry.store.db import init_db, make_engine, make_sessionmaker
```

(unchanged import line — `init_db`'s signature already accepts the optional second argument from Task 1, no new import needed.)

```python
async def build_store_and_scheduler(db_path: str) -> tuple[AsyncEngine, Store, Scheduler]:
    """Stand up a fresh engine/Store/Scheduler for `db_path`, recovering any
    active runs and starting the scheduler's tick loop.

    Shared by `foundry serve`'s startup and the demo-mode hot-swap routes
    (`src/foundry/api/routes/demo.py`) so both paths recover runs identically.
    Auto-creates `db_path`'s parent directory if missing (e.g. the demo db's
    default `.foundry-demo/demo.db` won't exist on first activation).

    Raises `foundry.store.db.SchemaDriftError` (uncaught here -- propagates
    to the caller) if `db_path` already exists with a table missing columns
    the current models declare.
    """
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    engine = make_engine(db_path)
    await init_db(engine, db_path)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    scheduler = Scheduler(store)
    await recover_active_runs(store, scheduler)
    await scheduler.start()

    return engine, store, scheduler
```

(Only the `await init_db(engine)` line changes, to `await init_db(engine, db_path)`, plus the docstring addition — everything else in the function is unchanged.)

- [ ] **Step 4: Update `src/foundry/cli.py`**

Update the three `init_db(engine)` calls that don't yet pass a path, and wrap every `init_db`/`build_store_and_scheduler` call site in the CLI with `SchemaDriftError` handling. Add the import:

```python
from foundry.store.db import SchemaDriftError, init_db, make_engine, make_sessionmaker
```

In `_run`, wrap the existing `init_db` call (the `try/except (PlaybookLoadError, PlaybookLintError)` block below it is separate and unaffected — this is a new, earlier try/except around just the `init_db` call):

```python
async def _run(
    playbook_path: str, project_path: str, db: str, driver_name: str = "fake"
) -> tuple[str, bool, int]:
    engine = make_engine(db)
    try:
        await init_db(engine, db)
    except SchemaDriftError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
```

(The rest of `_run` — the `try/except (PlaybookLoadError, PlaybookLintError)` block onward — is unchanged.)

In `_archive_events`:

```python
async def _archive_events(db: str, archive_dir: str, older_than_days: int) -> None:
    os.makedirs(archive_dir, exist_ok=True)
    engine = make_engine(db)
    try:
        await init_db(engine, db)
    except SchemaDriftError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
```

(The rest of `_archive_events` is unchanged.)

In `_demo_seed`:

```python
async def _demo_seed(db: str, repos_dir: str, reset: bool = False) -> None:
    if reset:
        reset_sqlite_db(db, repos_dir)

    engine = make_engine(db)
    try:
        await init_db(engine, db)
    except SchemaDriftError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    await run_demo_seed(store, repos_dir)

    await store.stop()
```

(The rest of `_demo_seed` is unchanged.)

In `_serve` (currently has no try/except around `build_store_and_scheduler` at all):

```python
async def _serve(db: str, host: str, port: int) -> None:
    try:
        engine, store, scheduler = await build_store_and_scheduler(db)
    except SchemaDriftError as e:
        typer.echo(str(e), err=True)
        raise typer.Exit(1) from e

    api_app = create_app(store, scheduler, engine=engine, original_db_path=db)
    config = uvicorn.Config(api_app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    try:
        await server.serve()
    finally:
        await api_app.state.scheduler.stop()
        await api_app.state.store.stop()
```

(Only the top of the function changes — wraps `build_store_and_scheduler` in `try/except SchemaDriftError`. The `server.serve()`/`finally` block is unchanged.)

Note: `_events` (the `foundry events` command) does NOT call `init_db` at all today (it only tails already-existing events, never creates schema) — leave it untouched, this task doesn't add a call site there.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_schema_drift.py -v`
Expected: PASS (2 tests).

Run: `uv run pytest tests/test_cli_recovery.py -v`
Expected: PASS (4 tests, unchanged — confirms `build_store_and_scheduler`'s signature/behavior change didn't break existing recovery tests).

- [ ] **Step 6: Update `tests/api/conftest.py`**

Thread `db_path` through both fixtures' `init_db` calls. In `_make_store_scheduler_app`:

```python
async def _make_store_scheduler_app(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    engine = make_engine(db_path)
    await init_db(engine, db_path)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)
    app = create_app(store, scheduler)
    return engine, store, scheduler, app
```

In `demo_api_client`:

```python
    original_db = str(tmp_path / "foundry.db")
    demo_db = str(tmp_path / "demo" / "demo.db")
    demo_repos = str(tmp_path / "demo" / "repos")

    engine = make_engine(original_db)
    await init_db(engine, original_db)
    store = Store(engine, make_sessionmaker(engine))
```

(Only the two `init_db(engine)` → `init_db(engine, <path>)` lines change in each fixture — everything else is unchanged.)

- [ ] **Step 7: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS (273 baseline + 3 new tests from Task 1 + 2 new tests from this task = 278).

- [ ] **Step 8: Commit**

```bash
git add src/foundry/cli.py src/foundry/api/bootstrap.py tests/api/conftest.py tests/test_cli_schema_drift.py
git commit -m "feat(cli): exit cleanly on schema drift instead of crashing

foundry serve/run/demo-seed/archive-events now catch SchemaDriftError
around their init_db call and exit 1 with the clear message instead of
an unhandled-exception traceback. build_store_and_scheduler (shared by
foundry serve and the demo hot-swap routes) passes db_path through to
init_db but deliberately does not catch the error itself -- that's
each caller's job, since serve/CLI and the hot-swap API routes need
very different failure handling."
```

---

### Task 3: API error class + demo hot-swap route wiring

**Files:**
- Modify: `src/foundry/api/errors.py`
- Modify: `src/foundry/api/routes/demo.py`
- Test: `tests/api/test_demo.py`

**Interfaces:**
- Consumes: `SchemaDriftError` (Task 1), `_swap_database` (existing).
- Produces: `class SchemaDriftApiError(FoundryApiError)` (`status_code = 500`, `code = "SCHEMA_DRIFT"`). Nothing else consumes this — it's the terminal integration point, converting the plain Python exception into this API's standard error envelope shape.

- [ ] **Step 1: Write the failing test**

Add to `tests/api/test_demo.py`:

```python
import sqlite3


def _write_stale_projects_table(db_path: str) -> None:
    import os

    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute(
        """
        CREATE TABLE projects (
            id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            path VARCHAR NOT NULL,
            kg_status VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (name)
        )
        """
    )
    raw_conn.commit()
    raw_conn.close()


@pytest.mark.asyncio
async def test_demo_activate_returns_a_clear_error_on_schema_drift(demo_api_client):
    client, app = demo_api_client
    _write_stale_projects_table(app.state.demo_db_path)

    resp = await client.post("/api/demo/activate")

    assert resp.status_code == 500
    body = resp.json()["error"]
    assert body["code"] == "SCHEMA_DRIFT"
    assert "default_driver" in body["message"]

    # The server must be left on its original db, not wedged on the
    # broken demo db or on a stopped/disposed store -- the existing
    # mid-swap-failure recovery mechanism should have rebuilt app.state
    # back onto original_db_path.
    assert app.state.current_db_path == app.state.original_db_path
    projects = await app.state.store.list_projects()  # must not hang/raise
    assert projects == []


@pytest.mark.asyncio
async def test_demo_deactivate_returns_a_clear_error_on_schema_drift(demo_api_client):
    client, app = demo_api_client
    _write_stale_projects_table(app.state.original_db_path)

    resp = await client.post("/api/demo/deactivate")

    assert resp.status_code == 500
    body = resp.json()["error"]
    assert body["code"] == "SCHEMA_DRIFT"
    assert "default_driver" in body["message"]
```

(`demo_api_client`'s fixture already builds `app.state.original_db_path`/`app.state.demo_db_path` fresh via `init_db` before either test runs, so both start from a fully current schema — each test then deliberately corrupts ONE of the two db files with a stale table, targeting exactly the db path that test's route swaps *to*, before making the request.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_demo.py -k schema_drift -v`
Expected: FAIL — currently `SchemaDriftError` propagates out of `_swap_database` uncaught by the route, which FastAPI's default exception handling turns into a response that doesn't match this test's expected `error.code == "SCHEMA_DRIFT"` envelope shape (no handler is registered for a bare `SchemaDriftError`, only for `FoundryApiError` subclasses and `RequestValidationError`).

- [ ] **Step 3: Add `SchemaDriftApiError`**

In `src/foundry/api/errors.py`, add this class after the existing `ValidationApiError`:

```python
class SchemaDriftApiError(FoundryApiError):
    status_code = 500
    code = "SCHEMA_DRIFT"
```

- [ ] **Step 4: Wire the demo routes**

In `src/foundry/api/routes/demo.py`, update the import:

```python
from foundry.api.errors import ConflictError, SchemaDriftApiError
from foundry.store.db import SchemaDriftError
```

Wrap each of the three mutating routes' `_swap_database` call:

```python
@router.post("/demo/activate")
async def activate_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    try:
        await _swap_database(
            app, app.state.demo_db_path, reset=False, seed_if_empty=True, repos_dir=app.state.demo_repos_dir
        )
    except SchemaDriftError as e:
        raise SchemaDriftApiError(str(e)) from e
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())


@router.post("/demo/deactivate")
async def deactivate_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    if app.state.original_db_path is None:
        raise ConflictError("no original database configured for this server")
    try:
        await _swap_database(app, app.state.original_db_path, reset=False, seed_if_empty=False)
    except SchemaDriftError as e:
        raise SchemaDriftApiError(str(e)) from e
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())


@router.post("/demo/reseed")
async def reseed_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    if app.state.current_db_path != app.state.demo_db_path:
        raise ConflictError("demo mode is not active")
    try:
        await _swap_database(
            app, app.state.demo_db_path, reset=True, seed_if_empty=True, repos_dir=app.state.demo_repos_dir
        )
    except SchemaDriftError as e:
        raise SchemaDriftApiError(str(e)) from e
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())
```

(`demo_status` — the `GET` route — is unaffected, it never calls `_swap_database`.)

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_demo.py -k schema_drift -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS (278 baseline + 2 new tests = 280).

- [ ] **Step 7: Run `uv run ruff check` and `uv run ruff format --check`**

Run: `uv run ruff check src/foundry/store/db.py src/foundry/cli.py src/foundry/api/bootstrap.py src/foundry/api/errors.py src/foundry/api/routes/demo.py tests/`
Run: `uv run ruff format --check src/foundry/store/db.py src/foundry/cli.py src/foundry/api/bootstrap.py src/foundry/api/errors.py src/foundry/api/routes/demo.py tests/`
Expected: both clean (these also run automatically via the pre-commit hook, but confirm explicitly since this task touches five files across three layers).

- [ ] **Step 8: Commit**

```bash
git add src/foundry/api/errors.py src/foundry/api/routes/demo.py tests/api/test_demo.py
git commit -m "feat(api): return a clear error on schema drift during a demo hot-swap

New SchemaDriftApiError (500, code SCHEMA_DRIFT) converts the plain
SchemaDriftError _swap_database already lets propagate into this API's
standard error envelope, instead of a generic unhandled-exception 500.
The server is left on its last-known-good db either way -- that part
was already correct, via _swap_database's existing mid-swap-failure
recovery (rebuilds app.state against previous_db_path, re-raises) from
the demo-mode-hotswap plan's final fix round. This only fixes what
response shape the client actually sees."
```

---

## Final verification

- [ ] Run: `uv run pytest -q` — expect all backend tests passing (273 before this plan, 280 after).
- [ ] Confirm every `init_db` call site passes its db path: `grep -rn "init_db(" src/foundry/ tests/` should show `init_db(engine, db_path)` or `init_db(engine, <variable>)` at all 6 sites, none bare `init_db(engine)` except where intentionally testing the optional-arg default (Task 1's tests).
- [ ] Manually reproduce the original incident is now handled cleanly: `rm -f /tmp/schema-drift-check.db*; sqlite3 /tmp/schema-drift-check.db "CREATE TABLE projects (id VARCHAR NOT NULL, name VARCHAR NOT NULL, path VARCHAR NOT NULL, kg_status VARCHAR NOT NULL, status VARCHAR NOT NULL, created_at DATETIME NOT NULL, PRIMARY KEY (id), UNIQUE (name))"; uv run foundry serve --db /tmp/schema-drift-check.db` — expect a clear `Schema drift in /tmp/schema-drift-check.db: projects.default_driver, projects.default_token_budget, projects.default_playbook_path missing...` message on stderr and a non-zero exit, not a port opening. Clean up: `rm -f /tmp/schema-drift-check.db*`.
