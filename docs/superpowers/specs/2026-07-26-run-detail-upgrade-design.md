# Run detail upgrade — design

## Goal

Close the gap between design doc §11's description of the Run detail screen
("the core screen, four synchronized panels") and what's actually built.
The current implementation is functionally complete (every route/action
works) but visually and interactively minimal compared to what was
designed: a static hand-computed SVG DAG with no click-through, a
single-pill status ribbon instead of the two-pill agent/human pattern, no
per-unit drawer, and a reject flow whose chip-feedback field has always
been sent empty.

This is the first of what will likely be several view-upgrade passes
across design doc §11's other under-built views (Fleet, Portfolio home,
Knowledge, Packs & settings) — Run detail was chosen first as the
highest-visibility, most self-contained gap.

## Current state (verified against the actual code, not assumed)

- `frontend/src/components/DagView.tsx` — a hand-rolled layered layout
  (`computeLevels` walks dependency levels, positions nodes in a fixed
  grid). No graph library is installed (`frontend/package.json` has no
  dagre/d3/react-flow). Nodes have no click handler; there is no drill-in
  view of any kind.
- `frontend/src/components/Ribbon.tsx` — one pill per step reading
  `{step_id} · {status}`, colored by `WorkUnit.status` alone. No gate
  information reaches this component at all today (`RunDetailPage`
  only passes `units`).
- `frontend/src/components/GateCard.tsx` — the reject flow already
  threads a `feedback: { chips: string[]; text: string }` shape through
  to `decideGate`, but the chip selector UI was never built — every
  rejection submits `chips: []`, hardcoded.
- `frontend/src/pages/RunDetailPage.tsx` — two-column grid (gates+artifacts
  panel, live feed panel) plus the DAG below. No per-unit detail view.
- Backend: `GET /api/runs/{run_id}` returns `run`, `units`, `gates`
  (gates carry `work_unit_id` and, for derived gates, a `cost_estimate`).
  `GET /api/runs/{run_id}/artifacts` returns artifacts, each carrying
  `work_unit_id`. `Event` rows (streamed live via SSE and re-fetchable)
  carry `unit_id`. `GET /api/sessions` exists but is fleet-wide and
  active-sessions-only — no way to see a specific run's session history
  once a session has closed or crashed.

## Scope

**In scope:**
- Two-pill ribbon (agent-done / human-approved) replacing the single
  status pill.
- Interactive DAG using `dagre` for layout, with click-through to a unit
  drawer.
- Unit drawer with four tabs: Events, Artifact, Gate, Session log.
- New backend endpoint for per-run session history (needed for the
  Session log tab — nothing else in scope needs it).
- Reject-with-chips: a fixed set of toggleable rejection-reason chips
  alongside the existing free-text field.

**Out of scope (explicitly deferred, not forgotten):**
- Any other §11 view (Fleet, Portfolio home, Knowledge, Packs & settings)
  — each is its own future upgrade pass.
- Chat / human↔role notes (design doc's "Feed & chat" panel) — this is
  the already-documented A4/G1 gap (`docs/design-deviations.md`),
  deliberately out of scope for the whole codebase, not something this
  pass reopens.
- Pan/zoom controls on the DAG beyond what dagre's static layout plus the
  page's existing `overflow-x-auto` wrapper already provide — if the
  laid-out graph is large enough to need real pan/zoom, that's a
  follow-up, not blocking this pass.
- Editable/configurable chip vocabulary (admin-defined rejection reasons)
  — the chip set is a fixed, hardcoded list for this pass.

## Design decisions

**1. Two-pill ribbon.**

`Ribbon` gains a second prop, `gates: Gate[]` (passed alongside the
existing `units: WorkUnit[]` from `RunDetailPage`, which already has both
in `detail`). For each non-session unit, look up its gate (if any) by
`gate.work_unit_id === unit.id`. Render two adjacent pills per step:

- **A** (agent) — colored by `unit.status`, same palette as today's single
  pill (`closed`/`blocked`/`failed`/`killed`/`in_progress`/`ready`/`open`).
- **H** (human) — colored by the associated gate's `decision`
  (`pending`/`approved`/`rejected`), or rendered dimmed/omitted if the
  step has no gate. Derived gates (`gate_type === "derived"`) get a
  visually distinct marker (a small corner badge or border style, not a
  third pill) so plan-approval gates read differently from human-review
  gates at a glance.

Steps with no gate (e.g. a step whose review is still pending dispatch)
show only the A pill — no phantom H pill for a gate that doesn't exist
yet.

**2. Interactive DAG via dagre.**

Add `dagre` (MIT-licensed, ~30KB, zero runtime dependencies beyond
`lodash`-lite internals it bundles) as a new frontend dependency.
`DagView` keeps its current props (`units`, `deps`) and still renders
plain SVG — dagre only replaces the layout math (`computeLevels` and the
manual `positions` grid), producing `x`/`y` per node and an edge-routing
point list per edge via `dagre.layout(graph)`. Visual styling (status
colors, convoy dashed-border grouping) is unchanged. Each node's `<g>`
wrapper gains `onClick={() => onNodeClick(unit)}`, plumbed up through a
new required prop `onNodeClick: (unit: WorkUnit) => void` — `RunDetailPage`
supplies this to open the drawer.

**3. Unit drawer.**

A slide-over panel (fixed-position overlay, dismissible via an explicit
close button and clicking the backdrop — no new routing/URL state, this
is local component state in `RunDetailPage`: `const [selectedUnit,
setSelectedUnit] = useState<WorkUnit | null>(null)`). Opened by clicking
either a DAG node or (for consistency) a Ribbon pill — both call the same
`onNodeClick`/equivalent handler. Four tabs, each filtering already-loaded
data client-side (no new fetches except the Session log tab):

- **Events** — `events.filter(e => e.unit_id === selectedUnit.id)` from
  the page's existing `useEventStream(runId)` result.
- **Artifact** — `artifacts.filter(a => a.work_unit_id === selectedUnit.id)`
  from the page's existing `getRunArtifacts` query, rendered via the
  existing `ArtifactCard` component (one card per version, newest first).
- **Gate** — the unit's gate (if any) from `detail.gates`, rendered via
  the existing `GateCard` component (same approve/reject affordance as
  today's flat gates list — the drawer doesn't duplicate gate-decision
  logic, it reuses the component).
- **Session log** — fetched from the new backend endpoint (below),
  filtered to `work_unit_id === selectedUnit.id`, rendered as a simple
  list (driver, model, status, token counts, started/ended timestamps) —
  no new component needed beyond a small inline list, matching the
  existing `FleetPage` list's visual weight.

**4. New backend endpoint: per-run session history.**

`GET /api/runs/{run_id}/sessions` in `src/foundry/api/routes/runs.py`.
Unlike `GET /api/sessions` (fleet-wide, `Store.list_active_sessions()`
only), this returns every `SessionRow` for the given run regardless of
status — needs a new `Store` method, `list_sessions(run_id: str) ->
list[SessionRow]`, a plain `select(SessionRow).where(SessionRow.run_id ==
run_id)` query (no new columns, no schema change). Response shape mirrors
the existing `SessionOut` pydantic model from `sessions.py` (reused, not
duplicated) — id, work_unit_id, run_id, step_id, driver, status, model,
tokens_in, tokens_out, started_at — plus `ended_at: str | None` if the
`SessionRow` model has that field (check `src/foundry/store/models.py`
before implementing; if it doesn't, that's an implementation-plan-level
finding, not a design gap — the endpoint should still ship without it
rather than block on a schema addition for a "nice to have" timestamp).

**5. Reject-with-chips.**

`GateCard`'s reject flow gains a fixed chip list above the existing
free-text `<textarea>`: `["missing tests", "wrong approach", "incomplete",
"needs docs"]` (matching the example vocabulary Part 1's demo-seed data
already uses, so seeded demo data and real usage read consistently).
Chips are toggleable (click to select/deselect, multiple selectable),
rendered as small pill buttons; selected chips populate the `chips: []`
array already threaded through to `onDecide("rejected", { chips, text })`
— no change to the data flow below `GateCard`, since `Gate.feedback_json`
already stores whatever shape is sent and nothing downstream currently
reads `chips` specifically (confirmed: no other component destructures
`feedback.chips` today, so this is purely additive, not a breaking change
to any existing consumer).

## Non-functional constraints

- No backend schema changes (the new endpoint is a read-only query over
  existing `SessionRow` data).
- `dagre` is the only new dependency this pass introduces — matches the
  scoped decision above, not a broader "add a graph library" free-for-all.
- Existing tests for `DagView`, `Ribbon`, `GateCard`, `RunDetailPage` all
  need updating for the new props/behavior, not just new tests bolted on
  — several of them assert on the current single-pill/no-click-handler
  shape and will need their assertions rewritten, not merely extended.

## What I did not design here

- Exact dagre configuration (rank direction, node separation, edge
  routing style) — implementation-plan-level, pick sensible defaults and
  adjust visually during implementation.
- Exact drawer open/close animation/transition — implementation detail.
- Exact chip pill styling/placement relative to the textarea — match
  existing Tailwind conventions used elsewhere in `GateCard`/`Ribbon`,
  implementation-plan-level.
- Whether `SessionRow` has an `ended_at` column — implementation-plan-level
  finding (see Design decision 4).
