# Foundry — Autonomous Development Pipeline Platform

> Working name: **Foundry** (rename freely). A greenfield platform for building software factories: plan-first, phase-gated, provider-agnostic agent orchestration with durable work, live visualization, and compounding knowledge.

Design date: 2026-07-12 · Author: Akshay (with Claude) · Status: Draft for review

---

## 1. Summary

Foundry orchestrates fleets of coding agents through the SDLC. Its two non-negotiable principles:

1. **Plan first, always.** No execution begins until a thorough, machine-readable plan exists and a human has approved it. Planning artifacts (requirements, architecture, test plan) are first-class, versioned, and gated.
2. **Phased execution, observable and gated.** Work proceeds through explicit SDLC phases. Every artifact an agent produces passes a human approval gate before the pipeline advances. Everything is visible on a live dashboard.

Synthesis of the four references:

| Source | What Foundry takes |
|---|---|
| **Watchtower** | SDLC phase model, artifact gates, persona-per-role, dashboard UX (pipeline ribbon, swim lanes, approvals, chat), internal/external API split |
| **Gas City** | Role-agnostic core: primitives (work units, playbooks, packs), durable work store, event bus, dependency-gated fan-out, orchestrator that reads state instead of holding it |
| **Compound Engineering** | Plan-first workflow (brainstorm → plan → work → review → compound), post-run learning capture that makes future runs cheaper |
| **code-review-graph** | Tree-sitter knowledge graph for minimal agent context, blast-radius analysis for reviews, graph visualization |

Key difference from Watchtower: **no roles, phases, or pipelines are hardcoded.** The engine executes declarative playbooks; Watchtower's story/bug pipeline becomes just the default pack that ships with the platform.

---

## 2. Requirements

### 2.1 Functional

- **F1 — Plan-first runs.** Every run starts in a planning stage that produces structured planning artifacts. A derived "plan approval" gate blocks all execution phases until every planning artifact is human-approved.
- **F2 — Artifact gates everywhere.** Every artifact creates an approval record. Reject with structured feedback re-spawns the producing agent in rework mode with that feedback.
- **F3 — Declarative playbooks.** Pipelines are defined as data (steps, dependencies, roles, gate policies, artifact schemas), not code. Applying a playbook materializes a run: a DAG of durable work units.
- **F4 — Parallel fan-out.** Independent work units within a phase execute concurrently across agents, capped by a concurrency limit. Dependency edges gate ordering; no central per-step scheduler logic.
- **F5 — Provider-agnostic agents.** Agents run through a driver interface. Ship Claude Code and Codex CLI drivers first; adding a provider requires only a new driver, no engine changes.
- **F6 — Durable work + crash recovery.** All work state lives in the store, not in process memory or agent sessions. Orchestrator or agent crash never loses progress; on restart the orchestrator reconciles and resumes.
- **F7 — Live visualization.** Web dashboard with pipeline view, run DAG, agent activity, artifact panel, approvals, event feed — updated in real time.
- **F8 — Knowledge graph context.** Code structure graph per project; agents get minimal context and blast-radius data instead of re-reading the repo; reviewers get risk-scored change impact.
- **F9 — Compounding memory.** A closing "compound" step distills learnings from each run into pack-scoped knowledge that is injected into future agent prompts.
- **F10 — Packs.** Roles, playbooks, artifact schemas, gate policies, and memory are bundled into packs. A local pack configures the deployment; packs are shareable and importable.
- **F11 — Multi-project portfolio.** One Foundry deployment builds, tracks, and monitors many software projects concurrently. Projects register/archive independently, each with its own knowledge graph, worktree root, memory scope, and run history. Runs from different projects execute concurrently under fair global scheduling. The dashboard provides both a portfolio view (all projects, health at a glance) and per-project drill-down; metrics roll up per project and across the portfolio.

### 2.2 Non-functional

- **Scale (v1):** 1 user, 5–10 registered projects, 1–5 concurrent runs across them, ≤10 concurrent agent sessions, repos to ~5k files. Team target (v2): ~20 users, ~50 projects, ~50 concurrent sessions.
- **Latency:** dashboard reflects events in <1s (SSE). Orchestrator dispatch latency <2s from unblock to spawn.
- **Durability:** zero loss of accepted work on process crash. Event log is append-only and replayable.
- **Portability:** local-first; single binary/process + SQLite, no external services required. Same codebase deploys team-shared with Postgres.
- **Cost control:** knowledge-graph-scoped context; per-run token budget with hard stop; model tier configurable per role. Default model policy: **latest Sonnet-class model; anything more expensive requires explicit opt-in per role** (matches your global preference).
- **Security:** agents run with project-scoped filesystem access; internal API protected by shared secret (v1) → per-user auth (v2); no provider credentials stored in the DB (use each CLI's own auth).

### 2.3 Constraints and assumptions

- **Backend stack (decided):** Python + FastAPI — Pydantic v2, SQLAlchemy 2 async + Alembic + aiosqlite (WAL), `jsonschema` for pack-defined artifact schemas, sse-starlette, psutil, uv packaging, pytest + FakeDriver. TS types for the dashboard are generated from the OpenAPI schema in CI to prevent contract drift. Rationale and the three-way comparison (incl. an empirical driver spike vs Node, analytical vs Rust) live in `backend-stack-comparison.md`; a Rust engine port remains open at M5+ via the contracts-first rule (§12).
- Agents execute on the same machine as the orchestrator in v1 (subprocess model).
- Git is the substrate for code output: every executing work unit operates in its own worktree/branch.

---

## 3. Core concepts

Six primitives, Gas City-shaped, with Foundry-specific gate semantics:

| Primitive | Answers | Description |
|---|---|---|
| **Role** | who | A configured worker: prompt template + provider + model + tool scope. Pure config. "Architect" is nothing but a prompt and a schema for what it must produce |
| **WorkUnit** | what | The durable unit of work: id, type, status, payload, dependency edges. Tasks, gates, sessions, artifacts-in-progress — all are work units differing by type |
| **Playbook** | how | Declarative method: steps, `needs` edges, role bindings, artifact contracts, gate policy per step. Applying one materializes work units; the run then lives independently of the file |
| **Project** | where | A registered git repo (or repo set) with its own work-unit namespace, knowledge graph, worktree root, memory scope, and run history. A deployment hosts many projects concurrently; each has a lifecycle (`active` → `paused` → `archived`) and its own settings overrides (default playbook, gate policy, budgets) |
| **Pack** | config | Bundle of roles + playbooks + schemas + memory. The deployment's root pack is the "factory"; imports pull in shared packs |
| **Event** | observe | Append-only, monotonically sequenced record of everything that happens. The dashboard, automations, and audits all read the same stream |

Foundry-specific additions on top:

- **Artifact** — an immutable, versioned output of a step (requirement, architecture, test plan, code diff, review, test results). Every artifact conforms to a JSON schema declared in the pack. **Code artifacts are pointers, not payloads:** a `code_diff_artifact` stores branch, base/head commit SHAs, and a stat summary — git is the storage; the dashboard renders diffs lazily from the worktree. Only structured metadata lives in the DB.
- **Gate** — an approval work unit auto-created when a gated step produces its artifact. Holds decision (approved / rejected+feedback), decider, timestamp. A step's successors carry an implicit `needs` edge to its gate.
- **HumanTask** — a work unit assigned to a person rather than an agent: run the manual E2E plan, click merge, resolve an escalated conflict. Distinct from a gate (which approves an agent's output); a human task *is* the work. Surfaced in a dedicated dashboard queue; closes when the human marks it done (optionally with an attached result artifact).
- **Run** — one application of a playbook to a project: the materialized DAG plus its artifacts, gates, sessions, and events. **A run pins the pack version at materialization** — playbook, role prompts, and artifact schemas are snapshotted, so a pack update mid-run never changes in-flight semantics; new versions apply to new runs only.

---

## 4. High-level architecture

```
┌────────────────────────────────────────────────────────────────────────┐
│ Foundry server (one process, v1)                                       │
│                                                                        │
│  ┌───────────┐   ┌──────────────┐   ┌───────────┐   ┌──────────────┐   │
│  │ HTTP API  │   │ Orchestrator │   │ Watchers  │   │ KG service   │   │
│  │ /api      │   │ (tick loop + │   │ PR poller │   │ code-review- │   │
│  │ /internal │   │  reconciler) │   │ CI poller │   │ graph (MCP)  │   │
│  └─────┬─────┘   └──────┬───────┘   └─────┬─────┘   └──────┬───────┘   │
│        │                │                 │                │           │
│  ┌─────▼────────────────▼─────────────────▼────────────────▼───────┐   │
│  │                      Store (SQLite v1 / Postgres v2)            │   │
│  │   work_units · artifacts · gates · runs · events · memory      │   │
│  └─────────────────────────────┬───────────────────────────────────┘   │
│                                │ append → fan-out                      │
│                       ┌────────▼────────┐                              │
│                       │ Event bus (SSE) │                              │
│                       └────────┬────────┘                              │
└────────────────────────────────┼────────────────────────────────────────┘
        ▲                        ▼                          ▲
 ┌──────┴──────┐        ┌────────────────┐         ┌────────┴────────┐
 │ Dashboard   │        │ Agent driver   │         │ git worktrees   │
 │ React/Vite  │        │ layer          │         │ per work unit   │
 │ DAG · ribbon│        │ ┌────────────┐ │         └─────────────────┘
 │ · approvals │        │ │Claude Code │ │
 └─────────────┘        │ │Codex CLI   │ │
                        │ │(API driver)│ │
                        │ └────────────┘ │
                        └────────────────┘
```

The loop closes through shared state (Gas City's key insight): the orchestrator *acts* on sessions (spawn/stop/retry) but *reads* progress from the store and event log — never from callbacks held in memory. That is what makes crash recovery trivial: state is always ground truth.

### 4.1 Orchestrator tick

Every tick (and immediately on a wake signal):

1. **Reconcile** — compare live sessions (PID table / driver query) against session work units. Adopt orphans; mark vanished sessions crashed and reopen their work units. Session units in `intent` state with no live process are known-never-spawned and safely re-dispatched.
2. **Unblock** — find work units whose `needs` edges are all closed and whose gate (if any) is approved; mark them `ready`.
3. **Dispatch (intent-first)** — for each `ready` unit up to the concurrency cap: **write the session work unit first in `intent` state**, then create a worktree if the step touches code, render the role's prompt (injecting artifacts, KG context, memory), spawn via the bound driver, and confirm the session unit to `running`. Recording intent before spawning means a crash between the two steps can never double-spawn: reconciliation distinguishes "never spawned" (re-dispatch) from "spawned and died" (adopt or fail).
4. **Collect** — ingest driver events (tool calls, completion, failure) into the event log; on step completion, validate the artifact against its schema, persist it, create its gate.
5. **Retry / escalate** — failed units retry with backoff up to `max_attempts`; then a `blocked` gate is surfaced for a human decision.

No role names, phase names, or SDLC knowledge appears anywhere in this loop.

---

## 5. Pipeline model — plan first, then phased execution

### 5.1 Playbook definition

Playbooks are TOML/YAML in a pack. Sketch of the default SDLC playbook (Watchtower's pipeline, expressed as data):

```toml
[playbook.sdlc_story]
description = "Story: requirement → plan → sliced implementation → review → merge"

[[step]]
id = "requirement"
role = "product_owner"
produces = "requirement_artifact"
gate = "human"                    # human | agent | none

[[step]]
id = "architecture"
role = "architect"
needs = ["requirement"]
produces = "architecture_artifact"
gate = "human"

[[step]]
id = "test_plan"
role = "qa"
needs = ["requirement"]           # parallel with architecture
produces = "test_plan_artifact"
gate = "human"

[[step]]
id = "plan_approval"
type = "derived_gate"             # green only when all listed gates approved
needs = ["requirement", "architecture", "test_plan"]

[[step]]
id = "implement"
role = "developer"
needs = ["plan_approval"]
fan_out = "architecture_artifact.slices"   # one unit per slice
produces = "code_diff_artifact"
gate = "human"

[[step]]
id = "agent_review"
role = "reviewer"
needs = ["implement"]             # per-slice, inherits fan-out
produces = "review_artifact"
gate = "agent"                    # loop, no human gate
loop = { back_to = "implement", until = "verdict == approved", max_rounds = 5 }

[[step]]
id = "integrate"
role = "integrator"
needs = ["agent_review"]          # per-run: waits for the whole convoy
produces = "integration_artifact" # merged branch pointer + conflict report
gate = "human"
# merges slice branches in architecture_artifact.build_order; resolves
# trivial conflicts itself; non-trivial conflicts escalate to a human_task

[[step]]
id = "open_pr"
role = "developer"
needs = ["integrate"]
produces = "pr_artifact"
gate = "human"

[[step]]
id = "e2e"
type = "human_task"               # a person runs the E2E plan on dev
needs = ["open_pr"]

[[step]]
id = "merge"
type = "human_task"               # the merge click belongs to a person
needs = ["e2e"]
# ... ci_wait, signoff omitted for brevity
```

The engine understands only: steps, needs, fan-out, produce+validate, gate types, loops, human tasks. Priya/Aino/Diego are pack content, not platform.

**Integration is a first-class step, not an afterthought.** Parallel worktrees *will* conflict. The `integrate` step merges slice branches in the architecture's declared build order; the integrator role resolves mechanical conflicts (imports, lockfiles, adjacent hunks) and runs the build+tests after each merge; anything semantic escalates to a `human_task` with both diffs and the KG blast-radius overlap attached. The integration artifact records what was auto-resolved so the human gate can audit it.

### 5.2 Plan-first as an enforced invariant

The platform enforces, not merely encourages, plan-first: a playbook is invalid unless every step that mutates a project (declared `writes = true` on the role) is transitively downstream of at least one `derived_gate` over human-gated planning artifacts. Lint at pack load time. This is the compound-engineering 80/20 baked into the schema.

### 5.3 Gate semantics

- Artifact produced → gate work unit created → event fired → dashboard shows pending approval.
- **Approve** → gate closes, successors can unblock.
- **Reject** (structured chips + free text) → producing step reopens in `rework` mode; the rejection feedback is injected into the rework prompt; artifact version increments. Successors remain blocked.
- **Agent gates** run a reviewer role instead of a human; verdict drives the loop with a hard round cap and a forced human escalation on cap.
- Gate policy is overridable per run at creation ("this run: auto-approve test_plan") — recorded in the event log for audit.
- **The plan-approval gate carries a cost estimate.** At plan approval the dashboard shows projected spend: slices × role model tiers × historical tokens-per-slice for this project (from the metrics rollup, §11.1). The human approves scope *and* budget in one decision; the run's token budget defaults to estimate + margin.

### 5.4 Fan-out and convoys

`fan_out` binds a step to an array inside an upstream artifact (e.g., architecture slices). Materialization creates one work unit per element, grouped in a **convoy** (container work unit) so the dashboard and gates can treat the batch as a unit. Downstream steps declared per-slice inherit the fan-out; steps declared per-run (e.g., `open_pr`) get a `needs` edge to the whole convoy.

---

## 6. Data model

Nine tables (SQLite v1; all IDs ULIDs; JSON payloads as text columns):

```
runs           id, project_id, playbook_ref, pack_version_pin, title, status, created_by,
               token_budget, tokens_used, created_at, closed_at
work_units     id, run_id, step_id, type(task|gate|human_task|session|convoy),
               status(open|ready|intent|in_progress|blocked|closed|failed|killed),
               payload_json, attempt, max_attempts, owner_session_id, convoy_id,
               assignee, created_at, updated_at
unit_deps      unit_id, needs_unit_id                       -- the DAG edges
artifacts      id, run_id, work_unit_id, kind, version, produced_by_role,
               payload_json, schema_ref, created_at         -- immutable, append-only
gates          id, work_unit_id, artifact_id, gate_type(human|agent|derived),
               decision(pending|approved|rejected), feedback_json, decided_by, decided_at
sessions       id, work_unit_id, driver, provider_session_ref, pid, model, status,
               started_at, ended_at, tokens_in, tokens_out
events         seq (autoincrement), run_id, unit_id, type, payload_json, created_at
memory         id, pack_id, scope(pack|project|role), kind(lesson|pattern|pitfall),
               title, body_md, source_run_id, embedding, created_at
projects/packs id, name, path/manifest_json, kg_status, created_at
```

Design notes:

- `events.seq` is the global monotonic cursor — SSE clients reconnect with `Last-Event-ID` and replay from any point (Gas City's event model).
- Artifacts are immutable; rework creates version N+1. `?latest=true` semantics (max version per kind+slice) come from Watchtower's hard-won bug class.
- Code artifacts store git pointers (branch, SHAs, stat summary) — never raw diffs (§3). Diff rendering reads from the worktree on demand.
- Sessions are work units *about* processes, not the source of truth for work — killing every session loses nothing but in-flight tokens.
- One store, namespaced by project prefix, rather than a DB per project — cross-project queries stay trivial.
- **SQLite discipline:** WAL mode mandatory; all writes funnel through a single writer task (asyncio queue) — sessions streaming tool-call events concurrently is exactly where SQLite's single-writer limit bites first. Readers are unlimited under WAL.
- **Event retention:** events for closed runs are archived to compressed JSONL on disk after N days (default 30) and pruned from the hot table; the archive remains replayable. **Redaction:** tool-call event payloads pass a redaction filter (env-var patterns, key-shaped strings, configurable globs for sensitive paths) before persistence — the event log is an audit surface, not a secrets store.

---

## 7. API and event design

Two surfaces, Watchtower-style, both REST + SSE:

**Public `/api` (dashboard, humans):**

```
POST   /api/runs                          create run (playbook, project, input, overrides)
GET    /api/runs?status=…                 list; GET /api/runs/{id} full detail
POST   /api/runs/{id}/cancel              immediate tree-kill + unit status flip
GET    /api/runs/{id}/graph               DAG snapshot for visualization
GET    /api/runs/{id}/artifacts?latest=1  artifact panel
POST   /api/gates/{id}/decide             {decision, feedback_chips[], feedback_text}
POST   /api/runs/{id}/chat                human note routed to the responsible role
GET    /api/stream[/{run_id}]             SSE (Last-Event-ID resume)
GET    /api/packs · /api/projects · /api/memory · /api/settings
GET    /api/kg/{project}/…                graph queries proxied to KG service
```

**Internal `/internal` (agents → server, shared-secret header):**

```
POST   /internal/artifacts                submit artifact (validated against schema)
POST   /internal/events                   progress/feed events from inside a session
PATCH  /internal/units/{id}               status transitions the driver can't infer
GET    /internal/context/{unit_id}        the rendered context bundle for this unit
```

**Event taxonomy** (dot-namespaced, additive-only): `run.created/closed/cancelled`, `unit.created/ready/started/closed/failed/retried`, `artifact.produced`, `gate.created/approved/rejected`, `session.spawned/adopted/crashed/ended`, `convoy.created/closed`, `kg.updated`, `memory.compounded`, `budget.warning/exceeded`.

Contract rule: events are facts, never commands. Anything that wants to react (dashboard, future automation triggers) subscribes; nothing is invoked directly by an event producer.

---

## 8. Provider adapter layer

The driver interface is deliberately narrow — five capabilities:

```python
class AgentDriver(Protocol):
    def spawn(self, spec: SessionSpec) -> SessionHandle: ...
    #   SessionSpec: cwd(worktree), prompt, model, tool_policy, mcp_servers,
    #                env, internal_endpoint+secret
    def stream_events(self, h: SessionHandle) -> Iterator[DriverEvent]: ...
    #   normalized: tool_call | text | usage | completed | failed
    def cancel(self, h: SessionHandle, tree_kill: bool = True) -> None: ...
    def adopt(self) -> list[SessionHandle]: ...      # find live sessions after restart
    def health(self, h: SessionHandle) -> SessionHealth: ...
```

v1 drivers:

- **FakeDriver** — a deterministic scripted driver, built *first*: returns canned artifacts instantly, fails on command, delays on command, emits synthetic tool-call streams. It is how the orchestrator, gate loops, fan-out, and crash recovery get tested without tokens, and what CI runs. Every engine feature must have a FakeDriver test before it meets a real provider.
- **ClaudeCodeDriver** — `claude -p` subprocess with `--output-format stream-json`; MCP servers injected via workspace `.mcp.json`; uses the user's existing subscription auth.
- **CodexDriver** — `codex exec` equivalent, same normalization.
- **ApiDriver** (v1.5) — direct Anthropic/OpenAI API with an in-house tool loop, for headless/CI environments without a CLI.

Normalization is the whole job: every driver maps its native stream to the same `DriverEvent` set so the orchestrator, event log, and dashboard are provider-blind. Model selection lives in the role config (`model = "sonnet-latest"` by default; higher tiers must be explicitly named per role).

**Driver spec requirements (empirical — from the Python/Node driver spike):**

1. **Process exit is authoritative for session end, never stream EOF.** Grandchild processes inherit stdout and hold the pipe open after the agent dies; a driver awaiting EOF hangs forever. Session completion = pid exit + the explicit `completed` event.
2. **Session transport is a log file, not a pipe.** Agent stdout redirects to `session.log`; the driver tails from a persisted byte offset. This makes crash adoption trivial (a successor orchestrator resumes exactly at the offset, zero duplicate events — verified) and sidesteps the EOF trap entirely.
3. **Reap the process group after every session end**, not only on cancel — clean completions leak grandchildren too. Tree-kill = SIGTERM to the process group, grace period, SIGKILL escalation (agents that trap SIGTERM are a tested case).
4. Stream readers must set explicit line-length limits (asyncio's default 64KB `readline` limit crashes on large tool results — raise to ≥1MB).

Prompt contract per role: the rendered prompt always contains (a) the role definition from the pack, (b) the input artifacts it needs, (c) a KG context bundle, (d) relevant memory items, (e) the artifact JSON schema it must POST to `/internal/artifacts`, and (f) chat notes addressed to it. Sections are templated so the same role file works across providers.

**Chat steering contract** (Watchtower's `notes_addressed` lesson): human chat notes to a role are queued and delivered at the role's *next spawn* (agents are stateless between spawns — no mid-session injection in v1). Every artifact schema for a role that accepts chat includes a required `notes_addressed` field listing the note IDs it read and how each was handled; artifact validation rejects submissions that ignore pending notes. Steering can therefore never silently drop.

---

## 9. Knowledge graph integration

Run code-review-graph as an embedded service per project (it is Python + SQLite — same stack, no new infra):

- **Build/update:** `kg build` on project registration; incremental update hooked to worktree merges and run completion (`kg.updated` event). Watch-mode daemon optional.
- **Context minimization (biggest cost lever):** `/internal/context/{unit_id}` composes the agent's context from `get_minimal_context` + blast radius of the slice's file list, instead of "read the repo". Target: implement/review steps read ~10–20 files, not hundreds.
- **Review intelligence:** the reviewer role's prompt includes `detect_changes` risk scores, affected flows, test-coverage gaps, and suggested questions for the slice diff. Cross-slice interference check: overlapping blast radii between parallel slices raise a warning event before both merge.
- **Planning input:** the architect role queries communities/hubs/bridges to propose slice boundaries aligned with the actual code structure — slicing quality is the main determinant of clean parallel fan-out.
- **Visualization:** dashboard embeds the D3 graph view; a run's blast radius is highlighted on it (see §11).
- **Worktree staleness:** the project graph is built from the main checkout, but agents work in worktrees that diverge from it. Each context bundle triggers an incremental parse of the worktree's changed files (code-review-graph's incremental update is <2s) and carries both the base graph SHA and the worktree delta, so reviewers reason about the code as it *is*, not as it was at branch point.

Agents reach the KG through MCP (drivers already support MCP injection), so this works identically across providers.

---

## 10. Memory and compounding

Every playbook ends with an ungated `compound` step (reviewer-class role, cheap model):

1. Reads the run's full event log, rejected artifact versions + feedback, review findings, and rework loops.
2. Distills structured memory items: `lesson` (what went wrong and the fix), `pattern` (what worked, reusable), `pitfall` (project-specific trap). Each is small, titled, markdown-bodied, with a source-run link.
3. Writes to the `memory` table scoped to pack, project, or role.

Injection: at prompt render, the top-k memory items are selected by scope match + embedding similarity to the step's input artifacts, under a fixed token budget (~1–2k). Memory is content, so packs can ship curated memory, and a periodic `consolidate` job (or manual dashboard action) merges duplicates and prunes stale items — mirroring rejected-feedback themes into role prompt improvements is the human-in-the-loop part of compounding.

Success metric to track from day one: **rework rate (rejections per artifact kind) should trend down across runs in the same project.** That's the compounding curve made visible.

---

## 11. Visualization and dashboard

React/Vite/TS + Tailwind (Watchtower-proven stack). SSE-first with poll reconciliation. Views:

- **Portfolio home** — the landing page: one card per project with health at a glance (active runs + phase, pending gates and human tasks, last-run outcome, rework-rate trend, budget burn this period). Sort by attention-needed. This is the "monitor multiple software projects" surface — a supervisor sees the whole factory floor before drilling into any project.
- **Project view** — one project's runs (active + history), its KG status, memory items, metrics trends, and project settings (default playbook, gate policy, budget caps).
- **Runs home** — cards per run: project, playbook, phase progress, pending-gate count, budget burn. Filterable by project.
- **Run detail** — the core screen, four synchronized panels:
  - *Pipeline ribbon* — playbook steps as nodes with the two-pill A/H (agent done / human approved) status from Watchtower; derived gates rendered distinctly.
  - *DAG view* — live force/dagre layout of work units: colors by status, convoy grouping, dependency edges; click → unit drawer (events, session log, artifact, gate). This is the "monitored and visualised" heart of the platform.
  - *Artifacts & gates panel* — latest artifacts by kind/slice, version history, approve/reject with chips + free text.
  - *Feed & chat* — event stream and human↔role notes.
- **Fleet view** — all active sessions across runs: model, tokens, current tool call ticker, cancel buttons.
- **My queue** — the human-task inbox: pending gates and `human_task` units across all runs, sorted by age, with batch-approve for convoys. This is the screen an operator lives in; gate latency is won or lost here.
- **Knowledge view** — embedded KG graph with run blast-radius overlay; memory browser with per-item provenance.
- **Packs & settings** — pack inventory, role/playbook viewer, gate-policy defaults, driver config, budgets.

### 11.1 Metrics rollup

All metrics derive from the event log — no separate instrumentation. A rollup job (on run close + nightly) materializes per-project time series; the dashboard gets a metrics view over them:

| Metric | Derivation | Why it matters |
|---|---|---|
| Approval latency | `gate.created` → `gate.approved/rejected` | The human bottleneck; the data that justifies (or kills) selective gating later |
| Portfolio rollups | all of the below, grouped by project | Cross-project comparison: which projects rework most, cost most, stall longest |
| Rework rate | rejections / artifacts, per kind | The compounding curve (§10) — must trend down per project |
| Tokens per slice / per run | session usage events | Feeds the plan-gate cost estimate (§5.3) |
| Phase durations | first/last unit events per step | Where wall-clock goes; exposes fan-out payoff |
| Retry & crash counts | `unit.retried`, `session.crashed` | Driver and infra health |
| Auto-resolved vs escalated conflicts | integration artifacts | Whether parallel slicing is actually working |

---

## 12. Reliability, scale, failure modes

- **Crash recovery:** on start, reconcile (adopt or fail sessions) → reopen `in_progress` units with no live owner → resume ticking. Because artifacts are immutable and units idempotent-by-attempt, replays are safe. Worktrees make partial code work recoverable (branch still there) or discardable (delete worktree).
- **Cancellation:** tree-kill process groups first, then flip statuses (Watchtower's cancel-propagation lesson: kill before you mark, and reject double-cancel).
- **Retries:** per-unit `max_attempts` with backoff; a failed unit past attempts becomes a human `blocked` gate, never a silent stall.
- **Budget:** token usage aggregated per session → run; warning at 80%, hard pause at 100% (pause = stop dispatching, surface a gate; never kill mid-write).
- **Backpressure & cross-project fairness:** three-level concurrency caps — global (machine capacity), per-project, per-run. Dispatch is weighted round-robin across projects with ready work, so one project's 6-slice fan-out cannot starve another project's single hotfix run; run priority (set at creation, adjustable from the dashboard) breaks ties within a project.
- **Contracts-first rule:** the store schema, event taxonomy, and REST/SSE contracts are the platform's real interface — engine logic never leaks into the ORM layer, and all cross-component communication goes through the documented APIs. This is what keeps the M5+ Rust engine port (see `backend-stack-comparison.md`) a drop-in swap rather than a rewrite of dashboard, packs, and drivers.
- **Scaling path:** the store is the only shared state, so team scale = swap SQLite→Postgres (SQLAlchemy from day one), move SSE fan-out to Postgres LISTEN/NOTIFY or Redis, run N orchestrator workers with unit-claim by compare-and-set (`current_step` claim pattern generalized), and move drivers to remote executor hosts that pull `ready` units. None of this changes the data model or API.
- **Failure modes considered:** orphaned worktrees (GC job keyed on closed units); schema-invalid artifacts (reject at `/internal/artifacts`, agent gets validation errors and retries — never store invalid); KG staleness (context bundle carries graph build SHA; reviewers warn if stale); provider CLI breaking changes (drivers are versioned, integration-tested against pinned CLI versions).

---

## 13. Trade-off analysis

| Decision | Chosen | Alternative | Why |
|---|---|---|---|
| Engine philosophy | Role-agnostic primitives (Gas City) | Hardcoded SDLC pipeline (Watchtower) | Slower start, but pipeline changes become pack edits; platform outlives any one workflow. Mitigation: ship the SDLC pack in-repo so day-1 UX equals Watchtower |
| Process model | Single process, embedded orchestrator | Separate orchestrator + queue (Celery/Temporal) | One deployable unit, no infra, shared store; the claim-based multi-worker path covers team scale later. Temporal reconsidered only if runs must span machines with exactly-once semantics |
| Store | SQLite via SQLAlchemy | Postgres from day one | Local-first requirement; ORM keeps the swap cheap. Known cost: one-writer limits — acceptable at v1 concurrency |
| Agent execution | CLI subprocess drivers | Direct API integration | Reuses subscriptions + CLIs' own tool sandboxes + MCP ecosystems; API driver added later for headless. Cost: parsing CLI streams is brittle → pin versions, contract-test drivers |
| Playbook format | Declarative TOML + JSON-schema artifacts | Python-defined pipelines | Data is inspectable, diffable, shareable in packs, and lint-able (plan-first invariant). Escape hatch: a step may reference a script for non-agent actions |
| Gates | Every artifact, human | Milestone-only gates | Your explicit choice; also the audit story. Cost is throughput — mitigated by per-run gate-policy overrides (recorded in events) |
| KG | Embed code-review-graph | Build our own indexer | Mature, MCP-native, same stack, 24 languages. Risk: upstream API churn → wrap behind one internal `KGService` interface |
| Context strategy | KG-minimal bundles | Full-repo agent exploration | 5–10× token reduction on implement/review steps; falls back to exploration when the graph has low confidence for a query |
| Worktrees per unit | Yes | Shared checkout per run | Parallel slices can't trample each other; failed work is discardable. Cost: disk + merge step complexity |

### 13.1 ADR practice — binding on implementation

The trade-offs above are this document's own record of the platform-wide decisions
made at design time. Decisions made **after** this document — a new constraint
discovered mid-build, a schema/API/protocol choice a milestone needs that this doc
left open — are recorded as Architecture Decision Records in `docs/adrs/`, not as
edits scattered through this file's prose.

**Rules for implementers and plans:**

1. Before writing an implementation plan (`superpowers:writing-plans`) or a task brief
   for any area with an existing ADR, read `docs/adrs/README.md`'s index first. An
   Accepted ADR is binding — implement to it, don't re-derive the decision from first
   principles or from a different convention you're more familiar with.
2. A plan or task that would contradict an Accepted ADR is a stop-and-ask, the same as
   any other plan-vs-reality conflict (see `superpowers:subagent-driven-development`'s
   review-loop rule: a finding that conflicts with a governing document is the human's
   call, not something to silently override either way).
3. If an ADR needs to change, write a new one that supersedes it (`Status: Superseded
   by ADR-XXX`) — never silently edit an Accepted ADR's decision out from under work
   that already depended on it.
4. This document stays the source of truth for the *initial* platform-wide trade-offs
   (§13 above); `docs/adrs/` is the source of truth for everything decided since. Where
   a later ADR revises something stated in this doc, the ADR wins — this document is
   not retroactively edited to match (that history is what makes ADRs useful; add a
   one-line pointer here only if a section would otherwise actively mislead a reader).

Current ADRs and what they bind: see `docs/adrs/README.md`. (As of this writing:
ADR-001, REST API response structure — binding on the `/api` work in M1, §15.)

---

## 14. Risks and open questions

1. **Gate fatigue.** Artifact-level gating of a 6-slice run ≈ 15+ approvals. Watch the approval-latency metric; the per-run override and a "batch approve convoy" UI action are the pressure valves.
2. **Driver brittleness** is the top operational risk — CLI stream formats change without notice. Contract tests in CI against pinned versions; `ApiDriver` is the strategic hedge.
3. **Slice-boundary quality** gates the value of parallelism. If KG-informed slicing underdelivers, fall back to fewer, larger slices (still correct, less parallel).
4. **Memory poisoning** — a bad lesson compounds negatively. Memory items are gated content too: new items land as `proposed` and appear on the dashboard for one-click accept/edit/discard.
5. **Open:** multi-repo runs (project = repo *set*) — data model supports it (namespace per repo), playbook semantics deferred to v2. Cross-run dependency (epic → child runs) — model as a playbook whose fan-out creates runs; defer.

---

## 15. Implementation roadmap

Each milestone is shippable and usable on its own; exit criteria are demos, not checklists.

### M0 — Durable core (2–3 weeks)
Store schema (WAL, single-writer task) + event log; playbook parser + DAG materializer; orchestrator tick loop (reconcile/unblock/intent-first dispatch/collect); **FakeDriver first** — the tick loop, retries, and crash recovery are proven deterministically against it in CI before any real provider is wired; ClaudeCodeDriver lands as a thin adapter at the end of the milestone; `/internal` API; CLI-only surface (`foundry run`, `foundry events --follow`).
**Exit:** (a) full engine test suite green on FakeDriver, including `kill -9` mid-run → restart → run completes, with zero tokens spent; (b) the same 3-step linear playbook (plan → implement → review) then runs end-to-end on a real repo via ClaudeCodeDriver. No UI, gates auto-approved.

### M1 — Plan-first + gates + dashboard MVP (3–4 weeks)
Artifact schemas + validation (incl. `notes_addressed` contract); human gates with reject/rework loop; `human_task` units + My-queue view; plan-first lint; derived plan-approval gate with cost estimate; dashboard: runs home, run detail (ribbon, artifacts/gates panel, SSE feed); cancel propagation; event redaction filter. `/api` responses conform to ADR-001 (`docs/adrs/001-api-response-structure.md`) — envelope, pagination, error shape, status codes — from the first endpoint, not retrofitted after the dashboard is built against something ad hoc.
**Exit:** full plan → approve → implement → reject → rework → approve cycle driven entirely from the browser, with **two registered projects running concurrently** (project registration + project-scoped runs land here; the data model is project-namespaced from M0). *This is the first daily-drivable version.*

### M2 — Fan-out + review loop + second provider (3 weeks)
Convoys + `fan_out`; per-unit worktrees; **`integrate` step** (build-order merge, integrator role, conflict escalation to human_task); agent-review loop with rotation and round cap; fleet view + DAG view; CodexDriver; concurrency caps + token budgets; metrics rollup + metrics view.
**Exit:** a 3-slice feature implemented by three parallel agents (mixed providers), peer-reviewed, integrated to one branch — including at least one auto-resolved conflict — visualized live on the DAG.

### M3 — Knowledge graph + memory (3 weeks)
KGService wrapping code-review-graph; context bundles on `/internal/context`; reviewer risk scores + cross-slice interference warnings; compound step + memory store + prompt injection + proposed-memory gating; knowledge view in dashboard.
**Exit:** measured token reduction on implement/review steps vs. M2 baseline; second run of a similar feature demonstrably references a lesson from the first.

### M4 — Packs + portfolio + polish (2–3 weeks)
Pack manifest + loader + imports + per-run version pinning; extract the built-in SDLC playbook/roles into the default pack; pack viewer UI; gate-policy overrides; chat-to-role; **portfolio home + project view + cross-project fair scheduling + project lifecycle (pause/archive)**; event archival/compaction job; docs.
**Exit:** (a) a second, different playbook (e.g., "bug fix" with a diagnose step) added purely as pack content — zero engine changes; (b) five projects registered, three running concurrently, portfolio home showing attention-ranked health across all of them.

### M5 — Team-shared (3–4 weeks, when needed)
Postgres migration; auth (basic → OIDC); multi-user approvals with decider identity; unit-claim for N workers; Docker single-image deploy (Watchtower's docker pattern); notification hooks (Teams/Slack/SMTP).
**Exit:** two users on one deployment, approving gates on shared runs, agents executing on the server.

**Sequencing rationale:** durability before UX (M0 before M1) because crash recovery is architectural — retrofitting it is a rewrite. Parallelism before intelligence (M2 before M3) because the KG's payoff is largest when reviews and slices exist to consume it. Packs late (M4) because extracting a working hardcoded pipeline into config is cheap; designing pack ergonomics before the engine exists is speculation.

### What I'd revisit as it grows
Store-mediated polling → LISTEN/NOTIFY push when tick latency matters; subprocess drivers → remote executors when agent compute outgrows one machine; JSON-schema artifacts → typed artifact registry if packs proliferate; per-artifact human gates → risk-scored selective gating (KG blast radius as the risk signal) once trust is earned — the data to justify that will be in the event log.
