# Project Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add per-project settings (default driver, default token budget,
default playbook path), editable via a new PATCH endpoint, and apply them
at run-creation time — closing design-deviations.md finding G4.

**Architecture:** Two backend tasks (schema + settings endpoint, then
token-budget application at run creation) followed by two frontend tasks
(a settings form on `ProjectDetailPage`, then `NewRunForm` pre-fill + a
previously-missing driver selector). Backend lands first since the frontend
tasks depend on `ProjectOut`'s new fields and the settings endpoint existing.

**Tech Stack:** Python 3.12+, SQLAlchemy 2 async, Pydantic v2, FastAPI,
pytest + pytest-asyncio (backend); React, TypeScript, `@tanstack/react-query`,
Vitest + Testing Library (frontend).

## Global Constraints

- No Alembic — direct SQLAlchemy model edits, same as every prior schema
  change in this codebase (D1's resolution: unused until M5).
- No gate-policy defaults — `gate_overrides` is playbook-step-id-keyed and
  has no stable per-project shape (see spec's "Scope decisions").
- No `Pack`-table changes — settings are per-project only.
- No `token_budget` field added to `NewRunForm`'s UI — the project default
  applies automatically server-side; a per-run override stays possible via
  the API (`RunCreate.token_budget`) but isn't exposed in this form.
- `orchestrator/budget.py`'s enforcement logic is unchanged — this plan
  only changes how `token_budget` gets *set* at run creation, not how it's
  checked afterward.

---

### Task 1: `Project` settings columns + `PATCH /api/projects/{id}/settings`

**Files:**
- Modify: `src/foundry/store/models.py` (`Project`)
- Modify: `src/foundry/api/routes/projects.py`
- Test: `tests/api/test_projects.py`

**Interfaces:**
- Produces: `Project.default_driver: str` (default `"fake"`),
  `Project.default_token_budget: int` (default `0`),
  `Project.default_playbook_path: str | None` (default `None`) columns.
- Produces: `ProjectOut` gains `default_driver: str`,
  `default_token_budget: int`, `default_playbook_path: str | None` fields —
  Task 3 (frontend) reads these from `GET /api/projects/{id}` and
  `GET /api/projects`.
- Produces: `PATCH /api/projects/{project_id}/settings` accepting a
  `ProjectSettingsUpdate` body (`driver: str | None`,
  `token_budget: int | None`, `playbook_path: str | None`, all optional —
  only provided fields change), returns the updated `ProjectOut`.

- [ ] **Step 1: Write the failing test for the new columns + defaults**

Add to `tests/api/test_projects.py`:

```python
@pytest.mark.asyncio
async def test_new_project_has_default_settings(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo5", "path": "."})

    body = resp.json()["data"]
    assert body["default_driver"] == "fake"
    assert body["default_token_budget"] == 0
    assert body["default_playbook_path"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_projects.py::test_new_project_has_default_settings -v`
Expected: FAIL — `KeyError: 'default_driver'` (field doesn't exist on
`ProjectOut` yet).

- [ ] **Step 3: Add the columns to `Project`**

In `src/foundry/store/models.py`, add to the `Project` class (after
`status`, before `created_at`):

```python
    default_driver: Mapped[str] = mapped_column(String, default="fake")
    default_token_budget: Mapped[int] = mapped_column(Integer, default=0)
    default_playbook_path: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Add the fields to `ProjectOut` and `_to_project_out`**

In `src/foundry/api/routes/projects.py`, update `ProjectOut`:

```python
class ProjectOut(BaseModel):
    id: str
    name: str
    path: str
    kg_status: str
    status: str
    created_at: str
    default_driver: str
    default_token_budget: int
    default_playbook_path: str | None
```

Update `_to_project_out`:

```python
def _to_project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        path=p.path,
        kg_status=p.kg_status,
        status=p.status,
        created_at=p.created_at.isoformat(),
        default_driver=p.default_driver,
        default_token_budget=p.default_token_budget,
        default_playbook_path=p.default_playbook_path,
    )
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/api/test_projects.py::test_new_project_has_default_settings -v`
Expected: PASS

- [ ] **Step 6: Write the failing test for the settings endpoint**

Add to `tests/api/test_projects.py`:

```python
@pytest.mark.asyncio
async def test_patch_settings_updates_only_provided_fields(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo6", "path": "."})
    project_id = resp.json()["data"]["id"]

    resp = await client.patch(f"/api/projects/{project_id}/settings", json={"driver": "codex"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["default_driver"] == "codex"
    assert body["default_token_budget"] == 0  # untouched
    assert body["default_playbook_path"] is None  # untouched

    resp = await client.patch(
        f"/api/projects/{project_id}/settings",
        json={"token_budget": 50000, "playbook_path": "packs/default/playbooks/bugfix.toml"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["default_driver"] == "codex"  # still untouched by this second call
    assert body["default_token_budget"] == 50000
    assert body["default_playbook_path"] == "packs/default/playbooks/bugfix.toml"


@pytest.mark.asyncio
async def test_patch_settings_for_missing_project_404s(api_client):
    client, _store, _scheduler = api_client

    resp = await client.patch("/api/projects/does-not-exist/settings", json={"driver": "codex"})

    assert resp.status_code == 404
```

- [ ] **Step 7: Run test to verify it fails**

Run: `uv run pytest tests/api/test_projects.py -k patch_settings -v`
Expected: FAIL — `405 Method Not Allowed` (route doesn't exist yet).

- [ ] **Step 8: Add the settings endpoint**

In `src/foundry/api/routes/projects.py`, add the request model and route
(after `ProjectOut`, before `_to_project_out` or anywhere else in the file —
placement among the other models is fine):

```python
class ProjectSettingsUpdate(BaseModel):
    driver: str | None = None
    token_budget: int | None = None
    playbook_path: str | None = None
```

Add the route (after `activate_project`, at the end of the file):

```python
@router.patch("/projects/{project_id}/settings")
async def update_project_settings(
    project_id: str, body: ProjectSettingsUpdate, request: Request
) -> ApiResponse[ProjectOut]:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    fields: dict[str, object] = {}
    if body.driver is not None:
        fields["default_driver"] = body.driver
    if body.token_budget is not None:
        fields["default_token_budget"] = body.token_budget
    if body.playbook_path is not None:
        fields["default_playbook_path"] = body.playbook_path

    if fields:
        await store.update_project(project_id, **fields)
        project = await store.get_project(project_id)

    return ApiResponse[ProjectOut](data=_to_project_out(project), paging=Paging.none())
```

- [ ] **Step 9: Run test to verify it passes**

Run: `uv run pytest tests/api/test_projects.py -k patch_settings -v`
Expected: PASS

- [ ] **Step 10: Run the full projects test file + full suite**

Run: `uv run pytest tests/api/test_projects.py -v && uv run pytest -q`
Expected: all PASS.

- [ ] **Step 11: Commit**

```bash
git add src/foundry/store/models.py src/foundry/api/routes/projects.py tests/api/test_projects.py
git commit -m "feat(api): add per-project settings (driver, token budget, playbook path)

New Project columns (default_driver, default_token_budget,
default_playbook_path) and PATCH /api/projects/{id}/settings for
partial updates. Storage only in this task -- run-creation
application lands in the next task."
```

---

### Task 2: Apply `default_token_budget` at run creation

**Files:**
- Modify: `src/foundry/store/store.py` (`create_run`)
- Modify: `src/foundry/api/routes/runs.py` (`RunCreate`, `create_run` route)
- Test: `tests/store/test_store.py`, `tests/api/test_runs.py`

**Interfaces:**
- Consumes: `Project.default_token_budget` (Task 1).
- Produces: `Store.create_run(..., token_budget: int = 0)` — new parameter,
  threaded into the `Run` row.
- Produces: `RunCreate.token_budget: int | None = None` — optional
  API-level override.

- [ ] **Step 1: Write the failing test for `Store.create_run`'s new parameter**

Add to `tests/store/test_store.py` (it already defines `make_store` and has
multiple `store.create_run(project.id, "pb.toml", "...")` calls to match the
style of):

```python
@pytest.mark.asyncio
async def test_create_run_persists_token_budget(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("p", str(tmp_path))

    run = await store.create_run(project.id, "playbook.toml", "title", token_budget=25000)
    assert run.token_budget == 25000

    fetched = await store.get_run(run.id)
    assert fetched.token_budget == 25000

    default_run = await store.create_run(project.id, "playbook2.toml", "title2")
    assert default_run.token_budget == 0

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/store/test_store.py -k persists_token_budget -v`
Expected: FAIL — `TypeError: create_run() got an unexpected keyword argument 'token_budget'`

- [ ] **Step 3: Add the parameter to `Store.create_run`**

In `src/foundry/store/store.py`, update `create_run`:

```python
    async def create_run(
        self,
        project_id: str,
        playbook_ref: str,
        title: str,
        pack_version_pin: str = "local",
        driver: str = "fake",
        token_budget: int = 0,
    ) -> Run:
        async def _op(session):
            run = Run(
                project_id=project_id,
                playbook_ref=playbook_ref,
                title=title,
                pack_version_pin=pack_version_pin,
                driver=driver,
                token_budget=token_budget,
            )
            session.add(run)
            await session.flush()
            return run

        return await self.write(_op)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/store/test_store.py -k persists_token_budget -v`
Expected: PASS

- [ ] **Step 5: Write the failing test for the API-level default resolution**

Add to `tests/api/test_runs.py`:

```python
@pytest.mark.asyncio
async def test_create_run_applies_project_default_token_budget(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "budgetproj", "path": "/tmp/budgetproj"})
    project_id = proj_resp.json()["data"]["id"]
    await client.patch(f"/api/projects/{project_id}/settings", json={"token_budget": 30000})

    run_resp = await client.post(
        "/api/runs",
        json={"project_id": project_id, "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml"},
    )
    assert run_resp.status_code == 201, run_resp.text
    assert run_resp.json()["data"]["token_budget"] == 30000


@pytest.mark.asyncio
async def test_create_run_explicit_token_budget_overrides_project_default(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "budgetproj2", "path": "/tmp/budgetproj2"})
    project_id = proj_resp.json()["data"]["id"]
    await client.patch(f"/api/projects/{project_id}/settings", json={"token_budget": 30000})

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "token_budget": 5000,
        },
    )
    assert run_resp.status_code == 201, run_resp.text
    assert run_resp.json()["data"]["token_budget"] == 5000
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/api/test_runs.py -k token_budget -v`
Expected: FAIL — `token_budget` not accepted by `RunCreate`
(`pydantic.ValidationError` — "extra fields not permitted" or the response
simply ignores it and stores `0`, depending on Pydantic config; either way
the assertion on `30000`/`5000` fails).

- [ ] **Step 7: Add `token_budget` to `RunCreate` and apply the default in the route**

In `src/foundry/api/routes/runs.py`, update `RunCreate`:

```python
class RunCreate(BaseModel):
    project_id: str
    playbook_path: str
    title: str | None = None
    gate_overrides: dict[str, Literal["approved", "rejected"]] | None = None
    driver: Literal["fake", "codex", "claude"] = "fake"
    token_budget: int | None = None
```

In `src/foundry/api/routes/runs.py`'s `create_run` route, the current code
(after `title`/`pack_version_pin` are computed) reads:

```python
    run = await store.create_run(
        project.id, body.playbook_path, title, pack_version_pin=pack_version_pin, driver=body.driver
    )
```

Change it to:

```python
    effective_token_budget = (
        body.token_budget if body.token_budget is not None else project.default_token_budget
    )
    run = await store.create_run(
        project.id, body.playbook_path, title, pack_version_pin=pack_version_pin,
        driver=body.driver, token_budget=effective_token_budget,
    )
```

Nothing else in the function changes — the `materialize(...)` call,
`gate_overrides` handling, and `scheduler.register(...)` call immediately
below stay exactly as they are.

- [ ] **Step 8: Run test to verify it passes**

Run: `uv run pytest tests/api/test_runs.py -k token_budget -v`
Expected: PASS

- [ ] **Step 9: Run the full backend suite**

Run: `uv run pytest -q`
Expected: all PASS — existing tests that call `store.create_run(...)`
without `token_budget` keep defaulting to `0`, matching current behavior.

- [ ] **Step 10: Commit**

```bash
git add src/foundry/store/store.py src/foundry/api/routes/runs.py \
        tests/store/test_store.py tests/api/test_runs.py
git commit -m "feat(api): apply project default_token_budget at run creation

RunCreate.token_budget is an optional override; when omitted, the
route resolves it from the owning project's default_token_budget.
Store.create_run threads the value into the new Run row."
```

---

### Task 3: Settings form on `ProjectDetailPage`

**Files:**
- Modify: `frontend/src/api/types.ts` (`Project`)
- Modify: `frontend/src/api/projects.ts`
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Test: `frontend/src/api/projects.test.ts`, `frontend/src/pages/ProjectDetailPage.test.tsx`

**Interfaces:**
- Consumes: `ProjectOut`'s new fields (Task 1), surfaced through the
  existing `Project` type/`getProject`/`listProjects`.
- Produces: `updateProjectSettings(id: string, fields: { driver?: string; token_budget?: number; playbook_path?: string }): Promise<Project>`
  in `frontend/src/api/projects.ts`. Task 4 doesn't need this directly (it
  reads `Project.default_*` fields, not this function), but it's this
  task's mutation.

- [ ] **Step 1: Write the failing test for `updateProjectSettings`**

Add to `frontend/src/api/projects.test.ts` (created in the G3 round; add
this as a new `describe` block):

```typescript
describe("updateProjectSettings", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn()));
  afterEach(() => vi.unstubAllGlobals());

  it("PATCHes only the provided fields", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({
      ok: true, status: 200,
      json: async () => ({
        data: {
          id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active",
          created_at: "2026-07-21T00:00:00Z", default_driver: "codex", default_token_budget: 0,
          default_playbook_path: null,
        },
        paging: {},
      }),
    });

    const project = await updateProjectSettings("p1", { driver: "codex" });

    expect(project.default_driver).toBe("codex");
    expect(fetch).toHaveBeenCalledWith(
      "/api/projects/p1/settings",
      expect.objectContaining({ method: "PATCH", body: JSON.stringify({ driver: "codex" }) }),
    );
  });
});
```

Add the import at the top of the file (alongside whatever's already
imported from `./projects`):

```typescript
import { updateProjectSettings } from "./projects";
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/projects.test.ts -t "updateProjectSettings"`
Expected: FAIL — `updateProjectSettings` is not exported.

- [ ] **Step 3: Extend the `Project` type and add the client function**

In `frontend/src/api/types.ts`, update `Project`:

```typescript
export interface Project {
  id: string;
  name: string;
  path: string;
  kg_status: string;
  status: string;
  created_at: string;
  default_driver: string;
  default_token_budget: number;
  default_playbook_path: string | null;
}
```

In `frontend/src/api/projects.ts`, add:

```typescript
export async function updateProjectSettings(
  id: string,
  fields: { driver?: string; token_budget?: number; playbook_path?: string },
): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}/settings`, {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(fields),
  });
  return res.data;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/projects.test.ts`
Expected: PASS

- [ ] **Step 5: Write the failing test for the settings section**

Add to `frontend/src/pages/ProjectDetailPage.test.tsx`:

```typescript
  it("submits updated settings and reflects the new values", async () => {
    let currentDriver = "fake";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (url === "/api/projects/p1" || url === "/api/projects/p1/settings") {
          if (init?.method === "PATCH") {
            currentDriver = "codex";
          }
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: {
                id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active",
                created_at: "2026-07-21T00:00:00Z", default_driver: currentDriver,
                default_token_budget: 0, default_playbook_path: null,
              },
              paging: {},
            }),
          });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders("p1");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByLabelText(/driver/i)).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/driver/i), "codex");
    await user.click(screen.getByRole("button", { name: /save settings/i }));

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith(
        "/api/projects/p1/settings",
        expect.objectContaining({ method: "PATCH" }),
      ),
    );
  });
```

Add the import at the top of the test file:

```typescript
import userEvent from "@testing-library/user-event";
```

(if not already imported — check the file first.)

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.test.tsx -t "submits updated settings"`
Expected: FAIL — no "driver" label / no "save settings" button exists yet.

- [ ] **Step 7: Add the settings section to `ProjectDetailPage`**

In `frontend/src/pages/ProjectDetailPage.tsx`, add the imports:

```typescript
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { updateProjectSettings } from "../api/projects";
```

Add state and a mutation inside the component, after the existing queries
and before the `if (isError)` guard:

```typescript
  const queryClient = useQueryClient();
  const [driver, setDriver] = useState("fake");
  const [tokenBudget, setTokenBudget] = useState(0);
  const [playbookPath, setPlaybookPath] = useState("");

  const settingsMutation = useMutation({
    mutationFn: () =>
      updateProjectSettings(projectId, {
        driver,
        token_budget: tokenBudget,
        playbook_path: playbookPath,
      }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project", projectId] }),
  });
```

Add a `useEffect` to sync local form state whenever `project` loads (after
the mutation definition, still before the `if (isError)` guard):

```typescript
  useEffect(() => {
    if (project) {
      setDriver(project.default_driver);
      setTokenBudget(project.default_token_budget);
      setPlaybookPath(project.default_playbook_path ?? "");
    }
  }, [project]);
```

Add the `useEffect` import to the existing `react` import line at the top
of the file (there isn't one yet in this file — add
`import { useEffect, useState } from "react";` as its own import line).

Add the settings section to the JSX, after the header `<div>` (right before
the "Runs" section):

```tsx
      <div className="flex flex-col gap-3">
        <h3 className="text-sm font-semibold uppercase tracking-wide text-slate-400">Settings</h3>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            settingsMutation.mutate();
          }}
        >
          <label className="flex flex-col text-sm">
            Driver
            <select
              className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
              value={driver}
              onChange={(e) => setDriver(e.target.value)}
            >
              <option value="fake">fake</option>
              <option value="codex">codex</option>
              <option value="claude">claude</option>
            </select>
          </label>
          <label className="flex flex-col text-sm">
            Token budget
            <input
              type="number"
              className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
              value={tokenBudget}
              onChange={(e) => setTokenBudget(Number(e.target.value))}
            />
          </label>
          <label className="flex flex-col text-sm">
            Default playbook path
            <input
              className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
              value={playbookPath}
              onChange={(e) => setPlaybookPath(e.target.value)}
              placeholder="packs/default/playbooks/sdlc_story.toml"
            />
          </label>
          <button
            type="submit"
            disabled={settingsMutation.isPending}
            className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500"
          >
            Save settings
          </button>
        </form>
      </div>
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/ProjectDetailPage.test.tsx`
Expected: PASS (all tests in the file).

- [ ] **Step 9: Run the full frontend suite + typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, no type errors.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/projects.ts frontend/src/api/projects.test.ts \
        frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.test.tsx
git commit -m "feat(frontend): add project settings form to ProjectDetailPage

Driver/token-budget/default-playbook-path form, PATCHes
/api/projects/:id/settings, invalidates the project query on save so
the whole page (including this form's own pre-filled values) reflects
the update immediately."
```

---

### Task 4: `NewRunForm` driver selector + pre-fill from project defaults

**Files:**
- Modify: `frontend/src/api/runs.ts` (`createRun`)
- Modify: `frontend/src/components/NewRunForm.tsx`
- Test: `frontend/src/components/NewRunForm.test.tsx` (create if it doesn't
  exist — check first with `ls frontend/src/components/NewRunForm.test.tsx`)

**Interfaces:**
- Consumes: `Project.default_driver`, `Project.default_playbook_path`
  (Task 1/3's `Project` type extension).
- Produces: `createRun(input: { project_id: string; playbook_path: string; title?: string; driver?: string }): Promise<Run>`
  — `driver` is a new optional field threaded into the POST body.

- [ ] **Step 1: Write the failing test for `createRun` sending `driver`**

`frontend/src/api/runs.test.ts` already exists with a `describe("runs API", ...)`
block containing a `"createRun POSTs the run creation payload"` test. Add
this new test into that same `describe` block (it already imports
`createRun` and sets up `vi.stubGlobal("fetch", ...)` in `beforeEach`, so no
new imports or wrapper needed):

```typescript
  it("createRun includes driver in the request body when provided", async () => {
    (fetch as ReturnType<typeof vi.fn>).mockResolvedValue({ ok: true, status: 201, json: async () => ({ data: sampleRun, paging: {} }) });

    await createRun({ project_id: "01JP1", playbook_path: "demo.toml", driver: "codex" });

    expect(fetch).toHaveBeenCalledWith("/api/runs", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ project_id: "01JP1", playbook_path: "demo.toml", driver: "codex" }),
    });
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/api/runs.test.ts`
Expected: FAIL — `createRun`'s input type doesn't accept `driver` (TS
compile error surfaced by Vitest, or the field is silently dropped from the
assertion's expected JSON — either way the `toHaveBeenCalledWith` assertion
fails since the actual body omits `driver`).

- [ ] **Step 3: Add `driver` to `createRun`**

In `frontend/src/api/runs.ts`, update the function signature:

```typescript
export async function createRun(input: {
  project_id: string;
  playbook_path: string;
  title?: string;
  driver?: string;
}): Promise<Run> {
  const res = await apiFetch<Run>("/api/runs", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}
```

(The body is already `JSON.stringify(input)` — passing `driver` through
`input` is all that's needed; no other line changes.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/api/runs.test.ts`
Expected: PASS

- [ ] **Step 5: Write the failing test for `NewRunForm`'s driver select + pre-fill**

Create `frontend/src/components/NewRunForm.test.tsx` (check first with
`ls frontend/src/components/NewRunForm.test.tsx` — if it already exists,
add this test into its existing `describe` block instead of creating a new
file):

```typescript
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import NewRunForm from "./NewRunForm";

const projects = [
  {
    id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active",
    created_at: "2026-07-21T00:00:00Z", default_driver: "codex", default_token_budget: 10000,
    default_playbook_path: "packs/default/playbooks/bugfix.toml",
  },
];

describe("NewRunForm", () => {
  it("pre-fills driver and playbook path from the selected project's defaults", async () => {
    render(<NewRunForm projects={projects} defaultProjectId="p1" onSubmit={vi.fn()} />);

    expect(screen.getByLabelText(/driver/i)).toHaveValue("codex");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("packs/default/playbooks/bugfix.toml");
  });

  it("still allows overriding the pre-filled values before submit", async () => {
    const onSubmit = vi.fn();
    render(<NewRunForm projects={projects} defaultProjectId="p1" onSubmit={onSubmit} />);
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText(/driver/i), "claude");
    await user.click(screen.getByRole("button", { name: /start run/i }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: "p1", driver: "claude" }),
    );
  });
});
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd frontend && npx vitest run src/components/NewRunForm.test.tsx`
Expected: FAIL — no driver `<select>` exists in the form yet.

- [ ] **Step 7: Add the driver select + pre-fill to `NewRunForm`**

Replace the full contents of `frontend/src/components/NewRunForm.tsx` with:

```typescript
import { useEffect, useState } from "react";
import type { Project } from "../api/types";

export default function NewRunForm({
  projects,
  defaultProjectId,
  onSubmit,
}: {
  projects: Project[];
  defaultProjectId?: string;
  onSubmit: (input: { project_id: string; playbook_path: string; title?: string; driver?: string }) => void;
}) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? "");
  const [playbookPath, setPlaybookPath] = useState("");
  const [title, setTitle] = useState("");
  const [driver, setDriver] = useState("fake");

  useEffect(() => {
    const selected = projects.find((p) => p.id === projectId);
    if (selected) {
      setDriver(selected.default_driver);
      setPlaybookPath(selected.default_playbook_path ?? "");
    }
  }, [projectId, projects]);

  return (
    <form
      className="flex flex-wrap items-end gap-3"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ project_id: projectId, playbook_path: playbookPath, title: title || undefined, driver });
        setPlaybookPath("");
        setTitle("");
      }}
    >
      <label className="flex flex-col text-sm">
        Project
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          required
        >
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col text-sm">
        Driver
        <select
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={driver}
          onChange={(e) => setDriver(e.target.value)}
        >
          <option value="fake">fake</option>
          <option value="codex">codex</option>
          <option value="claude">claude</option>
        </select>
      </label>
      <label className="flex flex-col text-sm">
        Playbook path
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={playbookPath}
          onChange={(e) => setPlaybookPath(e.target.value)}
          placeholder="tests/orchestrator/fixtures/linear_demo.toml"
          required
        />
      </label>
      <label className="flex flex-col text-sm">
        Title (optional)
        <input
          className="rounded border border-slate-700 bg-slate-900 px-2 py-1"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
        />
      </label>
      <button type="submit" className="rounded bg-orange-600 px-3 py-1.5 text-sm font-medium hover:bg-orange-500">
        Start run
      </button>
    </form>
  );
}
```

- [ ] **Step 8: Run test to verify it passes**

Run: `cd frontend && npx vitest run src/components/NewRunForm.test.tsx`
Expected: PASS

- [ ] **Step 9: Run the full frontend suite + typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: all PASS, no type errors. In particular, re-check
`frontend/src/pages/RunsHomePage.tsx` and its test — `NewRunForm`'s
`projects` prop type is unchanged (`Project[]`), and its `onSubmit` payload
now includes `driver`, which `createRun` (Task 4 Step 3) already accepts —
`RunsHomePage`'s existing `createMutation.mutate(input)` call needs no
changes since it just forwards whatever `onSubmit` passes through.

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/runs.ts frontend/src/api/runs.test.ts \
        frontend/src/components/NewRunForm.tsx frontend/src/components/NewRunForm.test.tsx
git commit -m "feat(frontend): add driver selector to NewRunForm, pre-fill from project defaults

Driver select was missing entirely despite the backend supporting
per-run driver selection since the earlier deviation-fixes round.
Both driver and playbook path now pre-fill from the selected
project's default_driver/default_playbook_path, still freely
editable before submit."
```

---

## Final verification

- [ ] Run: `uv run pytest -q && cd frontend && npx vitest run && npx tsc --noEmit`
  Expected: all backend and frontend tests pass, no type errors.
- [ ] Confirm the settings round-trip works end-to-end: `PATCH` a project's
  settings, then `POST /api/runs` for that project without an explicit
  `token_budget`/`driver`/`playbook_path` override, and confirm the created
  run reflects the project's defaults — covered by Task 2's
  `test_create_run_applies_project_default_token_budget`, plus
  `RunOut.driver`/`playbook_ref` already existed and are unaffected by this
  plan.
