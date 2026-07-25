# My-queue + batch-approve — design

Source: `docs/design-deviations.md` finding G2 — design doc §11 describes a
cross-project human-task inbox ("pending gates and `human_task` units across
all runs, sorted by age, with batch-approve for convoys"). No cross-project
listing exists today; gates are only ever viewed/decided per-run via
`RunDetailPage`.

## Scope decisions (resolved during brainstorming)

- **Includes `human_task` resolution, not just gates.** While scoping this,
  found `Store.complete_human_task()` exists but is never called from any
  API route — a `human_task` unit (budget-exceeded escalation, gate-conflict
  escalation, see `src/foundry/orchestrator/tick.py:523,663-686`) has zero
  path to actual resolution today. Same "built but dormant" pattern as
  earlier fixes this session. Fixing it here since My-queue would otherwise
  list human-task items with no action available.
- **Batch action is approve-only.** Design doc's literal wording is
  "batch-approve." Rejecting a gate carries structured feedback
  (chips + text) that doesn't have a meaningful bulk form — batch-reject
  would be a quality regression vs. today's single-gate reject flow.
  Rejecting stays a per-gate action on `RunDetailPage`, not duplicated here.

## In scope

**Backend — composition only, no new complex store queries.** Follows the
same pattern `src/foundry/api/routes/portfolio.py` already establishes:
fetch broad lists (`list_projects()`, `list_runs()`), loop per-run store
calls (`list_gates_for_run`, `list_units`), compose in the route layer.

- `GET /api/queue` — new route (`src/foundry/api/routes/queue.py`). Two
  sorted-oldest-first lists:
  - **Gates**: `gate_type in ("human", "derived")`, `decision == "pending"`.
    Excludes `agent`-type gates — those are decided by AI
    (`_dispatch_agent_reviews`), never awaiting a human. Each item enriched
    with project name, run title, and the underlying `WorkUnit.created_at`
    as an age proxy (`Gate` has no timestamp column of its own — adding one
    is unnecessary when the unit's timestamp is close enough and already
    available).
  - **Human tasks**: `WorkUnit.type == "human_task"`, `status == "open"`,
    enriched the same way.
- `POST /api/gates/batch-decide` — body `{gate_ids: string[]}`. Loops the
  existing `store.decide_gate(id, "approved", decided_by="api")` per id. A
  gate already decided by the time the batch runs (race with another
  approver, or the same gate submitted twice) is skipped, not treated as a
  batch failure — response reports which ids were approved vs. skipped.
- `POST /api/human-tasks/{unit_id}/complete` — thin wrapper around the
  existing `Store.complete_human_task()`. 404 if the unit doesn't exist,
  409 if it isn't an open `human_task` (already closed, or not a
  `human_task` type at all).

**Frontend:**
- New `QueuePage.tsx`, routed at `/queue`, added to nav. Two sections:
  - **Gates**: checkbox per row, "Approve selected" batch button calling
    `POST /api/gates/batch-decide`; each row links to `/runs/:id` for full
    context (artifact preview, reject-with-feedback) — the queue page
    itself doesn't duplicate `RunDetailPage`'s `GateCard`.
  - **Human tasks**: each row shows project/run/reason context with a
    "Mark resolved" button calling the new complete endpoint.

## Out of scope

- Batch-reject (see scope decision above).
- Any change to `RunDetailPage`'s existing single-gate decide flow or
  `GateCard` component.
- A `Gate.created_at` column — the underlying work unit's timestamp is used
  instead.
- Filtering the queue by project, assignee, or gate type in the UI — a
  flat, oldest-first list for both sections is the v1 shape; design doc
  doesn't call for filtering and nothing in the current dashboard has that
  pattern either.

## Testing

Backend: `GET /api/queue` returns only pending human/derived gates and open
human tasks (not agent gates, not already-decided gates, not closed human
tasks), sorted oldest-first, with correct project/run enrichment;
`POST /api/gates/batch-decide` approves multiple gates and correctly skips
an already-decided one without failing the whole batch;
`POST /api/human-tasks/{id}/complete` resolves an open human task and 404s/
409s appropriately. Frontend: `QueuePage` renders both sections, batch
checkbox selection + approve calls the endpoint with the right ids, human
task "Mark resolved" calls its endpoint.
