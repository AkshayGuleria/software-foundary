# Software Foundary (Foundry)

Autonomous, plan-first, phase-gated agent orchestration platform. Runs fleets
of coding agents (Claude Code, Codex CLI, ...) through declarative playbooks
with durable work, human approval gates, live visualization, and compounding
knowledge across runs.

Design doc: [`docs/software-foundary-design.md`](docs/software-foundary-design.md)

## Status

**M0-M2 shipped, M3 (knowledge graph + memory) in progress.** Durable store +
orchestrator + plan-first lint (M0); real gates with reject/rework + REST API
+ React/Vite dashboard (M1); fan-out/convoys, per-unit git worktrees,
agent-review loop, second driver, token budgets, metrics (M2). All backed by
a deterministic `FakeDriver` in CI — no tokens spent. See
[`docs/status.html`](docs/status.html) for the live build-status tracker and
`docs/superpowers/plans/` for each milestone's implementation plan.

Not yet built: real agent driver (`ClaudeCodeDriver`) wired end-to-end,
packs, portfolio view, multi-user/Postgres. See the design doc's roadmap
(§15) for the full milestone sequence.

## Stack

Backend: Python 3.12+, SQLAlchemy 2 (async) + aiosqlite (WAL), Pydantic v2,
FastAPI, Typer, pytest + pytest-asyncio. Frontend: React 18, Vite 5,
TypeScript 5, Tailwind CSS, TanStack Query, Vitest.

## Project layout

```
src/foundry/
  store/        SQLAlchemy models, WAL-mode engine, single-writer Store
  playbook/     TOML schema, loader (+ plan-first lint), DAG materializer
  drivers/      AgentDriver protocol, FakeDriver, CodexDriver
  orchestrator/ tick loop: reconcile -> unblock -> fan-out -> dispatch -> collect -> retry
  kg/           import-graph service + memory retrieval (M3)
  metrics/      compute-on-read rollup
  api/          FastAPI app, REST routes, SSE stream, scheduler
  cli.py        `foundry run`, `foundry events`, `foundry serve`
frontend/       React/Vite/TS dashboard (projects, runs, DAG/fleet/metrics views)
packs/default/  built-in SDLC playbook (not yet wired to a role/prompt system)
```

## Development

```bash
uv sync
uv run pytest -v

cd frontend
npm install
npm test
```

## Run the app (frontend + backend, dev env)

Two processes, two terminals — the frontend dev server proxies `/api` calls
to the backend.

**Terminal 1 — backend:**

```bash
uv run foundry serve --db /tmp/foundry.db --port 8000
```

Starts the FastAPI app + background scheduler at `http://localhost:8000`.
`--db` points at a SQLite file (created if it doesn't exist); use a fresh
path for a clean slate.

**Terminal 2 — frontend:**

```bash
cd frontend
npm install   # first time only
npm run dev
```

Vite prints a local URL (typically `http://localhost:5173`). Open it in a
browser — its dev server proxies `/api/*` to the backend on `:8000`
(configured in `frontend/vite.config.ts`), so both must be running together.

From there: create a project on the **Projects** page, start a run on
**Runs** against a playbook file (e.g.
`tests/orchestrator/fixtures/fanout_e2e.toml` for a full fan-out/review/
integrate demo), then open the run's detail page for the pipeline ribbon,
DAG view, gates/artifacts panel, and live event feed. **Fleet** shows active
sessions across all runs.

No real LLM calls happen in this mode — every run in this environment executes
on `FakeDriver` (scripted, deterministic, zero tokens) unless a real driver is
explicitly wired in, which hasn't shipped yet.

## Try it (CLI only, no browser)

Run a playbook end-to-end against `FakeDriver` (no real agents, no tokens):

```bash
uv run foundry run tests/playbook/fixtures/sdlc_mini.toml --db /tmp/foundry.db
uv run foundry events <run-id-printed-above> --db /tmp/foundry.db --once
```

`foundry run` exits non-zero and prints a clear error if the playbook fails
plan-first lint, has a bad reference, or the run gets stuck (e.g. an
unresolved `human_task` step).
