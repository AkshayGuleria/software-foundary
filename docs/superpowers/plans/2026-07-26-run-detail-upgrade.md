# Run Detail Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Upgrade the Run Detail screen to match design doc §11's vision: a two-pill agent/human status ribbon, an interactive dagre-laid-out DAG with click-through to a unit drawer (events/artifact/gate/session-log), and a working reject-with-chips flow on gates.

**Architecture:** Two small backend additions (thread `unit_id` through the SSE event stream; a new per-run session-history endpoint) unblock two of the drawer's four tabs from client-side-only data. Everything else is frontend-only: `Ribbon` and `DagView` each gain an optional click-handler prop; a new `UnitDrawer` component consumes already-fetched run data (units/gates/artifacts/events/sessions) filtered by the clicked unit's id; `GateCard` gains a fixed chip selector above its existing free-text rejection field.

**Tech Stack:** FastAPI + SQLAlchemy 2 async (backend, unchanged stack). React/Vite/TS + Tailwind + `@tanstack/react-query` (frontend, unchanged stack) plus one new dependency: `dagre` (+ `@types/dagre` for TypeScript, since this repo's `tsconfig.json` runs `strict: true`).

## Global Constraints

- No backend schema changes — the new session endpoint is a read-only query over the existing `SessionRow` table.
- `dagre` is the only new dependency this plan introduces.
- Existing tests for `DagView`, `Ribbon`, `GateCard`, `useEventStream`, and the backend's `test_stream.py` assert on the *current* shapes (single-pill ribbon, raw-payload SSE data, no click handlers) and must be rewritten, not just extended, per task.
- The existing "Gates & artifacts" flat panel on `RunDetailPage` stays exactly as-is — the unit drawer is a *supplementary* drill-in view opened from the ribbon/DAG, not a replacement for the main page's gate-approval flow.

---

### Task 1: Thread `unit_id` through the SSE event stream

**Files:**
- Modify: `src/foundry/api/routes/stream.py`
- Modify: `frontend/src/hooks/useEventStream.ts`
- Test: `tests/api/test_stream.py`
- Test: `frontend/src/hooks/useEventStream.test.ts`

**Interfaces:**
- Consumes: nothing new.
- Produces: SSE `data` payloads now shaped `{"unit_id": string | null, "payload": <event payload>}` instead of the raw payload. `FeedEvent` (frontend) gains a `unit_id: string | null` field. Task 5 (unit drawer) filters events by this field.

This task exists because the design spec assumed `unit_id` was already reaching the frontend (since `Event.unit_id` exists on the backend model) — it verifiably does not: `src/foundry/api/routes/stream.py`'s SSE generator currently sends only `json.dumps(ev.payload_json)` as `data`, discarding `ev.unit_id` entirely. Without this fix, the drawer's Events tab has no way to filter.

- [ ] **Step 1: Write the failing backend test**

Add to `tests/api/test_stream.py`:

```python
@pytest.mark.asyncio
async def test_stream_includes_unit_id_in_the_event_envelope(sse_api_client):
    client, store, _scheduler = sse_api_client

    project = await store.create_project("proj3", "/tmp/proj3")
    run = await store.create_run(project.id, "pb.toml", "unit-id envelope test")
    await store.append_event(run.id, "01JUNIT1", "unit.closed", {"note": "done"})

    lines: list[str] = []
    async with client.stream("GET", f"/api/stream/{run.id}", headers={"Last-Event-ID": "0"}) as response:
        async for line in response.aiter_lines():
            lines.append(line)
            if line == "" and any("unit.closed" in item for item in lines):
                break

    text = "\n".join(lines)
    assert '"unit_id": "01JUNIT1"' in text
    assert '"payload": {"note": "done"}' in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_stream.py -k unit_id_in_the_event_envelope -v`
Expected: FAIL — the current `data` is just `{"note": "done"}`, no `unit_id`/`payload` envelope keys.

- [ ] **Step 3: Update the SSE generator**

In `src/foundry/api/routes/stream.py`, change the `yield` line inside `event_generator`:

```python
            for ev in events:
                seq = ev.seq
                envelope = {"unit_id": ev.unit_id, "payload": ev.payload_json}
                yield {"id": str(ev.seq), "event": ev.type, "data": json.dumps(envelope)}
```

(This replaces the existing `yield {"id": str(ev.seq), "event": ev.type, "data": json.dumps(ev.payload_json)}` line — everything else in the file is unchanged.)

- [ ] **Step 4: Run the backend test to verify it passes**

Run: `uv run pytest tests/api/test_stream.py -v`
Expected: all PASS (including the two pre-existing tests — re-check their substring assertions still hold under the new envelope shape; they should, since `json.dumps` still renders `"note": "first"` verbatim inside the nested `"payload"` object, but run them to confirm rather than assume).

- [ ] **Step 5: Write the failing frontend test**

Replace the existing first `it(...)` block in `frontend/src/hooks/useEventStream.test.ts` (the "opens an EventSource... and appends received events" test) with:

```ts
  it("opens an EventSource to /api/stream/{runId} and appends received events with their unit_id", () => {
    const { result } = renderHook(() => useEventStream("01JR1"));
    expect(FakeEventSource.instances).toHaveLength(1);
    expect(FakeEventSource.instances[0].url).toBe("/api/stream/01JR1");

    act(() => {
      FakeEventSource.instances[0].emit(
        "unit.closed",
        JSON.stringify({ unit_id: "01JU1", payload: { note: "done" } }),
        "5"
      );
    });

    expect(result.current).toEqual([
      { seq: 5, type: "unit.closed", unit_id: "01JU1", payload: { note: "done" } },
    ]);
  });
```

(The second test, "closes the EventSource on unmount", is unaffected and stays as-is.)

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/hooks/useEventStream.test.ts`
Expected: FAIL — `result.current` currently has no `unit_id` key and `payload` is the whole raw object, not the nested `.payload`.

- [ ] **Step 7: Update `useEventStream`**

Replace `frontend/src/hooks/useEventStream.ts`'s `FeedEvent` interface and handler:

```ts
export interface FeedEvent {
  seq: number;
  type: string;
  unit_id: string | null;
  payload: unknown;
}
```

```ts
    const handler = (type: string) => (ev: MessageEvent) => {
      const envelope = JSON.parse(ev.data) as { unit_id: string | null; payload: unknown };
      setEvents((prev) => [
        ...prev,
        { seq: Number(ev.lastEventId), type, unit_id: envelope.unit_id, payload: envelope.payload },
      ]);
    };
```

(Everything else in the file — the `KNOWN_EVENT_TYPES` list, the `useEffect` setup/teardown — is unchanged.)

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/hooks/useEventStream.test.ts`
Expected: PASS (2 tests).

- [ ] **Step 9: Run both full suites**

Run: `uv run pytest -q` and `cd frontend && npx vitest run`
Expected: all PASS (269 backend before this task; 93 frontend before this task — confirm actual counts in output).

- [ ] **Step 10: Commit**

```bash
git add src/foundry/api/routes/stream.py tests/api/test_stream.py frontend/src/hooks/useEventStream.ts frontend/src/hooks/useEventStream.test.ts
git commit -m "feat(api): thread unit_id through the SSE event stream

The design doc's unit-drawer plan assumed unit_id already reached the
frontend since Event.unit_id exists on the backend model -- it didn't;
the SSE generator only ever sent the raw payload_json. Wrap SSE data as
{unit_id, payload} so the frontend can filter a run's live event feed
down to a single unit's events, which the upcoming drawer needs."
```

---

### Task 2: Per-run session history endpoint

**Files:**
- Modify: `src/foundry/api/routes/sessions.py`
- Modify: `src/foundry/api/routes/runs.py`
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/runs.ts`
- Test: `tests/api/test_runs.py`
- Test: `frontend/src/api/runs.test.ts`

**Interfaces:**
- Consumes: `Store.list_sessions_for_run(run_id: str) -> list[SessionRow]` (already exists, already used by `src/foundry/api/routes/metrics.py` — no `Store` changes needed in this task), `Store.list_units(run_id: str) -> list[WorkUnit]` (already exists, already used elsewhere in `runs.py`).
- Produces: `GET /api/runs/{run_id}/sessions` returning `ApiResponse[list[SessionOut]]`, frontend `getRunSessions(runId: string): Promise<Session[]>`. `Session`/`SessionOut` both gain `ended_at`. Task 5 (unit drawer) consumes `getRunSessions`.

This task turned out simpler than the design spec assumed: `Store.list_sessions_for_run(run_id)` already exists (`src/foundry/store/store.py`, already consumed by `metrics.py`) and returns every `SessionRow` for a run regardless of status — no new `Store` method needed. It returns raw `SessionRow` objects, though, which don't carry `run_id`/`step_id` (those live on `WorkUnit`, joined in at the route level, the same way `list_active_sessions` already does it for the fleet-wide endpoint).

- [ ] **Step 1: Write the failing backend test**

Add to `tests/api/test_runs.py`:

Add `from foundry.store.models import WorkUnit, utcnow` to the top of the file, alongside the existing `from foundry.orchestrator.worktrees import _git_env` import (not inline inside a test function — this repo's pre-commit `ruff check` enforces import placement).

```python
@pytest.mark.asyncio
async def test_get_run_sessions_returns_all_sessions_for_the_run(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("proj", "/tmp/proj")
    run = await store.create_run(project.id, "pb.toml", "session route test")
    session_unit = (
        await store.create_work_units(
            [WorkUnit(run_id=run.id, step_id="implement", type="session", status="running")]
        )
    )[0]
    # SessionRow's own primary key is always set equal to its owning
    # session-type WorkUnit's id -- see Orchestrator.dispatch()'s real
    # create_session_row(id=session_unit.id, work_unit_id=session_unit.id, ...)
    # call in src/foundry/orchestrator/tick.py; this test fixture matches
    # that real convention rather than inventing its own.
    await store.create_session_row(
        id=session_unit.id, work_unit_id=session_unit.id, driver="fake", status="running", model="m1",
        tokens_in=10, tokens_out=20,
    )

    resp = await client.get(f"/api/runs/{run.id}/sessions")

    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body) == 1
    assert body[0]["id"] == session_unit.id
    assert body[0]["work_unit_id"] == session_unit.id
    assert body[0]["step_id"] == "implement"
    assert body[0]["run_id"] == run.id


@pytest.mark.asyncio
async def test_get_run_sessions_includes_closed_sessions_with_ended_at(api_client):
    client, store, _scheduler = api_client

    project = await store.create_project("proj2", "/tmp/proj2")
    run = await store.create_run(project.id, "pb.toml", "closed session test")
    session_unit = (
        await store.create_work_units(
            [WorkUnit(run_id=run.id, step_id="implement", type="session", status="closed")]
        )
    )[0]

    await store.create_session_row(
        id=session_unit.id, work_unit_id=session_unit.id, driver="fake", status="closed",
        started_at=utcnow(), ended_at=utcnow(),
    )

    resp = await client.get(f"/api/runs/{run.id}/sessions")

    body = resp.json()["data"]
    assert len(body) == 1
    assert body[0]["ended_at"] is not None


@pytest.mark.asyncio
async def test_get_run_sessions_404s_for_an_unknown_run(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/runs/nonexistent/sessions")

    assert resp.status_code == 404
```

(`tests/api/test_runs.py` already imports `pytest` at the top — only the `from foundry.store.models import WorkUnit, utcnow` line above is new.)

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_runs.py -k get_run_sessions -v`
Expected: FAIL — 404 for all three (no such route yet) for the first two, and the third coincidentally also 404s but for the right reason once the route exists — re-run after Step 4 to confirm it's failing/passing for the correct reason, not by accident.

- [ ] **Step 3: Add `ended_at` to `SessionOut`**

In `src/foundry/api/routes/sessions.py`, add one field to the existing `SessionOut` model:

```python
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
    ended_at: str | None = None
```

(The `= None` default means `list_active_sessions`'s existing dicts, which never included an `ended_at` key, still construct `SessionOut(**row)` successfully without modification — this is purely additive, no other change needed in this file.)

- [ ] **Step 4: Add the route**

In `src/foundry/api/routes/runs.py`, add the import alongside the file's other imports:

```python
from foundry.api.routes.sessions import SessionOut
```

And add the new route at the end of the file, after `get_run_artifacts`:

```python
@router.get("/runs/{run_id}/sessions")
async def get_run_sessions(run_id: str, request: Request) -> ApiResponse[list[SessionOut]]:
    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    units_by_id = {u.id: u for u in await store.list_units(run_id)}
    session_rows = await store.list_sessions_for_run(run_id)
    sessions = [
        SessionOut(
            id=s.id,
            work_unit_id=s.work_unit_id,
            run_id=run_id,
            step_id=units_by_id[s.work_unit_id].step_id,
            driver=s.driver,
            status=s.status,
            model=s.model,
            tokens_in=s.tokens_in,
            tokens_out=s.tokens_out,
            started_at=s.started_at.isoformat() if s.started_at else None,
            ended_at=s.ended_at.isoformat() if s.ended_at else None,
        )
        for s in session_rows
    ]
    return ApiResponse[list[SessionOut]](data=sessions, paging=Paging.unpaginated(len(sessions)))
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_runs.py -k get_run_sessions -v`
Expected: PASS (3 tests).

- [ ] **Step 6: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS.

- [ ] **Step 7: Add `ended_at` to the frontend `Session` type and add `getRunSessions`**

In `frontend/src/api/types.ts`, add one field to the existing `Session` interface:

```ts
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
  ended_at: string | null;
}
```

- [ ] **Step 8: Write the failing frontend test**

Add to `frontend/src/api/runs.test.ts`:

```ts
  it("getRunSessions GETs /api/runs/{id}/sessions", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({ data: [{ id: "s1", work_unit_id: "u1", run_id: "r1", step_id: "implement", driver: "fake", status: "closed", model: "m1", tokens_in: 10, tokens_out: 20, started_at: "2026-07-21T00:00:00Z", ended_at: "2026-07-21T00:05:00Z" }], paging: {} }),
    });

    const sessions = await getRunSessions("r1");

    expect(fetch).toHaveBeenCalledWith("/api/runs/r1/sessions", undefined);
    expect(sessions).toHaveLength(1);
    expect(sessions[0].ended_at).toBe("2026-07-21T00:05:00Z");
  });
```

(Add `getRunSessions` to this test file's existing import line from `./runs`.)

- [ ] **Step 9: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/runs.test.ts`
Expected: FAIL — `getRunSessions is not a function`.

- [ ] **Step 10: Add `getRunSessions`**

Add to `frontend/src/api/runs.ts`:

```ts
export async function getRunSessions(runId: string): Promise<Session[]> {
  const res = await apiFetch<Session[]>(`/api/runs/${runId}/sessions`);
  return res.data;
}
```

(Add `Session` to this file's existing `import type { Artifact, Run, RunDetail, RunGraph } from "./types";` line.)

- [ ] **Step 11: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/runs.test.ts`
Expected: PASS.

- [ ] **Step 12: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 13: Commit**

```bash
git add src/foundry/api/routes/sessions.py src/foundry/api/routes/runs.py tests/api/test_runs.py frontend/src/api/types.ts frontend/src/api/runs.ts frontend/src/api/runs.test.ts
git commit -m "feat(api): add per-run session history endpoint

GET /api/runs/{run_id}/sessions returns every session for a run
regardless of status (unlike GET /api/sessions, which is fleet-wide and
active-only), reusing the already-existing Store.list_sessions_for_run
-- needed for the upcoming unit drawer's session-log tab to show real
history instead of nothing once a session has closed."
```

---

### Task 3: Two-pill ribbon (agent-done / human-approved)

**Files:**
- Modify: `frontend/src/components/Ribbon.tsx`
- Modify: `frontend/src/components/Ribbon.test.tsx`
- Modify: `frontend/src/pages/RunDetailPage.tsx`
- Modify: `frontend/src/pages/RunDetailPage.test.tsx`

**Interfaces:**
- Consumes: `Gate`, `WorkUnit` types (existing).
- Produces: `Ribbon({ units, gates, onSelectUnit? }: { units: WorkUnit[]; gates: Gate[]; onSelectUnit?: (unit: WorkUnit) => void })`. Task 5 (unit drawer) passes `onSelectUnit` from `RunDetailPage`; until then it's simply omitted (optional prop, safe to leave unused).

- [ ] **Step 1: Write the failing test**

Replace `frontend/src/components/Ribbon.test.tsx` entirely with:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import Ribbon from "./Ribbon";
import type { Gate, WorkUnit } from "../api/types";

const unit = (overrides: Partial<WorkUnit>): WorkUnit => ({
  id: "01J0", step_id: "step", type: "task", status: "open", attempt: 0, owner_session_id: null, convoy_id: null, ...overrides,
});
const gate = (overrides: Partial<Gate>): Gate => ({
  id: "01JG0", work_unit_id: "01J0", gate_type: "human", decision: "pending", ...overrides,
});

describe("Ribbon", () => {
  it("renders one agent pill per non-session unit, in id order", () => {
    const units: WorkUnit[] = [
      unit({ id: "01J3", step_id: "review", status: "open" }),
      unit({ id: "01J1", step_id: "plan", status: "closed" }),
      unit({ id: "01J2Z", step_id: "session-for-plan", type: "session", status: "closed" }),
      unit({ id: "01J2", step_id: "implement", status: "blocked" }),
    ];

    render(<Ribbon units={units} gates={[]} />);

    const pills = screen.getAllByTestId("ribbon-pill-agent");
    expect(pills).toHaveLength(3); // session unit excluded
    expect(pills.map((p) => p.textContent)).toEqual([
      expect.stringContaining("plan"),
      expect.stringContaining("implement"),
      expect.stringContaining("review"),
    ]);
  });

  it("colors a closed step's agent pill differently from a blocked one", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "a", status: "closed" }), unit({ id: "01J2", step_id: "b", status: "blocked" })];
    render(<Ribbon units={units} gates={[]} />);
    const pills = screen.getAllByTestId("ribbon-pill-agent");
    expect(pills[0].className).not.toEqual(pills[1].className);
  });

  it("renders a human pill only for a step that has a gate", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "gated", status: "blocked" }), unit({ id: "01J2", step_id: "ungated", status: "open" })];
    const gates: Gate[] = [gate({ id: "01JG1", work_unit_id: "01J1", decision: "pending" })];

    render(<Ribbon units={units} gates={gates} />);

    expect(screen.getAllByTestId("ribbon-pill-human")).toHaveLength(1);
  });

  it("colors an approved human pill differently from a rejected one", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "a", status: "closed" }), unit({ id: "01J2", step_id: "b", status: "closed" })];
    const gates: Gate[] = [
      gate({ id: "01JG1", work_unit_id: "01J1", decision: "approved" }),
      gate({ id: "01JG2", work_unit_id: "01J2", decision: "rejected" }),
    ];

    render(<Ribbon units={units} gates={gates} />);

    const humanPills = screen.getAllByTestId("ribbon-pill-human");
    expect(humanPills[0].className).not.toEqual(humanPills[1].className);
  });

  it("marks a derived gate's human pill distinctly from a human-type gate's", () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "a", status: "closed" }), unit({ id: "01J2", step_id: "b", status: "closed" })];
    const gates: Gate[] = [
      gate({ id: "01JG1", work_unit_id: "01J1", gate_type: "human", decision: "pending" }),
      gate({ id: "01JG2", work_unit_id: "01J2", gate_type: "derived", decision: "pending" }),
    ];

    render(<Ribbon units={units} gates={gates} />);

    const humanPills = screen.getAllByTestId("ribbon-pill-human");
    expect(humanPills[0].getAttribute("data-gate-type")).toBe("human");
    expect(humanPills[1].getAttribute("data-gate-type")).toBe("derived");
  });

  it("calls onSelectUnit with the clicked step's unit", async () => {
    const { default: userEvent } = await import("@testing-library/user-event");
    const onSelectUnit = vi.fn();
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "implement", status: "closed" })];

    render(<Ribbon units={units} gates={[]} onSelectUnit={onSelectUnit} />);
    const user = userEvent.setup();
    await user.click(screen.getByTestId("ribbon-step-01J1"));

    expect(onSelectUnit).toHaveBeenCalledWith(units[0]);
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/Ribbon.test.tsx`
Expected: FAIL — `Ribbon` doesn't accept a `gates` prop yet, `ribbon-pill-agent`/`ribbon-pill-human`/`ribbon-step-01J1` test ids don't exist.

- [ ] **Step 3: Rewrite `Ribbon.tsx`**

Replace `frontend/src/components/Ribbon.tsx` entirely with:

```tsx
import type { Gate, WorkUnit } from "../api/types";

const STATUS_STYLES: Record<string, string> = {
  closed: "bg-emerald-900 text-emerald-300",
  blocked: "bg-amber-900 text-amber-300",
  failed: "bg-red-900 text-red-300",
  killed: "bg-red-950 text-red-400",
  in_progress: "bg-orange-900 text-orange-300",
  ready: "bg-orange-950 text-orange-400",
  open: "bg-slate-800 text-slate-400",
};

const GATE_STYLES: Record<string, string> = {
  pending: "bg-slate-800 text-slate-400",
  approved: "bg-emerald-900 text-emerald-300",
  rejected: "bg-red-900 text-red-300",
};

function styleFor(status: string): string {
  return STATUS_STYLES[status] ?? STATUS_STYLES.open;
}

function gateStyleFor(decision: string): string {
  return GATE_STYLES[decision] ?? GATE_STYLES.pending;
}

export default function Ribbon({
  units,
  gates,
  onSelectUnit,
}: {
  units: WorkUnit[];
  gates: Gate[];
  onSelectUnit?: (unit: WorkUnit) => void;
}) {
  const steps = units
    .filter((u) => u.type !== "session")
    .slice()
    .sort((a, b) => (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
  const gateByUnit = new Map(gates.map((g) => [g.work_unit_id, g]));

  return (
    <div className="flex flex-wrap gap-2">
      {steps.map((u) => {
        const gate = gateByUnit.get(u.id);
        return (
          <div
            key={u.id}
            data-testid={`ribbon-step-${u.id}`}
            role={onSelectUnit ? "button" : undefined}
            onClick={() => onSelectUnit?.(u)}
            className={`flex overflow-hidden rounded-full border border-slate-700 text-sm font-medium ${onSelectUnit ? "cursor-pointer" : ""}`}
          >
            <span data-testid="ribbon-pill-agent" className={`px-3 py-1 ${styleFor(u.status)}`}>
              A · {u.step_id}
            </span>
            {gate && (
              <span
                data-testid="ribbon-pill-human"
                data-gate-type={gate.gate_type}
                className={`border-l border-slate-700 px-3 py-1 ${gateStyleFor(gate.decision)} ${gate.gate_type === "derived" ? "italic" : ""}`}
              >
                H
              </span>
            )}
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/Ribbon.test.tsx`
Expected: PASS (6 tests).

- [ ] **Step 5: Update `RunDetailPage` to pass `gates`**

In `frontend/src/pages/RunDetailPage.tsx`, change the `<Ribbon units={detail.units} />` line to:

```tsx
      <Ribbon units={detail.units} gates={detail.gates} />
```

(`onSelectUnit` is intentionally not passed yet — Task 5 adds it once the drawer exists.)

- [ ] **Step 6: Update `RunDetailPage.test.tsx`'s mock data**

The existing tests already supply `units`/`gates` in their `/api/runs/01JR1` mock response — no new mock is needed. Run the file to confirm nothing broke from the `Ribbon` prop change:

Run: `cd frontend && npx vitest run src/pages/RunDetailPage.test.tsx`
Expected: PASS (3 tests, unchanged) — the existing "renders the ribbon..." test asserts `screen.getByText(/plan_approval/)`, which still matches since the agent pill's text is `A · plan_approval`, containing the substring.

- [ ] **Step 7: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/components/Ribbon.tsx frontend/src/components/Ribbon.test.tsx frontend/src/pages/RunDetailPage.tsx
git commit -m "feat(frontend): two-pill agent/human ribbon

Replaces the single step_id-plus-status pill with two adjacent pills
per step: an agent pill colored by unit status, and (when the step has
a gate) a human pill colored by the gate's decision, with derived
gates marked distinctly from human-type ones. Ribbon also gains an
optional onSelectUnit click handler, unused until the unit drawer
lands."
```

---

### Task 4: Interactive DAG via dagre

**Files:**
- Modify: `frontend/src/components/DagView.tsx`
- Modify: `frontend/src/components/DagView.test.tsx`
- Modify: `frontend/package.json` (new dependency)
- Modify: `frontend/src/pages/RunDetailPage.tsx`

**Interfaces:**
- Consumes: `dagre` npm package.
- Produces: `DagView({ units, deps, onNodeClick? }: { units: WorkUnit[]; deps: {...}[]; onNodeClick?: (unit: WorkUnit) => void })`. Task 5 passes `onNodeClick`; until then it's omitted.

- [ ] **Step 1: Install dagre**

```bash
cd frontend && npm install dagre && npm install --save-dev @types/dagre
```

- [ ] **Step 2: Write the failing test**

Replace `frontend/src/components/DagView.test.tsx` entirely with:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
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

  it("positions a unit strictly after everything it depends on (topological rank)", () => {
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

  it("calls onNodeClick with the clicked unit", async () => {
    const onNodeClick = vi.fn();
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "implement", status: "closed" })];
    render(<DagView units={units} deps={[]} onNodeClick={onNodeClick} />);
    const user = userEvent.setup();

    await user.click(screen.getByTestId("dag-node-01J1"));

    expect(onNodeClick).toHaveBeenCalledWith(units[0]);
  });

  it("does not throw when onNodeClick is not provided", async () => {
    const units: WorkUnit[] = [unit({ id: "01J1", step_id: "implement", status: "closed" })];
    render(<DagView units={units} deps={[]} />);
    const user = userEvent.setup();

    await user.click(screen.getByTestId("dag-node-01J1"));
    // no assertion needed beyond "didn't throw" -- the click must be a safe no-op
  });
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/DagView.test.tsx`
Expected: FAIL — `onNodeClick` prop doesn't exist yet, click has no effect.

- [ ] **Step 4: Rewrite `DagView.tsx` to use dagre for layout**

Replace `frontend/src/components/DagView.tsx` entirely with:

```tsx
import dagre from "dagre";
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

function layout(
  units: WorkUnit[],
  deps: { unit_id: string; needs_unit_id: string }[]
): { positions: Map<string, { x: number; y: number }>; width: number; height: number } {
  const idsInGraph = new Set(units.map((u) => u.id));
  const visibleDeps = deps.filter((d) => idsInGraph.has(d.unit_id) && idsInGraph.has(d.needs_unit_id));

  const g = new dagre.graphlib.Graph();
  g.setGraph({ rankdir: "LR", nodesep: ROW_GAP, ranksep: COL_GAP });
  g.setDefaultEdgeLabel(() => ({}));

  for (const unit of units) {
    g.setNode(unit.id, { width: NODE_WIDTH, height: NODE_HEIGHT });
  }
  for (const dep of visibleDeps) {
    g.setEdge(dep.needs_unit_id, dep.unit_id);
  }

  dagre.layout(g);

  const positions = new Map<string, { x: number; y: number }>();
  let maxX = 0;
  let maxY = 0;
  for (const unit of units) {
    const node = g.node(unit.id);
    // dagre positions are node CENTERS; convert to top-left for rect x/y.
    const x = node.x - NODE_WIDTH / 2;
    const y = node.y - NODE_HEIGHT / 2;
    positions.set(unit.id, { x, y });
    maxX = Math.max(maxX, x + NODE_WIDTH);
    maxY = Math.max(maxY, y + NODE_HEIGHT);
  }

  return { positions, width: maxX, height: maxY };
}

export default function DagView({
  units,
  deps,
  onNodeClick,
}: {
  units: WorkUnit[];
  deps: { unit_id: string; needs_unit_id: string }[];
  onNodeClick?: (unit: WorkUnit) => void;
}) {
  const nodes = units.filter((u) => u.type !== "session");
  const nodeIds = new Set(nodes.map((u) => u.id));
  const visibleDeps = deps.filter((d) => nodeIds.has(d.unit_id) && nodeIds.has(d.needs_unit_id));

  const { positions, width, height } = layout(nodes, visibleDeps);

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
          <g key={unit.id} data-testid="dag-node" data-convoy={unit.convoy_id}>
            <rect
              data-testid={`dag-node-${unit.id}`}
              onClick={() => onNodeClick?.(unit)}
              style={{ cursor: onNodeClick ? "pointer" : "default" }}
              aria-label={`${unit.step_id} node`}
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

Test-id structure is deliberate: the outer `<g>` keeps the generic `data-testid="dag-node"` (matching the pre-dagre component, so the "one node per unit" count assertion via `getAllByTestId("dag-node")` keeps working unchanged), while the inner `<rect>` — which also carries the `onClick` handler, since it's the actual visible/clickable shape — gets the per-unit `data-testid={\`dag-node-${unit.id}\`}` used for both position assertions and the click test. Only the layout math (`layout()`, replacing the old `computeLevels`/manual grid) actually changed; the rendered DOM shape matches the original component exactly.

- [ ] **Step 5: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/DagView.test.tsx`
Expected: PASS (5 tests).

- [ ] **Step 6: Type-check the build**

Run: `cd frontend && npx tsc -b`
Expected: no errors. If dagre's types aren't found (`TS7016` or similar), confirm `@types/dagre` installed in Step 1 actually took effect (`cat frontend/node_modules/@types/dagre/package.json` should exist) — don't skip this check, `vitest` alone doesn't run full `tsc` type-checking and could pass while the real `npm run build` fails.

- [ ] **Step 7: Update `RunDetailPage`**

No prop changes needed yet (`onNodeClick` is optional and Task 5 wires it) — this step is just re-confirming the page still renders correctly with the new `DagView` internals:

Run: `cd frontend && npx vitest run src/pages/RunDetailPage.test.tsx`
Expected: PASS (3 tests, unchanged).

- [ ] **Step 8: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/components/DagView.tsx frontend/src/components/DagView.test.tsx
git commit -m "feat(frontend): lay out the run DAG with dagre, add click-through

Replaces the hand-rolled layered layout with dagre's hierarchical
layout engine (same visual conventions -- status colors, convoy dashed
outline -- just real layout math instead of a fixed grid). Nodes gain
an optional onNodeClick handler, unused until the unit drawer lands."
```

---

### Task 5: Unit drawer

**Files:**
- Create: `frontend/src/components/UnitDrawer.tsx`
- Test: `frontend/src/components/UnitDrawer.test.tsx`
- Modify: `frontend/src/pages/RunDetailPage.tsx`
- Modify: `frontend/src/pages/RunDetailPage.test.tsx`

**Interfaces:**
- Consumes: `getRunSessions` (Task 2), `FeedEvent.unit_id` (Task 1), `Ribbon`'s `onSelectUnit` (Task 3), `DagView`'s `onNodeClick` (Task 4), existing `ArtifactCard`/`GateCard` components.
- Produces: `UnitDrawer({ unit, events, artifacts, gates, sessions, onClose }: {...})`. Nothing else consumes this — it's the terminal integration point.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/UnitDrawer.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import UnitDrawer from "./UnitDrawer";
import type { Artifact, FeedEventLike, Gate, Session, WorkUnit } from "../api/types";

// SessionRow.work_unit_id always points to a SESSION-type WorkUnit, never
// the TASK-type unit clicked in the Ribbon/DAG (see Orchestrator.dispatch()
// in src/foundry/orchestrator/tick.py: a fresh session-type unit is created
// per dispatch attempt, and the task unit's own owner_session_id is updated
// to point at it). So a task unit's sessions can only be found via its
// owner_session_id, not its own id -- these fixtures set that up explicitly.
const unit: WorkUnit = {
  id: "01JU1", step_id: "implement", type: "task", status: "closed", attempt: 0, owner_session_id: "01JS1", convoy_id: null,
};
const otherUnit: WorkUnit = { ...unit, id: "01JU2", step_id: "review", owner_session_id: "01JS2" };

describe("UnitDrawer", () => {
  it("shows only the selected unit's events, artifacts, and sessions -- not other units'", () => {
    const events = [
      { seq: 1, type: "unit.closed", unit_id: "01JU1", payload: { a: 1 } },
      { seq: 2, type: "unit.closed", unit_id: "01JU2", payload: { a: 2 } },
    ];
    const artifacts: Artifact[] = [
      { id: "a1", work_unit_id: "01JU1", kind: "diff", version: 1, produced_by_role: "implementer", payload_json: {} },
      { id: "a2", work_unit_id: "01JU2", kind: "diff", version: 1, produced_by_role: "implementer", payload_json: {} },
    ];
    const gates: Gate[] = [
      { id: "g1", work_unit_id: "01JU1", gate_type: "human", decision: "pending" },
      { id: "g2", work_unit_id: "01JU2", gate_type: "human", decision: "pending" },
    ];
    // Session ids/work_unit_ids match the two units' owner_session_id
    // values above (01JS1/01JS2), NOT 01JU1/01JU2 -- see the comment above
    // unit's declaration for why.
    const sessions: Session[] = [
      { id: "01JS1", work_unit_id: "01JS1", run_id: "r1", step_id: "implement", driver: "fake", status: "closed", model: "m1", tokens_in: 1, tokens_out: 2, started_at: null, ended_at: null },
      { id: "01JS2", work_unit_id: "01JS2", run_id: "r1", step_id: "review", driver: "fake", status: "closed", model: "m1", tokens_in: 1, tokens_out: 2, started_at: null, ended_at: null },
    ];

    render(
      <UnitDrawer
        unit={unit}
        events={events as FeedEventLike[]}
        artifacts={artifacts}
        gates={gates}
        sessions={sessions}
        onClose={vi.fn()}
        onDecideGate={vi.fn()}
      />
    );

    expect(screen.getByText(/implement/)).toBeInTheDocument();
    expect(screen.queryByText(/"a":2/)).not.toBeInTheDocument(); // other unit's event payload
    expect(screen.getAllByTestId("drawer-artifact")).toHaveLength(1);
    expect(screen.getAllByTestId("drawer-session")).toHaveLength(1);
  });

  it("calls onClose when the close button is clicked", async () => {
    const onClose = vi.fn();
    render(
      <UnitDrawer unit={unit} events={[]} artifacts={[]} gates={[]} sessions={[]} onClose={onClose} onDecideGate={vi.fn()} />
    );
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /close/i }));

    expect(onClose).toHaveBeenCalled();
  });

  it("shows the unit's gate via GateCard when one exists", () => {
    const gates: Gate[] = [{ id: "g1", work_unit_id: "01JU1", gate_type: "human", decision: "pending" }];
    render(<UnitDrawer unit={unit} events={[]} artifacts={[]} gates={gates} sessions={[]} onClose={vi.fn()} onDecideGate={vi.fn()} />);

    expect(screen.getByRole("button", { name: /approve/i })).toBeInTheDocument();
  });

  it("shows no gate tab content for a unit with no gate", () => {
    render(<UnitDrawer unit={otherUnit} events={[]} artifacts={[]} gates={[]} sessions={[]} onClose={vi.fn()} onDecideGate={vi.fn()} />);

    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
    expect(screen.getByText(/no gate/i)).toBeInTheDocument();
  });
});
```

This test references a `FeedEventLike` type that doesn't exist yet — add it to `frontend/src/api/types.ts` as part of this task (it's a structural subset of `useEventStream`'s `FeedEvent`, needed here because `UnitDrawer` shouldn't import from a hook module, only from `types.ts`, to keep it a presentational component with no hook dependency):

```ts
export interface FeedEventLike {
  seq: number;
  type: string;
  unit_id: string | null;
  payload: unknown;
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/UnitDrawer.test.tsx`
Expected: FAIL — `Cannot find module './UnitDrawer'`.

- [ ] **Step 3: Create `UnitDrawer.tsx`**

```tsx
import type { Artifact, FeedEventLike, Gate, Session, WorkUnit } from "../api/types";
import ArtifactCard from "./ArtifactCard";
import GateCard from "./GateCard";

export default function UnitDrawer({
  unit,
  events,
  artifacts,
  gates,
  sessions,
  onClose,
  onDecideGate,
}: {
  unit: WorkUnit;
  events: FeedEventLike[];
  artifacts: Artifact[];
  gates: Gate[];
  sessions: Session[];
  onClose: () => void;
  onDecideGate: (gateId: string, decision: "approved" | "rejected", feedback?: { chips: string[]; text: string }) => void;
}) {
  const unitEvents = events.filter((e) => e.unit_id === unit.id);
  const unitArtifacts = artifacts.filter((a) => a.work_unit_id === unit.id).sort((a, b) => b.version - a.version);
  const unitGate = gates.find((g) => g.work_unit_id === unit.id);
  // Sessions attach to a SESSION-type WorkUnit, not the TASK-type unit this
  // drawer is scoped to -- filter by the task's owner_session_id (its
  // current/latest session), not its own id, which would never match any
  // session's work_unit_id. This only surfaces the most recent attempt, not
  // full retry history: once a task retries, owner_session_id is
  // reassigned to the new session unit and the old session unit's id is no
  // longer reachable from the task, and there's no other stored link back
  // to it without a schema change -- a real limitation discovered while
  // implementing this plan (not in the original design spec), accepted
  // here as out of scope rather than blocking on a schema change.
  const unitSessions = sessions.filter((s) => s.work_unit_id === unit.owner_session_id);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={onClose}>
      <div
        className="flex h-full w-full max-w-lg flex-col gap-4 overflow-y-auto border-l border-slate-800 bg-slate-950 p-4"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between">
          <h3 className="text-lg font-semibold">{unit.step_id}</h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-slate-700 px-2 py-1 text-xs hover:border-orange-400"
          >
            Close
          </button>
        </div>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Gate</h4>
          {unitGate ? (
            <GateCard
              gate={unitGate}
              artifact={unitGate.artifact_id ? unitArtifacts.find((a) => a.id === unitGate.artifact_id) : undefined}
              onDecide={(decision, feedback) => onDecideGate(unitGate.id, decision, feedback)}
            />
          ) : (
            <p className="text-sm text-slate-500">No gate for this step.</p>
          )}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Artifacts</h4>
          {unitArtifacts.length === 0 && <p className="text-sm text-slate-500">No artifacts yet.</p>}
          {unitArtifacts.map((a) => (
            <div key={a.id} data-testid="drawer-artifact">
              <ArtifactCard artifact={a} />
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Session log</h4>
          {unitSessions.length === 0 && <p className="text-sm text-slate-500">No sessions yet.</p>}
          {unitSessions.map((s) => (
            <div
              key={s.id}
              data-testid="drawer-session"
              className="flex items-center justify-between rounded border border-slate-800 px-2 py-1 text-xs text-slate-400"
            >
              <span>{s.driver} · {s.model ?? "—"}</span>
              <span>{s.status}</span>
              <span className="tabular-nums">{s.tokens_in} in / {s.tokens_out} out</span>
            </div>
          ))}
        </section>

        <section className="flex flex-col gap-2">
          <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-400">Events</h4>
          {unitEvents.length === 0 && <p className="text-sm text-slate-500">No events yet.</p>}
          {unitEvents.map((e) => (
            <div key={e.seq} className="font-mono text-xs text-slate-400">
              [{e.seq}] {e.type} {JSON.stringify(e.payload)}
            </div>
          ))}
        </section>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/UnitDrawer.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 5: Wire the drawer into `RunDetailPage`**

Replace `frontend/src/pages/RunDetailPage.tsx` entirely with:

```tsx
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { decideGate } from "../api/gates";
import { cancelRun, getRunArtifacts, getRunDetail, getRunGraph, getRunSessions } from "../api/runs";
import type { WorkUnit } from "../api/types";
import DagView from "../components/DagView";
import EventFeed from "../components/EventFeed";
import GateCard from "../components/GateCard";
import Ribbon from "../components/Ribbon";
import UnitDrawer from "../components/UnitDrawer";
import { useEventStream } from "../hooks/useEventStream";

export default function RunDetailPage() {
  const { id } = useParams<{ id: string }>();
  const runId = id!;
  const queryClient = useQueryClient();
  const events = useEventStream(runId);
  const [selectedUnit, setSelectedUnit] = useState<WorkUnit | null>(null);

  const { data: detail, isLoading } = useQuery({ queryKey: ["run", runId], queryFn: () => getRunDetail(runId) });
  const { data: artifacts } = useQuery({ queryKey: ["run-artifacts", runId], queryFn: () => getRunArtifacts(runId) });
  const { data: graph } = useQuery({ queryKey: ["run-graph", runId], queryFn: () => getRunGraph(runId) });
  const { data: sessions } = useQuery({
    queryKey: ["run-sessions", runId],
    queryFn: () => getRunSessions(runId),
    enabled: selectedUnit !== null, // no need to fetch session history until the drawer is actually open
  });

  useEffect(() => {
    if (events.length === 0) return;
    queryClient.invalidateQueries({ queryKey: ["run", runId] });
    queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
    queryClient.invalidateQueries({ queryKey: ["run-graph", runId] });
  }, [events.length, runId, queryClient]);

  const decideMutation = useMutation({
    mutationFn: ({ gateId, decision, feedback }: { gateId: string; decision: "approved" | "rejected"; feedback?: { chips: string[]; text: string } }) =>
      decideGate(gateId, decision, feedback),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
    },
  });

  const cancelMutation = useMutation({
    mutationFn: () => cancelRun(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["run", runId] });
      queryClient.invalidateQueries({ queryKey: ["run-artifacts", runId] });
    },
  });

  if (isLoading || !detail) {
    return <p className="text-slate-400">Loading…</p>;
  }

  const isTerminal = detail.run.status === "closed" || detail.run.status === "cancelled";
  const artifactById = new Map((artifacts ?? []).map((a) => [a.id, a]));

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-semibold">{detail.run.title}</h2>
          <p className="text-sm text-slate-500">{detail.run.status}</p>
          <p className="text-xs text-slate-500">Pack: {detail.run.pack_version_pin}</p>
        </div>
        <button
          className="rounded bg-red-900 px-3 py-1.5 text-sm hover:bg-red-800 disabled:opacity-40"
          disabled={isTerminal}
          onClick={() => cancelMutation.mutate()}
        >
          Cancel run
        </button>
      </div>

      <Ribbon units={detail.units} gates={detail.gates} onSelectUnit={setSelectedUnit} />

      <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Gates & artifacts</h3>
          {detail.gates.map((gate) => (
            <GateCard
              key={gate.id}
              gate={gate}
              artifact={gate.artifact_id ? artifactById.get(gate.artifact_id) : undefined}
              onDecide={(decision, feedback) => decideMutation.mutate({ gateId: gate.id, decision, feedback })}
            />
          ))}
          {detail.gates.length === 0 && <p className="text-sm text-slate-500">No gates yet.</p>}
        </div>

        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Live feed</h3>
          <EventFeed events={events} />
        </div>
      </div>

      {graph && (
        <div className="flex flex-col gap-3">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">DAG</h3>
          <div className="overflow-x-auto">
            <DagView units={graph.units} deps={graph.deps} onNodeClick={setSelectedUnit} />
          </div>
        </div>
      )}

      {selectedUnit && (
        <UnitDrawer
          unit={selectedUnit}
          events={events}
          artifacts={artifacts ?? []}
          gates={detail.gates}
          sessions={sessions ?? []}
          onClose={() => setSelectedUnit(null)}
          onDecideGate={(gateId, decision, feedback) => decideMutation.mutate({ gateId, decision, feedback })}
        />
      )}
    </div>
  );
}
```

- [ ] **Step 6: Write a `RunDetailPage` test proving the drawer opens on click**

Add to `frontend/src/pages/RunDetailPage.test.tsx` (add `import userEvent from "@testing-library/user-event";` to the top if not already imported):

```tsx
  it("opens the unit drawer when a ribbon step is clicked, showing its gate", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockImplementation((url: string) => {
      if (url === "/api/runs/01JR1") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: {
              run: { id: "01JR1", project_id: "01JP1", playbook_ref: "demo.toml", title: "demo run", status: "active", created_at: "2026-07-21T00:00:00Z" },
              units: [{ id: "01JU1", step_id: "implement", type: "task", status: "closed", attempt: 0, owner_session_id: null }],
              gates: [{ id: "01JG1", work_unit_id: "01JU1", gate_type: "human", decision: "pending" }],
            },
            paging: {},
          }),
        });
      }
      if (url === "/api/runs/01JR1/graph") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: { units: [], deps: [] }, paging: {} }) });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });

    renderPage("01JR1");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByTestId("ribbon-step-01JU1")).toBeInTheDocument());
    await user.click(screen.getByTestId("ribbon-step-01JU1"));

    await waitFor(() => expect(screen.getAllByText(/implement/).length).toBeGreaterThan(1));
    expect(screen.getAllByRole("button", { name: /approve/i }).length).toBeGreaterThan(0);
  });
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/RunDetailPage.test.tsx`
Expected: PASS (4 tests).

- [ ] **Step 8: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/UnitDrawer.tsx frontend/src/components/UnitDrawer.test.tsx frontend/src/pages/RunDetailPage.tsx frontend/src/pages/RunDetailPage.test.tsx frontend/src/api/types.ts
git commit -m "feat(frontend): unit drawer with events/artifact/gate/session-log tabs

Clicking a ribbon step or DAG node opens a slide-over drawer scoped to
that unit, filtering the page's already-fetched events/artifacts/gates
client-side and lazily fetching session history (only once the drawer
is actually opened, via React Query's enabled flag) from Task 2's new
endpoint. Reuses GateCard/ArtifactCard rather than duplicating their
logic. The existing flat gates-and-artifacts panel stays untouched --
the drawer is a supplementary drill-in, not a replacement."
```

---

### Task 6: Reject-with-chips

**Files:**
- Modify: `frontend/src/components/GateCard.tsx`
- Modify: `frontend/src/components/GateCard.test.tsx`

**Interfaces:**
- Consumes: nothing new (uses `GateCard`'s existing `onDecide` prop, unchanged signature).
- Produces: nothing new consumed elsewhere — this is a self-contained UI change.

- [ ] **Step 1: Write the failing test**

Add to `frontend/src/components/GateCard.test.tsx`:

```tsx
  it("includes selected chips alongside free text in the rejection feedback", async () => {
    const onDecide = vi.fn();
    render(<GateCard gate={pendingHumanGate} artifact={undefined} onDecide={onDecide} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /reject/i }));
    await user.click(screen.getByRole("button", { name: /missing tests/i }));
    await user.type(screen.getByLabelText(/feedback/i), "add coverage");
    await user.click(screen.getByRole("button", { name: /submit rejection/i }));

    expect(onDecide).toHaveBeenCalledWith("rejected", { chips: ["missing tests"], text: "add coverage" });
  });

  it("deselects a chip on a second click", async () => {
    const onDecide = vi.fn();
    render(<GateCard gate={pendingHumanGate} artifact={undefined} onDecide={onDecide} />);
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: /reject/i }));
    await user.click(screen.getByRole("button", { name: /missing tests/i }));
    await user.click(screen.getByRole("button", { name: /missing tests/i }));
    await user.type(screen.getByLabelText(/feedback/i), "nvm");
    await user.click(screen.getByRole("button", { name: /submit rejection/i }));

    expect(onDecide).toHaveBeenCalledWith("rejected", { chips: [], text: "nvm" });
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/GateCard.test.tsx`
Expected: FAIL — no chip buttons exist yet (`getByRole("button", { name: /missing tests/i })` finds nothing).

- [ ] **Step 3: Add the chip selector**

In `frontend/src/components/GateCard.tsx`, add the chip constant near the top of the file (after the imports):

```tsx
const REJECTION_CHIPS = ["missing tests", "wrong approach", "incomplete", "needs docs"];
```

Add chip-selection state alongside the existing `feedbackText` state:

```tsx
  const [selectedChips, setSelectedChips] = useState<string[]>([]);

  function toggleChip(chip: string) {
    setSelectedChips((prev) => (prev.includes(chip) ? prev.filter((c) => c !== chip) : [...prev, chip]));
  }
```

Insert the chip row above the existing `<label>` in the `rejecting` branch:

```tsx
            <div className="flex flex-col gap-2">
              <div className="flex flex-wrap gap-1">
                {REJECTION_CHIPS.map((chip) => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => toggleChip(chip)}
                    className={`rounded-full border px-2 py-0.5 text-xs ${
                      selectedChips.includes(chip)
                        ? "border-orange-500 bg-orange-950 text-orange-300"
                        : "border-slate-700 text-slate-400 hover:border-slate-500"
                    }`}
                  >
                    {chip}
                  </button>
                ))}
              </div>
              <label className="flex flex-col text-xs">
                Feedback
                <textarea
                  className="rounded border border-slate-700 bg-slate-900 px-2 py-1 text-sm"
                  value={feedbackText}
                  onChange={(e) => setFeedbackText(e.target.value)}
                />
              </label>
              <button
                className="self-start rounded bg-red-800 px-3 py-1 text-sm hover:bg-red-700"
                onClick={() => {
                  onDecide("rejected", { chips: selectedChips, text: feedbackText });
                  setRejecting(false);
                  setFeedbackText("");
                  setSelectedChips([]);
                }}
              >
                Submit rejection
              </button>
            </div>
```

(This replaces the existing `rejecting`-branch `<div className="flex flex-col gap-2">...</div>` block entirely — same structure, with the chip row inserted above the label and `chips: selectedChips` replacing the old hardcoded `chips: []` in the submit handler.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/GateCard.test.tsx`
Expected: PASS (6 tests — the 4 existing plus the 2 new ones; the existing "requires feedback text before submitting" test, which never clicks a chip, still asserts `{ chips: [], text: "not good enough" }` and should be unaffected).

- [ ] **Step 5: Run the full frontend suite**

Run: `cd frontend && npx vitest run`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/GateCard.tsx frontend/src/components/GateCard.test.tsx
git commit -m "feat(frontend): reject-with-chips on gate cards

GateCard's rejection flow already threaded a chips: string[] field
through to the API but always sent it empty -- the selector UI never
existed. Adds a fixed, toggleable set of common rejection reasons
above the existing free-text field; selected chips and text both
submit together in Gate.feedback_json, unchanged shape."
```

---

## Final verification

- [ ] Run: `uv run pytest -q` — expect all backend tests passing (269 before this plan, plus this plan's new tests).
- [ ] Run: `cd frontend && npx vitest run` — expect all frontend tests passing.
- [ ] Run: `cd frontend && npx tsc -b` — expect no type errors (confirms `dagre`'s types resolve correctly under this repo's `strict: true` config).
- [ ] Confirm the design spec's five pieces are all present: two-pill ribbon (`Ribbon.tsx` renders `ribbon-pill-agent`/`ribbon-pill-human`), interactive dagre DAG (`DagView.tsx` imports `dagre`, nodes have `onClick`), unit drawer with four tabs (`UnitDrawer.tsx`), new session-history endpoint (`GET /api/runs/{run_id}/sessions`), reject-with-chips (`GateCard.tsx` renders `REJECTION_CHIPS`).
- [ ] Confirm the existing flat "Gates & artifacts" panel on `RunDetailPage` is still present and unchanged — the drawer supplements it, per the plan's Global Constraints, it does not replace it.
