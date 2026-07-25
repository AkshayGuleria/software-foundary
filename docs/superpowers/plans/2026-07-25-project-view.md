# Project Detail View Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a per-project drill-down page at `/projects/:id` composing that
project's runs, metrics, KG graph, and memory items — closing
design-deviations.md finding G3.

**Architecture:** One new page, `ProjectDetailPage.tsx`, built incrementally
across 4 tasks (header/route → runs+metrics → knowledge → navigation
repoint). Every data-fetching/rendering piece is reused from existing pages
(`ProjectLifecycleButtons`, `KgGraphView`, `MemoryBrowser`, `metricsStats`,
`listRuns`) — no new backend routes.

**Tech Stack:** React, TypeScript, `@tanstack/react-query`,
`react-router-dom` (`useParams`), Tailwind, Vitest + Testing Library.

## Global Constraints

- No backend changes anywhere in this plan.
- No settings/config section — `Project` has no fields for default playbook,
  gate policy, or budget caps (deviation G4's separate scope).
- Follow this codebase's established test convention: `vi.stubGlobal("fetch", ...)`,
  `QueryClientProvider` + `MemoryRouter` wrapper (see
  `frontend/src/pages/PortfolioHomePage.test.tsx`).
- `useParams<{ id: string }>()` + non-null assertion is this codebase's
  existing pattern for a required route param (see
  `frontend/src/pages/RunDetailPage.tsx:12-13`) — follow it, don't invent a
  different param-handling approach.

---

### Task 1: `getProject()` client function + page skeleton + route

**Files:**
- Modify: `frontend/src/api/projects.ts`
- Create: `frontend/src/pages/ProjectDetailPage.tsx`
- Test: `frontend/src/pages/ProjectDetailPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Produces: `getProject(id: string): Promise<Project>` in
  `frontend/src/api/projects.ts`. Tasks 2-3 don't need it directly (they
  fetch their own data), but it's this task's foundation for the header.
- Produces: `ProjectDetailPage` default export, mounted at `/projects/:id`.
  Tasks 2-3 add sections to this same component.

- [ ] **Step 1: Write the failing test for `getProject`**

Add to a new test file `frontend/src/api/projects.test.ts` if one doesn't
already exist — check first with `ls frontend/src/api/projects.test.ts`. If
it exists, add this test into it; if not, create it with just this test:

```typescript
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getProject } from "./projects";

describe("getProject", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("fetches a single project by id", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: { id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" },
        paging: {},
      }),
    });

    const project = await getProject("p1");

    expect(project.name).toBe("acme");
    expect(fetch).toHaveBeenCalledWith("/api/projects/p1", undefined);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/projects.test.ts`
Expected: FAIL — `getProject` is not exported from `./projects`.

- [ ] **Step 3: Add `getProject` to the API client**

In `frontend/src/api/projects.ts`, add:

```typescript
export async function getProject(id: string): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}`);
  return res.data;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/projects.test.ts`
Expected: PASS

- [ ] **Step 5: Write the failing test for the page skeleton**

Create `frontend/src/pages/ProjectDetailPage.test.tsx`:

```typescript
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectDetailPage from "./ProjectDetailPage";

function renderWithProviders(projectId: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[`/projects/${projectId}`]}>
        <Routes>
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProjectDetailPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("renders the project header with name, path, and status", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" },
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders("p1");

    await waitFor(() => expect(screen.getByText("acme")).toBeInTheDocument());
    expect(screen.getByText("/tmp/acme")).toBeInTheDocument();
    expect(screen.getByText("active")).toBeInTheDocument();
  });

  it("shows a not-found message for an unknown project", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false, status: 404,
        json: async () => ({ error: { code: "NOT_FOUND", message: "Project p1 not found", status_code: 404, details: null } }),
      }),
    );

    renderWithProviders("p1");

    await waitFor(() => expect(screen.getByText(/project not found/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.test.tsx`
Expected: FAIL — `Cannot find module './ProjectDetailPage'`.

- [ ] **Step 7: Implement the page skeleton**

Create `frontend/src/pages/ProjectDetailPage.tsx`:

```typescript
import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { getProject } from "../api/projects";
import ProjectLifecycleButtons from "../components/ProjectLifecycleButtons";

export default function ProjectDetailPage() {
  const { id } = useParams<{ id: string }>();
  const projectId = id!;

  const { data: project, isError } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => getProject(projectId),
  });

  if (isError) {
    return <p className="text-slate-400">Project not found.</p>;
  }

  if (!project) {
    return <p className="text-slate-400">Loading…</p>;
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <h2 className="text-xl font-semibold">{project.name}</h2>
          <span className="text-xs uppercase text-slate-500">{project.status}</span>
        </div>
        <span className="text-sm text-slate-500">{project.path}</span>
        <ProjectLifecycleButtons
          projectId={project.id}
          status={project.status}
          invalidateQueryKey={["project", projectId]}
        />
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.test.tsx`
Expected: PASS

- [ ] **Step 9: Wire the route into `App.tsx`**

In `frontend/src/App.tsx`, add the import:

```typescript
import ProjectDetailPage from "./pages/ProjectDetailPage";
```

Add the route, placed right after the `/projects` route (before `/runs`):

```tsx
          <Route path="/projects" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectDetailPage />} />
          <Route path="/runs" element={<RunsHomePage />} />
```

- [ ] **Step 10: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add frontend/src/api/projects.ts frontend/src/api/projects.test.ts \
        frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.test.tsx \
        frontend/src/App.tsx
git commit -m "feat(frontend): add project detail page skeleton at /projects/:id

Header (name, path, status, lifecycle buttons) + route wiring.
Sections for runs/metrics/knowledge land in follow-up tasks."
```

---

### Task 2: Runs + metrics sections

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.test.tsx`

**Interfaces:**
- Consumes: `listRuns(params?: { project_id?: string; status?: string }): Promise<Run[]>`
  (`frontend/src/api/runs.ts`); `getProjectMetrics(projectId: string): Promise<ProjectMetrics>`
  and `metricsStats(metrics: ProjectMetrics): { label: string; value: string }[]`
  (`frontend/src/api/metrics.ts`, `frontend/src/components/MetricsSummary.tsx`).

- [ ] **Step 1: Write the failing test for runs + metrics sections**

Add to `frontend/src/pages/ProjectDetailPage.test.tsx`:

```typescript
  it("renders recent runs and metrics for the project", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" },
              paging: {},
            }),
          });
        }
        if (url === "/api/runs?project_id=p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: [{ id: "r1", project_id: "p1", playbook_ref: "demo.toml", title: "demo run", status: "active", created_at: "2026-07-21T00:00:00Z" }],
              paging: {},
            }),
          });
        }
        if (url === "/api/metrics/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { approval_latency_seconds: 30, rework_rate: 0.2, retry_count: 1, crash_count: 0, auto_resolved_count: 2, escalated_count: 0 },
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders("p1");

    await waitFor(() => expect(screen.getByRole("link", { name: /demo run/i })).toHaveAttribute("href", "/runs/r1"));
    expect(screen.getByRole("link", { name: /view all runs/i })).toHaveAttribute("href", "/runs?project_id=p1");
    expect(screen.getByText("20%")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.test.tsx -t "renders recent runs"`
Expected: FAIL — no runs or metrics rendered yet.

- [ ] **Step 3: Add runs + metrics sections to the page**

In `frontend/src/pages/ProjectDetailPage.tsx`, add the imports:

```typescript
import { Link } from "react-router-dom";
import { getProjectMetrics } from "../api/metrics";
import { listRuns } from "../api/runs";
import { metricsStats } from "../components/MetricsSummary";
```

Add the two queries inside the component, after the existing `project` query:

```typescript
  const { data: runs } = useQuery({
    queryKey: ["runs", projectId],
    queryFn: () => listRuns({ project_id: projectId }),
    enabled: !!project,
  });
  const { data: metrics } = useQuery({
    queryKey: ["project-metrics", projectId],
    queryFn: () => getProjectMetrics(projectId),
    enabled: !!project,
  });
```

Add the two sections to the returned JSX, after the header `<div>` and
before the closing `</div>` of the outer container:

```tsx
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Runs</h3>
          <Link to={`/runs?project_id=${projectId}`} className="text-sm text-orange-400 hover:underline">
            View all runs →
          </Link>
        </div>
        <ul className="flex flex-col gap-2">
          {(runs ?? []).slice(0, 5).map((r) => (
            <li key={r.id} className="flex items-center justify-between rounded border border-slate-800 px-3 py-2">
              <Link to={`/runs/${r.id}`} className="font-medium text-orange-400 hover:underline">
                {r.title}
              </Link>
              <span className="text-sm text-slate-500">{r.status}</span>
            </li>
          ))}
        </ul>
      </div>

      {metrics && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Metrics</h3>
          <div className="grid grid-cols-2 gap-2 rounded border border-slate-800 p-3 sm:grid-cols-3 md:grid-cols-6">
            {metricsStats(metrics).map((s) => (
              <div key={s.label} className="flex flex-col gap-1">
                <span className="text-lg font-semibold tabular-nums">{s.value}</span>
                <span className="text-xs text-slate-500">{s.label}</span>
              </div>
            ))}
          </div>
        </div>
      )}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.test.tsx`
Expected: PASS (all tests in the file, including Task 1's).

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.test.tsx
git commit -m "feat(frontend): add runs and metrics sections to project detail page

Most recent 5 runs inline + link to the full filterable runs list;
metrics reuse metricsStats() directly, no duplicated formatting."
```

---

### Task 3: Knowledge section (KG graph + memory)

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.test.tsx`

**Interfaces:**
- Consumes: `getProjectKgGraph(projectId: string): Promise<KgGraph>`,
  `listMemory(params?: { project_id?: string }): Promise<MemoryItem[]>`
  (`frontend/src/api/knowledge.ts`); `KgGraphView` props
  `{ nodes: string[]; edges: { from: string; to: string }[]; highlight?: string[] }`
  and `MemoryBrowser` props `{ items: MemoryItem[] }` (both components
  unchanged, same as `KnowledgePage`'s usage).

- [ ] **Step 1: Write the failing test for the knowledge section**

Add to `frontend/src/pages/ProjectDetailPage.test.tsx`:

```typescript
  it("renders the KG graph and memory items for the project", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string) => {
        if (url === "/api/projects/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" },
              paging: {},
            }),
          });
        }
        if (url === "/api/projects/p1/kg-graph") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({ data: { nodes: ["a.py", "b.py"], edges: [{ from: "a.py", to: "b.py" }] }, paging: {} }),
          });
        }
        if (url === "/api/memory?project_id=p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: [{ id: "m1", scope: "project", kind: "lesson", title: "Watch the pgid", body_md: "...", project_id: "p1", pack_id: null, source_run_id: null, created_at: "2026-07-21T00:00:00Z" }],
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders("p1");

    await waitFor(() => expect(screen.getByText("a.py")).toBeInTheDocument());
    expect(screen.getByText("Watch the pgid")).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.test.tsx -t "renders the KG graph"`
Expected: FAIL — knowledge section not rendered yet.

- [ ] **Step 3: Add the knowledge section**

In `frontend/src/pages/ProjectDetailPage.tsx`, add the imports:

```typescript
import { getProjectKgGraph, listMemory } from "../api/knowledge";
import KgGraphView from "../components/KgGraphView";
import MemoryBrowser from "../components/MemoryBrowser";
```

Add the two queries alongside the existing `runs`/`metrics` queries:

```typescript
  const { data: graph } = useQuery({
    queryKey: ["kg-graph", projectId],
    queryFn: () => getProjectKgGraph(projectId),
    enabled: !!project,
  });
  const { data: memory } = useQuery({
    queryKey: ["memory", projectId],
    queryFn: () => listMemory({ project_id: projectId }),
    enabled: !!project,
  });
```

Add the section to the JSX, after the metrics section:

```tsx
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Knowledge graph</h3>
        <div className="overflow-x-auto">
          {graph && <KgGraphView nodes={graph.nodes} edges={graph.edges} />}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Memory</h3>
        <MemoryBrowser items={memory ?? []} />
      </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.test.tsx`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.test.tsx
git commit -m "feat(frontend): add knowledge graph and memory sections to project detail page

Reuses KgGraphView/MemoryBrowser and their query shapes directly
from KnowledgePage -- same components, same data, new location."
```

---

### Task 4: Repoint navigation links

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/pages/PortfolioHomePage.tsx`
- Modify: `frontend/src/pages/ProjectsPage.test.tsx`
- Modify: `frontend/src/pages/PortfolioHomePage.test.tsx`

**Interfaces:** None — this task only changes link targets (`to={...}` props),
no new data or components.

- [ ] **Step 1: Write the failing test for `ProjectsPage`'s link target**

Add to `frontend/src/pages/ProjectsPage.test.tsx`, inside the existing
`describe("ProjectsPage", ...)` block:

```typescript
  it("links each project name to its detail page", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: [{ id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-01-01T00:00:00Z" }],
        paging: {},
      }),
    });

    renderWithClient(<ProjectsPage />);

    await waitFor(() => expect(screen.getByRole("link", { name: "acme" })).toHaveAttribute("href", "/projects/p1"));
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ProjectsPage.test.tsx -t "links each project name"`
Expected: FAIL — link currently points to `/runs?project_id=p1`.

- [ ] **Step 3: Repoint the link in `ProjectsPage.tsx`**

In `frontend/src/pages/ProjectsPage.tsx`, change:

```tsx
                  <Link to={`/runs?project_id=${p.id}`} className="font-medium text-orange-400 hover:underline">
```

to:

```tsx
                  <Link to={`/projects/${p.id}`} className="font-medium text-orange-400 hover:underline">
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/ProjectsPage.test.tsx`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Write the failing test for `PortfolioHomePage`'s link target**

Add to `frontend/src/pages/PortfolioHomePage.test.tsx`, inside the existing
`describe("PortfolioHomePage", ...)` block:

```typescript
  it("links each project card to its detail page", async () => {
    const rows = [
      {
        project_id: "p1", name: "quiet", status: "active", active_run_count: 0, pending_gate_count: 0,
        last_run_status: null, last_run_at: null, rework_rate: null, budget_burn_ratio: null, attention_score: 0.0,
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: rows, paging: {} }) }),
    );

    renderWithClient(<PortfolioHomePage />);

    await waitFor(() => expect(screen.getByRole("link", { name: "quiet" })).toHaveAttribute("href", "/projects/p1"));
  });
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/PortfolioHomePage.test.tsx -t "links each project card"`
Expected: FAIL — link currently points to `/runs?project_id=p1`.

- [ ] **Step 7: Repoint the link in `PortfolioHomePage.tsx`**

In `frontend/src/pages/PortfolioHomePage.tsx`, change:

```tsx
        <Link to={`/runs?project_id=${project.project_id}`} className="font-medium text-orange-400 hover:underline">
```

to:

```tsx
        <Link to={`/projects/${project.project_id}`} className="font-medium text-orange-400 hover:underline">
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/PortfolioHomePage.test.tsx`
Expected: PASS (all tests in the file).

- [ ] **Step 9: Run the full frontend suite + typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all tests pass, no type errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/pages/ProjectsPage.tsx frontend/src/pages/PortfolioHomePage.tsx \
        frontend/src/pages/ProjectsPage.test.tsx frontend/src/pages/PortfolioHomePage.test.tsx
git commit -m "feat(frontend): repoint project links to the new detail page

ProjectsPage rows and PortfolioHomePage cards now link to
/projects/:id instead of straight to /runs?project_id=X -- matches
design doc's portfolio -> project drill-down -> further detail
intent. The old direct-to-runs link is still reachable via the new
page's own 'View all runs' link."
```

---

## Final verification

- [ ] Run: `cd frontend && npx vitest run && npx tsc --noEmit`
  Expected: all tests pass, no type errors.
- [ ] Confirm no dangling old links:
  `grep -rn "runs?project_id=" frontend/src/pages/ProjectsPage.tsx frontend/src/pages/PortfolioHomePage.tsx`
  Expected: no matches (both repointed to `/projects/`).
