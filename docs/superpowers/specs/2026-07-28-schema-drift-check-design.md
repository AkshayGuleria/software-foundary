# Startup schema-drift check — design

## Goal

Catch a stale SQLite db file (one whose tables predate a later `Base`
model change) at the point a db is opened, with a clear message — instead
of letting an unrelated query 500 later with a cryptic
`sqlite3.OperationalError: no such column: ...` deep in a SQLAlchemy
traceback.

## Why this needs its own design

This surfaced as a real incident: `/tmp/foundry.db`'s `projects` table
predated the G4 per-project-settings model change (missing
`default_driver`/`default_token_budget`/`default_playbook_path`), and
`GET /api/projects` 500'd after switching out of demo mode. Root cause
was schema drift, not a demo-mode bug — confirmed by reproducing cleanly
against a fresh db and only failing against the stale file
(`docs/superpowers/specs/2026-07-26-demo-mode-hotswap-design.md` and the
run-detail-upgrade work are unrelated; this bug predates both). This
codebase has no migration tooling (`Base.metadata.create_all` only
creates missing tables, never adds missing columns to existing ones —
deliberately deferred to M5, see `docs/design-deviations.md`'s D1), so
this class of bug will recur for any local dev db whenever a model gains
a column, until M5 ships real migrations. This design doesn't add
migrations — it makes the resulting failure mode clear instead of cryptic.

## Scope

**In scope:**
- A schema-drift check: for each table `Base.metadata` declares, compare
  its declared column names against what's actually reflected from the
  live database connection. Missing columns are drift.
- Enforced at every `init_db(engine)` call site (all 6 in the codebase:
  `foundry serve`, `foundry run`, `foundry demo-seed`, `foundry events`,
  the two test fixtures in `tests/api/conftest.py`, and — via
  `build_store_and_scheduler`, which calls `init_db` — every demo-mode
  hot-swap route) by folding the check into `init_db` itself, so no new
  call sites are needed anywhere.
- Clear failure messages naming every drifted `table.column`, not just
  the first one found, plus the db path and a one-line suggested fix.
- CLI commands (`serve`/`run`/`demo-seed`/`events`) refuse to start/run:
  clear stderr message, `typer.Exit(1)`.
- Demo hot-swap routes (`activate`/`deactivate`/`reseed`) reject the swap
  with a proper API error response (matching the existing
  `ErrorEnvelope` shape every other endpoint uses) and leave the server
  on its last-known-good db — this falls out of the mid-swap-failure
  recovery mechanism already built during the demo-mode-hotswap plan's
  final fix round (`_swap_database` already rebuilds against
  `previous_db_path` and re-raises on any exception from
  `build_store_and_scheduler`), not new machinery.

**Out of scope:**
- Actually adding missing columns automatically (that's migration
  tooling — explicitly deferred to M5, not something this check should
  attempt).
- Detecting extra/unexpected columns, or column type mismatches — not
  the failure mode this incident exposed, and SQLite's dynamic typing
  makes type-checking unreliable. Ignored entirely.
- Any change to `Base.metadata.create_all`'s own behavior (missing
  *tables* are still created normally, unaffected by this check).

## Design decisions

**1. Detection mechanism.** A new function in `src/foundry/store/db.py`
(the schema-management module `init_db` already lives in), called from
`init_db` immediately after `create_all`:

```python
async def _check_schema_drift(conn, db_path: str) -> None:
    inspector_columns = await conn.run_sync(
        lambda sync_conn: {
            table_name: {col["name"] for col in inspect(sync_conn).get_columns(table_name)}
            for table_name in Base.metadata.tables
        }
    )
    missing: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        actual = inspector_columns.get(table_name, set())
        for column in table.columns:
            if column.name not in actual:
                missing.append(f"{table_name}.{column.name}")
    if missing:
        raise SchemaDriftError(
            f"Schema drift in {db_path}: {', '.join(missing)} missing. "
            "Delete the db file and restart, or add the missing columns "
            "manually (no migration tooling yet)."
        )
```

Called inside the same `engine.begin()` block `create_all` already runs
in, so a single connection does both — no extra connection overhead. On
a freshly-created (or already-current) db, `inspector_columns` matches
`Base.metadata` exactly and this is a no-op.

**2. Error type.** `class SchemaDriftError(Exception)` defined in
`store/db.py` itself — plain Python exception, no FastAPI dependency,
since `store/db.py` is used by both the CLI (`cli.py`, no web framework
in play) and the API layer. Message format is fixed as shown above:
every drifted column listed, not truncated to the first one, so a single
run of `foundry serve` surfaces the full picture rather than a
whack-a-mole one-column-at-a-time discovery.

**3. `init_db`'s new signature.** `init_db(engine: AsyncEngine, db_path:
str | None = None) -> None` — `db_path` is optional (defaults to `None`,
included in the error message as `"<unknown>"` if omitted) purely so the
error message can name the actual file; every real call site already has
the path string available (it's what was passed to `make_engine(...)`
moments earlier) and should pass it through. This is an additive,
backward-compatible signature change — every existing call site gets one
new argument, not a breaking one.

**4. Per-caller failure handling.**
- `src/foundry/cli.py`'s `_serve`, `_run`, `_demo_seed`, `_events`: wrap
  the `await init_db(engine, db)` call in `try/except SchemaDriftError as
  e:` → `typer.echo(str(e), err=True); raise typer.Exit(1) from e`. No
  partial startup — the process exits before opening a port, spawning a
  scheduler, or dispatching any work.
- `src/foundry/api/errors.py` gains a new `FoundryApiError` subclass,
  `SchemaDriftApiError` (`status_code = 500`, `code = "SCHEMA_DRIFT"` —
  still genuinely an internal/server-data problem, the fix here is
  message clarity, not reclassifying it as a client error).
- `src/foundry/api/routes/demo.py`'s `activate_demo`/`deactivate_demo`/
  `reseed_demo`: each already calls `_swap_database`, which already
  catches any exception from the build-new-db phase, recovers `app.state`
  back onto `previous_db_path`, and re-raises. Each route wraps its
  `await _swap_database(...)` call in `try/except SchemaDriftError as e:`
  → `raise SchemaDriftApiError(str(e)) from e`, converting the plain
  exception into the API's standard error envelope. The server is left
  on its last-known-good db either way (that part is unchanged from the
  existing recovery mechanism) — this step only fixes what HTTP response
  shape the client sees.

## Non-functional constraints

- No new dependencies — `sqlalchemy.inspect` is already available via
  the existing SQLAlchemy dependency.
- No schema changes of any kind (this check reads schema, never writes
  it).
- `init_db`'s signature change (`db_path` param) touches all 6 call
  sites but is additive/backward-compatible in behavior — every existing
  test that constructs a store via `init_db(engine)` alone (omitting the
  new param) still works, just with a slightly less specific error
  message if drift is ever hit in a test (which it won't be, since test
  fixtures always create fresh dbs).

## What I did not design here

- Exact wording tweaks to the error message beyond the format shown —
  implementation-plan-level polish.
- Whether `SchemaDriftApiError`'s `status_code` should differ from 500
  in some future refinement — picked 500 here since it's genuinely a
  server-side data problem, not a client mistake; revisit only if this
  choice causes friction in practice.
