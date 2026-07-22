# M4b — Portfolio Home + Pack Viewer Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the dashboard surface M4's own exit criterion (b) requires — a portfolio home showing attention-ranked health across every registered project — plus the pack-viewer UI the M4 roadmap calls for, consuming the pack/lifecycle backend M4a shipped (pack loader, project pause/archive/activate, gate overrides, pack-version pinning) that currently has zero UI surface.

**Architecture:** Two small new backend routers (`/api/portfolio`, a single-endpoint rollup; `/api/packs`, reading `pack.toml` files off disk on demand via the existing `load_pack`, no new persistence) plus two small additive fixes to the existing `runs.py`/`projects.py` routers. The rollup deliberately avoids the N+1-across-full-history pattern already present in `metrics.py`'s per-project endpoint: it fetches all projects and all runs in two queries total, then only issues one `list_gates_for_run` per *currently active* run (bounded by how many runs are in flight, not by total history) to compute pending-gate counts and a rework-rate approximation. Frontend: two new pages (`PortfolioHomePage`, `PacksPage`) plus lifecycle-action wiring (pause/archive/activate) added to both the new portfolio cards and the existing `ProjectsPage`, following this codebase's established patterns exactly — Vitest+RTL with hand-rolled `fetch` mocking (no MSW), TanStack Query, the `ApiResponse`/`Paging` envelope, `data-testid` attributes for any layout-bearing element.

**Tech Stack:** Same as M0-M4a backend (Python 3.12+, FastAPI, Pydantic v2, pytest+pytest-asyncio, ruff) and M1b-M3b frontend (React 18, Vite 5, TypeScript 5, Tailwind CSS 3, React Router 6, TanStack Query 5, Vitest+RTL). No new dependencies on either side.

## Global Constraints

- **The attention-ranking formula is a documented, deliberately simple heuristic, not a prediction model.** Design doc §11 names five signals for a portfolio card (active runs+phase, pending gates/human tasks, last-run outcome, rework-rate trend, budget burn) but does not specify a scoring formula. This plan defines one explicit, testable formula (Task 2) and documents it as a starting point — matching this project's established pattern of documented substitutions for underspecified design-doc asks (KGService's stdlib-`ast` substitution, keyword-overlap memory retrieval). Do not attempt to build a "smarter" ranking; a wrong precise number is worse than a right simple one here.
- **`rework_rate` in the portfolio rollup reflects only each project's currently-active runs' gates, not full project history.** This is a deliberate scope limitation to keep the rollup query-efficient (see Architecture) — computing a true historical rework rate would require the same expensive per-run event/session/artifact fetch `metrics.py`'s existing per-project endpoint already does, multiplied across every project, which is exactly the N+1 anti-pattern this task avoids. A project with zero active runs gets `rework_rate: null` in the response, not a stale historical number silently mislabeled as current.
- **The pack-viewer reads `pack.toml` files from disk on every request — it does not read or write the dormant `Pack` ORM table.** `src/foundry/store/models.py`'s `Pack` model has existed unused since M0 and nothing populates it; wiring it up would require a new import/seeding step this plan doesn't need. Matches the existing pattern (`load_pack`/`resolve_pack_version` already read `pack.toml` on demand at run-creation time) — extending that same pattern to a read endpoint is lower-risk than introducing new persistence.
- **`My queue` (cross-run gate/human-task inbox), `chat-to-role`, cross-project fair scheduling, and pack/project "settings" (gate-policy defaults, driver config, budget caps) are explicitly out of scope.** Design doc §11 lists `My queue` as a separate, not-yet-built view; this plan's portfolio card shows pending-gate *counts* per project (needed for the attention score) but does not build the inbox itself. `chat-to-role` remains blocked on the undesigned `notes_addressed` chat contract, unchanged since M1a's original deferral. Cross-project fair scheduling is a scheduler-internals concern already covered by M2a's `GlobalDispatchLimiter`, unrelated to this UI-focused milestone.
- All new backend files live under `src/foundry/api/routes/` or `src/foundry/packs/`; all new frontend files live under `frontend/src/pages/`, `frontend/src/components/`, or `frontend/src/api/`.

---

### Task 1: Expose `gate_overrides`, `token_budget`, `tokens_used` on `RunOut`

**Files:**
- Modify: `src/foundry/api/routes/runs.py`
- Test: `tests/api/test_runs.py` (extend)

**Interfaces:**
- Produces: `RunOut` gains `gate_overrides: dict[str, str]`, `token_budget: int`, `tokens_used: int` fields, populated in `_to_run_out` from `Run.gate_overrides_json`/`Run.token_budget`/`Run.tokens_used` (all three columns already exist on the `Run` model — `src/foundry/store/models.py:60-68` — this task only extends the API response shape, no store/model changes). These three fields are stored today but never returned through any API response; the portfolio rollup (Task 2) needs `token_budget`/`tokens_used` to compute budget-burn, and a run-detail view needs `gate_overrides` to show which gates were pre-decided.

- [ ] **Step 1: Write the failing test**

Read `src/foundry/api/routes/runs.py`'s current `RunOut` class and `_to_run_out` function in full first (both already quoted in this plan below, but confirm no drift before editing).

```python
# append to tests/api/test_runs.py
@pytest.mark.asyncio
async def test_run_out_exposes_gate_overrides_and_token_fields(api_client):
    client, store, _scheduler = api_client
    project = await store.create_project("demo", ".")
    resp = await client.post(
        "/api/runs",
        json={
            "project_id": project.id,
            "playbook_path": "packs/default/playbooks/bugfix.toml",
            "gate_overrides": {"diagnose": "approved"},
        },
    )
    assert resp.status_code == 201
    body = resp.json()["data"]
    assert body["gate_overrides"] == {"diagnose": "approved"}
    assert body["token_budget"] == 0
    assert body["tokens_used"] == 0
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/api/test_runs.py::test_run_out_exposes_gate_overrides_and_token_fields -v`
Expected: FAIL — `KeyError: 'gate_overrides'`

- [ ] **Step 3: Extend `RunOut` and `_to_run_out`**

In `src/foundry/api/routes/runs.py`:

```python
class RunOut(BaseModel):
    id: str
    project_id: str
    playbook_ref: str
    title: str
    status: str
    created_at: str
    pack_version_pin: str
    gate_overrides: dict[str, str]
    token_budget: int
    tokens_used: int
```

```python
def _to_run_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id,
        project_id=r.project_id,
        playbook_ref=r.playbook_ref,
        title=r.title,
        status=r.status,
        created_at=r.created_at.isoformat(),
        pack_version_pin=r.pack_version_pin,
        gate_overrides=r.gate_overrides_json,
        token_budget=r.token_budget,
        tokens_used=r.tokens_used,
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions (every existing `RunOut`-shape assertion checks specific keys, not exact-match dict equality, per the existing test file's style — confirm this holds by reading the file; if any test asserts exact dict equality against `RunOut`'s shape, it needs updating to include the three new fields)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/routes/runs.py tests/api/test_runs.py
git commit -m "feat(api): expose gate_overrides, token_budget, tokens_used on RunOut"
```

---

### Task 2: Portfolio rollup endpoint — `GET /api/portfolio`

**Files:**
- Create: `src/foundry/api/routes/portfolio.py`
- Modify: `src/foundry/api/app.py`
- Test: `tests/api/test_portfolio.py`

**Interfaces:**
- Consumes: `Store.list_projects()`, `Store.list_runs(project_id=None, status=None)` (both already unfiltered-capable, confirmed by reading `src/foundry/store/store.py`), `Store.list_gates_for_run(run_id)`.
- Produces: `ProjectHealthOut` (Pydantic): `project_id: str`, `name: str`, `status: str`, `active_run_count: int`, `pending_gate_count: int`, `last_run_status: str | None`, `last_run_at: str | None`, `rework_rate: float | None`, `budget_burn_ratio: float | None`, `attention_score: float`. `GET /api/portfolio` returns `ApiResponse[list[ProjectHealthOut]]` sorted by `attention_score` descending, using `Paging.unpaginated(len(result))` (matching the convention `Paging.unpaginated` already uses for non-offset/limit list responses like `/api/runs/{id}/artifacts`).

- [ ] **Step 1: Write the failing tests**

Read `src/foundry/api/schemas.py` (for `ApiResponse`/`Paging.unpaginated`) and `src/foundry/api/routes/projects.py` (for `_get_store` — reused, already imported this way by `runs.py`) in full first.

```python
# tests/api/test_portfolio.py
import pytest

from foundry.store.models import WorkUnit


@pytest.mark.asyncio
async def test_portfolio_empty_when_no_projects(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_portfolio_ranks_project_with_pending_gates_and_rejections_higher(api_client):
    client, store, _scheduler = api_client

    quiet = await store.create_project("quiet", ".")
    busy = await store.create_project("busy", ".")

    # "quiet" has one closed run, nothing pending -> low attention.
    quiet_run = await store.create_run(quiet.id, "p.toml", "quiet-run")
    await store.update_run(quiet_run.id, status="closed")

    # "busy" has one active run with two pending gates and one rejected gate
    # -> should rank above "quiet". There is no create_unit helper — work
    # units are created in batches via create_work_units(list[WorkUnit]).
    busy_run = await store.create_run(busy.id, "p.toml", "busy-run")
    unit1, unit2, unit3 = await store.create_work_units(
        [
            WorkUnit(run_id=busy_run.id, step_id="step1", type="task", status="open"),
            WorkUnit(run_id=busy_run.id, step_id="step2", type="task", status="open"),
            WorkUnit(run_id=busy_run.id, step_id="step3", type="task", status="open"),
        ]
    )
    await store.create_gate(work_unit_id=unit1.id, gate_type="human", decision="pending")
    await store.create_gate(work_unit_id=unit2.id, gate_type="human", decision="pending")
    await store.create_gate(work_unit_id=unit3.id, gate_type="human", decision="rejected")

    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert len(body) == 2

    by_name = {row["name"]: row for row in body}
    assert by_name["busy"]["active_run_count"] == 1
    assert by_name["busy"]["pending_gate_count"] == 2
    assert by_name["busy"]["rework_rate"] == pytest.approx(1 / 3)
    assert by_name["quiet"]["active_run_count"] == 0
    assert by_name["quiet"]["pending_gate_count"] == 0
    assert by_name["quiet"]["rework_rate"] is None
    assert by_name["quiet"]["last_run_status"] == "closed"

    # Sorted descending by attention_score: "busy" (pending gates + rejections) first.
    assert body[0]["name"] == "busy"
    assert body[0]["attention_score"] > body[1]["attention_score"]


@pytest.mark.asyncio
async def test_portfolio_project_with_no_runs_has_zero_attention(api_client):
    client, store, _scheduler = api_client
    await store.create_project("untouched", ".")

    resp = await client.get("/api/portfolio")
    body = resp.json()["data"]
    assert body[0]["last_run_status"] is None
    assert body[0]["last_run_at"] is None
    assert body[0]["attention_score"] == 0.0
```

`create_gate(work_unit_id=..., gate_type=..., decision=...)` and `create_work_units(list[WorkUnit])` are both confirmed against the current `src/foundry/store/store.py`/`src/foundry/store/models.py` as of this plan being written — no other Store method creates a work unit singly.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_portfolio.py -v`
Expected: FAIL — `404 Not Found` (no route registered yet)

- [ ] **Step 3: Write `src/foundry/api/routes/portfolio.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging

router = APIRouter()

_TERMINAL_RUN_STATUSES = {"closed", "cancelled", "failed"}
_STALENESS_CAP_HOURS = 168.0  # one week; staleness contributes at most this much


class ProjectHealthOut(BaseModel):
    project_id: str
    name: str
    status: str
    active_run_count: int
    pending_gate_count: int
    last_run_status: str | None
    last_run_at: str | None
    rework_rate: float | None
    budget_burn_ratio: float | None
    attention_score: float


@router.get("/portfolio")
async def get_portfolio(request: Request) -> ApiResponse[list[ProjectHealthOut]]:
    store = _get_store(request)

    projects = await store.list_projects()
    all_runs = await store.list_runs()

    runs_by_project: dict[str, list] = {}
    for run in all_runs:
        runs_by_project.setdefault(run.project_id, []).append(run)

    now = _now()
    rows: list[ProjectHealthOut] = []
    for project in projects:
        project_runs = runs_by_project.get(project.id, [])
        active_runs = [r for r in project_runs if r.status not in _TERMINAL_RUN_STATUSES]

        pending_gate_count = 0
        decided_count = 0
        rejected_count = 0
        for run in active_runs:
            gates = await store.list_gates_for_run(run.id)
            for gate in gates:
                if gate.decision == "pending":
                    pending_gate_count += 1
                elif gate.decision == "approved":
                    decided_count += 1
                elif gate.decision == "rejected":
                    decided_count += 1
                    rejected_count += 1

        # rejected / total-gates-seen-among-active-runs (including still-pending
        # ones), not rejected/decided-only - a project that's mostly pending with
        # one rejection should read as a fraction of everything currently open,
        # not spike to 100% just because nothing else has been decided yet.
        total_gate_count = pending_gate_count + decided_count
        rework_rate = (rejected_count / total_gate_count) if total_gate_count else None

        total_budget = sum(r.token_budget for r in project_runs)
        total_used = sum(r.tokens_used for r in project_runs)
        budget_burn_ratio = (total_used / total_budget) if total_budget else None

        last_run = max(project_runs, key=lambda r: r.created_at) if project_runs else None
        last_run_status = last_run.status if last_run else None
        last_run_at = last_run.created_at.isoformat() if last_run else None

        if last_run is None:
            attention_score = 0.0
        else:
            staleness_hours = min((now - last_run.created_at).total_seconds() / 3600, _STALENESS_CAP_HOURS)
            attention_score = (
                active_run_count * 5.0
                + pending_gate_count * 10.0
                + (rework_rate or 0.0) * 20.0
                + (budget_burn_ratio or 0.0) * 15.0
                + staleness_hours * 0.5
            )

        rows.append(
            ProjectHealthOut(
                project_id=project.id,
                name=project.name,
                status=project.status,
                active_run_count=len(active_runs),
                pending_gate_count=pending_gate_count,
                last_run_status=last_run_status,
                last_run_at=last_run_at,
                rework_rate=rework_rate,
                budget_burn_ratio=budget_burn_ratio,
                attention_score=attention_score,
            )
        )

    rows.sort(key=lambda r: r.attention_score, reverse=True)
    return ApiResponse[list[ProjectHealthOut]](data=rows, paging=Paging.unpaginated(len(rows)))


def _now():
    from foundry.store.models import utcnow

    return utcnow()
```

(The `_now()` wrapper exists only so the test file can, if needed later, monkeypatch it — but no test in this task does that; write it as a plain top-level `from foundry.store.models import utcnow` import instead if that's simpler and matches this file's existing import style better. Read `src/foundry/store/models.py` to confirm `utcnow` is importable this way — it already is, per `store.py`'s own usage.)

- [ ] **Step 4: Register the router in `src/foundry/api/app.py`**

```python
from foundry.api.routes.portfolio import router as portfolio_router
```

```python
    app.include_router(portfolio_router, prefix="/api")
```

(Add both in alphabetical position matching this file's existing import/registration order.)

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_portfolio.py -v`
Expected: PASS (3 tests)

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 7: Commit**

```bash
git add src/foundry/api/routes/portfolio.py src/foundry/api/app.py tests/api/test_portfolio.py
git commit -m "feat(api): GET /api/portfolio - attention-ranked project health rollup"
```

---

### Task 3: Pack-viewer read endpoints — `GET /api/packs`, `GET /api/packs/{pack_id}`

**Files:**
- Modify: `src/foundry/packs/loader.py` (add `list_packs`)
- Create: `src/foundry/api/routes/packs.py`
- Modify: `src/foundry/api/app.py`
- Test: `tests/packs/test_loader.py` (extend), `tests/api/test_packs_route.py`

**Interfaces:**
- Produces: `list_packs(packs_root: str) -> list[PackManifest]` (`src/foundry/packs/loader.py`) — scans immediate subdirectories of `packs_root`, calls `load_pack` on each that contains a `pack.toml`, silently skips (does not raise) any subdirectory whose `pack.toml` fails to load (a single broken pack must not 500 the whole list). `GET /api/packs -> ApiResponse[list[PackManifest]]` and `GET /api/packs/{pack_id} -> ApiResponse[PackManifest]` (404 via `NotFoundError` if no scanned pack's `manifest.id` matches `pack_id`) — both reusing `foundry.packs.schema.PackManifest`/`RoleSpec` directly as response models, no new response types. The packs root is hardcoded to the literal string `"packs"` (relative to the process's working directory) matching how `foundry.cli`'s `run`/`_run` already resolve playbook paths relative to CWD — no new configuration surface.

- [ ] **Step 1: Write the failing test for `list_packs`**

Read `src/foundry/packs/loader.py`'s current `load_pack`/`PackLoadError` in full first (already known from M4a, but confirm no drift).

```python
# append to tests/packs/test_loader.py
def test_list_packs_scans_subdirectories_and_skips_broken_ones(tmp_path):
    good_dir = tmp_path / "good_pack"
    good_dir.mkdir()
    (good_dir / "pack.toml").write_text(
        'playbooks = []\n\n[pack]\nid = "good"\nversion = "1.0.0"\n'
    )

    broken_dir = tmp_path / "broken_pack"
    broken_dir.mkdir()
    (broken_dir / "pack.toml").write_text("not valid toml [[[")

    not_a_pack_dir = tmp_path / "not_a_pack"
    not_a_pack_dir.mkdir()  # no pack.toml at all

    manifests = list_packs(str(tmp_path))
    assert [m.id for m in manifests] == ["good"]
```

Add `list_packs` to the existing `from foundry.packs.loader import ...` import line at the top of the test file.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/packs/test_loader.py::test_list_packs_scans_subdirectories_and_skips_broken_ones -v`
Expected: FAIL — `ImportError: cannot import name 'list_packs'`

- [ ] **Step 3: Add `list_packs` to `src/foundry/packs/loader.py`**

```python
def list_packs(packs_root: str) -> list[PackManifest]:
    root = Path(packs_root)
    if not root.is_dir():
        return []

    manifests: list[PackManifest] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "pack.toml").exists():
            continue
        try:
            manifests.append(load_pack(str(entry)))
        except PackLoadError:
            continue
    return manifests
```

(`Path` is already imported in this file per M4a's `load_pack` implementation — confirm before adding a duplicate import.)

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/packs/test_loader.py -v`
Expected: PASS (all tests, including the new one)

- [ ] **Step 5: Write the failing route tests**

```python
# tests/api/test_packs_route.py
import pytest


@pytest.mark.asyncio
async def test_list_packs_returns_the_shipped_default_pack(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs")
    assert resp.status_code == 200
    body = resp.json()["data"]
    ids = [p["id"] for p in body]
    assert "default" in ids


@pytest.mark.asyncio
async def test_get_pack_by_id_returns_full_manifest(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs/default")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["id"] == "default"
    role_ids = {r["id"] for r in body["roles"]}
    assert "developer" in role_ids
    assert "playbooks/sdlc_story.toml" in body["playbooks"]
    assert "playbooks/bugfix.toml" in body["playbooks"]


@pytest.mark.asyncio
async def test_get_pack_by_unknown_id_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs/does-not-exist")
    assert resp.status_code == 404
```

These tests rely on `packs/default/` (shipped in M4a, at the repo root) being discoverable relative to the test runner's working directory — confirm `uv run pytest` runs from the repo root (it does, matching every other test in this suite that references `packs/default/playbooks/...` by a repo-root-relative path, e.g. `tests/api/test_runs.py`'s existing pack-pin test).

- [ ] **Step 6: Run the route tests to verify they fail**

Run: `uv run pytest tests/api/test_packs_route.py -v`
Expected: FAIL — `404 Not Found` (no route registered yet)

- [ ] **Step 7: Write `src/foundry/api/routes/packs.py`**

```python
from __future__ import annotations

from fastapi import APIRouter, Request

from foundry.api.errors import NotFoundError
from foundry.api.routes.projects import _get_store  # noqa: F401  (kept for handler-signature parity; unused here)
from foundry.api.schemas import ApiResponse, Paging
from foundry.packs.loader import list_packs
from foundry.packs.schema import PackManifest

router = APIRouter()

PACKS_ROOT = "packs"


@router.get("/packs")
async def get_packs() -> ApiResponse[list[PackManifest]]:
    manifests = list_packs(PACKS_ROOT)
    return ApiResponse[list[PackManifest]](data=manifests, paging=Paging.unpaginated(len(manifests)))


@router.get("/packs/{pack_id}")
async def get_pack(pack_id: str) -> ApiResponse[PackManifest]:
    manifests = list_packs(PACKS_ROOT)
    for manifest in manifests:
        if manifest.id == pack_id:
            return ApiResponse[PackManifest](data=manifest, paging=Paging.none())
    raise NotFoundError(f"Pack {pack_id!r} not found")
```

(The `_get_store` import is a placeholder shown only to flag that this router does NOT need the store at all — packs are read from disk, not the database. Delete that import line entirely rather than keeping an unused one; it's shown here only to make explicit, in the plan, that omitting store access is intentional, not an oversight. Do not add a `# noqa` comment for an import you're not actually including.)

- [ ] **Step 8: Register the router in `src/foundry/api/app.py`**

```python
from foundry.api.routes.packs import router as packs_router
```

```python
    app.include_router(packs_router, prefix="/api")
```

- [ ] **Step 9: Run the route tests to verify they pass**

Run: `uv run pytest tests/api/test_packs_route.py -v`
Expected: PASS (3 tests)

- [ ] **Step 10: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS, no regressions

- [ ] **Step 11: Commit**

```bash
git add src/foundry/packs/loader.py src/foundry/api/routes/packs.py src/foundry/api/app.py \
        tests/packs/test_loader.py tests/api/test_packs_route.py
git commit -m "feat(api): GET /api/packs and /api/packs/{id} - on-demand pack manifest read endpoints"
```

---

### Task 4: Frontend types + API clients for portfolio, packs, and project lifecycle

**Files:**
- Modify: `frontend/src/api/types.ts`
- Modify: `frontend/src/api/projects.ts`
- Create: `frontend/src/api/portfolio.ts`
- Create: `frontend/src/api/packs.ts`
- Test: `frontend/src/api/projects.test.ts` (extend), `frontend/src/api/portfolio.test.ts`, `frontend/src/api/packs.test.ts`

**Interfaces:**
- Consumes: `apiFetch<T>` from `frontend/src/api/client.ts` (existing, unmodified).
- Produces: `Project` type gains `status: string`. `Run` type gains `pack_version_pin: string`, `gate_overrides: Record<string, string>`, `token_budget: number`, `tokens_used: number`. New types: `ProjectHealth` (mirrors backend `ProjectHealthOut`), `RoleSpec { id: string; model: string }`, `PackManifest { id: string; version: string; roles: RoleSpec[]; playbooks: string[] }`. New functions: `pauseProject(id): Promise<Project>`, `archiveProject(id): Promise<Project>`, `activateProject(id): Promise<Project>` (in `projects.ts`), `getPortfolio(): Promise<ProjectHealth[]>` (in `portfolio.ts`), `listPacks(): Promise<PackManifest[]>`, `getPack(id): Promise<PackManifest>` (in `packs.ts`).

- [ ] **Step 1: Read the current `frontend/src/api/types.ts`, `frontend/src/api/projects.ts`, and one existing API client test file in full**

Confirm the exact current `Project`/`Run` interfaces and `projects.ts`'s existing `listProjects`/`createProject` implementations, and copy the exact `fetch`-mocking test style from an existing `*.test.ts` file (e.g. `frontend/src/api/runs.test.ts` or `frontend/src/api/metrics.test.ts`) before writing the new tests below — match its mock-response shape (`{ ok, status, json: async () => ({data, paging}) }`) exactly.

- [ ] **Step 2: Write the failing tests**

```typescript
// append to frontend/src/api/projects.test.ts
describe("pauseProject / archiveProject / activateProject", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("pauseProject posts to the pause endpoint and returns the updated project", async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({
        data: { id: "p1", name: "demo", path: ".", kg_status: "none", status: "paused", created_at: "2026-01-01T00:00:00Z" },
        paging: {},
      }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await pauseProject("p1");

    expect(mockFetch).toHaveBeenCalledWith("/api/projects/p1/pause", expect.objectContaining({ method: "POST" }));
    expect(result.status).toBe("paused");
  });
});
```

```typescript
// frontend/src/api/portfolio.test.ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { getPortfolio } from "./portfolio";

describe("getPortfolio", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("fetches /api/portfolio and returns the data array", async () => {
    const row = {
      project_id: "p1", name: "demo", status: "active",
      active_run_count: 1, pending_gate_count: 2,
      last_run_status: "active", last_run_at: "2026-01-01T00:00:00Z",
      rework_rate: 0.5, budget_burn_ratio: null, attention_score: 25.0,
    };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [row], paging: {} }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await getPortfolio();

    expect(mockFetch).toHaveBeenCalledWith("/api/portfolio", expect.anything());
    expect(result).toEqual([row]);
  });
});
```

```typescript
// frontend/src/api/packs.test.ts
import { describe, it, expect, vi, afterEach } from "vitest";
import { listPacks, getPack } from "./packs";

describe("listPacks / getPack", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("listPacks fetches /api/packs", async () => {
    const pack = { id: "default", version: "0.1.0", roles: [{ id: "developer", model: "fake" }], playbooks: ["playbooks/sdlc_story.toml"] };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: [pack], paging: {} }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await listPacks();

    expect(mockFetch).toHaveBeenCalledWith("/api/packs", expect.anything());
    expect(result).toEqual([pack]);
  });

  it("getPack fetches /api/packs/{id}", async () => {
    const pack = { id: "default", version: "0.1.0", roles: [], playbooks: [] };
    const mockFetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: async () => ({ data: pack, paging: {} }),
    });
    vi.stubGlobal("fetch", mockFetch);

    const result = await getPack("default");

    expect(mockFetch).toHaveBeenCalledWith("/api/packs/default", expect.anything());
    expect(result).toEqual(pack);
  });
});
```

(Match every test's exact imports — `describe`/`it`/`expect`/`vi`/`afterEach` from `"vitest"` — to whichever import style the existing test files in this directory actually use; some projects import `vi` differently or rely on globals. Read `frontend/src/api/runs.test.ts` first and mirror it exactly.)

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/projects.test.ts src/api/portfolio.test.ts src/api/packs.test.ts`
Expected: FAIL — `portfolio.ts`/`packs.ts` don't exist yet; `pauseProject` is not exported from `projects.ts`

- [ ] **Step 4: Extend `frontend/src/api/types.ts`**

Add `status: string;` to the existing `Project` interface. Add `pack_version_pin: string; gate_overrides: Record<string, string>; token_budget: number; tokens_used: number;` to the existing `Run` interface. Append:

```typescript
export interface RoleSpec {
  id: string;
  model: string;
}

export interface PackManifest {
  id: string;
  version: string;
  roles: RoleSpec[];
  playbooks: string[];
}

export interface ProjectHealth {
  project_id: string;
  name: string;
  status: string;
  active_run_count: number;
  pending_gate_count: number;
  last_run_status: string | null;
  last_run_at: string | null;
  rework_rate: number | null;
  budget_burn_ratio: number | null;
  attention_score: number;
}
```

- [ ] **Step 5: Extend `frontend/src/api/projects.ts`**

```typescript
export async function pauseProject(id: string): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}/pause`, { method: "POST" });
  return res.data;
}

export async function archiveProject(id: string): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}/archive`, { method: "POST" });
  return res.data;
}

export async function activateProject(id: string): Promise<Project> {
  const res = await apiFetch<Project>(`/api/projects/${id}/activate`, { method: "POST" });
  return res.data;
}
```

(Match the exact `apiFetch` call signature already used by `createProject`/other mutating calls in this file — read it first; the shape above assumes `apiFetch<T>(path, init)` returns `ApiResponse<T>` and callers unwrap `.data`, consistent with the rest of this file.)

- [ ] **Step 6: Write `frontend/src/api/portfolio.ts`**

```typescript
import { apiFetch } from "./client";
import type { ProjectHealth } from "./types";

export async function getPortfolio(): Promise<ProjectHealth[]> {
  const res = await apiFetch<ProjectHealth[]>("/api/portfolio");
  return res.data;
}
```

- [ ] **Step 7: Write `frontend/src/api/packs.ts`**

```typescript
import { apiFetch } from "./client";
import type { PackManifest } from "./types";

export async function listPacks(): Promise<PackManifest[]> {
  const res = await apiFetch<PackManifest[]>("/api/packs");
  return res.data;
}

export async function getPack(id: string): Promise<PackManifest> {
  const res = await apiFetch<PackManifest>(`/api/packs/${id}`);
  return res.data;
}
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/api/projects.test.ts src/api/portfolio.test.ts src/api/packs.test.ts`
Expected: PASS

- [ ] **Step 9: Run the full frontend suite and typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS, no regressions, no type errors

- [ ] **Step 10: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/projects.ts frontend/src/api/portfolio.ts frontend/src/api/packs.ts \
        frontend/src/api/projects.test.ts frontend/src/api/portfolio.test.ts frontend/src/api/packs.test.ts
git commit -m "feat(frontend): types + API clients for portfolio rollup, packs, and project lifecycle actions"
```

---

### Task 5: `PortfolioHomePage`

**Files:**
- Create: `frontend/src/pages/PortfolioHomePage.tsx`
- Test: `frontend/src/pages/PortfolioHomePage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `getPortfolio` (Task 4), `pauseProject`/`archiveProject`/`activateProject` (Task 4), `ProjectHealth` type (Task 4).
- Produces: `PortfolioHomePage` — one card per project (name, status pill, active run count, pending gate count, last-run outcome, rework-rate %, budget-burn %, a link to `/runs?project_id={id}`), rendered in the `attention_score`-descending order the backend already returns, with pause/archive/activate buttons that call the respective mutation and invalidate the `["portfolio"]` query on success. Mounted at `/` (replacing the current unconditional redirect to `/runs`).

- [ ] **Step 1: Read `frontend/src/pages/ProjectsPage.tsx` and `frontend/src/pages/RunsHomePage.tsx` in full, and `frontend/src/App.tsx`'s current routing block**

Confirm the exact `useQuery`/`useMutation` (TanStack Query) patterns, the exact current `/` redirect implementation, and the nav-bar markup structure, before writing new code that must match them.

- [ ] **Step 2: Write the failing test**

```typescript
// frontend/src/pages/PortfolioHomePage.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders } from "../test-utils"; // adjust to this project's actual helper location/name
import PortfolioHomePage from "./PortfolioHomePage";

describe("PortfolioHomePage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders project cards sorted by attention score with health signals", async () => {
    const rows = [
      {
        project_id: "p2", name: "busy", status: "active",
        active_run_count: 1, pending_gate_count: 2,
        last_run_status: "active", last_run_at: "2026-07-22T00:00:00Z",
        rework_rate: 0.5, budget_burn_ratio: 0.2, attention_score: 30.0,
      },
      {
        project_id: "p1", name: "quiet", status: "active",
        active_run_count: 0, pending_gate_count: 0,
        last_run_status: "closed", last_run_at: "2026-07-01T00:00:00Z",
        rework_rate: null, budget_burn_ratio: null, attention_score: 1.0,
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: rows, paging: {} }) })
    );

    renderWithProviders(<PortfolioHomePage />);

    await waitFor(() => expect(screen.getByText("busy")).toBeInTheDocument());
    const cards = screen.getAllByTestId(/^portfolio-card-/);
    expect(cards[0]).toHaveAttribute("data-testid", "portfolio-card-p2");
    expect(cards[1]).toHaveAttribute("data-testid", "portfolio-card-p1");
    expect(screen.getByText(/2/)).toBeInTheDocument(); // pending gate count somewhere on "busy"'s card
  });

  it("pausing a project calls the pause endpoint", async () => {
    const rows = [
      {
        project_id: "p1", name: "demo", status: "active",
        active_run_count: 0, pending_gate_count: 0,
        last_run_status: null, last_run_at: null,
        rework_rate: null, budget_burn_ratio: null, attention_score: 0.0,
      },
    ];
    const mockFetch = vi.fn()
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => ({ data: rows, paging: {} }) })
      .mockResolvedValueOnce({
        ok: true, status: 200,
        json: async () => ({ data: { ...rows[0], status: "paused" }, paging: {} }),
      })
      .mockResolvedValueOnce({
        ok: true, status: 200,
        json: async () => ({ data: [{ ...rows[0], status: "paused" }], paging: {} }),
      });
    vi.stubGlobal("fetch", mockFetch);

    renderWithProviders(<PortfolioHomePage />);
    await waitFor(() => expect(screen.getByText("demo")).toBeInTheDocument());

    await userEvent.click(screen.getByRole("button", { name: /pause/i }));

    await waitFor(() =>
      expect(mockFetch).toHaveBeenCalledWith("/api/projects/p1/pause", expect.objectContaining({ method: "POST" }))
    );
  });
});
```

Before finalizing, read whichever existing frontend test file has the most similar shape (`ProjectsPage.test.tsx`, since it also exercises a create-then-refetch mutation flow) to confirm the exact provider-wrapping helper name/import path (`renderWithClient` vs `renderWithProviders` — this plan's earlier research saw both names used informally; use whichever the codebase's actual helper is called) and match the `mockResolvedValueOnce` chaining style exactly.

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/PortfolioHomePage.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 4: Write `frontend/src/pages/PortfolioHomePage.tsx`**

```tsx
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { getPortfolio } from "../api/portfolio";
import { pauseProject, archiveProject, activateProject } from "../api/projects";
import type { ProjectHealth } from "../api/types";

function formatPercent(value: number | null): string {
  return value === null ? "—" : `${Math.round(value * 100)}%`;
}

function ProjectCard({ project }: { project: ProjectHealth }) {
  const queryClient = useQueryClient();

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ["portfolio"] });
  const pauseMutation = useMutation({ mutationFn: () => pauseProject(project.project_id), onSuccess: invalidate });
  const archiveMutation = useMutation({ mutationFn: () => archiveProject(project.project_id), onSuccess: invalidate });
  const activateMutation = useMutation({ mutationFn: () => activateProject(project.project_id), onSuccess: invalidate });

  return (
    <div data-testid={`portfolio-card-${project.project_id}`} className="border rounded p-4 space-y-2">
      <div className="flex items-center justify-between">
        <Link to={`/runs?project_id=${project.project_id}`} className="font-semibold">
          {project.name}
        </Link>
        <span className="text-xs uppercase">{project.status}</span>
      </div>
      <div className="text-sm space-y-1">
        <div>Active runs: {project.active_run_count}</div>
        <div>Pending gates: {project.pending_gate_count}</div>
        <div>Last run: {project.last_run_status ?? "none yet"}</div>
        <div>Rework rate: {formatPercent(project.rework_rate)}</div>
        <div>Budget burn: {formatPercent(project.budget_burn_ratio)}</div>
      </div>
      <div className="flex gap-2">
        {project.status !== "paused" && (
          <button onClick={() => pauseMutation.mutate()} disabled={pauseMutation.isPending}>
            Pause
          </button>
        )}
        {project.status !== "archived" && (
          <button onClick={() => archiveMutation.mutate()} disabled={archiveMutation.isPending}>
            Archive
          </button>
        )}
        {project.status !== "active" && (
          <button onClick={() => activateMutation.mutate()} disabled={activateMutation.isPending}>
            Activate
          </button>
        )}
      </div>
    </div>
  );
}

export default function PortfolioHomePage() {
  const { data: projects, isLoading } = useQuery({ queryKey: ["portfolio"], queryFn: getPortfolio });

  if (isLoading) return <div>Loading…</div>;

  return (
    <div className="grid gap-4">
      {(projects ?? []).map((project) => (
        <ProjectCard key={project.project_id} project={project} />
      ))}
    </div>
  );
}
```

(Match the exact `useQuery`/`useMutation` import path and call signature — `@tanstack/react-query` version-specific object-vs-positional-args API — to whatever `RunsHomePage.tsx`/`ProjectsPage.tsx` already use; this plan's snippet assumes the v5 object-argument form seen in M1b-M3b's own shipped pages.)

- [ ] **Step 5: Wire the route and nav link in `frontend/src/App.tsx`**

Replace the current unconditional `/` → `/runs` redirect with `<Route path="/" element={<PortfolioHomePage />} />`, and add a "Portfolio" nav link (as the first item, before "Projects") pointing to `/`.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/PortfolioHomePage.test.tsx`
Expected: PASS (2 tests)

- [ ] **Step 7: Run the full frontend suite and typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/PortfolioHomePage.tsx frontend/src/pages/PortfolioHomePage.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): portfolio home - attention-ranked project cards with lifecycle actions"
```

---

### Task 6: `PacksPage`

**Files:**
- Create: `frontend/src/pages/PacksPage.tsx`
- Test: `frontend/src/pages/PacksPage.test.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: `listPacks` (Task 4), `PackManifest`/`RoleSpec` types (Task 4).
- Produces: `PacksPage` — lists every pack (id, version), and for each pack, an expandable/inline view of its declared roles (id + model) and playbooks (file paths) — a "role/playbook viewer" per design doc §11's "Packs & settings" description. Mounted at `/packs`, with a nav link.

- [ ] **Step 1: Read `frontend/src/pages/KnowledgePage.tsx` in full**

It's this codebase's closest precedent for a page rendering a nested/structured read-only object (roles + playbooks per pack, analogous to KG nodes/edges) — match its component-composition and data-fetching style.

- [ ] **Step 2: Write the failing test**

```typescript
// frontend/src/pages/PacksPage.test.tsx
import { describe, it, expect, vi, afterEach } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders } from "../test-utils";
import PacksPage from "./PacksPage";

describe("PacksPage", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("lists packs and shows each pack's roles and playbooks", async () => {
    const packs = [
      {
        id: "default", version: "0.1.0",
        roles: [{ id: "developer", model: "fake" }, { id: "reviewer", model: "fake" }],
        playbooks: ["playbooks/sdlc_story.toml", "playbooks/bugfix.toml"],
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: packs, paging: {} }) })
    );

    renderWithProviders(<PacksPage />);

    await waitFor(() => expect(screen.getByText(/default/)).toBeInTheDocument());
    expect(screen.getByText(/0\.1\.0/)).toBeInTheDocument();
    expect(screen.getByText("developer")).toBeInTheDocument();
    expect(screen.getByText("reviewer")).toBeInTheDocument();
    expect(screen.getByText("playbooks/sdlc_story.toml")).toBeInTheDocument();
    expect(screen.getByText("playbooks/bugfix.toml")).toBeInTheDocument();
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/pages/PacksPage.test.tsx`
Expected: FAIL — module not found

- [ ] **Step 4: Write `frontend/src/pages/PacksPage.tsx`**

```tsx
import { useQuery } from "@tanstack/react-query";
import { listPacks } from "../api/packs";
import type { PackManifest } from "../api/types";

function PackCard({ pack }: { pack: PackManifest }) {
  return (
    <div className="border rounded p-4 space-y-2">
      <div className="flex items-baseline gap-2">
        <span className="font-semibold">{pack.id}</span>
        <span className="text-sm text-gray-500">{pack.version}</span>
      </div>
      <div>
        <div className="text-xs uppercase text-gray-500">Roles</div>
        <ul>
          {pack.roles.map((role) => (
            <li key={role.id}>
              {role.id} <span className="text-xs text-gray-500">({role.model})</span>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <div className="text-xs uppercase text-gray-500">Playbooks</div>
        <ul>
          {pack.playbooks.map((path) => (
            <li key={path}>{path}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function PacksPage() {
  const { data: packs, isLoading } = useQuery({ queryKey: ["packs"], queryFn: listPacks });

  if (isLoading) return <div>Loading…</div>;

  return (
    <div className="grid gap-4">
      {(packs ?? []).map((pack) => (
        <PackCard key={pack.id} pack={pack} />
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Wire the route and nav link in `frontend/src/App.tsx`**

Add `<Route path="/packs" element={<PacksPage />} />` and a "Packs" nav link, matching the existing nav-bar markup pattern.

- [ ] **Step 6: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/pages/PacksPage.test.tsx`
Expected: PASS

- [ ] **Step 7: Run the full frontend suite and typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/PacksPage.tsx frontend/src/pages/PacksPage.test.tsx frontend/src/App.tsx
git commit -m "feat(frontend): pack viewer - list packs, browse roles and playbooks per pack"
```

---

### Task 7: Surface project status + lifecycle actions on `ProjectsPage`; surface `pack_version_pin` on run detail

**Files:**
- Modify: `frontend/src/pages/ProjectsPage.tsx`
- Modify: `frontend/src/pages/RunDetailPage.tsx`
- Test: `frontend/src/pages/ProjectsPage.test.tsx` (extend), `frontend/src/pages/RunDetailPage.test.tsx` (extend)

**Interfaces:**
- Consumes: `Project.status` (Task 4), `pauseProject`/`archiveProject`/`activateProject` (Task 4), `Run.pack_version_pin` (Task 4).
- Produces: `ProjectsPage`'s existing project list gains a status pill and the same three lifecycle buttons `PortfolioHomePage` has, for consistency between the two views of the same data. `RunDetailPage` gains a small `pack_version_pin` label near the run title/header (e.g. "Pack: default@0.1.0" or "Pack: local").

- [ ] **Step 1: Read `frontend/src/pages/ProjectsPage.tsx` and `frontend/src/pages/RunDetailPage.tsx` in full**

Confirm the exact current list-rendering markup and header layout before adding to them — this task extends existing, already-tested components rather than replacing them, so match existing conventions precisely (e.g. reuse whatever list-item component/markup `ProjectsPage` already renders per project, don't introduce a second, differently-styled project card).

- [ ] **Step 2: Write the failing tests**

```typescript
// append to frontend/src/pages/ProjectsPage.test.tsx
it("shows a status pill and pause button for each project", async () => {
  const projects = [{ id: "p1", name: "demo", path: ".", kg_status: "none", status: "active", created_at: "2026-01-01T00:00:00Z" }];
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({ ok: true, status: 200, json: async () => ({ data: projects, paging: {} }) })
  );

  renderWithProviders(<ProjectsPage />);

  await waitFor(() => expect(screen.getByText("demo")).toBeInTheDocument());
  expect(screen.getByText("active")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: /pause/i })).toBeInTheDocument();
});
```

```typescript
// append to frontend/src/pages/RunDetailPage.test.tsx
it("shows the run's pack_version_pin", async () => {
  // Extend this test file's existing run-detail mock fixture with pack_version_pin: "default@0.1.0"
  // (read the existing mock run object in this file first and add the field to it, rather than
  // constructing a new fixture from scratch) and assert:
  await waitFor(() => expect(screen.getByText(/default@0\.1\.0/)).toBeInTheDocument());
});
```

Both of these are deliberately written as guidance-plus-partial-code rather than fully standalone blocks, because they must be spliced into each file's EXISTING mock-fetch setup (which already mocks multiple endpoints per test) rather than duplicating that setup — read each file's current test(s) first and extend the existing mock fixtures/assertions in place.

- [ ] **Step 3: Run the tests to verify they fail**

Run: `cd frontend && npx vitest run src/pages/ProjectsPage.test.tsx src/pages/RunDetailPage.test.tsx`
Expected: FAIL — status pill/pack pin text not found

- [ ] **Step 4: Add the status pill + lifecycle buttons to `ProjectsPage.tsx`**

Add a `<span>{project.status}</span>` and the same three conditionally-rendered pause/archive/activate buttons (with `useMutation` + `queryClient.invalidateQueries({queryKey: [...]})` matching whatever query key `ProjectsPage` already uses for its project list — read it first, do not invent a new key that diverges from the existing cache entry) into each project's existing list-item render, reusing the exact `pauseProject`/`archiveProject`/`activateProject` functions from Task 4 (do not duplicate the mutation logic written in `PortfolioHomePage.tsx` — if the two components' button logic is identical enough to extract, extract a small shared `ProjectLifecycleButtons` component into `frontend/src/components/`; if `ProjectsPage`'s list-item shape is different enough that a shared component would need awkward prop plumbing, duplicating the ~10 lines is acceptable per this project's established preference for straightforward code over premature abstraction — use judgment based on how similar the two render sites actually end up looking once written).

- [ ] **Step 5: Add the `pack_version_pin` label to `RunDetailPage.tsx`**

Add a small text element near the run's title/header showing `Pack: {run.pack_version_pin}`.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npx vitest run src/pages/ProjectsPage.test.tsx src/pages/RunDetailPage.test.tsx`
Expected: PASS

- [ ] **Step 7: Run the full frontend suite and typecheck**

Run: `cd frontend && npx vitest run && npx tsc --noEmit`
Expected: PASS, no regressions

- [ ] **Step 8: Commit**

```bash
git add frontend/src/pages/ProjectsPage.tsx frontend/src/pages/RunDetailPage.tsx \
        frontend/src/pages/ProjectsPage.test.tsx frontend/src/pages/RunDetailPage.test.tsx
git commit -m "feat(frontend): project status + lifecycle actions on ProjectsPage, pack_version_pin on run detail"
```

---

### Task 8: End-to-end proof — exit criterion (b)

**Files:**
- Test: `tests/api/test_portfolio_e2e.py`

**Interfaces:**
- Consumes: everything from Tasks 1-3 (backend). No new production code — this task proves M4's exit criterion (b): "five projects registered, three running concurrently, portfolio home showing attention-ranked health across all of them," at the API layer (the layer `PortfolioHomePage` directly renders from, per Task 5 — a passing test here is a direct guarantee about what the dashboard will show, not a separate claim).

- [ ] **Step 1: Write the end-to-end test**

```python
# tests/api/test_portfolio_e2e.py
import pytest

from foundry.store.models import WorkUnit


@pytest.mark.asyncio
async def test_five_projects_three_active_portfolio_shows_attention_ranked_health(api_client):
    client, store, _scheduler = api_client

    # Five projects registered.
    projects = [await store.create_project(f"project-{i}", ".") for i in range(5)]

    # Three running concurrently: each gets an active run with a mix of
    # pending/rejected gates so their attention scores differ meaningfully.
    # Work units are created in batches via create_work_units(list[WorkUnit]) -
    # there is no singular create_unit helper.
    active_specs = [
        (projects[0], 3, 0),  # 3 pending gates, 0 rejected -> highest pending-gate signal
        (projects[1], 1, 1),  # 1 pending, 1 rejected -> rework-rate signal
        (projects[2], 0, 0),  # active run, no gates yet -> lowest of the three active ones
    ]
    for project, pending_count, rejected_count in active_specs:
        run = await store.create_run(project.id, "p.toml", f"{project.name}-run")
        specs = [
            WorkUnit(run_id=run.id, step_id=f"pending-{i}", type="task", status="open") for i in range(pending_count)
        ] + [
            WorkUnit(run_id=run.id, step_id=f"rejected-{i}", type="task", status="open")
            for i in range(rejected_count)
        ]
        created = await store.create_work_units(specs) if specs else []
        pending_units, rejected_units = created[:pending_count], created[pending_count:]
        for unit in pending_units:
            await store.create_gate(work_unit_id=unit.id, gate_type="human", decision="pending")
        for unit in rejected_units:
            await store.create_gate(work_unit_id=unit.id, gate_type="human", decision="rejected")

    # Two projects with no active runs (one with a closed run, one untouched).
    closed_run = await store.create_run(projects[3].id, "p.toml", "old-run")
    await store.update_run(closed_run.id, status="closed")
    # projects[4] has zero runs at all.

    resp = await client.get("/api/portfolio")
    assert resp.status_code == 200
    body = resp.json()["data"]

    assert len(body) == 5

    by_name = {row["name"]: row for row in body}
    assert by_name["project-0"]["active_run_count"] == 1
    assert by_name["project-0"]["pending_gate_count"] == 3
    assert by_name["project-1"]["pending_gate_count"] == 1
    # rework_rate = rejected / total-gates-seen-among-active-runs (including
    # still-pending ones), not rejected/decided-only - confirmed by Task 2's
    # own review against its test fixture (2 pending + 1 rejected -> 1/3).
    # Here: 1 pending + 1 rejected -> 1/2.
    assert by_name["project-1"]["rework_rate"] == pytest.approx(0.5)
    assert by_name["project-2"]["active_run_count"] == 1
    assert by_name["project-2"]["pending_gate_count"] == 0
    assert by_name["project-3"]["active_run_count"] == 0
    assert by_name["project-3"]["last_run_status"] == "closed"
    assert by_name["project-4"]["active_run_count"] == 0
    assert by_name["project-4"]["last_run_status"] is None
    assert by_name["project-4"]["attention_score"] == 0.0

    # Attention-ranked: the three active projects with real signal (0, 1, 2)
    # must all outrank the two untouched/closed ones (3, 4), and within the
    # active set, more pending/rejected gates ranks higher.
    scores = {row["name"]: row["attention_score"] for row in body}
    assert scores["project-0"] > scores["project-2"]
    assert scores["project-1"] > scores["project-2"]
    assert scores["project-2"] > scores["project-3"]
    assert scores["project-2"] > scores["project-4"]

    # The response itself is already sorted descending by attention_score -
    # this is what PortfolioHomePage renders directly, with no client-side sort.
    returned_scores = [row["attention_score"] for row in body]
    assert returned_scores == sorted(returned_scores, reverse=True)
```

`create_work_units`/`create_gate`'s signatures are confirmed the same way as Task 2's test — no further verification needed before implementing.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/api/test_portfolio_e2e.py -v`
Expected: PASS. Treat any failure as a real signal to debug against Tasks 1-3's actual implementation (most likely the attention-score formula's relative ordering, or `create_unit`/`create_gate`'s exact signatures), not a reason to weaken the assertions.

- [ ] **Step 3: Run the full backend suite one more time**

Run: `uv run pytest -q`
Expected: PASS, full suite green

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_portfolio_e2e.py
git commit -m "test(api): end-to-end proof - five projects, three active, portfolio ranks attention correctly (M4 exit criterion b)"
```

---

## Out of scope for this plan (tracked, not forgotten)

- **`My queue`** (cross-run gate/human-task inbox with batch-approve) — a separate, not-yet-built dashboard view per design doc §11; the portfolio card's `pending_gate_count` signal needs roughly the same underlying data this page would, but building the inbox itself is a distinct milestone-sized piece of work.
- **Historical (not just currently-active-run) rework rate** — deliberately scoped out of the portfolio rollup to avoid the N+1-across-full-history pattern; `GET /api/metrics/{project_id}` (existing, unmodified) remains the source of truth for full historical metrics on a per-project drill-down.
- **`chat-to-role`, cross-project fair scheduling, pack/project "settings"** (gate-policy defaults, driver config, budget caps) — all explicitly named in design doc §11/§15 but out of scope per this plan's Global Constraints; no backend model exists for any of them today.
- **A richer "Project view"** (KG status, memory items, metrics trends, and settings all on one page, per design doc §11) beyond what this plan adds — today's `RunsHomePage?project_id=` plus the new status/lifecycle additions (Task 7) is the closest thing; a dedicated project-view page composing KG status + memory + metrics + settings in one place is future work.
- **`/api/settings`** — named in design doc §7 as a planned route, unrelated to this milestone's packs/portfolio scope.
