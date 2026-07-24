# Dedicated Metrics View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated `/metrics` page showing a portfolio-wide comparison
table (one row per project) of the six stats currently only visible embedded
in `RunsHomePage` for a single filtered project.

**Architecture:** Extract `MetricsSummary`'s six-stat computation into an
exported pure function, reused by both the existing `MetricsSummary` component
(unchanged output) and a new `MetricsPage` that fetches all projects' metrics
via `useQueries`, sorts by rework rate descending, and renders one table row
per project. Remove the now-redundant inline `MetricsSummary` embed from
`RunsHomePage` in favor of a link to `/metrics`.

**Tech Stack:** React, TypeScript, `@tanstack/react-query` (including
`useQueries`, not yet used elsewhere in this codebase but part of the existing
dependency), `react-router-dom`, Tailwind, Vitest + Testing Library.

## Global Constraints

- No backend changes. Reuses `GET /api/metrics/{project_id}`
  (`src/foundry/api/routes/metrics.py`) exactly as-is — do not modify it.
- No new API client functions beyond what's listed below — `listProjects()`
  (`frontend/src/api/projects.ts`) and `getProjectMetrics()`
  (`frontend/src/api/metrics.ts`) already exist and are reused unchanged.
- Follow this codebase's existing test convention exactly: `vi.stubGlobal("fetch", ...)`
  mocking `apiFetch`'s underlying `fetch` call, `QueryClientProvider` +
  `MemoryRouter` wrapper (see `frontend/src/pages/PortfolioHomePage.test.tsx`
  for the reference pattern).
- `ProjectMetrics.rework_rate` is a plain `number` (not nullable) — no
  null-handling needed when sorting, unlike `ProjectHealth.rework_rate` on
  the portfolio page which is `number | null`.

---

### Task 1: Extract `metricsStats` as a reusable pure function

**Files:**
- Modify: `frontend/src/components/MetricsSummary.tsx`
- Test: `frontend/src/components/MetricsSummary.test.tsx` (existing test must
  still pass unchanged; add one new unit test for the exported function)

**Interfaces:**
- Produces: `metricsStats(metrics: ProjectMetrics): { label: string; value: string }[]`,
  exported from `frontend/src/components/MetricsSummary.tsx`. Task 2 imports
  this directly.

- [ ] **Step 1: Write the failing test for the exported function**

Add to `frontend/src/components/MetricsSummary.test.tsx` (keep the existing
`describe("MetricsSummary", ...)` block and its one test exactly as-is; add
this as a new top-level `describe` block in the same file):

```typescript
import { metricsStats } from "./MetricsSummary";

describe("metricsStats", () => {
  it("formats all six stats from raw metrics", () => {
    const stats = metricsStats({
      approval_latency_seconds: 120,
      rework_rate: 0.25,
      retry_count: 2,
      crash_count: 1,
      auto_resolved_count: 3,
      escalated_count: 1,
    });

    expect(stats).toEqual([
      { label: "Rework rate", value: "25%" },
      { label: "Avg approval latency", value: "120s" },
      { label: "Retries", value: "2" },
      { label: "Crashes", value: "1" },
      { label: "Auto-resolved conflicts", value: "3" },
      { label: "Escalated conflicts", value: "1" },
    ]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/MetricsSummary.test.tsx`
Expected: FAIL — `metricsStats` is not exported from `./MetricsSummary` yet.

- [ ] **Step 3: Extract the function and use it in the component**

Replace the full contents of `frontend/src/components/MetricsSummary.tsx`
with:

```typescript
import { useQuery } from "@tanstack/react-query";
import { getProjectMetrics } from "../api/metrics";
import type { ProjectMetrics } from "../api/metrics";

export function metricsStats(metrics: ProjectMetrics): { label: string; value: string }[] {
  return [
    { label: "Rework rate", value: `${Math.round(metrics.rework_rate * 100)}%` },
    { label: "Avg approval latency", value: `${Math.round(metrics.approval_latency_seconds)}s` },
    { label: "Retries", value: String(metrics.retry_count) },
    { label: "Crashes", value: String(metrics.crash_count) },
    { label: "Auto-resolved conflicts", value: String(metrics.auto_resolved_count) },
    { label: "Escalated conflicts", value: String(metrics.escalated_count) },
  ];
}

export default function MetricsSummary({ projectId }: { projectId: string }) {
  const { data: metrics } = useQuery({
    queryKey: ["project-metrics", projectId],
    queryFn: () => getProjectMetrics(projectId),
  });

  if (!metrics) return null;

  return (
    <div className="grid grid-cols-2 gap-2 rounded border border-slate-800 p-3 sm:grid-cols-3 md:grid-cols-6">
      {metricsStats(metrics).map((s) => (
        <div key={s.label} className="flex flex-col gap-1">
          <span className="text-lg font-semibold tabular-nums">{s.value}</span>
          <span className="text-xs text-slate-500">{s.label}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 4: Run tests to verify both pass**

Run: `cd frontend && npx vitest run src/components/MetricsSummary.test.tsx`
Expected: PASS — both the pre-existing `MetricsSummary` rendering test and
the new `metricsStats` unit test.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/MetricsSummary.tsx frontend/src/components/MetricsSummary.test.tsx
git commit -m "refactor(frontend): extract metricsStats as a reusable pure function

No behavior change to MetricsSummary's rendered output -- pulls the
six-stat formatting logic out so the upcoming portfolio-wide metrics
table can reuse it without duplicating the label/value formatting."
```

---

### Task 2: `MetricsPage` + nav/route wiring + `RunsHomePage` cleanup

**Files:**
- Create: `frontend/src/pages/MetricsPage.tsx`
- Test: `frontend/src/pages/MetricsPage.test.tsx`
- Modify: `frontend/src/App.tsx` (add route + nav link)
- Modify: `frontend/src/pages/RunsHomePage.tsx` (remove `MetricsSummary` embed, add link)
- Modify: `frontend/src/pages/RunsHomePage.test.tsx` (assert the new link instead)

**Interfaces:**
- Consumes: `metricsStats(metrics: ProjectMetrics)` from Task 1
  (`frontend/src/components/MetricsSummary.tsx`); `listProjects(): Promise<Project[]>`
  (`frontend/src/api/projects.ts`); `getProjectMetrics(id: string): Promise<ProjectMetrics>`
  and `ProjectMetrics` type (`frontend/src/api/metrics.ts`); `Project` type
  (`frontend/src/api/types.ts`, has `id: string; name: string; ...`).

- [ ] **Step 1: Write the failing test for `MetricsPage`**

Create `frontend/src/pages/MetricsPage.test.tsx`:

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import MetricsPage from "./MetricsPage";

function renderWithProviders() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <MetricsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("MetricsPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders one row per project sorted by rework rate descending", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: [
                { id: "p1", name: "quiet", path: "/tmp/quiet", kg_status: "none", status: "active", created_at: "2026-07-01T00:00:00Z" },
                { id: "p2", name: "busy", path: "/tmp/busy", kg_status: "none", status: "active", created_at: "2026-07-01T00:00:00Z" },
              ],
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { approval_latency_seconds: 10, rework_rate: 0.1, retry_count: 0, crash_count: 0, auto_resolved_count: 0, escalated_count: 0 },
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p2") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { approval_latency_seconds: 20, rework_rate: 0.9, retry_count: 1, crash_count: 1, auto_resolved_count: 0, escalated_count: 1 },
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders();

    await waitFor(() => expect(screen.getByText("busy")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("quiet")).toBeInTheDocument());

    const rows = screen.getAllByRole("row").filter((r) => r.textContent?.includes("busy") || r.textContent?.includes("quiet"));
    expect(rows[0]).toHaveTextContent("busy");
    expect(rows[1]).toHaveTextContent("quiet");
    expect(screen.getByText("90%")).toBeInTheDocument();
  });

  it("shows a per-row error state without dropping the row or blocking other rows", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: [
                { id: "p1", name: "healthy", path: "/tmp/healthy", kg_status: "none", status: "active", created_at: "2026-07-01T00:00:00Z" },
                { id: "p2", name: "broken", path: "/tmp/broken", kg_status: "none", status: "active", created_at: "2026-07-01T00:00:00Z" },
              ],
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { approval_latency_seconds: 10, rework_rate: 0.1, retry_count: 0, crash_count: 0, auto_resolved_count: 0, escalated_count: 0 },
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p2") {
          return Promise.resolve({
            ok: false, status: 500,
            json: async () => ({ error: { code: "INTERNAL_ERROR", message: "boom", status_code: 500, details: null } }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders();

    await waitFor(() => expect(screen.getByText("healthy")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText("broken")).toBeInTheDocument());
    await waitFor(() => expect(screen.getByText(/failed to load metrics/i)).toBeInTheDocument());
    // The healthy row's real stats still render even though the other row errored.
    expect(screen.getByText("10%")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/MetricsPage.test.tsx`
Expected: FAIL — `Cannot find module './MetricsPage'`.

- [ ] **Step 3: Implement `MetricsPage`**

Per the spec's error-handling requirement, a project whose metrics query is
still loading or has failed must still render its row (with a loading/error
state), not be silently dropped from the table — the table must not block on
every project's fetch settling before showing anything.

Create `frontend/src/pages/MetricsPage.tsx`:

```typescript
import { useQueries, useQuery } from "@tanstack/react-query";
import { getProjectMetrics } from "../api/metrics";
import { listProjects } from "../api/projects";
import { metricsStats } from "../components/MetricsSummary";

const STAT_LABELS = [
  "Rework rate",
  "Avg approval latency",
  "Retries",
  "Crashes",
  "Auto-resolved conflicts",
  "Escalated conflicts",
];

export default function MetricsPage() {
  const { data: projects, isLoading: projectsLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: listProjects,
  });

  const metricsQueries = useQueries({
    queries: (projects ?? []).map((project) => ({
      queryKey: ["project-metrics", project.id],
      queryFn: () => getProjectMetrics(project.id),
    })),
  });

  if (projectsLoading || !projects) {
    return <p className="text-slate-400">Loading…</p>;
  }

  const rows = projects
    .map((project, i) => ({ project, query: metricsQueries[i] }))
    .sort((a, b) => (b.query.data?.rework_rate ?? -1) - (a.query.data?.rework_rate ?? -1));

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Metrics</h2>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-slate-800 text-xs uppercase text-slate-500">
            <th className="py-2">Project</th>
            {STAT_LABELS.map((label) => (
              <th key={label} className="py-2">{label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(({ project, query }) => (
            <tr key={project.id} className="border-b border-slate-900">
              <td className="py-2 font-medium">{project.name}</td>
              {query.isError ? (
                <td colSpan={STAT_LABELS.length} className="py-2 text-red-400">
                  Failed to load metrics
                </td>
              ) : query.data ? (
                metricsStats(query.data).map((s) => (
                  <td key={s.label} className="py-2 tabular-nums">{s.value}</td>
                ))
              ) : (
                <td colSpan={STAT_LABELS.length} className="py-2 text-slate-500">
                  Loading…
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/MetricsPage.test.tsx`
Expected: PASS

- [ ] **Step 5: Wire the route and nav link into `App.tsx`**

In `frontend/src/App.tsx`, add the import:

```typescript
import MetricsPage from "./pages/MetricsPage";
```

Add a nav link after the "Fleet" link and before "Packs" (matches the design
doc §11's view ordering — metrics sits alongside the other operational
views):

```tsx
          <NavLink to="/fleet" className="text-slate-400 hover:text-orange-400">
            Fleet
          </NavLink>
          <NavLink to="/metrics" className="text-slate-400 hover:text-orange-400">
            Metrics
          </NavLink>
          <NavLink to="/packs" className="text-slate-400 hover:text-orange-400">
            Packs
          </NavLink>
```

Add the route:

```tsx
          <Route path="/fleet" element={<FleetPage />} />
          <Route path="/metrics" element={<MetricsPage />} />
          <Route path="/packs" element={<PacksPage />} />
```

- [ ] **Step 6: Remove the inline `MetricsSummary` embed from `RunsHomePage`**

In `frontend/src/pages/RunsHomePage.tsx`, remove the `MetricsSummary` import
and replace its usage:

```typescript
import { Link, useSearchParams } from "react-router-dom";
```

(remove the `import MetricsSummary from "../components/MetricsSummary";` line
entirely — nothing else in this file references it)

Replace:

```tsx
      {projectId && <MetricsSummary projectId={projectId} />}
```

with:

```tsx
      {projectId && (
        <Link to="/metrics" className="text-sm text-orange-400 hover:underline">
          View portfolio metrics →
        </Link>
      )}
```

- [ ] **Step 7: Update `RunsHomePage.test.tsx`**

`frontend/src/pages/RunsHomePage.test.tsx`'s existing test
(`"lists runs and links each to its detail page"`) doesn't reference
`MetricsSummary` or metrics at all, so it needs no change — verify this by
re-running it. Add one new test to the same `describe` block confirming the
link now renders instead:

```typescript
  it("shows a link to the metrics page when filtered by project", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200, json: async () => ({ data: [], paging: {} }),
    });

    renderWithProviders(["/runs?project_id=01JP1"]);

    await waitFor(() =>
      expect(screen.getByRole("link", { name: /view portfolio metrics/i })).toHaveAttribute("href", "/metrics"),
    );
  });
```

- [ ] **Step 8: Run the full frontend test suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS — no regressions in any other page's tests.

- [ ] **Step 9: Manually verify in a running dev server**

Run: `cd frontend && npm run dev` (or the project's existing dev-server
command — check `frontend/package.json`'s `scripts` if `npm run dev` isn't
right), then in a browser: navigate to `/metrics`, confirm the table renders
with real backend data (requires the backend API server running too — see
`foundry serve` in `src/foundry/cli.py`); navigate to `/runs?project_id=<real-id>`,
confirm the "View portfolio metrics →" link appears and navigates correctly.
Stop the dev server when done.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/MetricsPage.tsx frontend/src/pages/MetricsPage.test.tsx \
        frontend/src/App.tsx frontend/src/pages/RunsHomePage.tsx frontend/src/pages/RunsHomePage.test.tsx
git commit -m "feat(frontend): add dedicated portfolio metrics view at /metrics

Closes design-deviations.md finding G5. Table sorted by rework rate
descending (design doc §11.1's own framing: 'must trend down per
project' makes it the natural attention-order, matching the portfolio
page's existing attention-score sort). Removes the now-redundant
inline MetricsSummary embed from RunsHomePage in favor of a link."
```

---

## Final verification

- [ ] Run: `cd frontend && npx vitest run && npx tsc --noEmit`
  Expected: all tests pass, no type errors.
- [ ] Confirm no dangling references: `grep -rn "MetricsSummary" frontend/src`
  Expected: only `MetricsSummary.tsx`, `MetricsSummary.test.tsx`, and
  `MetricsPage.tsx` (which imports `metricsStats` from it) — `RunsHomePage.tsx`
  no longer appears.
