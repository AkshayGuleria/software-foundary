# M3b — Dashboard: Knowledge View (KG Graph + Memory Browser) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out M3's roadmap ("knowledge view in dashboard") per design doc §11: "embedded KG graph with run blast-radius overlay; memory browser with per-item provenance." M3a built the KGService and memory store but never exposed either over `/api` — this is the dashboard half of M3, following the exact M1a/b, M2a/b, M3a a/b split pattern.

**Architecture:** Three new, small, read-only `/api` endpoints (ordinary public dashboard endpoints — no relation to M3a's deliberately-not-built `/internal` HTTP surface, no new auth) computing the KG graph and a run's blast radius **on demand**, not by reusing M3a's `Orchestrator.kg_snapshot` (which, per M3a's own final review, is never actually constructed by any production entry point yet — that's a separate, deferred wiring decision this plan doesn't need to resolve). `build_kg`/`blast_radius` are cheap, pure, stdlib-only functions (Task 7's M3a benchmark measured them running against this repo's own 39-file source tree in well under a second) — computing them fresh per dashboard request is simple, correct, and completely decoupled from whether `dispatch()` ever gets a cached snapshot. The frontend gets a new generic, reusable layered-SVG graph component (same deterministic-layout approach `DagView` already established in M2b, generalized beyond `WorkUnit` so this plan doesn't need a second graph-rendering library) plus a memory browser list.

**Tech Stack:** Same as M2b/M3a — FastAPI, Pydantic v2, pytest for the backend; React 18, Vite 5, TypeScript 5, Tailwind CSS 3, React Router 6, TanStack Query 5, Vitest for the frontend. No new dependencies on either side.

## Global Constraints

- **No reuse of `Orchestrator.kg_snapshot` or any `/internal` surface.** This plan's three new endpoints call `build_kg(project.path)` fresh on each request via `src/foundry/kg/service.py` (M3a, already merged) — they do not touch `Scheduler`, `Orchestrator`, or the still-deferred question of wiring a cached KG snapshot into dispatch. That's real future work (tracked in M3a's own follow-up notes), not something this dashboard-only plan should improvise a design for.
- **The KG graph view is a generalized version of M2b's `DagView` layered-SVG layout**, not a new graph library and not a duplicate implementation. `DagView` is `WorkUnit`-specific (nodes keyed by unit id, edges from `UnitDep`); this plan extracts the layout algorithm into a new, generic component (`KgGraphView`) taking plain `{id: string}[]` nodes and `{from: string, to: string}[]` edges, so it works for both an import graph (this plan) and, unmodified, anything else that's shaped like a DAG. `DagView` itself is left as-is — this plan does not touch it, avoiding any risk of regressing the M2b run-detail page's own DAG panel.
- **Memory browser is read-only.** Nothing in this plan lets a user create, edit, or delete a memory item from the dashboard — `Store.create_memory_item` is only ever called by the engine's compound-step contract (M3a). This matches design doc §10's framing of memory as engine-authored content a human can browse and gets prompt input from, not a CMS.
- **No changes to `src/foundry/orchestrator/`, `src/foundry/playbook/`, or `src/foundry/drivers/`.** This plan touches only `src/foundry/api/`, `src/foundry/kg/` (read-only consumption, no changes to the module itself), and `frontend/`.
- Every new/changed backend file lives under `src/foundry/api/`; every new/changed frontend file lives under `frontend/src/`.

---

### Task 1: Backend — `GET /api/memory`

**Files:**
- Create: `src/foundry/api/routes/memory.py`
- Modify: `src/foundry/api/app.py` (register the router)
- Test: `tests/api/test_memory_route.py`

**Interfaces:**
- Consumes: `Store.list_memory_items` (M3a, already merged).
- Produces: `GET /api/memory?project_id=&scope=&kind=` (all query params optional, same AND-combination semantics `Store.list_memory_items` already implements) — `MemoryOut` (`id`, `scope`, `kind`, `title`, `body_md`, `project_id`, `pack_id`, `source_run_id`, `created_at`), ADR-001 envelope, unpaginated (matches `GET /api/runs/{id}/graph`'s existing `Paging.unpaginated` precedent — memory lists are small at this scale).

- [ ] **Step 1: Write the failing tests**

Read `src/foundry/api/routes/projects.py` first (for the `_get_store` helper you'll reuse) and `tests/api/conftest.py` (for the `api_client` fixture's 3-tuple shape — `(client, store, scheduler)`).

```python
# tests/api/test_memory_route.py
import pytest


@pytest.mark.asyncio
async def test_list_memory_returns_empty_with_no_items(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/memory")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_list_memory_filters_by_project_id(api_client):
    client, store, _scheduler = api_client
    await store.create_memory_item(scope="project", kind="lesson", title="A", body_md="x", project_id="p1")
    await store.create_memory_item(scope="project", kind="lesson", title="B", body_md="x", project_id="p2")

    resp = await client.get("/api/memory?project_id=p1")
    data = resp.json()["data"]
    assert [item["title"] for item in data] == ["A"]


@pytest.mark.asyncio
async def test_list_memory_filters_by_scope_and_kind(api_client):
    client, store, _scheduler = api_client
    await store.create_memory_item(scope="project", kind="lesson", title="L", body_md="x", project_id="p1")
    await store.create_memory_item(scope="project", kind="pattern", title="P", body_md="x", project_id="p1")

    resp = await client.get("/api/memory?project_id=p1&kind=pattern")
    data = resp.json()["data"]
    assert [item["title"] for item in data] == ["P"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_memory_route.py -v`
Expected: FAIL — 404, route doesn't exist yet.

- [ ] **Step 3: Write `src/foundry/api/routes/memory.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.store.models import Memory

router = APIRouter()


class MemoryOut(BaseModel):
    id: str
    scope: str
    kind: str
    title: str
    body_md: str
    project_id: str | None
    pack_id: str | None
    source_run_id: str | None
    created_at: str


def _to_memory_out(m: Memory) -> MemoryOut:
    return MemoryOut(
        id=m.id,
        scope=m.scope,
        kind=m.kind,
        title=m.title,
        body_md=m.body_md,
        project_id=m.project_id,
        pack_id=m.pack_id,
        source_run_id=m.source_run_id,
        created_at=m.created_at.isoformat(),
    )


@router.get("/memory")
async def list_memory(
    request: Request,
    project_id: str | None = None,
    scope: str | None = None,
    kind: str | None = None,
) -> ApiResponse[list[MemoryOut]]:
    store = _get_store(request)
    items = await store.list_memory_items(scope=scope, project_id=project_id, kind=kind)
    memory_out = [_to_memory_out(m) for m in items]
    return ApiResponse[list[MemoryOut]](data=memory_out, paging=Paging.unpaginated(len(memory_out)))
```

- [ ] **Step 4: Register the router in `src/foundry/api/app.py`**

Read the file first to confirm the current registration pattern (there are now 6 routers: projects, runs, gates, stream, metrics, sessions). Add:

```python
from foundry.api.routes.memory import router as memory_router
```

```python
    app.include_router(memory_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_memory_route.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions (153 pre-existing + 3 new)

- [ ] **Step 7: Commit**

```bash
git add src/foundry/api/routes/memory.py src/foundry/api/app.py tests/api/test_memory_route.py
git commit -m "feat(api): GET /api/memory — read-only listing of compound-step memory items"
```

---

### Task 2: Backend — `GET /api/projects/{id}/kg-graph`

**Files:**
- Create: `src/foundry/api/routes/knowledge.py`
- Modify: `src/foundry/api/app.py`
- Test: `tests/api/test_knowledge_route.py`

**Interfaces:**
- Consumes: `build_kg` (M3a, `src/foundry/kg/service.py`).
- Produces: `GET /api/projects/{project_id}/kg-graph` — `KgGraphOut` (`nodes: list[str]`, `edges: list[{from: str, to: str}]`), built fresh via `build_kg(project.path)` on every request. 404s if the project doesn't exist. Does **not** cache — this is deliberately simple for v1 dashboard scale (design doc §9's own "incremental update" caching is real future work, not this plan's job).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_knowledge_route.py
import pytest


@pytest.mark.asyncio
async def test_kg_graph_404s_for_unknown_project(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/projects/01JUNKNOWN/kg-graph")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_kg_graph_builds_from_project_path(api_client, tmp_path):
    client, store, _scheduler = api_client
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text("X = 1\n")
    project = await store.create_project("demo", str(tmp_path))

    resp = await client.get(f"/api/projects/{project.id}/kg-graph")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data["nodes"]) == {"a.py", "b.py"}
    assert {"from": "a.py", "to": "b.py"} in data["edges"]


@pytest.mark.asyncio
async def test_kg_graph_empty_for_project_with_no_python_files(api_client, tmp_path):
    client, store, _scheduler = api_client
    project = await store.create_project("demo", str(tmp_path))

    resp = await client.get(f"/api/projects/{project.id}/kg-graph")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"nodes": [], "edges": []}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_knowledge_route.py -v`
Expected: FAIL — 404 (route doesn't exist), or module-not-found for `knowledge.py`.

- [ ] **Step 3: Write `src/foundry/api/routes/knowledge.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import NotFoundError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.kg.service import build_kg

router = APIRouter()


class KgGraphOut(BaseModel):
    nodes: list[str]
    edges: list[dict]


@router.get("/projects/{project_id}/kg-graph")
async def get_project_kg_graph(project_id: str, request: Request) -> ApiResponse[KgGraphOut]:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    snapshot = build_kg(project.path)
    edges = [{"from": src, "to": target} for src, targets in snapshot.imports.items() for target in targets]
    graph = KgGraphOut(nodes=sorted(snapshot.nodes), edges=edges)
    return ApiResponse[KgGraphOut](data=graph, paging=Paging.unpaginated(len(graph.nodes)))
```

Edges are plain `dict` (`{"from": ..., "to": ...}`), not a nested Pydantic model — `from` is a Python reserved word and can't be a plain Pydantic field name without aliasing complexity that isn't worth it for two string fields.

- [ ] **Step 4: Register the router in `src/foundry/api/app.py`**

```python
from foundry.api.routes.knowledge import router as knowledge_router
```

```python
    app.include_router(knowledge_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_knowledge_route.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 7: Commit**

```bash
git add src/foundry/api/routes/knowledge.py src/foundry/api/app.py tests/api/test_knowledge_route.py
git commit -m "feat(api): GET /api/projects/{id}/kg-graph — on-demand import-graph build for the dashboard"
```

---

### Task 3: Backend — `GET /api/runs/{id}/blast-radius`

**Files:**
- Modify: `src/foundry/api/routes/knowledge.py`
- Test: `tests/api/test_knowledge_route.py` (extend)

**Interfaces:**
- Consumes: `build_kg`, `blast_radius` (M3a).
- Produces: `GET /api/runs/{run_id}/blast-radius` — gathers the run's artifacts' `payload_json.get("files", [])` (the same convention `_compose_context_bundle`, M3a Task 5, already established — no new convention invented here), builds a fresh KG from the run's project's path, computes `blast_radius`, returns `BlastRadiusOut` (`changed_files: list[str]`, `radius: list[str]`) for the frontend's KG graph view to highlight as an overlay. 404s if the run doesn't exist.

- [ ] **Step 1: Add the failing tests**

```python
# append to tests/api/test_knowledge_route.py
import pytest


@pytest.mark.asyncio
async def test_blast_radius_404s_for_unknown_run(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/runs/01JUNKNOWN/blast-radius")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_blast_radius_computed_from_run_artifacts(api_client, tmp_path):
    client, store, _scheduler = api_client
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text("X = 1\n")
    (tmp_path / "c.py").write_text("Y = 1\n")
    project = await store.create_project("demo", str(tmp_path))
    run = await store.create_run(project.id, "x.toml", "demo run")
    unit = (
        await store.create_work_units(
            [__import__("foundry.store.models", fromlist=["WorkUnit"]).WorkUnit(run_id=run.id, step_id="a", type="task", status="closed")]
        )
    )[0]
    await store.create_artifact(
        run_id=run.id, work_unit_id=unit.id, kind="code_diff_artifact", version=1,
        produced_by_role="dev", payload_json={"files": ["a.py"]},
    )

    resp = await client.get(f"/api/runs/{run.id}/blast-radius")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["changed_files"] == ["a.py"]
    assert "b.py" in data["radius"]
    assert "c.py" not in data["radius"]
```

Follow the same import style already established in `tests/api/test_sessions.py` (M2b) for the inline `WorkUnit` import if this repo's convention there has since settled on a top-level `from foundry.store.models import WorkUnit` instead — read that file first and match whichever style it actually uses, since the plan's own inline `__import__` form has been flagged as non-idiomatic in a prior milestone's review.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_knowledge_route.py -v`
Expected: FAIL — 404, route doesn't exist yet.

- [ ] **Step 3: Add the route to `src/foundry/api/routes/knowledge.py`**

```python
class BlastRadiusOut(BaseModel):
    changed_files: list[str]
    radius: list[str]


@router.get("/runs/{run_id}/blast-radius")
async def get_run_blast_radius(run_id: str, request: Request) -> ApiResponse[BlastRadiusOut]:
    from foundry.kg.service import blast_radius

    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    project = await store.get_project(run.project_id)
    artifacts = await store.list_artifacts(run_id)
    changed_files: list[str] = []
    for a in artifacts:
        changed_files.extend(a.payload_json.get("files", []))
    changed_files = sorted(set(changed_files))

    radius: list[str] = []
    if changed_files and project is not None:
        snapshot = build_kg(project.path)
        radius = sorted(blast_radius(snapshot, changed_files))

    out = BlastRadiusOut(changed_files=changed_files, radius=radius)
    return ApiResponse[BlastRadiusOut](data=out, paging=Paging.none())
```

Move the `from foundry.kg.service import blast_radius` import to the top of the file alongside the existing `build_kg` import, rather than inline inside the function — the inline form above is only written that way in this plan to keep the diff-sized snippet self-contained; the actual committed file should have one clean import block at the top like every other route file in this codebase.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_knowledge_route.py -v`
Expected: PASS (5 tests total: 3 from Task 2 + 2 new)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/routes/knowledge.py tests/api/test_knowledge_route.py
git commit -m "feat(api): GET /api/runs/{id}/blast-radius — on-demand blast-radius overlay for the knowledge view"
```

---

### Task 4: Frontend — types + API clients

**Files:**
- Modify: `frontend/src/api/types.ts`
- Create: `frontend/src/api/knowledge.ts`
- Test: `frontend/src/api/knowledge.test.ts`

**Interfaces:**
- Consumes: `apiFetch` (M1b).
- Produces: `MemoryItem`, `KgGraph` (`{nodes: string[]; edges: {from: string; to: string}[]}`), `BlastRadius` (`{changed_files: string[]; radius: string[]}`) interfaces in `types.ts`, matching Tasks 1-3's backend shapes field-for-field. `listMemory(params?: {project_id?, scope?, kind?}): Promise<MemoryItem[]>`, `getProjectKgGraph(projectId: string): Promise<KgGraph>`, `getRunBlastRadius(runId: string): Promise<BlastRadius>` in `api/knowledge.ts`.

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/api/knowledge.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getProjectKgGraph, getRunBlastRadius, listMemory } from "./knowledge";

describe("knowledge API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listMemory GETs /api/memory with query params", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: [
          {
            id: "01JM1", scope: "project", kind: "lesson", title: "L", body_md: "x",
            project_id: "01JP1", pack_id: null, source_run_id: "01JR1", created_at: "2026-07-22T00:00:00Z",
          },
        ],
        paging: {},
      }),
    });

    const items = await listMemory({ project_id: "01JP1" });

    expect(fetch).toHaveBeenCalledWith("/api/memory?project_id=01JP1", undefined);
    expect(items).toHaveLength(1);
    expect(items[0].title).toBe("L");
  });

  it("listMemory with no params hits the bare endpoint", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    await listMemory();
    expect(fetch).toHaveBeenCalledWith("/api/memory", undefined);
  });

  it("getProjectKgGraph GETs /api/projects/{id}/kg-graph", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { nodes: ["a.py", "b.py"], edges: [{ from: "a.py", to: "b.py" }] }, paging: {} }),
    });

    const graph = await getProjectKgGraph("01JP1");

    expect(fetch).toHaveBeenCalledWith("/api/projects/01JP1/kg-graph", undefined);
    expect(graph.nodes).toEqual(["a.py", "b.py"]);
  });

  it("getRunBlastRadius GETs /api/runs/{id}/blast-radius", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: { changed_files: ["a.py"], radius: ["a.py", "b.py"] }, paging: {} }),
    });

    const result = await getRunBlastRadius("01JR1");

    expect(fetch).toHaveBeenCalledWith("/api/runs/01JR1/blast-radius", undefined);
    expect(result.radius).toContain("b.py");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './knowledge'`

- [ ] **Step 3: Extend `frontend/src/api/types.ts`**

```typescript
export interface MemoryItem {
  id: string;
  scope: string;
  kind: string;
  title: string;
  body_md: string;
  project_id: string | null;
  pack_id: string | null;
  source_run_id: string | null;
  created_at: string;
}

export interface KgGraph {
  nodes: string[];
  edges: { from: string; to: string }[];
}

export interface BlastRadius {
  changed_files: string[];
  radius: string[];
}
```

- [ ] **Step 4: Write `frontend/src/api/knowledge.ts`**

```typescript
import { apiFetch } from "./client";
import type { BlastRadius, KgGraph, MemoryItem } from "./types";

export async function listMemory(params?: {
  project_id?: string;
  scope?: string;
  kind?: string;
}): Promise<MemoryItem[]> {
  const query = new URLSearchParams();
  if (params?.project_id) query.set("project_id", params.project_id);
  if (params?.scope) query.set("scope", params.scope);
  if (params?.kind) query.set("kind", params.kind);
  const qs = query.toString();
  const res = await apiFetch<MemoryItem[]>(`/api/memory${qs ? `?${qs}` : ""}`);
  return res.data;
}

export async function getProjectKgGraph(projectId: string): Promise<KgGraph> {
  const res = await apiFetch<KgGraph>(`/api/projects/${projectId}/kg-graph`);
  return res.data;
}

export async function getRunBlastRadius(runId: string): Promise<BlastRadius> {
  const res = await apiFetch<BlastRadius>(`/api/runs/${runId}/blast-radius`);
  return res.data;
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all tests, including M1b/M2b's)

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/knowledge.ts frontend/src/api/knowledge.test.ts
git commit -m "feat(frontend): memory/kg-graph/blast-radius API client"
```

---

### Task 5: Frontend — `KgGraphView` (generalized layered graph) + `MemoryBrowser`

**Files:**
- Create: `frontend/src/components/KgGraphView.tsx`
- Create: `frontend/src/components/MemoryBrowser.tsx`
- Test: `frontend/src/components/KgGraphView.test.tsx`, `frontend/src/components/MemoryBrowser.test.tsx`

**Interfaces:**
- Consumes: `KgGraph`, `BlastRadius`, `MemoryItem` (Task 4).
- Produces: `<KgGraphView nodes={string[]} edges={{from,to}[]} highlight={Set<string> | string[]} />` — a generalized version of M2b's `DagView` layered-SVG layout algorithm (same topological-level-by-longest-path, stable-sort-within-level approach), taking plain string node ids instead of `WorkUnit` objects, with nodes in `highlight` rendered with a distinct fill/stroke (the blast-radius overlay). `<MemoryBrowser items={MemoryItem[]} />` — a simple list, grouped by `kind`, each item showing title, a truncated `body_md` preview, `scope`, and `source_run_id` (linked to `/runs/{id}` when present) as its provenance.

- [ ] **Step 1: Write the failing tests**

```tsx
// frontend/src/components/KgGraphView.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import KgGraphView from "./KgGraphView";

describe("KgGraphView", () => {
  it("renders one node per file and one edge per import", () => {
    render(<KgGraphView nodes={["a.py", "b.py", "c.py"]} edges={[{ from: "a.py", to: "b.py" }]} />);

    expect(screen.getAllByTestId("kg-node")).toHaveLength(3);
    expect(screen.getAllByTestId("kg-edge")).toHaveLength(1);
  });

  it("positions an importer strictly after what it imports", () => {
    render(
      <KgGraphView
        nodes={["a.py", "b.py", "c.py"]}
        edges={[
          { from: "a.py", to: "b.py" },
          { from: "b.py", to: "c.py" },
        ]}
      />
    );

    const nodeA = screen.getByTestId("kg-node-a.py");
    const nodeB = screen.getByTestId("kg-node-b.py");
    const nodeC = screen.getByTestId("kg-node-c.py");
    expect(Number(nodeB.getAttribute("data-x"))).toBeGreaterThan(Number(nodeA.getAttribute("data-x")));
    expect(Number(nodeC.getAttribute("data-x"))).toBeGreaterThan(Number(nodeB.getAttribute("data-x")));
  });

  it("marks nodes in the highlight set distinctly", () => {
    render(<KgGraphView nodes={["a.py", "b.py"]} edges={[]} highlight={["a.py"]} />);

    expect(screen.getByTestId("kg-node-a.py").getAttribute("data-highlighted")).toBe("true");
    expect(screen.getByTestId("kg-node-b.py").getAttribute("data-highlighted")).toBe("false");
  });

  it("handles an empty graph without crashing", () => {
    render(<KgGraphView nodes={[]} edges={[]} />);
    expect(screen.queryAllByTestId("kg-node")).toHaveLength(0);
  });
});
```

```tsx
// frontend/src/components/MemoryBrowser.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import MemoryBrowser from "./MemoryBrowser";
import type { MemoryItem } from "../api/types";

const item = (overrides: Partial<MemoryItem>): MemoryItem => ({
  id: "01JM1", scope: "project", kind: "lesson", title: "A lesson", body_md: "body text",
  project_id: "01JP1", pack_id: null, source_run_id: null, created_at: "2026-07-22T00:00:00Z", ...overrides,
});

describe("MemoryBrowser", () => {
  it("renders each item's title and kind", () => {
    render(<MemoryBrowser items={[item({ title: "Lesson one" }), item({ id: "01JM2", kind: "pattern", title: "Pattern one" })]} />);

    expect(screen.getByText("Lesson one")).toBeInTheDocument();
    expect(screen.getByText("Pattern one")).toBeInTheDocument();
  });

  it("links to the source run when one exists", () => {
    render(<MemoryBrowser items={[item({ source_run_id: "01JR1" })]} />);
    expect(screen.getByRole("link", { name: /01JR1/i })).toHaveAttribute("href", "/runs/01JR1");
  });

  it("shows an empty state when there are no items", () => {
    render(<MemoryBrowser items={[]} />);
    expect(screen.getByText(/no memory items/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL — modules don't exist yet.

- [ ] **Step 3: Write `frontend/src/components/KgGraphView.tsx`**

```tsx
const NODE_WIDTH = 140;
const NODE_HEIGHT = 32;
const COL_GAP = 60;
const ROW_GAP = 14;

function computeLevels(nodes: string[], edges: { from: string; to: string }[]): Map<string, number> {
  const nodeSet = new Set(nodes);
  const dependsOn: Map<string, string[]> = new Map();
  for (const edge of edges) {
    if (!nodeSet.has(edge.from) || !nodeSet.has(edge.to)) continue;
    const list = dependsOn.get(edge.from) ?? [];
    list.push(edge.to);
    dependsOn.set(edge.from, list);
  }

  const levels = new Map<string, number>();
  function levelOf(id: string, seen: Set<string>): number {
    if (levels.has(id)) return levels.get(id)!;
    if (seen.has(id)) return 0;
    seen.add(id);
    const deps = dependsOn.get(id) ?? [];
    const level = deps.length === 0 ? 0 : Math.max(...deps.map((d) => levelOf(d, seen))) + 1;
    levels.set(id, level);
    return level;
  }

  for (const node of nodes) levelOf(node, new Set());
  return levels;
}

export default function KgGraphView({
  nodes,
  edges,
  highlight,
}: {
  nodes: string[];
  edges: { from: string; to: string }[];
  highlight?: string[] | Set<string>;
}) {
  const highlightSet = highlight instanceof Set ? highlight : new Set(highlight ?? []);
  const levels = computeLevels(nodes, edges);

  const byLevel = new Map<number, string[]>();
  for (const node of nodes.slice().sort()) {
    const level = levels.get(node) ?? 0;
    const list = byLevel.get(level) ?? [];
    list.push(node);
    byLevel.set(level, list);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [level, nodesAtLevel] of byLevel) {
    nodesAtLevel.forEach((node, row) => {
      positions.set(node, { x: level * (NODE_WIDTH + COL_GAP), y: row * (NODE_HEIGHT + ROW_GAP) });
    });
  }

  const maxLevel = Math.max(0, ...Array.from(byLevel.keys()));
  const maxRows = Math.max(1, ...Array.from(byLevel.values()).map((n) => n.length));
  const width = (maxLevel + 1) * (NODE_WIDTH + COL_GAP);
  const height = maxRows * (NODE_HEIGHT + ROW_GAP);

  const nodeSet = new Set(nodes);
  const visibleEdges = edges.filter((e) => nodeSet.has(e.from) && nodeSet.has(e.to));

  return (
    <svg
      role="img"
      aria-label="Knowledge graph"
      width={Math.max(width, 200)}
      height={Math.max(height, 100)}
      className="rounded border border-slate-800 bg-slate-950"
    >
      {visibleEdges.map((edge) => {
        const from = positions.get(edge.from);
        const to = positions.get(edge.to);
        if (!from || !to) return null;
        return (
          <line
            key={`${edge.from}-${edge.to}`}
            data-testid="kg-edge"
            x1={from.x + NODE_WIDTH}
            y1={from.y + NODE_HEIGHT / 2}
            x2={to.x}
            y2={to.y + NODE_HEIGHT / 2}
            stroke="#2a303b"
            strokeWidth={1.5}
          />
        );
      })}
      {nodes.map((node) => {
        const pos = positions.get(node) ?? { x: 0, y: 0 };
        const isHighlighted = highlightSet.has(node);
        return (
          <g key={node} data-testid="kg-node">
            <rect
              data-testid={`kg-node-${node}`}
              data-x={pos.x}
              data-y={pos.y}
              data-highlighted={isHighlighted ? "true" : "false"}
              x={pos.x}
              y={pos.y}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={6}
              fill={isHighlighted ? "#3a2320" : "#191d24"}
              stroke={isHighlighted ? "#e8752c" : "#2a303b"}
              strokeWidth={isHighlighted ? 2.5 : 1}
            />
            <text x={pos.x + 8} y={pos.y + NODE_HEIGHT / 2 + 4} fontSize={10} fill="#e7eaee">
              {node}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
```

- [ ] **Step 4: Write `frontend/src/components/MemoryBrowser.tsx`**

```tsx
import { Link } from "react-router-dom";
import type { MemoryItem } from "../api/types";

export default function MemoryBrowser({ items }: { items: MemoryItem[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-slate-500">No memory items yet.</p>;
  }

  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => (
        <li key={item.id} className="rounded border border-slate-800 p-3 text-sm">
          <div className="flex items-center justify-between">
            <span className="font-medium">{item.title}</span>
            <span className="rounded-full bg-slate-800 px-2 py-0.5 text-xs uppercase text-slate-400">
              {item.kind}
            </span>
          </div>
          <p className="mt-1 text-slate-400">{item.body_md}</p>
          <div className="mt-2 text-xs text-slate-500">
            {item.scope}
            {item.source_run_id && (
              <>
                {" · from "}
                <Link to={`/runs/${item.source_run_id}`} className="text-orange-400 hover:underline">
                  {item.source_run_id}
                </Link>
              </>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/KgGraphView.tsx frontend/src/components/KgGraphView.test.tsx \
        frontend/src/components/MemoryBrowser.tsx frontend/src/components/MemoryBrowser.test.tsx
git commit -m "feat(frontend): KgGraphView (generalized layered graph) + MemoryBrowser components"
```

---

### Task 6: Frontend — Knowledge view page + routing

**Files:**
- Create: `frontend/src/pages/KnowledgePage.tsx`
- Modify: `frontend/src/App.tsx`
- Test: `frontend/src/pages/KnowledgePage.test.tsx`

**Interfaces:**
- Consumes: `getProjectKgGraph`, `getRunBlastRadius`, `listMemory` (Task 4), `KgGraphView`, `MemoryBrowser` (Task 5), `listProjects` (M1b).
- Produces: `<KnowledgePage />` — project-scoped like `RunsHomePage` (reads `?project_id=` via `useSearchParams`, with a project picker when absent), shows the project's KG graph, an optional run-id input to compute/overlay that run's blast radius on the graph, and the project's memory browser below it. `/knowledge` route + nav link in `App.tsx`.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/KnowledgePage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import KnowledgePage from "./KnowledgePage";

function renderWithProviders(initialEntries: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={initialEntries}>
        <KnowledgePage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("KnowledgePage", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("renders the project's KG graph and memory browser", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url.includes("/kg-graph")) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { nodes: ["a.py", "b.py"], edges: [{ from: "a.py", to: "b.py" }] }, paging: {} }),
        });
      }
      if (url.startsWith("/api/memory")) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [
              {
                id: "01JM1", scope: "project", kind: "lesson", title: "A real lesson", body_md: "x",
                project_id: "01JP1", pack_id: null, source_run_id: null, created_at: "2026-07-22T00:00:00Z",
              },
            ],
            paging: {},
          }),
        });
      }
      if (url.startsWith("/api/projects")) {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: [{ id: "01JP1", name: "demo", path: "/tmp/demo", kg_status: "none", created_at: "2026-07-22T00:00:00Z" }], paging: {} }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });

    renderWithProviders(["/knowledge?project_id=01JP1"]);

    await waitFor(() => expect(screen.getAllByTestId("kg-node")).toHaveLength(2));
    await waitFor(() => expect(screen.getByText("A real lesson")).toBeInTheDocument());
  });

  it("prompts for a project when none is selected", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: [{ id: "01JP1", name: "demo", path: "/tmp/demo", kg_status: "none", created_at: "2026-07-22T00:00:00Z" }], paging: {} }),
    });

    renderWithProviders(["/knowledge"]);

    await waitFor(() => expect(screen.getByText(/select a project/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './KnowledgePage'`

- [ ] **Step 3: Write `frontend/src/pages/KnowledgePage.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { listProjects } from "../api/projects";
import { getProjectKgGraph, getRunBlastRadius, listMemory } from "../api/knowledge";
import KgGraphView from "../components/KgGraphView";
import MemoryBrowser from "../components/MemoryBrowser";

export default function KnowledgePage() {
  const [searchParams] = useSearchParams();
  const projectId = searchParams.get("project_id") ?? undefined;
  const [runIdInput, setRunIdInput] = useState("");
  const [blastRadiusRunId, setBlastRadiusRunId] = useState<string | undefined>(undefined);

  const { data: projects } = useQuery({ queryKey: ["projects"], queryFn: listProjects });
  const { data: graph } = useQuery({
    queryKey: ["kg-graph", projectId],
    queryFn: () => getProjectKgGraph(projectId!),
    enabled: !!projectId,
  });
  const { data: memory } = useQuery({
    queryKey: ["memory", projectId],
    queryFn: () => listMemory({ project_id: projectId }),
    enabled: !!projectId,
  });
  const { data: blastRadius } = useQuery({
    queryKey: ["blast-radius", blastRadiusRunId],
    queryFn: () => getRunBlastRadius(blastRadiusRunId!),
    enabled: !!blastRadiusRunId,
  });

  if (!projectId) {
    return (
      <div className="flex flex-col gap-4">
        <h2 className="text-xl font-semibold">Knowledge</h2>
        <p className="text-sm text-slate-400">Select a project to view its knowledge graph and memory.</p>
        <ul className="flex flex-col gap-2">
          {projects?.map((p) => (
            <li key={p.id}>
              <Link to={`/knowledge?project_id=${p.id}`} className="text-orange-400 hover:underline">
                {p.name}
              </Link>
            </li>
          ))}
        </ul>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Knowledge</h2>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Import graph</h3>
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            setBlastRadiusRunId(runIdInput || undefined);
          }}
        >
          <input
            className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
            placeholder="Run ID to overlay blast radius"
            value={runIdInput}
            onChange={(e) => setRunIdInput(e.target.value)}
          />
          <button type="submit" className="rounded bg-orange-600 px-3 py-1 text-sm hover:bg-orange-500">
            Highlight
          </button>
        </form>
        <div className="overflow-x-auto">
          {graph && <KgGraphView nodes={graph.nodes} edges={graph.edges} highlight={blastRadius?.radius} />}
        </div>
      </div>

      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Memory</h3>
        <MemoryBrowser items={memory ?? []} />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Wire the `/knowledge` route into `App.tsx`**

Read the current file first, then add alongside the existing routes/nav links:

```tsx
import KnowledgePage from "./pages/KnowledgePage";
```

```tsx
          <NavLink to="/knowledge" className="text-slate-400 hover:text-orange-400">
            Knowledge
          </NavLink>
```

```tsx
          <Route path="/knowledge" element={<KnowledgePage />} />
```

- [ ] **Step 5: Run tests and typecheck**

Run: `cd frontend && npm test && npx tsc -b`
Expected: PASS, no errors

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/KnowledgePage.tsx frontend/src/pages/KnowledgePage.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): knowledge view page — KG graph with blast-radius overlay + memory browser"
```

---

### Task 7: End-to-end manual verification against the real backend

**Files:** None created — same pattern as every prior milestone's final dashboard task (M1b Task 8, M2b Task 6).

**Interfaces:** None new.

- [ ] **Step 1: Check for available browser automation**

Run: `which chromium chromium-browser google-chrome 2>/dev/null; npx --no-install playwright --version 2>&1 | head -3` (from `frontend/`). If unavailable (the established pattern in this environment across every prior milestone), substitute direct HTTP verification against a real running `foundry serve` + confirm the Vite `/api` proxy forwards the three new routes correctly — same substitution this repo's own precedent already establishes, don't skip the task, adapt the method.

- [ ] **Step 2: Start the backend and frontend**

```bash
cd /Users/akshay.guleria/work/software-foundary-master-view
uv run foundry serve --db /tmp/foundry-m3b-verify.db --port 8000 > /tmp/foundry-serve.log 2>&1 &
sleep 2
cd frontend && npm run dev > /tmp/vite-dev.log 2>&1 &
sleep 2
```

- [ ] **Step 3: Verify all three new surfaces against real data**

1. Create a project pointed at this repo's own `src/foundry` directory (a real, non-trivial Python tree — exactly what Task 7 of the M3a plan benchmarked against) via `POST /api/projects`.
2. Confirm `GET /api/projects/{id}/kg-graph` (directly, or via the Knowledge page) returns a non-trivial graph (dozens of nodes, real edges) — cross-check the node/edge counts roughly match M3a's own benchmark numbers (39 files in `src/foundry` as of M3a; if this plan runs after other work has changed that count, that's expected drift, not a bug).
3. Start a run against `tests/orchestrator/fixtures/fanout_e2e.toml` (M2a's exit-criterion fixture, still the richest available fixture with real per-slice `files` artifact fields) registered against that same project, drive it to completion (same cycle every prior milestone's e2e task has driven).
4. Confirm `GET /api/runs/{id}/blast-radius` (directly, or via the Knowledge page's run-id overlay input) returns a non-empty `radius` reflecting the run's actual changed files.
5. Confirm `GET /api/memory?project_id=` (directly, or via the Memory browser) shows items if the run's playbook produced any (the `fanout_e2e.toml` fixture doesn't have a compound step — if this step shows zero memory items, that's expected given the fixture, not a bug; note it in the report rather than treating it as a failure).

- [ ] **Step 4: If ANY step reveals a real bug, fix it now**

Same rationale as every prior milestone's equivalent task.

- [ ] **Step 5: Stop both servers and clean up**

```bash
pkill -f "foundry serve" 2>/dev/null
pkill -f "vite" 2>/dev/null
sleep 1
lsof -i :8000 -i :5173 2>&1
rm -f /tmp/foundry-m3b-verify.db*
```

Confirm via `lsof` that neither port is still bound.

- [ ] **Step 6: Run the full test suites one more time**

Run: `uv run pytest -q && cd frontend && npm test`
Expected: PASS (both), no regressions from any Step 4 fixes.

- [ ] **Step 7: Commit any fixes from Step 4**

```bash
git add -A
git commit -m "fix(frontend): address issues found in M3b end-to-end manual verification"
```

Skip entirely if Step 4 needed no fixes.

---

## Out of scope for this plan (tracked, not forgotten)

- **Wiring `kg_snapshot` into `Orchestrator`/`Scheduler`/CLI for real dispatch-time context composition.** Still deferred from M3a's own final review — this plan's endpoints compute fresh, standalone KG snapshots per request, deliberately decoupled from that unresolved design question.
- **KG graph caching / incremental updates on worktree merge** (design doc §9). This plan computes fresh every request; fine at this scale, a real cost at portfolio scale (M4+).
- **Editing or curating memory from the dashboard.** Read-only browser only — matches design doc §10's framing of memory as engine-authored, human-reviewed content, not a CMS.
- **A dedicated `/knowledge/:runId` deep-link or a richer blast-radius diff view** (e.g., showing exactly which files a rejection's rework changed vs. the original). The run-id text-input overlay is intentionally minimal for v1.
