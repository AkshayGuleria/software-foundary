# M2b — Dashboard: DAG View, Fleet View, Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out M2's roadmap text ("fleet + DAG view... metrics rollup + metrics view") and its exit criterion's "visualized live on the DAG" clause, which M2a's engine work (convoys, review loop, budgets, metrics computation) made possible but did not itself render anywhere. This is the dashboard half of M2, following the exact M1a/M1b (and M2a) split pattern.

**Architecture:** Extends the existing M1b dashboard (`frontend/`) — no new npm dependencies, no new pages beyond what's needed. The DAG view is a new panel added to `RunDetailPage` (design doc §11's "four synchronized panels": ribbon, DAG, artifacts/gates, feed — M1b built three of the four). It's a hand-rolled layered (topological-level) SVG layout, not a force-directed physics simulation or an npm graph library — the design doc's "force/dagre layout" phrasing describes intent, not a mandated implementation; a deterministic layered layout is simpler, has zero new dependencies, and is fully sufficient for the DAG sizes this milestone produces (single-digit-to-low-tens of units per run). Fleet view is a new top-level route/page listing active sessions across all runs — this requires two small, explicitly-scoped backend additions (Task 1) since M2a computed session data but never exposed it via `/api`: `convoy_id` on the existing `WorkUnitOut` (needed so the DAG view can group/color by convoy), and a new `GET /api/sessions` endpoint backed by a new `Store.list_active_sessions` query.

**Tech Stack:** Same as M1b — React 18, Vite 5, TypeScript 5, Tailwind CSS 3, React Router 6, TanStack Query 5, Vitest + React Testing Library. Same as M2a for the two backend additions — FastAPI, SQLAlchemy 2 async, Pydantic v2.

## Global Constraints

- **DAG layout is a deterministic layered SVG render, not a physics simulation.** Nodes are positioned by topological level (longest path from any root = column index) and stable within-level ordering (by unit id, which is a ULID and therefore already chronological) = row index. No new dependency (no dagre, no d3-force, no react-flow). This is a documented simplification of design doc §11's "force/dagre layout" phrasing, chosen because: (a) it's a strict scope reduction with no missing capability for this milestone's actual DAG sizes, (b) adding a new npm dependency's own security-advisory surface (M1b's Task 1 already flagged one unresolved critical advisory in the existing dependency tree) isn't worth it for a v1 render, (c) it keeps the bundle and the plan small. Revisit if/when M4's portfolio-scale graphs need it.
- **No changes to `src/foundry/orchestrator/`, `src/foundry/playbook/`, or `src/foundry/drivers/`.** This plan touches only `src/foundry/api/routes/`, `src/foundry/api/schemas.py` (if needed), `src/foundry/store/store.py` (one new read-only query method), and `frontend/`. M2a's engine is done; this plan only reads what it already produces.
- **Fleet view shows only what `SessionRow` already persists** — `driver`, `status`, `model`, `tokens_in`, `tokens_out`, `started_at`. Design doc §11 also mentions a "current tool call ticker" per session; that would require either a new persisted "last tool call" field on `SessionRow` or a live event-derived computation, neither of which exists yet — out of scope for this plan, and not silently implied by any of this plan's own code (no task here claims to build it).
- **Metrics view is a summary panel on `RunsHomePage`, not a new page.** M1b never built a per-project "Project view" page (design doc §11 names one; it's M4 scope per the roadmap's own "portfolio home + project view" bullet under M4). `RunsHomePage` is already project-scoped via its `?project_id=` query param, so a metrics summary section there — visible only when a `project_id` is present — is the natural, minimal-scope home for `GET /api/metrics/{project_id}`'s output until a real Project view exists.
- Every new/changed backend file lives under `src/foundry/`; every new/changed frontend file lives under `frontend/src/`.

---

### Task 1: Backend — `convoy_id` on `WorkUnitOut` + `GET /api/sessions`

**Files:**
- Modify: `src/foundry/api/routes/runs.py` (add `convoy_id` to `WorkUnitOut`/`_to_unit_out`)
- Modify: `src/foundry/store/store.py` (new `list_active_sessions` method)
- Create: `src/foundry/api/routes/sessions.py`
- Modify: `src/foundry/api/app.py` (register the new router)
- Test: `tests/api/test_sessions.py`, plus one assertion added to the existing `tests/api/test_runs.py`

**Interfaces:**
- Consumes: `Store.list_sessions_for_run` (M2a, `src/foundry/store/store.py`), `WorkUnit.convoy_id` (M0 schema column, unused by the API layer until now).
- Produces: `WorkUnitOut.convoy_id: str | None` (new field). `Store.list_active_sessions() -> list[dict]` — a single joined query (`SessionRow` join `WorkUnit`) returning dicts with `id`, `work_unit_id`, `run_id`, `step_id`, `driver`, `status`, `model`, `tokens_in`, `tokens_out`, `started_at`, restricted to `SessionRow.status in ("intent", "running")` (i.e. genuinely active, matching design doc §11's "all **active** sessions across runs"). `GET /api/sessions` (`src/foundry/api/routes/sessions.py`) — no path params, ADR-001 envelope, returns the list as-is (small enough in v1 scale that pagination isn't needed — matches `GET /api/runs/{id}/graph`'s existing `Paging.unpaginated` precedent).

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_sessions.py
import pytest


@pytest.mark.asyncio
async def test_list_active_sessions_returns_empty_when_none_running(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/sessions")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_list_active_sessions_includes_running_excludes_ended(api_client):
    client, store, _scheduler = api_client
    project = await store.create_project("demo", "/tmp/demo")
    run = await store.create_run(project.id, "x.toml", "demo run")
    unit = (
        await store.create_work_units(
            [__import__("foundry.store.models", fromlist=["WorkUnit"]).WorkUnit(run_id=run.id, step_id="a", type="session", status="running")]
        )
    )[0]
    await store.create_session_row(
        id=unit.id, work_unit_id=unit.id, driver="FakeDriver", status="running", model="fake", tokens_in=10, tokens_out=20
    )
    ended_unit = (
        await store.create_work_units(
            [__import__("foundry.store.models", fromlist=["WorkUnit"]).WorkUnit(run_id=run.id, step_id="b", type="session", status="closed")]
        )
    )[0]
    await store.create_session_row(id=ended_unit.id, work_unit_id=ended_unit.id, driver="FakeDriver", status="ended")

    resp = await client.get("/api/sessions")
    data = resp.json()["data"]
    assert len(data) == 1
    assert data[0]["run_id"] == run.id
    assert data[0]["step_id"] == "a"
    assert data[0]["tokens_in"] == 10
    assert data[0]["tokens_out"] == 20
```

Add this assertion to `tests/api/test_runs.py`'s existing run-detail test (find the test that asserts on `WorkUnitOut` fields, e.g. checks `id`/`step_id`/`status`, and add a check that the response includes `"convoy_id"` as a key, expected `None` for a non-fan-out playbook's units) — read the file first to place it correctly rather than guessing at the exact existing test name.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_sessions.py tests/api/test_runs.py -v`
Expected: FAIL — `404 Not Found` for `/api/sessions` (route doesn't exist), and a `KeyError`/missing-key assertion failure for `convoy_id`.

- [ ] **Step 3: Add `convoy_id` to `WorkUnitOut`**

In `src/foundry/api/routes/runs.py`:

```python
class WorkUnitOut(BaseModel):
    id: str
    step_id: str
    type: str
    status: str
    attempt: int
    owner_session_id: str | None
    convoy_id: str | None
```

Update `_to_unit_out`:

```python
def _to_unit_out(u: WorkUnit) -> WorkUnitOut:
    return WorkUnitOut(
        id=u.id,
        step_id=u.step_id,
        type=u.type,
        status=u.status,
        attempt=u.attempt,
        owner_session_id=u.owner_session_id,
        convoy_id=u.convoy_id,
    )
```

- [ ] **Step 4: Add `Store.list_active_sessions`**

In `src/foundry/store/store.py`, near `list_sessions_for_run` (added in M2a):

```python
    async def list_active_sessions(self) -> list[dict]:
        async def _op(session):
            res = await session.execute(
                select(SessionRow, WorkUnit.run_id, WorkUnit.step_id)
                .join(WorkUnit, WorkUnit.id == SessionRow.work_unit_id)
                .where(SessionRow.status.in_(("intent", "running")))
            )
            rows = []
            for session_row, run_id, step_id in res.all():
                rows.append(
                    {
                        "id": session_row.id,
                        "work_unit_id": session_row.work_unit_id,
                        "run_id": run_id,
                        "step_id": step_id,
                        "driver": session_row.driver,
                        "status": session_row.status,
                        "model": session_row.model,
                        "tokens_in": session_row.tokens_in,
                        "tokens_out": session_row.tokens_out,
                        "started_at": session_row.started_at.isoformat() if session_row.started_at else None,
                    }
                )
            return rows

        return await self.read(_op)
```

- [ ] **Step 5: Write `src/foundry/api/routes/sessions.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging

router = APIRouter()


class SessionOut(BaseModel):
    id: str
    work_unit_id: str
    run_id: str
    step_id: str
    driver: str
    status: str
    model: str | None
    tokens_in: int
    tokens_out: int
    started_at: str | None


@router.get("/sessions")
async def list_active_sessions(request: Request) -> ApiResponse[list[SessionOut]]:
    store = _get_store(request)
    rows = await store.list_active_sessions()
    sessions = [SessionOut(**row) for row in rows]
    return ApiResponse[list[SessionOut]](data=sessions, paging=Paging.unpaginated(len(sessions)))
```

- [ ] **Step 6: Register the router in `src/foundry/api/app.py`**

```python
from foundry.api.routes.sessions import router as sessions_router
```

```python
    app.include_router(sessions_router, prefix="/api")
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_sessions.py tests/api/test_runs.py -v`
Expected: PASS

- [ ] **Step 8: Run the full backend suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions (123 pre-existing + new)

- [ ] **Step 9: Commit**

```bash
git add src/foundry/api/routes/runs.py src/foundry/api/routes/sessions.py src/foundry/api/app.py \
        src/foundry/store/store.py tests/api/test_sessions.py tests/api/test_runs.py
git commit -m "feat(api): expose convoy_id on work units + GET /api/sessions for fleet view"
```

---

### Task 2: Frontend — types + API clients for sessions and convoy grouping

**Files:**
- Modify: `frontend/src/api/types.ts` (`WorkUnit.convoy_id`, new `Session` interface)
- Create: `frontend/src/api/sessions.ts`
- Test: `frontend/src/api/sessions.test.ts`

**Interfaces:**
- Consumes: `apiFetch` (M1b Task 1).
- Produces: `WorkUnit.convoy_id: string | null` (extends the existing interface). `Session` interface matching `SessionOut` field-for-field. `listActiveSessions(): Promise<Session[]>` (in `api/sessions.ts`).

- [ ] **Step 1: Write the failing test**

```typescript
// frontend/src/api/sessions.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listActiveSessions } from "./sessions";

describe("sessions API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("listActiveSessions GETs /api/sessions and returns the data array", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: [
          {
            id: "01JS1", work_unit_id: "01JU1", run_id: "01JR1", step_id: "implement",
            driver: "FakeDriver", status: "running", model: "fake", tokens_in: 10, tokens_out: 20,
            started_at: "2026-07-21T00:00:00Z",
          },
        ],
        paging: {},
      }),
    });

    const sessions = await listActiveSessions();

    expect(fetch).toHaveBeenCalledWith("/api/sessions", undefined);
    expect(sessions).toHaveLength(1);
    expect(sessions[0].step_id).toBe("implement");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './sessions'`

- [ ] **Step 3: Extend `frontend/src/api/types.ts`**

Add `convoy_id` to the existing `WorkUnit` interface:

```typescript
export interface WorkUnit {
  id: string;
  step_id: string;
  type: string;
  status: string;
  attempt: number;
  owner_session_id: string | null;
  convoy_id: string | null;
}
```

Add a new `Session` interface (place it near `Gate`/`Artifact`):

```typescript
export interface Session {
  id: string;
  work_unit_id: string;
  run_id: string;
  step_id: string;
  driver: string;
  status: string;
  model: string | null;
  tokens_in: number;
  tokens_out: number;
  started_at: string | null;
}
```

- [ ] **Step 4: Write `frontend/src/api/sessions.ts`**

```typescript
import { apiFetch } from "./client";
import type { Session } from "./types";

export async function listActiveSessions(): Promise<Session[]> {
  const res = await apiFetch<Session[]>("/api/sessions");
  return res.data;
}
```

- [ ] **Step 5: Run to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all tests, including M1b's)

- [ ] **Step 6: Typecheck**

Run: `cd frontend && npx tsc -b`
Expected: no errors — this step also verifies adding `convoy_id` to `WorkUnit` didn't break any existing consumer (`Ribbon.tsx` destructures individual fields it needs and doesn't exhaustively type-check against the full shape, so this is expected to be a no-op change for existing components, but confirm it via a clean typecheck rather than assuming).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/sessions.ts frontend/src/api/sessions.test.ts
git commit -m "feat(frontend): convoy_id on WorkUnit + sessions API client"
```

---

### Task 3: DAG view panel

**Files:**
- Create: `frontend/src/components/DagView.tsx`
- Test: `frontend/src/components/DagView.test.tsx`

**Interfaces:**
- Consumes: `WorkUnit` (Task 2), `RunGraph` (M1b Task 1, already has `units`/`deps`).
- Produces: `<DagView units={WorkUnit[]} deps={{unit_id, needs_unit_id}[]} />` — renders an SVG: nodes positioned by topological level (column) and a stable within-level index (row), edges as lines between node centers, nodes colored by status (reusing the same status→color mapping convention `Ribbon.tsx` already established) and outlined distinctly when they share a `convoy_id` (convoy grouping, per design doc §11). `session`-type units are excluded (same convention as `Ribbon.tsx` — they aren't pipeline/DAG nodes, they're dynamically-created process handles).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/DagView.test.tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import DagView from "./DagView";
import type { WorkUnit } from "../api/types";

const unit = (overrides: Partial<WorkUnit>): WorkUnit => ({
  id: "01J0", step_id: "step", type: "task", status: "open", attempt: 0,
  owner_session_id: null, convoy_id: null, ...overrides,
});

describe("DagView", () => {
  it("renders one node per non-session unit and one line per dep edge", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J1", step_id: "architecture", status: "closed" }),
      unit({ id: "01J2", step_id: "implement", status: "ready" }),
      unit({ id: "01J3", step_id: "sess", type: "session", status: "closed" }),
    ];
    const deps = [{ unit_id: "01J2", needs_unit_id: "01J1" }];

    render(<DagView units={units} deps={deps} />);

    const nodes = screen.getAllByTestId("dag-node");
    expect(nodes).toHaveLength(2); // session excluded
    expect(screen.getAllByTestId("dag-edge")).toHaveLength(1);
  });

  it("positions a unit strictly after everything it depends on (topological level)", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J1", step_id: "a", status: "closed" }),
      unit({ id: "01J2", step_id: "b", status: "closed" }),
      unit({ id: "01J3", step_id: "c", status: "ready" }),
    ];
    const deps = [
      { unit_id: "01J2", needs_unit_id: "01J1" },
      { unit_id: "01J3", needs_unit_id: "01J2" },
    ];

    render(<DagView units={units} deps={deps} />);

    const nodeA = screen.getByTestId("dag-node-01J1");
    const nodeB = screen.getByTestId("dag-node-01J2");
    const nodeC = screen.getByTestId("dag-node-01J3");
    const xA = Number(nodeA.getAttribute("data-x"));
    const xB = Number(nodeB.getAttribute("data-x"));
    const xC = Number(nodeC.getAttribute("data-x"));
    expect(xB).toBeGreaterThan(xA);
    expect(xC).toBeGreaterThan(xB);
  });

  it("marks units sharing a convoy_id with a distinct outline", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J1", step_id: "implement", status: "closed", convoy_id: "01JC1" }),
      unit({ id: "01J2", step_id: "review", status: "ready", convoy_id: "01JC1" }),
      unit({ id: "01J3", step_id: "solo", status: "open", convoy_id: null }),
    ];
    render(<DagView units={units} deps={[]} />);

    const convoyNode = screen.getByTestId("dag-node-01J1");
    const soloNode = screen.getByTestId("dag-node-01J3");
    expect(convoyNode.getAttribute("data-convoy")).toBe("01JC1");
    expect(soloNode.getAttribute("data-convoy")).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './DagView'`

- [ ] **Step 3: Write `frontend/src/components/DagView.tsx`**

```tsx
import type { WorkUnit } from "../api/types";

const STATUS_COLORS: Record<string, string> = {
  closed: "#4fae7c",
  blocked: "#d9a441",
  failed: "#dc4a4a",
  killed: "#8a2e2e",
  in_progress: "#e8752c",
  ready: "#c9601f",
  open: "#5b6472",
};

function colorFor(status: string): string {
  return STATUS_COLORS[status] ?? STATUS_COLORS.open;
}

const NODE_WIDTH = 140;
const NODE_HEIGHT = 36;
const COL_GAP = 60;
const ROW_GAP = 16;

function computeLevels(
  units: WorkUnit[],
  deps: { unit_id: string; needs_unit_id: string }[]
): Map<string, number> {
  const idsInGraph = new Set(units.map((u) => u.id));
  const needsMap = new Map<string, string[]>();
  for (const dep of deps) {
    if (!idsInGraph.has(dep.unit_id) || !idsInGraph.has(dep.needs_unit_id)) continue;
    const list = needsMap.get(dep.unit_id) ?? [];
    list.push(dep.needs_unit_id);
    needsMap.set(dep.unit_id, list);
  }

  const levels = new Map<string, number>();
  function levelOf(id: string, seen: Set<string>): number {
    if (levels.has(id)) return levels.get(id)!;
    if (seen.has(id)) return 0; // defensive: cyclical data shouldn't happen, don't infinite-loop
    seen.add(id);
    const needs = needsMap.get(id) ?? [];
    const level = needs.length === 0 ? 0 : Math.max(...needs.map((n) => levelOf(n, seen))) + 1;
    levels.set(id, level);
    return level;
  }

  for (const unit of units) levelOf(unit.id, new Set());
  return levels;
}

export default function DagView({
  units,
  deps,
}: {
  units: WorkUnit[];
  deps: { unit_id: string; needs_unit_id: string }[];
}) {
  const nodes = units.filter((u) => u.type !== "session");
  const levels = computeLevels(nodes, deps);

  const byLevel = new Map<number, WorkUnit[]>();
  for (const unit of nodes.slice().sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0))) {
    const level = levels.get(unit.id) ?? 0;
    const list = byLevel.get(level) ?? [];
    list.push(unit);
    byLevel.set(level, list);
  }

  const positions = new Map<string, { x: number; y: number }>();
  for (const [level, unitsAtLevel] of byLevel) {
    unitsAtLevel.forEach((unit, row) => {
      positions.set(unit.id, {
        x: level * (NODE_WIDTH + COL_GAP),
        y: row * (NODE_HEIGHT + ROW_GAP),
      });
    });
  }

  const maxLevel = Math.max(0, ...Array.from(byLevel.keys()));
  const maxRows = Math.max(1, ...Array.from(byLevel.values()).map((u) => u.length));
  const width = (maxLevel + 1) * (NODE_WIDTH + COL_GAP);
  const height = maxRows * (NODE_HEIGHT + ROW_GAP);

  const nodeIds = new Set(nodes.map((u) => u.id));
  const visibleDeps = deps.filter((d) => nodeIds.has(d.unit_id) && nodeIds.has(d.needs_unit_id));

  return (
    <svg
      role="img"
      aria-label="Run DAG"
      width={Math.max(width, 200)}
      height={Math.max(height, 100)}
      className="rounded border border-slate-800 bg-slate-950"
    >
      {visibleDeps.map((dep) => {
        const from = positions.get(dep.needs_unit_id);
        const to = positions.get(dep.unit_id);
        if (!from || !to) return null;
        return (
          <line
            key={`${dep.unit_id}-${dep.needs_unit_id}`}
            data-testid="dag-edge"
            x1={from.x + NODE_WIDTH}
            y1={from.y + NODE_HEIGHT / 2}
            x2={to.x}
            y2={to.y + NODE_HEIGHT / 2}
            stroke="#2a303b"
            strokeWidth={1.5}
          />
        );
      })}
      {nodes.map((unit) => {
        const pos = positions.get(unit.id) ?? { x: 0, y: 0 };
        return (
          <g
            key={unit.id}
            data-testid="dag-node"
            data-x={pos.x}
            data-y={pos.y}
            data-convoy={unit.convoy_id}
          >
            <rect
              data-testid={`dag-node-${unit.id}`}
              data-x={pos.x}
              data-y={pos.y}
              data-convoy={unit.convoy_id}
              x={pos.x}
              y={pos.y}
              width={NODE_WIDTH}
              height={NODE_HEIGHT}
              rx={6}
              fill="#191d24"
              stroke={colorFor(unit.status)}
              strokeWidth={unit.convoy_id ? 3 : 1.5}
              strokeDasharray={unit.convoy_id ? "4 2" : undefined}
            />
            <text x={pos.x + 8} y={pos.y + NODE_HEIGHT / 2 + 4} fontSize={11} fill="#e7eaee">
              {unit.step_id}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 5: Wire `DagView` into `RunDetailPage`**

Read the current `frontend/src/pages/RunDetailPage.tsx` in full first (it already has `getRunGraph` available in `api/runs.ts` since M1b, but the page itself has never called it — confirm this before assuming). Add a `useQuery` for the graph and render `DagView` as a new panel alongside the existing gates/artifacts and live-feed panels:

```tsx
// add to the existing imports in RunDetailPage.tsx
import DagView from "../components/DagView";
import { getRunGraph } from "../api/runs";
```

```tsx
  // add alongside the existing `detail`/`artifacts` queries
  const { data: graph } = useQuery({ queryKey: ["run-graph", runId], queryFn: () => getRunGraph(runId) });
```

Add the graph query to the same SSE-driven invalidation effect that already refetches `["run", runId]`/`["run-artifacts", runId]` on new events (read the existing `useEffect` and add `queryClient.invalidateQueries({ queryKey: ["run-graph", runId] })` alongside the other two invalidations — this is the exact bug class M1b's own final whole-branch review found and fixed for the other two queries, so the DAG panel must not repeat it).

Render the panel (add a third grid item, or a new row, below the existing two-column grid — use your judgment on layout matching the existing Tailwind conventions in the file):

```tsx
      {graph && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">DAG</h3>
          <div className="overflow-x-auto">
            <DagView units={graph.units} deps={graph.deps} />
          </div>
        </div>
      )}
```

- [ ] **Step 6: Run tests and typecheck**

Run: `cd frontend && npm test && npx tsc -b`
Expected: PASS, no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/components/DagView.tsx frontend/src/components/DagView.test.tsx \
        frontend/src/pages/RunDetailPage.tsx
git commit -m "feat(frontend): DAG view panel (layered layout, convoy grouping) on run detail"
```

---

### Task 4: Fleet view page

**Files:**
- Create: `frontend/src/pages/FleetPage.tsx`
- Modify: `frontend/src/App.tsx` (add `/fleet` route + nav link)
- Test: `frontend/src/pages/FleetPage.test.tsx`

**Interfaces:**
- Consumes: `listActiveSessions` (Task 2).
- Produces: `<FleetPage />` — polls `GET /api/sessions` (TanStack Query `refetchInterval`, since there's no session-level SSE stream — the run-level `/api/stream/{run_id}` this dashboard already uses is per-run, and fleet view is deliberately cross-run), lists each active session's run/step/driver/model/tokens, with a link to that session's run detail page and a cancel button. `App.tsx` gains `/fleet` in its `<Routes>` and a nav link.

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/FleetPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import FleetPage from "./FleetPage";

function renderWithProviders() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <FleetPage />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

describe("FleetPage", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("lists active sessions with a link to their run", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: [
          {
            id: "01JS1", work_unit_id: "01JU1", run_id: "01JR1", step_id: "implement",
            driver: "FakeDriver", status: "running", model: "fake", tokens_in: 10, tokens_out: 20,
            started_at: "2026-07-21T00:00:00Z",
          },
        ],
        paging: {},
      }),
    });

    renderWithProviders();

    await waitFor(() => expect(screen.getByText("implement")).toBeInTheDocument());
    expect(screen.getByRole("link", { name: /implement/i })).toHaveAttribute("href", "/runs/01JR1");
  });

  it("shows an empty state when no sessions are active", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });

    renderWithProviders();

    await waitFor(() => expect(screen.getByText(/no active sessions/i)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd frontend && npm test`
Expected: FAIL — `Cannot find module './FleetPage'`

- [ ] **Step 3: Write `frontend/src/pages/FleetPage.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listActiveSessions } from "../api/sessions";

export default function FleetPage() {
  const { data: sessions, isLoading } = useQuery({
    queryKey: ["active-sessions"],
    queryFn: listActiveSessions,
    refetchInterval: 3000,
  });

  return (
    <div className="flex flex-col gap-6">
      <h2 className="text-xl font-semibold">Fleet</h2>
      {isLoading ? (
        <p className="text-slate-400">Loading…</p>
      ) : sessions && sessions.length > 0 ? (
        <ul className="flex flex-col gap-2">
          {sessions.map((s) => (
            <li
              key={s.id}
              className="flex items-center justify-between rounded border border-slate-800 px-3 py-2 text-sm"
            >
              <Link to={`/runs/${s.run_id}`} className="font-medium text-orange-400 hover:underline">
                {s.step_id}
              </Link>
              <span className="text-slate-500">{s.driver}</span>
              <span className="text-slate-500">{s.model ?? "—"}</span>
              <span className="tabular-nums text-slate-500">
                {s.tokens_in.toLocaleString()} in / {s.tokens_out.toLocaleString()} out
              </span>
              <span className="text-slate-500">{s.status}</span>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-sm text-slate-500">No active sessions.</p>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run to verify it passes**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 5: Wire the `/fleet` route into `App.tsx`**

```tsx
import FleetPage from "./pages/FleetPage";
```

```tsx
          <NavLink to="/fleet" className="text-slate-400 hover:text-orange-400">
            Fleet
          </NavLink>
```

```tsx
          <Route path="/fleet" element={<FleetPage />} />
```

(Insert the `NavLink` alongside the existing `Projects`/`Runs` links, and the `Route` alongside the existing routes — read the current file first, don't blindly replace the whole block.)

- [ ] **Step 6: Run tests and typecheck**

Run: `cd frontend && npm test && npx tsc -b`
Expected: PASS, no errors

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/FleetPage.tsx frontend/src/pages/FleetPage.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): fleet view — active sessions across all runs"
```

---

### Task 5: Metrics summary panel on Runs Home

**Files:**
- Create: `frontend/src/api/metrics.ts`
- Create: `frontend/src/components/MetricsSummary.tsx`
- Modify: `frontend/src/pages/RunsHomePage.tsx`
- Test: `frontend/src/api/metrics.test.ts`, `frontend/src/components/MetricsSummary.test.tsx`

**Interfaces:**
- Consumes: `apiFetch` (M1b Task 1).
- Produces: `getProjectMetrics(projectId: string): Promise<ProjectMetrics>` (in `api/metrics.ts`; `ProjectMetrics` interface matching `compute_project_metrics`'s output field-for-field — `approval_latency_seconds`, `rework_rate`, `retry_count`, `crash_count`, `auto_resolved_count`, `escalated_count`). `<MetricsSummary projectId={string} />` — fetches and renders the six metrics as a compact stat row; rendered on `RunsHomePage` only when `?project_id=` is present in the URL.

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/api/metrics.test.ts
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getProjectMetrics } from "./metrics";

describe("metrics API", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("getProjectMetrics GETs /api/metrics/{projectId}", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: {
          approval_latency_seconds: 120, rework_rate: 0.25, retry_count: 2,
          crash_count: 1, auto_resolved_count: 3, escalated_count: 1,
        },
        paging: {},
      }),
    });

    const metrics = await getProjectMetrics("01JP1");

    expect(fetch).toHaveBeenCalledWith("/api/metrics/01JP1", undefined);
    expect(metrics.rework_rate).toBe(0.25);
  });
});
```

```tsx
// frontend/src/components/MetricsSummary.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import MetricsSummary from "./MetricsSummary";

function renderWithClient(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

describe("MetricsSummary", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("renders rework rate as a percentage", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: {
          approval_latency_seconds: 120, rework_rate: 0.25, retry_count: 2,
          crash_count: 1, auto_resolved_count: 3, escalated_count: 1,
        },
        paging: {},
      }),
    });

    renderWithClient(<MetricsSummary projectId="01JP1" />);

    await waitFor(() => expect(screen.getByText(/25%/)).toBeInTheDocument());
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd frontend && npm test`
Expected: FAIL — modules don't exist yet.

- [ ] **Step 3: Write `frontend/src/api/metrics.ts`**

```typescript
import { apiFetch } from "./client";

export interface ProjectMetrics {
  approval_latency_seconds: number;
  rework_rate: number;
  retry_count: number;
  crash_count: number;
  auto_resolved_count: number;
  escalated_count: number;
}

export async function getProjectMetrics(projectId: string): Promise<ProjectMetrics> {
  const res = await apiFetch<ProjectMetrics>(`/api/metrics/${projectId}`);
  return res.data;
}
```

- [ ] **Step 4: Write `frontend/src/components/MetricsSummary.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { getProjectMetrics } from "../api/metrics";

export default function MetricsSummary({ projectId }: { projectId: string }) {
  const { data: metrics } = useQuery({
    queryKey: ["project-metrics", projectId],
    queryFn: () => getProjectMetrics(projectId),
  });

  if (!metrics) return null;

  const stats: { label: string; value: string }[] = [
    { label: "Rework rate", value: `${Math.round(metrics.rework_rate * 100)}%` },
    { label: "Avg approval latency", value: `${Math.round(metrics.approval_latency_seconds)}s` },
    { label: "Retries", value: String(metrics.retry_count) },
    { label: "Crashes", value: String(metrics.crash_count) },
    { label: "Auto-resolved conflicts", value: String(metrics.auto_resolved_count) },
    { label: "Escalated conflicts", value: String(metrics.escalated_count) },
  ];

  return (
    <div className="grid grid-cols-2 gap-2 rounded border border-slate-800 p-3 sm:grid-cols-3 md:grid-cols-6">
      {stats.map((s) => (
        <div key={s.label} className="flex flex-col gap-1">
          <span className="text-lg font-semibold tabular-nums">{s.value}</span>
          <span className="text-xs text-slate-500">{s.label}</span>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Run to verify they pass**

Run: `cd frontend && npm test`
Expected: PASS (all tests)

- [ ] **Step 6: Wire `MetricsSummary` into `RunsHomePage`**

Read the current `frontend/src/pages/RunsHomePage.tsx` in full, then add the import and render it conditionally on `projectId`:

```tsx
import MetricsSummary from "../components/MetricsSummary";
```

```tsx
      {projectId && <MetricsSummary projectId={projectId} />}
```

(Place it near the top of the returned JSX, above or below the `<h2>`, matching the file's existing layout conventions.)

- [ ] **Step 7: Run tests and typecheck**

Run: `cd frontend && npm test && npx tsc -b`
Expected: PASS, no errors

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/metrics.ts frontend/src/api/metrics.test.ts \
        frontend/src/components/MetricsSummary.tsx frontend/src/components/MetricsSummary.test.tsx \
        frontend/src/pages/RunsHomePage.tsx
git commit -m "feat(frontend): project metrics summary panel on runs home"
```

---

### Task 6: End-to-end manual verification against the real backend

**Files:** None created — this task drives the real `foundry serve` + `npm run dev` stack through DAG view, fleet view, and metrics, the same pattern M1b's Task 8 used.

**Interfaces:** None new — this task only drives already-built code against the already-built backend.

- [ ] **Step 1: Check for available browser automation**

Run: `which chromium chromium-browser google-chrome 2>/dev/null; npx --no-install playwright --version 2>&1 | head -3`

If a real browser is available in this environment, use it (or the `run` skill) to drive the verification below through actual browser interaction. If not — matching M1b Task 8's precedent in this exact repo — substitute equivalent verification via direct HTTP calls against a real running `foundry serve` (proving the API layer's new endpoints work end-to-end) plus confirming the Vite dev server's `/api` proxy forwards the two new routes correctly. Either way, do not skip this task; adapt the method, not the goal.

- [ ] **Step 2: Start the backend and frontend**

```bash
cd /Users/akshay.guleria/work/software-foundary-master-view
uv run foundry serve --db /tmp/foundry-m2b-verify.db --port 8000 > /tmp/foundry-serve.log 2>&1 &
sleep 2
cd frontend && npm run dev > /tmp/vite-dev.log 2>&1 &
sleep 2
```

- [ ] **Step 3: Drive a fan-out run and verify all three new surfaces**

1. Create a project and start a run against `tests/orchestrator/fixtures/fanout_e2e.toml` (the M2a exit-criterion fixture — it's the one playbook in this repo that actually exercises fan-out/convoys/review-loop/escalation, making it the right fixture to verify the DAG/fleet/metrics views against real data shapes).
2. Confirm `GET /api/sessions` (directly, or via the Fleet page) shows at least one active session while the run is progressing — capture output before the run finishes, since active sessions are transient.
3. Confirm `GET /api/runs/{id}/graph` (directly, or via the DAG panel on the run's detail page) includes `convoy_id` on the fanned-out units and that the values match between slices of the same convoy.
4. Drive the run to completion (approve gates, let the review loop/escalation play out — same cycle Task 10 of the M2a plan already automated, just now observed through the API/UI instead of FakeDriver-internal assertions).
5. Confirm `GET /api/metrics/{project_id}` (directly, or via the metrics summary panel on Runs Home with `?project_id=` set) reflects nonzero `escalated_count` and `auto_resolved_count` after the run's `integrate` step produces its artifact.

- [ ] **Step 4: If ANY step reveals a real bug, fix it now**

Same rationale as every prior milestone's equivalent task in this repo: this is exactly the kind of gap only a real end-to-end pass surfaces.

- [ ] **Step 5: Stop both servers and clean up**

```bash
pkill -f "foundry serve" 2>/dev/null
pkill -f "vite" 2>/dev/null
sleep 1
lsof -i :8000 -i :5173 2>&1
rm -f /tmp/foundry-m2b-verify.db*
```

Confirm via the `lsof` output that neither port is still bound before finishing.

- [ ] **Step 6: Run the full test suites one more time**

Run: `uv run pytest -q && cd frontend && npm test`
Expected: PASS (both), no regressions from any fixes made in Step 4.

- [ ] **Step 7: Commit any fixes from Step 4**

```bash
git add -A
git commit -m "fix(frontend): address issues found in M2b end-to-end manual verification"
```

(Skip this commit entirely if Step 4 needed no fixes.)

---

## Out of scope for this plan (tracked, not forgotten)

- **Force-directed / dagre-style physics layout for the DAG view** — a deterministic layered layout is used instead (Global Constraints). Revisit at M4's portfolio scale if the layered layout's simplicity stops being sufficient.
- **Per-session "current tool call" ticker on fleet view** — `SessionRow` doesn't persist this; would need either a new column or a live event-derived computation. Not built here.
- **A real per-project "Project view" page** (KG status, memory items, project settings) — explicitly M4 scope per the roadmap; this plan's metrics panel lives on `RunsHomePage` instead.
- **Persisted/scheduled metrics rollup** — still compute-on-read (M2a's own scope decision, unchanged here).
