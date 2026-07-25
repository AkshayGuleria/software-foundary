# Demo mode — design

**Refined 2026-07-26:** this spec was originally written right after the
metrics-view round shipped, before Project view (G3), per-project settings
(G4), and My-queue (G2) existed. Refinement added two scope items those
features need (below), resolved both open design questions, and — a second
refinement pass the same day — added a UI-driven demo-mode toggle (see
"UI demo-mode toggle" section below), extending scope from "CLI seeds a
file you point `foundry serve --db` at" to "the running server can hot-swap
its own database at runtime."

## Goal

A one-command way to populate a throwaway SQLite database with realistic,
varied fake data — multiple projects at different lifecycle stages, runs in
different states (active, closed, cancelled), gates in every decision state,
artifacts, memory items, and a real on-disk knowledge graph — so a new
visitor can run `foundry serve` against it and see every dashboard view
populated meaningfully, without spending tokens or needing a real driver.

## Why this needs its own design (not just a fixture)

This is a different job from the existing test fixtures under `tests/`:
those exist to exercise specific engine behaviors in isolation (one playbook,
one scenario, torn down per test). Demo mode needs *breadth* — a believable
slice of a working deployment, all at once, that stays up and browsable.

## Scope

**In scope:**
- A `foundry demo-seed` CLI command that populates a fresh SQLite db.
- 4-5 fake projects spanning every `Project.status` value the dashboard
  renders differently (`active`, `paused`, `archived`).
- Per project, 2-4 runs spanning every state the dashboard distinguishes:
  `active` with a pending human gate, `active` with a pending agent-review
  gate, `closed` (successful), `closed` with a rejection→rework cycle in its
  history, `cancelled`.
- Real artifacts, gates (all three `gate_type`s, all three `decision`s),
  events, and sessions backing those runs — not just header rows — so
  `RunDetailPage`'s ribbon/DAG/gates/feed panels all have real content, and
  `MetricsPage`'s rework-rate/approval-latency/retry/crash columns are
  non-zero and varied across projects (the entire point of a *comparison*
  view is worthless if every row is identical).
- Real memory items (a few `lesson`/`pattern`/`pitfall` entries per project)
  so `MemoryBrowser` has content.
- A **real on-disk toy Python package** per demo project (10-20 files with
  genuine import relationships), because `GET /api/projects/{id}/kg-graph`
  and `GET /api/runs/{id}/blast-radius` call `build_kg(project.path)` live
  against the filesystem (`src/foundry/api/routes/knowledge.py:26,53`) — a
  demo project whose `path` points nowhere, or to an empty directory, would
  render an empty Knowledge view no matter how much fake DB data exists.
  This is not optional set-dressing; it's a hard dependency of the feature
  actually working.
- A `foundry demo-seed --reset` flag (or equivalent) to wipe and re-seed
  idempotently, since running the command twice on the same db file should
  not double every row.
- **At least one open `human_task` unit** (`type="human_task", status="open"`)
  on one demo run — the simplest to construct deliberately is the
  budget-exceeded case (a run with `token_budget` set low and `tokens_used`
  already past it; `dispatch()` creates the unit itself once budget-exceeded
  is detected, so this can ride the same real-orchestrator path as everything
  else rather than needing a direct `Store` write). Without this, `QueuePage`'s
  human-tasks section renders empty in the demo — the whole point of seed
  data is that every dashboard view has real content.
- **Varied per-project settings** — each demo project gets different
  `default_driver`/`default_token_budget`/`default_playbook_path` values
  (direct `Store`/`update_project` writes, not reachable through a playbook
  run) so `ProjectDetailPage`'s Settings form and `NewRunForm`'s pre-fill
  behavior have something real to show instead of every project sitting on
  the same defaults.
- **A UI toggle to switch the running server into and out of demo mode**
  (see "UI demo-mode toggle" section below) — auto-seeding the demo db on
  first activation if it hasn't been seeded yet, plus a "Reseed" action
  while active. This is the second refinement's addition: demo mode is no
  longer just a CLI command you point a separate `foundry serve` at, it's a
  runtime-switchable mode on the server you're already running.

**Out of scope:**
- Not a replacement for pytest fixtures — existing `tests/fixtures/` and
  `tests/*/fixtures/` stay exactly as they are, untouched.
- Not wired to any real driver — demo data is either directly inserted via
  `Store` methods or produced by running real playbooks through the
  orchestrator on `FakeDriver` (see design decision 1 below), never
  `CodexDriver`/`ClaudeCodeDriver`. No tokens, no network calls, ever.
- No auth/multi-tenant concerns — out of scope for the whole codebase until
  M5, demo mode doesn't change that.
- Not a perpetual background data generator (no cron, no continuously
  "live" demo) — one seed, static afterward, matches how every other
  Foundry deployment behaves today.

## Design decisions (resolved 2026-07-26)

**1. How is the data produced — direct `Store` writes, or real orchestrator runs on `FakeDriver`?**

**Decided: hybrid.** Drive the bulk of run/gate/artifact data through real
`Orchestrator.run_to_completion()` calls on `FakeDriver` (reusing the
default pack's playbooks, scripting different `FakeStepScript` outcomes per
run to get the state variety) — this is guaranteed structurally valid by
construction and doubles as a live smoke test that the engine still
produces sensible output. Apply direct `Store` writes only for the states
unreachable by construction: project pause/archive, run cancellation,
backdated `created_at` timestamps (so the changelog/metrics don't all
cluster at the exact seed moment), and the varied per-project settings
added above. The budget-exceeded `human_task` unit rides the real-orchestrator
path (set a low `token_budget` on one run, let `dispatch()` create the unit
itself) rather than needing a direct write — the only human_task-adjacent
state that *does* need a direct write is nothing, this one's free.

**2. Where does the demo command live, and where does the toy on-disk repo come from?**

**Decided:** a new `foundry demo-seed` Typer command in `src/foundry/cli.py`,
matching the existing `run`/`events`/`serve`/`archive-events` pattern — no
separate script to discover, works via `uv run foundry demo-seed` like
everything else. The toy on-disk repo is generated fresh each run into
`.foundry-demo/toy-repo-N/` (small synthetic Python package, 10-20 files
with genuine import relationships) rather than committed to this repo —
keeps the demo data self-contained with no risk of drifting from whatever
DB rows reference it, and avoids unrelated fake Python files in
`software-foundary`'s own source tree that a future contributor might
mistake for real code.

## UI demo-mode toggle (added in second refinement, 2026-07-26)

A true toggle: switching into demo mode and back to the server's original
database both happen at runtime, without restarting the `foundry serve`
process. Resolved during brainstorming: hot-swap the running server's DB
connection (not a link to a separately-started demo server) — the
architecture supports this cleanly (see below), and a one-way-only switch
was rejected as an odd fit for a UI toggle affordance.

**Backend — new `src/foundry/api/routes/demo.py`:**
- `GET /api/demo/status` → `{active: bool, db_path: str}`, so the frontend
  can render the correct toggle state on page load/refresh without
  guessing from client-side state alone.
- `POST /api/demo/activate` → hot-swap to the demo db, seeding it first if
  it hasn't been seeded yet (detect via a marker row/table, not just file
  existence — see "What I did not design here" below). Returns updated status.
- `POST /api/demo/deactivate` → hot-swap back to the original db the
  server was started with.
- `POST /api/demo/reseed` → 409s if demo mode isn't currently active
  (reseeding only makes sense for the db you're currently on); otherwise
  wipes and reseeds the demo db in place.

**Swap mechanics**, shared by all three mutating endpoints via one helper:
1. Stop the current `Scheduler` (`await scheduler.stop()` — already cancels
   its tick loop cleanly, existing method, no changes needed to it).
2. Stop the current `Store` (`await store.stop()` — already drains its
   single-writer queue and joins the writer task cleanly, existing method).
3. Dispose the old engine.
4. Build a fresh engine/sessionmaker for the target db path
   (`make_engine`/`make_sessionmaker`/`init_db`, all existing), seed it if
   this is an activation-of-an-unseeded-demo-db case.
5. Construct and start a new `Store` and `Scheduler` for the target db,
   including the equivalent of `_recover_active_runs` so any in-flight runs
   on that db get re-registered.
6. Only after the new `Store`/`Scheduler` are fully started, reassign
   `app.state.store`/`app.state.scheduler` in place — `_get_store(request)`
   already reads `request.app.state.store` fresh per-request
   (`src/foundry/api/routes/projects.py`), so no FastAPI app restart is
   needed; existing route handlers pick up the new store on their next call
   automatically.
7. The whole swap is wrapped in a lock (e.g. an `asyncio.Lock` on
   `app.state`) so two swap requests can't race each other.

**Server needs to remember its original db path** — stashed as
`app.state.original_db_path` at `foundry serve` startup — for the
deactivate direction to know what to swap back to.

**Reusable seeding function, not CLI-only.** Because both `foundry
demo-seed` (CLI) and `POST /api/demo/activate`/`reseed` (API) need to run
the exact same seeding logic, the seeding code must be built as an
importable function from the start (e.g. `foundry.demo.seed.run_demo_seed(store, ...)`
returning once seeding is complete), not written as a CLI-command-only
script that would need duplicating or awkwardly invoking as a subprocess
from the API layer.

**Frontend:** a "Demo mode" toggle in the nav header (calls
`GET /api/demo/status` on mount, `POST /api/demo/activate`/`deactivate` on
toggle); a "Reseed" button rendered only while active. Because the entire
database underneath the app just changed, any of these three calls clears
the whole TanStack Query cache (not a targeted `invalidateQueries` on one
key — everything is potentially stale) and navigates back to `/`, since a
deep-linked run/project id from before the swap won't exist against the
new db.

## Non-functional constraints carried over from the rest of the codebase

- Must not touch a real/default `foundry.db` by accident — `demo-seed`
  should require an explicit `--db` path (or default to something obviously
  demo-named like `demo.db`, never silently reuse whatever `foundry.db`
  already contains real data in).
- No new dependencies.
- Runs entirely offline, same as every existing test in this suite.

## What I did not design here

Exact seed data (which project names, how many of each state, exact fake
lesson/pitfall text) and the toy repo's generated file/import structure are
implementation-plan-level detail, not spec-level — the plan should pick
concrete numbers consistent with the design decisions above. Also
implementation-plan-level, from the UI toggle addition:
- The exact "has this db been seeded" detection mechanism (a marker
  row/table vs. checking whether any projects exist at all).
- What happens to a request that was already in-flight against the old
  store at the exact moment of a swap (accepted as a best-effort brief
  window, not worth distributed-locking machinery for what is fundamentally
  a demo/kiosk feature, not a production concern).
- Exact toggle/button placement and styling in the nav header.
