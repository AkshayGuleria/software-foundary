# Design vs. Implementation Deviations

Reviewed against `docs/software-foundary-design.md` and the codebase state at
`master @ 7f67412` (2026-07-23, M4 complete). Original audit was documentation-only.

**Update (2026-07-25, `master @ 885838c`):** a fix pass closed A2, C1, C3, D1, and
half of E1 — see `docs/superpowers/plans/2026-07-24-deviation-fixes.md` for what
shipped. Items below are marked `[FIXED]` where closed, left as-is otherwise. A new
section G adds frontend-side findings from a follow-up review (backend-only in the
original pass).

## A. Never built

- **A1. `/internal` HTTP API.** Design doc §7 specifies a full internal API
  (`/internal/context/{unit_id}`, event ingestion, etc.) alongside the public `/api`
  surface. Only `/api/*` routes exist (`src/foundry/api/routes/`); no `/internal/*`
  routes anywhere in the codebase. Still open — deliberately out of scope for the
  2026-07-25 fix pass (see that plan's "explicitly out of scope" list).
- **A2. `ClaudeCodeDriver`.** `[FIXED]` `src/foundry/drivers/claude_code.py` now
  exists, mirrors `CodexDriver` structurally, wired into `make_driver()`
  (`src/foundry/drivers/factory.py`) and selectable via `foundry run --driver claude`
  or the API's `driver` field. M0 exit criterion (b) met as of `885838c`.
- **A3. `ApiDriver`** (design doc's v1.5 driver, direct-API-key provider). Not present;
  expected per roadmap but not yet due.
- **A4. Chat-to-role / `notes_addressed` mapping** (design doc §11 dashboard chat
  contract). Explicitly deferred since M1a; still absent.
- **A5. My-queue view + batch-approve.** Design doc §11 describes a cross-project
  "My queue" with batch gate approval. No such view or endpoint exists; gates are
  approved per-run only. Frontend confirmed absent too — see G2.
- **A6. Packs & settings page / Project view** as separately specified in §11. What
  shipped in M4b (`PortfolioHomePage`, `PacksPage`) covers similar ground but isn't
  the same page structure the design doc lays out. Frontend confirmed absent too —
  see G3 (Project view), G4 (Packs & settings).

## B. Built differently than specified

- **B1. Knowledge graph.** Design doc §9 calls for embedding the `code-review-graph`
  tool. Actual `KGService` (`src/foundry/kg/service.py`) builds its own import graph
  using stdlib `ast` — no `code-review-graph` dependency anywhere.
- **B2. Memory retrieval.** Design doc §10 specifies embedding-similarity retrieval.
  Actual implementation (`src/foundry/kg/memory_retrieval.py`) uses Jaccard
  keyword overlap. The `embedding` column exists on the model
  (`src/foundry/store/models.py:154`) but is never populated or queried.
- **B3. Context bundling.** Spec'd as an `/internal/context/{unit_id}` HTTP call
  (§7, §9). Actual bundling happens in-process, composed directly by the
  orchestrator — no HTTP hop, no `/internal` route (ties back to A1).
- **B4. Frontend TS types.** Design doc §2.3 calls for generating TypeScript types
  from the OpenAPI schema. Types in `frontend/src/` are hand-written; no
  OpenAPI-generation step exists in tooling or CI.

## C. Built but dormant (mechanism exists, no production path exercises it)

- **C1. Per-unit git worktree isolation.** `[FIXED]` `WorktreeManager` now
  constructed with real values at all 3 production call sites (`cli.py`'s `run` and
  `_recover_active_runs`, `api/routes/runs.py`'s `create_run`), via
  `src/foundry/api/scheduler.py`'s `register()` gaining a `worktree_manager=` kwarg.
- **C2. `GlobalDispatchLimiter` cross-project concurrency caps**
  (`src/foundry/api/scheduler.py:12`). Still open — its own docstring documents that
  the caps are non-load-bearing under the current sequential single-tick dispatch
  model; only the ordering/fairness behavior is real. Not touched by the fix pass
  (would require a genuinely concurrent dispatch model, out of scope).
- **C3. KG blast-radius / interference warnings.** `[FIXED]` Same wiring as C1 —
  `Scheduler.register()` and both `cli.py` call sites now construct a real
  `KGSnapshot` via `build_kg(project_path)` and pass it through, so
  `_check_convoy_interference` and blast-radius bundle expansion are live in
  production, not just provable in tests.

## D. Declared but unused

- **D1. Alembic.** `[FIXED]` Dependency removed (`pyproject.toml`, `uv.lock`).
  Revisit when M5's Postgres migration actually needs migration tooling.

## E. Structural only

- **E1. `integrate` step / conflict auto-resolution.** `[PARTIALLY FIXED]` The
  `integrator` role (`packs/default/pack.toml`) now carries real content — explicit
  merge/conflict-resolution instructions ("auto-resolve non-overlapping changes,
  escalate on same-lines conflicts") — and every role's description is threaded into
  a real rendered prompt (`src/foundry/orchestrator/prompt.py`), replacing the old
  stub `f"step:{id} files:{n} memory:{n}"` string. What's still open: this only
  matters once a real driver reads and acts on the prompt — under `FakeDriver`
  (still the only driver wired into any actual run today; `ClaudeCodeDriver`/
  `CodexDriver` are *selectable* per C1/A2 but nothing defaults to them) the
  "auto-resolved conflicts" metric is still FakeDriver-scripted, not the product of
  real conflict resolution. Closing this fully means running a real driver against
  the `integrate` step at least once.

## F. Verified compliant (for balance)

- Budget enforcement (80% warning / 100% exceeded) —
  `src/foundry/orchestrator/budget.py`, wired at `tick.py:500-531`.
- Event redaction — `src/foundry/store/redaction.py`.
- Immutable, append-only artifacts; code artifacts stored as git pointers, not raw
  diffs.
- ULIDs for all IDs; SQLite WAL; single-writer `Store` task.
- ADR practice matches design doc — only `ADR-001` exists so far, consistent with
  how little architecture has diverged enough to need one.

## G. Frontend (reviewed 2026-07-25, `master @ 885838c`)

Same design doc §11 ("Visualization and dashboard"), checked against
`frontend/src/`. These are the frontend face of A4/A5/A6 above, confirming the gap
is end-to-end, not backend-only, plus one new structural finding:

- **G1. "Feed & chat" panel is feed-only.** `EventFeed.tsx` has zero POST/textarea/
  mutation — pure read-only event stream. Design's human↔role chat notes (§11)
  never built on the frontend either. Frontend face of A4.
- **G2. "My queue" doesn't exist.** No route, no component — `grep` for
  queue/batch-approve across `frontend/src` is empty. Frontend face of A5.
- **G3. "Project view" never built.** Design specifies a per-project drill-down
  (runs, KG status, memory items, metrics trends, settings). No `/projects/:id`
  route exists in `App.tsx`; `ProjectsPage` is a flat list, and clicking a project
  links to `/runs?project_id=X` (filtered runs list) rather than a dedicated page.
- **G4. "Packs & settings" is view-only.** `PacksPage.tsx` has zero POST/PUT/
  mutation — pure pack/role/playbook browser. Design's gate-policy defaults /
  driver config / budget settings surface never built. G3+G4 are the frontend face
  of A6.
- **G5. No dedicated Metrics view (new finding, not in original audit).** Design
  §11.1 implies a standalone metrics screen ("the dashboard gets a metrics view
  over them"). `MetricsSummary` exists but is mounted inline on `RunsHomePage`
  only — no dedicated route.

What's compliant: stack matches (`React/Vite/TS` + Tailwind, real `EventSource`-based
SSE per `useEventStream.ts`), and Portfolio home / Runs home / Run detail / Fleet
view / Knowledge view all exist and route correctly. Run detail's panel layout
matches design reasonably (Ribbon, DAG view, gates+artifacts combined into
`GateCard`, event feed) apart from G1's missing chat half.

## Note on likely root cause

A1 (`/internal` API) and A4 (chat/notes system) are the remaining load-bearing
gaps: G1/G2 (frontend) and the still-open half of E1 all trace back to A4 never
existing, and A1 not existing constrains anything that would want an HTTP context
boundary. A2 (`ClaudeCodeDriver`) is now built (see update note at top) but not yet
the *default* anywhere — every actual run still executes against `FakeDriver`
unless a caller explicitly opts into `--driver claude`/`codex`.
