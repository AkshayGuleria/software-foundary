# Project view (per-project drill-down) — design

Source: `docs/design-deviations.md` finding G3 — design doc §11 specifies a
per-project drill-down page (runs, KG status, memory items, metrics trends,
settings). No `/projects/:id` route exists today; `ProjectsPage` is a flat
list, and project links go straight to `/runs?project_id=X`.

## Scope

Frontend composition only. No new backend routes — every piece of data this
page needs already has a working endpoint:

- `GET /api/projects/{id}` (project header)
- `GET /api/runs?project_id={id}` (runs)
- `GET /api/metrics/{id}` (metrics)
- `GET /api/projects/{id}/kg-graph` (KG graph)
- `GET /api/memory?project_id={id}` (memory items)

**Explicitly excluded: project settings** (default playbook, gate policy,
budget caps). Design doc §11 lists these as part of the "Project view," but
`Project` (`src/foundry/store/models.py:37-44`) has no columns for any of
them — there is nothing to display or edit. That's deviation G4's scope
(Packs & settings mutations), a separate spec/plan/build cycle. This page
ships without a settings section; it is not a partial implementation of one.

## Architecture

New page `frontend/src/pages/ProjectDetailPage.tsx`, routed at `/projects/:id`
in `App.tsx`. Every data-fetching/rendering piece is reused from existing
pages, not reimplemented:

- **Header:** project name, path, status pill, `ProjectLifecycleButtons`
  (`frontend/src/components/ProjectLifecycleButtons.tsx`, used exactly as on
  `ProjectsPage`/`PortfolioHomePage` today, `invalidateQueryKey` scoped to
  this project's own query key).
- **Runs:** `listRuns({ project_id })` (`frontend/src/api/runs.ts`), most
  recent 5 shown inline (each linking to `/runs/:id`), plus a
  "View all runs →" link to `/runs?project_id={id}` for full filterable
  history. Reuses the same run-row rendering shape `RunsHomePage` already
  has (status + link), not a new list component.
- **Metrics:** `getProjectMetrics(id)` (`frontend/src/api/metrics.ts`) +
  `metricsStats()` (`frontend/src/components/MetricsSummary.tsx`, exported
  as a pure function per the metrics-view work) — same six stats shown
  elsewhere, rendered inline rather than as a table row.
- **Knowledge:** `getProjectKgGraph(id)` + `KgGraphView` and
  `listMemory({ project_id: id })` + `MemoryBrowser` — both lifted directly
  from `KnowledgePage`'s existing per-project rendering
  (`frontend/src/pages/KnowledgePage.tsx:16-25,73-81`), same components, same
  query shapes.

**New API client function:** `getProject(id: string): Promise<Project>` in
`frontend/src/api/projects.ts` — the only client-side gap; the backend route
(`GET /api/projects/{project_id}`, `src/foundry/api/routes/projects.py:60-65`)
already exists and is untouched.

## Navigation change

`ProjectsPage`'s row link and `PortfolioHomePage`'s card link both repoint
from `/runs?project_id={id}` to `/projects/{id}`. The new page's own
"View all runs →" link is how a user reaches the full filterable runs list
that used to be the direct target — nothing about `RunsHomePage` itself
changes, only what links into it from these two places.

## Error handling

A project ID that doesn't resolve (`GET /api/projects/{id}` 404s) renders a
"Project not found" message rather than a blank page or crash — same
`ApiClientError` handling pattern `apiFetch` already provides elsewhere (no
new error-handling mechanism, just don't let it go unhandled).

## Testing

`ProjectDetailPage.test.tsx` following this codebase's existing page-test
convention (mock `fetch`, assert each section renders with its data). Two
small additions to existing test files: `ProjectsPage.test.tsx` and
`PortfolioHomePage.test.tsx` get their link-target assertions updated from
`/runs?project_id=...` to `/projects/...` (if either file currently asserts
on the old href — check before assuming; if neither does today, this becomes
a new assertion added, not a modification of an existing one).

## Out of scope

- No settings/config editing (G4, separate cycle).
- No changes to `RunsHomePage`, `KnowledgePage`, or `MetricsPage` themselves —
  this page composes their underlying data/components, it doesn't replace or
  modify them. `KnowledgePage`'s own project-picker flow (for someone who
  lands on `/knowledge` directly without a project context) stays as-is.
- No new backend routes, no schema changes.
