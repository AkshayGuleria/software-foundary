# Software Foundary (Foundry)

Autonomous, plan-first, phase-gated agent orchestration platform. Runs fleets
of coding agents (Claude Code, Codex CLI, ...) through declarative playbooks
with durable work, human approval gates, live visualization, and compounding
knowledge across runs.

Design doc: [`docs/software-foundary-design.md`](docs/software-foundary-design.md)

## Status

**M0-M4 shipped, M5 (team-shared: Postgres/auth/multi-user) planned.** Durable
store + orchestrator + plan-first lint (M0); real gates with reject/rework +
REST API + dashboard (M1); fan-out/convoys, per-unit git worktrees,
agent-review loop, second driver, token budgets, metrics (M2); knowledge
graph + compounding memory (M3); packs, portfolio view, project lifecycle,
demo mode (M4). The dashboard also completed a full design-system migration
(oklch tokens, light/dark theming, a dependency-free component library) in
two follow-on phases after M4. All backed by a deterministic `FakeDriver` in
CI — no tokens spent. See [`docs/status.html`](docs/status.html) for the live
build-status tracker and `docs/superpowers/plans/` for every milestone's and
phase's implementation plan.

Not yet built: a real agent driver (`ClaudeCodeDriver`) proven end-to-end
against the live CLI (it exists and is selectable, just not yet run for
real), multi-user/Postgres, per-role multi-driver dispatch, chat-to-role.
See the design doc's roadmap (§15) for the full milestone sequence.

## Stack

Backend: Python 3.12+, SQLAlchemy 2 (async) + aiosqlite (WAL), Pydantic v2,
FastAPI, Typer, pytest + pytest-asyncio. Frontend: React 18, Vite 5,
TypeScript 5, Tailwind CSS (oklch design tokens, dependency-free primitives),
TanStack Query, Vitest, Playwright.

## Project layout

```
src/foundry/
  store/        SQLAlchemy models, WAL-mode engine, single-writer Store
  playbook/     TOML schema, loader (+ plan-first lint), DAG materializer
  packs/        pack manifest schema + loader (roles + playbook registry)
  drivers/      AgentDriver protocol, FakeDriver, CodexDriver, ClaudeCodeDriver
  orchestrator/ tick loop: reconcile -> unblock -> fan-out -> dispatch -> collect -> retry
  kg/           import-graph service + memory retrieval
  metrics/      compute-on-read rollup
  api/          FastAPI app, REST routes, SSE stream, scheduler
  cli.py        `foundry run`, `foundry events`, `foundry serve`, `foundry demo-seed`, `foundry archive-events`
frontend/       React/Vite/TS dashboard
  src/components/ui/  ported design-system primitives (Button, Input, Card, Sheet, ...)
  src/tokens/          oklch color tokens, semantic status tokens
packs/default/  built-in pack: two playbooks (sdlc_story, bugfix) + role roster
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
path for a clean slate. Want the dashboard pre-populated instead of empty?
Seed one first: `uv run foundry demo-seed --db /tmp/foundry.db` (see
`foundry demo-seed --help` for `--reset`/`--repos-dir`), or toggle demo mode
live from the dashboard's top bar once it's running.

**Terminal 2 — frontend:**

```bash
cd frontend
npm install   # first time only
npm run dev
```

Vite prints a local URL (typically `http://localhost:5173`). Open it in a
browser — its dev server proxies `/api/*` to the backend on `:8000`
(configured in `frontend/vite.config.ts`), so both must be running together.
A `/dev/ui-kit` route (not linked from the nav) is a living reference for
every ported design-system primitive, useful when building new UI.

From there: create a project on the **Projects** page, start a run on
**Runs** against a playbook path (see "Set up a new pipeline" below for how
to write one, or point at an existing one like
`packs/default/playbooks/bugfix.toml`), then open the run's detail page for
the status ribbon, DAG view, gates/artifacts panel, and live event feed.
**Fleet** shows active sessions across all runs, **Queue** is your
cross-project inbox of pending gates/human tasks, **Knowledge** browses the
per-project import graph and compounding memory, **Metrics** and **Packs**
round out the rest.

No real LLM calls happen in this mode — every run executes on `FakeDriver`
(scripted, deterministic, zero tokens) unless a real driver is explicitly
selected (see below).

## Set up a new pipeline

A "pipeline" in Foundry is a **playbook**: a declarative TOML file describing
a DAG of steps, each assigned to a **role**. Playbooks live inside a
**pack** (`packs/<pack-id>/`) alongside the roster of roles they use. This
repo ships one pack, `packs/default/` (id `default`, version `0.1.0`), with
two playbooks: `sdlc_story.toml` (the full requirement → architecture →
fan-out implementation → agent review loop → integrate flow) and
`bugfix.toml` (a much simpler diagnose → fix → review flow, deliberately
structured differently to prove pack content doesn't require engine
changes).

### 1. Decide: new playbook in the existing pack, or a new pack?

- **New playbook, existing roles** (e.g. a "hotfix" or "docs-only" flow) —
  just add a `.toml` file under `packs/default/playbooks/` and register its
  path in `packs/default/pack.toml`'s `playbooks` list. This is the common
  case and needs zero engine changes — that guarantee is exercise by an
  end-to-end test in this repo's own test suite (`bugfix.toml` was added
  this way as M4's proof).
- **New pack** (different project domain, different role roster entirely) —
  create `packs/<your-id>/pack.toml` with its own `[pack]` id/version,
  `[[role]]` entries, and `playbooks` list, plus the playbook file(s) it
  points at. A project picks its pack via the pack's `id`, and pins a
  specific `version` per run.

### 2. Define roles (skip if reusing an existing pack's roles)

Each role in `pack.toml`:

```toml
[[role]]
id = "developer"                 # referenced by step.role below
model = "fake"                   # session model hint (NOT the driver — see step 4)
description = "Implement the assigned slice. Produce a code_diff_artifact ..."
```

`description` becomes part of the agent's rendered prompt — write it like
instructions to a new hire, not a one-line label. `model` is recorded on the
session for display/metrics; it does not select which driver CLI runs (that's
a per-run choice, see step 4) — leave it `"fake"` unless you have a specific
reason to pin something else.

### 3. Write the playbook

Every step (`[[step]]` in the TOML) has this shape (from
`src/foundry/playbook/schema.py`):

| Field | Type | Meaning |
|---|---|---|
| `id` | string | unique within the playbook |
| `role` | string | must match a role `id` in the pack |
| `type` | `"task"` \| `"derived_gate"` \| `"human_task"` | default `"task"`; `derived_gate` is an automated plan-approval checkpoint (no agent session runs), `human_task` is a step a human completes directly, not an agent |
| `needs` | list of step ids | upstream dependencies; a step only becomes ready once all of these are closed |
| `produces` | string \| null | the artifact kind this step writes, e.g. `"code_diff_artifact"` |
| `gate` | `"human"` \| `"agent"` \| `"none"` | who must approve the step's output before downstream steps unblock |
| `writes` | bool | `true` if this step's agent is allowed to touch files on disk — **see the plan-first rule below** |
| `fan_out` | string \| null | e.g. `"architecture_artifact.slices"` — dynamically expands into one unit per item in that upstream artifact's field, at tick time |
| `fan_out_from` | string \| null | marks a step as consuming a fanned-out step's units one-to-one (mutually exclusive with `fan_out`, must reference a step that itself has `fan_out` set — one-hop chains only) |
| `loop` | table \| null | `{ back_to = "implement", until = "verdict == approved", max_rounds = 5 }` — reopens `back_to` if this step's verdict doesn't match `until`, up to `max_rounds` times |
| `escalates_on` | string \| null | e.g. `"escalated"` — a verdict value that routes this step to a human instead of auto-continuing (the `integrate` step's conflict-resolution handoff uses this) |

**Plan-first is enforced, not a convention.** Every `writes = true` step must
be transitively downstream of a `derived_gate` step (via `needs` chains) —
`foundry run`/`foundry serve` reject a playbook that violates this at load
time (`PlaybookLintError`), before any agent session can run. This is the
platform's core guarantee: nothing writes to disk until a plan has been
approved.

Minimal example — this is `packs/default/playbooks/bugfix.toml` in full,
the simplest real pipeline in this repo (no fan-out, no loop):

```toml
[playbook]
id = "bugfix"
description = "Bug fix: diagnose -> fix -> review, no fan-out"

[[step]]
id = "diagnose"
role = "developer"
produces = "diagnosis_artifact"
gate = "human"

[[step]]
id = "diagnose_approval"
role = "system"
type = "derived_gate"
needs = ["diagnose"]

[[step]]
id = "fix"
role = "developer"
needs = ["diagnose_approval"]   # <- this is what satisfies the plan-first rule for `writes = true` below
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

For a fan-out + agent-review-loop example (parallel implementation slices,
each independently reviewed with a bounded retry loop, then integrated with
human escalation on conflict), read `packs/default/playbooks/sdlc_story.toml`
in full — every field above appears in it at least once.

### 4. Register and run it

Add the new playbook's path to `pack.toml`'s top-level `playbooks` array (a
path relative to the pack directory):

```toml
playbooks = ["playbooks/sdlc_story.toml", "playbooks/bugfix.toml", "playbooks/your_new_one.toml"]
```

Then run it either way:

**CLI** (no dashboard/server needed):

```bash
uv run foundry run packs/default/playbooks/your_new_one.toml \
  --project-path /path/to/target/repo \
  --db /tmp/foundry.db \
  --driver fake   # or "codex" / "claude" -- the AgentDriver used for every step's session
uv run foundry events <run-id-printed-above> --db /tmp/foundry.db --once
```

`foundry run` exits non-zero with a clear error if the playbook fails
plan-first lint, has a bad reference, or the run gets stuck (e.g. an
unresolved `human_task` step).

**Dashboard:** register the target project on the **Projects** page (or set
it as that project's `default_playbook_path` in its Settings), then on
**Runs** pick the new playbook from the "Playbook" dropdown. The run's
detail page drives approvals/rejections from there — nothing about the UI
needs to know a new playbook exists ahead of time beyond appearing in the
picker (see below).

### 5. Test it

Point `foundry run` at a disposable throwaway git repo with `--driver fake`
first — no tokens spent, fully deterministic, and `foundry events --once`
gives you the full event trace to confirm each step fired in the order you
expect. `tests/orchestrator/fixtures/` and `tests/playbook/fixtures/` have
several playbook fixtures used by this repo's own test suite if you want a
reference for exercising fan-out, loops, or escalation in isolation.

### Alternative: edit playbooks from the dashboard, per project

You don't have to hand-author a `.toml` file and register it in `pack.toml`
to try a playbook out — each project also has its own writable library of
playbook copies, separate from the shared `packs/` tree, editable straight
from the UI:

- On a project's detail page, the **Playbooks** section lists that
  project's own copies and links to **New** (blank editor) or an existing
  slug's **Edit** page (`/projects/:id/playbooks/new` and
  `/projects/:id/playbooks/:slug`), each a raw-TOML textarea.
- Instead of starting blank, "start from a pack template" lets you preview
  an existing pack playbook's content read-only, then clone it into the
  project's library as a starting point.
- Save runs the same validation a real run does — `load_playbook` +
  `lint_plan_first`, server-side, on every write — so a playbook that fails
  the schema or the plan-first invariant is rejected with an error instead
  of being written; a bad edit can never corrupt the last-good copy on disk.

Saved copies land at `project_playbooks/<project_id>/<slug>.toml` and are
run-ready paths just like anything under `packs/` — point a run at one the
same way you would any other playbook path.

Neither starting a run nor setting a project's default playbook path
requires typing a path by hand anymore: both use a shared dropdown picker
(grouped into "Project playbooks" and "Pack templates", with a "New
playbook →" link straight into the editor above), and an already-set custom
path is still shown rather than silently dropped. The playbook editor page
also has a collapsible, read-only field-reference panel listing every
`PlaybookSpec`/`StepSpec`/`LoopSpec` attribute (type, default, required,
description) straight from the real Pydantic schema, so it can't drift out
of sync with what a playbook actually accepts.
