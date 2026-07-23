# Design vs. Implementation Deviations

Reviewed against `docs/software-foundary-design.md` and the codebase state at
`master @ 7f67412` (2026-07-23, M4 complete). This is a documentation-only audit —
no fixes applied here. Findings are grouped by kind, each with file:line evidence.

## A. Never built

- **A1. `/internal` HTTP API.** Design doc §7 specifies a full internal API
  (`/internal/context/{unit_id}`, event ingestion, etc.) alongside the public `/api`
  surface. Only `/api/*` routes exist (`src/foundry/api/routes/`); no `/internal/*`
  routes anywhere in the codebase.
- **A2. `ClaudeCodeDriver`.** Design doc §8 and M0's own exit criteria call for a real
  driver against Claude Code. `src/foundry/drivers/` contains only `base.py`,
  `fake.py`, `codex.py` — no Claude driver. M0 exit criterion (b) has never actually
  been met; every milestone since has built on `FakeDriver`/`CodexDriver` only.
- **A3. `ApiDriver`** (design doc's v1.5 driver, direct-API-key provider). Not present;
  expected per roadmap but not yet due.
- **A4. Chat-to-role / `notes_addressed` mapping** (design doc §11 dashboard chat
  contract). Explicitly deferred since M1a; still absent.
- **A5. My-queue view + batch-approve.** Design doc §11 describes a cross-project
  "My queue" with batch gate approval. No such view or endpoint exists; gates are
  approved per-run only.
- **A6. Packs & settings page / Project view** as separately specified in §11. What
  shipped in M4b (`PortfolioHomePage`, `PacksPage`) covers similar ground but isn't
  the same page structure the design doc lays out.

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

- **C1. Per-unit git worktree isolation.** `WorktreeManager` is fully implemented
  and tested (M2b), but neither production call site constructs an `Orchestrator`
  with it wired in: `src/foundry/cli.py:57` and `src/foundry/api/scheduler.py:74`
  both omit it. Worktree isolation has never actually run outside its own test suite.
- **C2. `GlobalDispatchLimiter` cross-project concurrency caps**
  (`src/foundry/api/scheduler.py:12`). Its own docstring documents that the caps are
  non-load-bearing under the current sequential single-tick dispatch model — only the
  ordering/fairness behavior is real; the cap enforcement isn't.
- **C3. KG blast-radius / interference warnings.** Provable on demand (exercised by
  tests, callable directly), but not wired into the live dispatch loop — nothing in
  `tick.py` consults it before scheduling a unit.

## D. Declared but unused

- **D1. Alembic.** `pyproject.toml` declares `alembic>=1.13` as a dependency. No
  `alembic.ini`, no `versions/` directory, no migration has ever been written —
  schema changes have all shipped as direct model edits.

## E. Structural only

- **E1. `integrate` step / conflict auto-resolution.** The `integrate` step exists
  structurally and matches the design doc's stated engine/role boundary
  (`packs/default/playbooks/sdlc_story.toml:49-54`, with `escalates_on`). But the
  `integrator` role (`packs/default/pack.toml:31-33`) carries no prompt or
  build-order content — the actual "auto-resolve conflicts, escalate on merge
  failure" behavior §5.1 describes has never been implemented at either the engine
  or the role-content layer. The "auto-resolved conflicts" metric has only ever been
  populated by FakeDriver scripting in tests, never by real conflict resolution.

## F. Verified compliant (for balance)

- Budget enforcement (80% warning / 100% exceeded) —
  `src/foundry/orchestrator/budget.py`, wired at `tick.py:500-531`.
- Event redaction — `src/foundry/store/redaction.py`.
- Immutable, append-only artifacts; code artifacts stored as git pointers, not raw
  diffs.
- ULIDs for all IDs; SQLite WAL; single-writer `Store` task.
- ADR practice matches design doc — only `ADR-001` exists so far, consistent with
  how little architecture has diverged enough to need one.

## Note on likely root cause

A1 (`/internal` API) and A2 (`ClaudeCodeDriver`) are probably the load-bearing gap:
B3 (context bundling shortcut) and part of A4 trace directly back to A1 never
existing, and every milestone since M0 has been built and tested exclusively against
`FakeDriver`/`CodexDriver` because A2 was never done.
