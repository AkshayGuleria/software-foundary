# Dedicated metrics view — design

Source: `docs/design-deviations.md` finding G5 — design doc §11.1 implies a
standalone metrics screen ("the dashboard gets a metrics view over them"), but
`MetricsSummary` is only ever mounted inline on `RunsHomePage`, scoped to one
project, with no dedicated route.

## Scope

Frontend only. No backend changes — the existing `GET /api/metrics/{project_id}`
endpoint (`src/foundry/api/routes/metrics.py`) is reused, called once per project
from the client. §11.1's "Portfolio rollups... cross-project comparison" framing
is the point of this view, not a per-project detail screen — that's already what
the inline `MetricsSummary` on a filtered `RunsHomePage` gives you today.

## Architecture

New page `frontend/src/pages/MetricsPage.tsx`, routed at `/metrics`, added to
`App.tsx`'s nav alongside the existing Portfolio/Projects/Runs/Knowledge/Fleet/
Packs links.

**Data flow:** `listProjects()` (existing, `frontend/src/api/projects.ts`) to get
the project list, then one `getProjectMetrics(id)` query per project (existing,
`frontend/src/api/metrics.ts`) run in parallel via TanStack Query. No new API
client functions needed.

**Layout:** a table, one row per project — project name, rework rate, avg
approval latency, retry count, crash count, auto-resolved conflicts, escalated
conflicts. Same six stats `MetricsSummary` already computes and renders, just
laid out per-row instead of per-project-block. Default sort: rework rate
descending — the design doc's own framing of this metric ("must trend down per
project", §11.1's table) makes it the natural attention-order, same spirit as
`PortfolioHomePage`'s existing attention-score sort.

**Reuse decision:** `MetricsSummary`'s six-stat computation gets extracted into
a shared pure function (or the component itself is reused as a table-row
renderer, if that doesn't force an awkward API onto it) — implementer's call at
plan-writing time, whichever keeps `MetricsSummary` single-responsibility rather
than bending its existing per-project-block API to double as a table row.

**Cleanup:** `RunsHomePage`'s inline `<MetricsSummary projectId={projectId} />`
is removed (redundant once `/metrics` exists) and replaced with a plain link to
`/metrics`.

## Error handling

A project whose metrics fetch fails or is still loading renders its row with a
loading/error state rather than blocking the whole table — matches existing
per-query-key TanStack Query behavior elsewhere in this codebase (e.g.
`PortfolioHomePage`), no new pattern needed.

## Testing

`MetricsPage.test.tsx` following this codebase's existing page-test convention
(mock the API client module, assert rows render for each project, assert
default sort order is rework-rate-descending). `RunsHomePage.test.tsx` gets a
small update: assert the link to `/metrics` renders instead of the old
`MetricsSummary` embed.

## Out of scope

- No new backend endpoint. If N+1 per-project fetches become a real performance
  problem at higher project counts, a batched `GET /api/metrics?project_ids=...`
  endpoint is a natural follow-up — not needed at current scale (design doc's
  own non-functional target: 5-10 registered projects, §2.2).
- No changes to `MetricsSummary`'s six computed stats or their derivation
  (`src/foundry/metrics/rollup.py`) — this is a presentation-layer change only.
