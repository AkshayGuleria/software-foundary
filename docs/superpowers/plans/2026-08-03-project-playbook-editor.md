# Project-Specific Playbook Editor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let each project accumulate its own library of playbook copies — clonable from any pack playbook, edited as raw TOML, validated with the platform's real schema + plan-first-lint rules on save — and fix the two playbook-path inputs that are currently too narrow to read.

**Architecture:** Pure filesystem storage (`project_playbooks/<project_id>/<slug>.toml`, no new DB table) mirroring how `packs/` already works; a new backend module is the single validation gate (reuses `load_playbook`/`lint_plan_first` unchanged); a thin CRUD API layer; a new raw-TOML editor page on the frontend plus a list section on the existing project-detail page.

**Tech Stack:** Python 3.12+ (FastAPI, Pydantic v2, pytest + pytest-asyncio), React 18 + TypeScript + Vitest + Testing Library.

## Global Constraints

- **No new database table, no migration.** This codebase has no migration tooling (`create_all` only adds new tables, never columns to existing ones) — storage is 100% filesystem, exactly like `packs/`.
- **Zero changes to `load_playbook`, `lint_plan_first`, `PlaybookSpec`/`StepSpec`, `POST /api/runs`, or `Project.default_playbook_path`.** A project playbook's stable path slots into the existing run-creation flow completely unmodified — same as any `packs/...` path today.
- **Validation on save must be at least as broad as what the platform's other TOML entry points already require of themselves.** `load_playbook` can raise `tomllib.TOMLDecodeError`, `KeyError` (missing `[playbook]` section), `pydantic.ValidationError` (bad step fields), or `ValueError` (from `PlaybookSpec`'s own fan_out/loop validator) — not just `PlaybookLoadError`. `POST /api/runs` today only catches `(PlaybookLoadError, PlaybookLintError)`, which is an existing narrow-catch gap (the same class of bug M4b's review already found and fixed once for `packs/loader.py`'s `list_packs`, per `docs/status.html`'s 2026-07-23 changelog entry) — do not copy that narrow pattern into new code. A hand-typed TOML editor makes syntax typos the *most* likely failure mode, not the least.
- **Raw TOML `Textarea` editor only** — no structured step-builder form, no new code-editor dependency (no CodeMirror/Monaco).
- **Editor never runs its own TOML/lint logic client-side** — every validation error the user sees is the server's own message, surfaced through the existing `ApiResponse`/`ErrorEnvelope`/`ApiClientError` pattern.
- **Slug collisions reject with `409 Conflict`** (matches this codebase's existing `pause`/`archive`/`activate` conflict-error usage) — no auto-suffixing.
- **Clone flow is preview-first** — selecting a template fetches its content into the textarea; nothing is written until the user explicitly saves.
- **Deletes are unconditional** — no reference-counting against past `Run.playbook_ref` rows (nothing does that for `packs/` files today either).

---

## Task A: Backend storage module

**Files:**
- Create: `src/foundry/project_playbooks/__init__.py` (empty)
- Create: `src/foundry/project_playbooks/loader.py`
- Test: `tests/project_playbooks/__init__.py` (empty)
- Test: `tests/project_playbooks/test_loader.py`

**Interfaces:**
- Produces: `ProjectPlaybookError(Exception)`, `ProjectPlaybookValidationError(ProjectPlaybookError)` (raised by `write_project_playbook_atomic` on any load/lint failure — this single type is what Task B's route layer catches, so it never needs to know about `tomllib`/`pydantic` internals), `ProjectPlaybookMeta` dataclass (`slug: str`, `project_id: str`, `playbook_id: str`, `description: str`, `path: str`, `updated_at: str`), `project_playbook_dir(root, project_id) -> Path`, `project_playbook_path(root, project_id, slug) -> str`, `slugify(name) -> str`, `list_project_playbooks(root, project_id) -> list[ProjectPlaybookMeta]`, `read_project_playbook(root, project_id, slug) -> str`, `get_project_playbook_meta(root, project_id, slug) -> ProjectPlaybookMeta`, `write_project_playbook_atomic(root, project_id, slug, content) -> ProjectPlaybookMeta`, `delete_project_playbook(root, project_id, slug) -> None`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/project_playbooks/__init__.py
```

```python
# tests/project_playbooks/test_loader.py
import os

import pytest

from foundry.project_playbooks.loader import (
    ProjectPlaybookError,
    ProjectPlaybookValidationError,
    delete_project_playbook,
    get_project_playbook_meta,
    list_project_playbooks,
    project_playbook_path,
    read_project_playbook,
    slugify,
    write_project_playbook_atomic,
)
from foundry.packs.resolve import resolve_pack_manifest, resolve_pack_version

VALID_TOML = """
[playbook]
id = "hotfix"
description = "A minimal one-step playbook"

[[step]]
id = "review"
role = "reviewer"
produces = "review_artifact"
gate = "human"
"""

WRITES_WITHOUT_GATE_TOML = """
[playbook]
id = "unsafe"
description = "writes=true with no upstream derived_gate"

[[step]]
id = "fix"
role = "developer"
produces = "code_diff_artifact"
gate = "none"
writes = true
"""

SYNTAX_ERROR_TOML = "[playbook\nid = broken"


def test_slugify_normalizes_names():
    assert slugify("My Hotfix Flow!") == "my-hotfix-flow"
    assert slugify("  spaced -- out  ") == "spaced-out"


def test_slugify_rejects_a_name_with_no_alphanumeric_characters():
    with pytest.raises(ProjectPlaybookError):
        slugify("!!!")


def test_list_returns_empty_for_a_project_with_no_playbooks_yet(tmp_path):
    assert list_project_playbooks(str(tmp_path), "proj-1") == []


def test_write_then_read_roundtrip(tmp_path):
    root = str(tmp_path)
    meta = write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    assert meta.slug == "hotfix"
    assert meta.playbook_id == "hotfix"
    assert meta.description == "A minimal one-step playbook"
    assert read_project_playbook(root, "proj-1", "hotfix") == VALID_TOML

    listed = list_project_playbooks(root, "proj-1")
    assert [m.slug for m in listed] == ["hotfix"]


def test_write_leaves_no_tmp_file_after_success(tmp_path):
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    final_path = project_playbook_path(root, "proj-1", "hotfix")
    assert os.path.exists(final_path)
    assert not os.path.exists(f"{final_path}.tmp")


def test_write_with_syntax_error_raises_and_leaves_no_tmp_file(tmp_path):
    root = str(tmp_path)
    with pytest.raises(ProjectPlaybookValidationError):
        write_project_playbook_atomic(root, "proj-1", "hotfix", SYNTAX_ERROR_TOML)
    final_path = project_playbook_path(root, "proj-1", "hotfix")
    assert not os.path.exists(final_path)
    assert not os.path.exists(f"{final_path}.tmp")


def test_failed_update_does_not_corrupt_the_previous_good_copy(tmp_path):
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    with pytest.raises(ProjectPlaybookValidationError):
        write_project_playbook_atomic(root, "proj-1", "hotfix", SYNTAX_ERROR_TOML)
    assert read_project_playbook(root, "proj-1", "hotfix") == VALID_TOML


def test_write_rejects_a_writes_step_not_downstream_of_a_derived_gate(tmp_path):
    """The platform's core safety invariant -- the easiest thing to
    accidentally bypass in a brand-new write path."""
    root = str(tmp_path)
    with pytest.raises(ProjectPlaybookValidationError):
        write_project_playbook_atomic(root, "proj-1", "unsafe", WRITES_WITHOUT_GATE_TOML)


def test_read_missing_playbook_raises(tmp_path):
    with pytest.raises(ProjectPlaybookError):
        read_project_playbook(str(tmp_path), "proj-1", "does-not-exist")


def test_get_meta_missing_playbook_raises(tmp_path):
    with pytest.raises(ProjectPlaybookError):
        get_project_playbook_meta(str(tmp_path), "proj-1", "does-not-exist")


def test_delete_removes_the_file(tmp_path):
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    delete_project_playbook(root, "proj-1", "hotfix")
    assert list_project_playbooks(root, "proj-1") == []


def test_delete_missing_playbook_raises(tmp_path):
    with pytest.raises(ProjectPlaybookError):
        delete_project_playbook(str(tmp_path), "proj-1", "does-not-exist")


def test_list_skips_a_file_that_fails_to_parse_rather_than_erroring_the_whole_list(tmp_path):
    """Same 'one bad file doesn't break the list' behavior M4b's review
    fixed for packs/loader.py's list_packs -- don't regress it here."""
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    project_dir = project_playbook_path(root, "proj-1", "broken")
    with open(project_dir, "w", encoding="utf-8") as f:
        f.write(SYNTAX_ERROR_TOML)  # written directly, bypassing the validation gate

    listed = list_project_playbooks(root, "proj-1")
    assert [m.slug for m in listed] == ["hotfix"]


def test_project_playbook_path_is_not_a_pack_regression_check(tmp_path):
    """Confirms the 'no pack.toml special-casing needed' design claim as
    code: resolve.py's parent-directory walk never finds one from inside
    project_playbooks/, so a project playbook gets the exact same
    pack_version_pin fallback as any other ad-hoc playbook path."""
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    path = project_playbook_path(root, "proj-1", "hotfix")

    assert resolve_pack_version(path) == "local"
    assert resolve_pack_manifest(path) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/project_playbooks/test_loader.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'foundry.project_playbooks'`

- [ ] **Step 3: Implement the module**

```python
# src/foundry/project_playbooks/__init__.py
```

```python
# src/foundry/project_playbooks/loader.py
from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from foundry.playbook.lint import PlaybookLintError, lint_plan_first
from foundry.playbook.loader import PlaybookLoadError, load_playbook
from foundry.playbook.schema import PlaybookSpec

_VALIDATION_ERRORS = (
    PlaybookLoadError,
    PlaybookLintError,
    tomllib.TOMLDecodeError,
    ValidationError,
    KeyError,
    ValueError,
    TypeError,
)


class ProjectPlaybookError(Exception):
    pass


class ProjectPlaybookValidationError(ProjectPlaybookError):
    pass


def project_playbook_dir(root: str, project_id: str) -> Path:
    return Path(root) / project_id


def project_playbook_path(root: str, project_id: str, slug: str) -> str:
    return str(project_playbook_dir(root, project_id) / f"{slug}.toml")


def slugify(name: str) -> str:
    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not slug:
        raise ProjectPlaybookError(f"name {name!r} produces an empty slug")
    return slug


@dataclass
class ProjectPlaybookMeta:
    slug: str
    project_id: str
    playbook_id: str
    description: str
    path: str
    updated_at: str


def _meta_from_playbook(project_id: str, slug: str, path: str, playbook: PlaybookSpec) -> ProjectPlaybookMeta:
    mtime = os.stat(path).st_mtime
    updated_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    return ProjectPlaybookMeta(
        slug=slug,
        project_id=project_id,
        playbook_id=playbook.id,
        description=playbook.description,
        path=path,
        updated_at=updated_at,
    )


def list_project_playbooks(root: str, project_id: str) -> list[ProjectPlaybookMeta]:
    directory = project_playbook_dir(root, project_id)
    if not directory.is_dir():
        return []

    metas: list[ProjectPlaybookMeta] = []
    for entry in sorted(directory.iterdir()):
        if entry.suffix != ".toml":
            continue
        try:
            playbook = load_playbook(str(entry))
        except _VALIDATION_ERRORS:
            continue
        metas.append(_meta_from_playbook(project_id, entry.stem, str(entry), playbook))
    return metas


def read_project_playbook(root: str, project_id: str, slug: str) -> str:
    path = project_playbook_path(root, project_id, slug)
    if not os.path.exists(path):
        raise ProjectPlaybookError(f"project playbook {slug!r} not found for project {project_id!r}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def get_project_playbook_meta(root: str, project_id: str, slug: str) -> ProjectPlaybookMeta:
    path = project_playbook_path(root, project_id, slug)
    if not os.path.exists(path):
        raise ProjectPlaybookError(f"project playbook {slug!r} not found for project {project_id!r}")
    playbook = load_playbook(path)
    return _meta_from_playbook(project_id, slug, path, playbook)


def write_project_playbook_atomic(root: str, project_id: str, slug: str, content: str) -> ProjectPlaybookMeta:
    directory = project_playbook_dir(root, project_id)
    directory.mkdir(parents=True, exist_ok=True)
    final_path = project_playbook_path(root, project_id, slug)
    tmp_path = f"{final_path}.tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)

    try:
        playbook = load_playbook(tmp_path)
        lint_plan_first(playbook)
    except _VALIDATION_ERRORS as e:
        os.remove(tmp_path)
        raise ProjectPlaybookValidationError(str(e)) from e

    os.replace(tmp_path, final_path)
    return _meta_from_playbook(project_id, slug, final_path, playbook)


def delete_project_playbook(root: str, project_id: str, slug: str) -> None:
    path = project_playbook_path(root, project_id, slug)
    if not os.path.exists(path):
        raise ProjectPlaybookError(f"project playbook {slug!r} not found for project {project_id!r}")
    os.remove(path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/project_playbooks/test_loader.py -v`
Expected: PASS, 14/14

- [ ] **Step 5: Commit**

```bash
git add src/foundry/project_playbooks/ tests/project_playbooks/
git commit -m "feat(project-playbooks): add filesystem-backed storage module with plan-first validation"
```

---

## Task B: Backend API routes

**Files:**
- Create: `src/foundry/api/routes/project_playbooks.py`
- Modify: `src/foundry/api/routes/packs.py` (add clone-preview endpoint)
- Modify: `src/foundry/api/app.py` (register new router, add `project_playbooks_root` param)
- Modify: `tests/api/conftest.py` (`api_client` fixture must pass a tmp-path-scoped `project_playbooks_root`, or tests would write real files into the repo's actual `project_playbooks/` directory)
- Test: `tests/api/test_project_playbooks_route.py`
- Test: `tests/api/test_packs_route.py` (extend, for the new clone-preview endpoint)

**Interfaces:**
- Consumes: everything from Task A (`src/foundry/project_playbooks/loader.py`).
- Produces: `GET/POST /api/projects/{project_id}/playbooks`, `GET/PUT/DELETE /api/projects/{project_id}/playbooks/{slug}`, `GET /api/packs/{pack_id}/{rel_path:path}`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/api/test_project_playbooks_route.py
import pytest

VALID_TOML = """
[playbook]
id = "hotfix"
description = "A minimal one-step playbook"

[[step]]
id = "review"
role = "reviewer"
produces = "review_artifact"
gate = "human"
"""

INVALID_TOML = "[playbook\nid = broken"


async def _create_project(client):
    resp = await client.post("/api/projects", json={"name": "acme", "path": "/tmp/acme"})
    return resp.json()["data"]["id"]


@pytest.mark.asyncio
async def test_list_playbooks_empty_for_a_fresh_project(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    resp = await client.get(f"/api/projects/{project_id}/playbooks")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_list_playbooks_unknown_project_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/projects/does-not-exist/playbooks")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_then_get_then_list_roundtrip(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    create_resp = await client.post(
        f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix Flow", "content": VALID_TOML}
    )
    assert create_resp.status_code == 201
    body = create_resp.json()["data"]
    assert body["slug"] == "hotfix-flow"
    assert body["playbook_id"] == "hotfix"
    assert body["content"] == VALID_TOML

    get_resp = await client.get(f"/api/projects/{project_id}/playbooks/hotfix-flow")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["content"] == VALID_TOML

    list_resp = await client.get(f"/api/projects/{project_id}/playbooks")
    assert [p["slug"] for p in list_resp.json()["data"]] == ["hotfix-flow"]


@pytest.mark.asyncio
async def test_create_with_invalid_toml_returns_400(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    resp = await client.post(
        f"/api/projects/{project_id}/playbooks", json={"name": "Broken", "content": INVALID_TOML}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_duplicate_slug_returns_409(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    await client.post(f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML})

    resp = await client.post(f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML})
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_unknown_slug_returns_404(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    resp = await client.put(f"/api/projects/{project_id}/playbooks/does-not-exist", json={"content": VALID_TOML})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_persists_new_content(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    await client.post(f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML})

    updated_toml = VALID_TOML.replace("A minimal", "An updated minimal")
    resp = await client.put(f"/api/projects/{project_id}/playbooks/hotfix", json={"content": updated_toml})
    assert resp.status_code == 200
    assert resp.json()["data"]["content"] == updated_toml


@pytest.mark.asyncio
async def test_delete_then_list_is_empty(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    await client.post(f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML})

    del_resp = await client.delete(f"/api/projects/{project_id}/playbooks/hotfix")
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/api/projects/{project_id}/playbooks")
    assert list_resp.json()["data"] == []


@pytest.mark.asyncio
async def test_delete_unknown_slug_returns_404(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    resp = await client.delete(f"/api/projects/{project_id}/playbooks/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_project_playbook_can_start_a_real_run(api_client):
    """End-to-end: a project playbook's returned path is a completely valid
    RunCreate.playbook_path -- proves the full-stack integration claim, not
    just the storage-layer one from Task A."""
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    create_resp = await client.post(
        f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML}
    )
    path = create_resp.json()["data"]["path"]

    run_resp = await client.post(
        "/api/runs", json={"project_id": project_id, "playbook_path": path, "driver": "fake"}
    )
    assert run_resp.status_code == 201
    assert run_resp.json()["data"]["pack_version_pin"] == "local"
```

Append to `tests/api/test_packs_route.py`:

```python
@pytest.mark.asyncio
async def test_get_pack_playbook_content_returns_raw_toml(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs/default/playbooks/bugfix.toml")
    assert resp.status_code == 200
    content = resp.json()["data"]["content"]
    assert '[playbook]' in content
    assert 'id = "bugfix"' in content


@pytest.mark.asyncio
async def test_get_pack_playbook_content_unknown_pack_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs/does-not-exist/playbooks/bugfix.toml")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_get_pack_playbook_content_unknown_path_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs/default/playbooks/does-not-exist.toml")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_project_playbooks_route.py tests/api/test_packs_route.py -v`
Expected: FAIL — `404 Not Found` for the new routes (they don't exist yet) and `ImportError`/collection errors are NOT expected since these are pure HTTP calls against an existing app; the new-route tests fail on status-code assertions instead.

- [ ] **Step 3: Update `tests/api/conftest.py` so the `api_client` fixture doesn't write into the real repo**

In `tests/api/conftest.py`, change `_make_store_scheduler_app`:

```python
async def _make_store_scheduler_app(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    engine = make_engine(db_path)
    await init_db(engine, db_path)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)
    app = create_app(store, scheduler, project_playbooks_root=str(tmp_path / "project_playbooks"))
    return engine, store, scheduler, app
```

(Only the `create_app(...)` call's arguments change — add `project_playbooks_root=str(tmp_path / "project_playbooks")`. This keeps every test using `api_client` isolated to `tmp_path`, never the real repo-root `project_playbooks/` directory.)

- [ ] **Step 4: Implement the routes**

```python
# src/foundry/api/routes/project_playbooks.py
from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from foundry.api.errors import ConflictError, NotFoundError, ValidationApiError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.project_playbooks.loader import (
    ProjectPlaybookError,
    ProjectPlaybookMeta,
    ProjectPlaybookValidationError,
    delete_project_playbook,
    get_project_playbook_meta,
    list_project_playbooks,
    project_playbook_path,
    read_project_playbook,
    slugify,
    write_project_playbook_atomic,
)

router = APIRouter()


def _get_root(request: Request) -> str:
    return request.app.state.project_playbooks_root


class ProjectPlaybookOut(BaseModel):
    slug: str
    project_id: str
    playbook_id: str
    description: str
    path: str
    updated_at: str


class ProjectPlaybookDetailOut(ProjectPlaybookOut):
    content: str


class ProjectPlaybookCreate(BaseModel):
    name: str
    content: str


class ProjectPlaybookUpdate(BaseModel):
    content: str


def _to_out(meta: ProjectPlaybookMeta) -> ProjectPlaybookOut:
    return ProjectPlaybookOut(
        slug=meta.slug,
        project_id=meta.project_id,
        playbook_id=meta.playbook_id,
        description=meta.description,
        path=meta.path,
        updated_at=meta.updated_at,
    )


async def _require_project(request: Request, project_id: str) -> None:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")


@router.get("/projects/{project_id}/playbooks")
async def list_playbooks(project_id: str, request: Request) -> ApiResponse[list[ProjectPlaybookOut]]:
    await _require_project(request, project_id)
    metas = list_project_playbooks(_get_root(request), project_id)
    out = [_to_out(m) for m in metas]
    return ApiResponse[list[ProjectPlaybookOut]](data=out, paging=Paging.unpaginated(len(out)))


@router.get("/projects/{project_id}/playbooks/{slug}")
async def get_playbook(project_id: str, slug: str, request: Request) -> ApiResponse[ProjectPlaybookDetailOut]:
    await _require_project(request, project_id)
    root = _get_root(request)
    try:
        meta = get_project_playbook_meta(root, project_id, slug)
        content = read_project_playbook(root, project_id, slug)
    except ProjectPlaybookError as e:
        raise NotFoundError(str(e)) from e
    out = ProjectPlaybookDetailOut(**_to_out(meta).model_dump(), content=content)
    return ApiResponse[ProjectPlaybookDetailOut](data=out, paging=Paging.none())


@router.post("/projects/{project_id}/playbooks", status_code=201)
async def create_playbook(
    project_id: str, body: ProjectPlaybookCreate, request: Request
) -> ApiResponse[ProjectPlaybookDetailOut]:
    await _require_project(request, project_id)
    root = _get_root(request)
    slug = slugify(body.name)

    if os.path.exists(project_playbook_path(root, project_id, slug)):
        raise ConflictError(f"Project {project_id} already has a playbook named {slug!r}")

    try:
        meta = write_project_playbook_atomic(root, project_id, slug, body.content)
    except ProjectPlaybookValidationError as e:
        raise ValidationApiError(str(e)) from e

    out = ProjectPlaybookDetailOut(**_to_out(meta).model_dump(), content=body.content)
    return ApiResponse[ProjectPlaybookDetailOut](data=out, paging=Paging.none())


@router.put("/projects/{project_id}/playbooks/{slug}")
async def update_playbook(
    project_id: str, slug: str, body: ProjectPlaybookUpdate, request: Request
) -> ApiResponse[ProjectPlaybookDetailOut]:
    await _require_project(request, project_id)
    root = _get_root(request)

    if not os.path.exists(project_playbook_path(root, project_id, slug)):
        raise NotFoundError(f"Project playbook {slug!r} not found for project {project_id}")

    try:
        meta = write_project_playbook_atomic(root, project_id, slug, body.content)
    except ProjectPlaybookValidationError as e:
        raise ValidationApiError(str(e)) from e

    out = ProjectPlaybookDetailOut(**_to_out(meta).model_dump(), content=body.content)
    return ApiResponse[ProjectPlaybookDetailOut](data=out, paging=Paging.none())


@router.delete("/projects/{project_id}/playbooks/{slug}", status_code=204)
async def delete_playbook(project_id: str, slug: str, request: Request) -> Response:
    await _require_project(request, project_id)
    root = _get_root(request)
    try:
        delete_project_playbook(root, project_id, slug)
    except ProjectPlaybookError as e:
        raise NotFoundError(str(e)) from e
    return Response(status_code=204)
```

In `src/foundry/api/routes/packs.py`, add the clone-preview endpoint (full new file content — this file is currently 28 lines):

```python
from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi import APIRouter
from pydantic import ValidationError

from foundry.api.errors import NotFoundError
from foundry.api.schemas import ApiResponse, Paging
from foundry.packs.loader import PackLoadError, list_packs, load_pack
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


def _find_pack_dir(packs_root: str, pack_id: str) -> Path | None:
    root = Path(packs_root)
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not (entry / "pack.toml").exists():
            continue
        try:
            manifest = load_pack(str(entry))
        except (PackLoadError, tomllib.TOMLDecodeError, ValidationError, TypeError):
            continue
        if manifest.id == pack_id:
            return entry
    return None


@router.get("/packs/{pack_id}/{rel_path:path}")
async def get_pack_playbook_content(pack_id: str, rel_path: str) -> ApiResponse[dict]:
    pack_dir = _find_pack_dir(PACKS_ROOT, pack_id)
    if pack_dir is None:
        raise NotFoundError(f"Pack {pack_id!r} not found")

    manifest = load_pack(str(pack_dir))
    if rel_path not in manifest.playbooks:
        raise NotFoundError(f"Pack {pack_id!r} has no playbook {rel_path!r}")

    with open(pack_dir / rel_path, encoding="utf-8") as f:
        content = f.read()
    return ApiResponse[dict](data={"content": content}, paging=Paging.none())
```

`rel_path` here is the value exactly as stored in `PackManifest.playbooks` (e.g. `"playbooks/bugfix.toml"`) — the client calls `GET /api/packs/default/playbooks/bugfix.toml`, so the URL's trailing segments already spell out the stored relative path with no extra prefix/duplication. The new route (`{rel_path:path}`, multi-segment) and the existing `GET /packs/{pack_id}` (single-segment) don't collide — FastAPI matches by path shape, not registration order.

In `src/foundry/api/app.py`:
1. Add the import alongside the other 12:
```python
from foundry.api.routes.project_playbooks import router as project_playbooks_router
```
2. Add a `project_playbooks_root` parameter to `create_app` and store it on `app.state`:
```python
def create_app(
    store: Store,
    scheduler: Scheduler,
    engine: AsyncEngine | None = None,
    original_db_path: str | None = None,
    demo_db_path: str = ".foundry-demo/demo.db",
    demo_repos_dir: str = ".foundry-demo/repos",
    project_playbooks_root: str = "project_playbooks",
) -> FastAPI:
    app = FastAPI(title="Foundry API")
    app.state.store = store
    app.state.scheduler = scheduler
    app.state.engine = engine
    app.state.original_db_path = original_db_path
    app.state.current_db_path = original_db_path
    app.state.demo_db_path = demo_db_path
    app.state.demo_repos_dir = demo_repos_dir
    app.state.demo_swap_lock = asyncio.Lock()
    app.state.project_playbooks_root = project_playbooks_root
```
3. Register the router next to the other 12:
```python
    app.include_router(project_playbooks_router, prefix="/api")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/project_playbooks/ tests/api/test_project_playbooks_route.py tests/api/test_packs_route.py -v`
Expected: PASS, all green (11 new project-playbook route tests + 3 new pack-content tests + the 3 pre-existing pack-route tests).

Run the full backend suite to confirm no regression: `uv run pytest -v`
Expected: PASS (baseline 279 + the new tests from Task A + Task B).

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/routes/project_playbooks.py src/foundry/api/routes/packs.py src/foundry/api/app.py tests/api/conftest.py tests/api/test_project_playbooks_route.py tests/api/test_packs_route.py
git commit -m "feat(api): add project-playbook CRUD routes and a pack-playbook content endpoint"
```

---

## Task C: Frontend API client

**Files:**
- Modify: `frontend/src/api/types.ts` (add two interfaces)
- Create: `frontend/src/api/projectPlaybooks.ts`
- Test: `frontend/src/api/projectPlaybooks.test.ts`

**Interfaces:**
- Consumes: `apiFetch` from `frontend/src/api/client.ts` (unchanged).
- Produces: `listProjectPlaybooks(projectId)`, `getProjectPlaybook(projectId, slug)`, `createProjectPlaybook(projectId, {name, content})`, `updateProjectPlaybook(projectId, slug, {content})`, `deleteProjectPlaybook(projectId, slug)`, `getPackPlaybookContent(packId, relPath)` — consumed by Task D and Task E.

- [ ] **Step 1: Write the failing test**

```ts
// frontend/src/api/projectPlaybooks.test.ts
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createProjectPlaybook,
  deleteProjectPlaybook,
  getPackPlaybookContent,
  getProjectPlaybook,
  listProjectPlaybooks,
  updateProjectPlaybook,
} from "./projectPlaybooks";

function mockFetchOnce(data: unknown, status = 200) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockResolvedValue({
      ok: status < 400,
      status,
      json: async () => ({ data, paging: {} }),
    }),
  );
}

describe("projectPlaybooks API client", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("listProjectPlaybooks calls the right URL", async () => {
    mockFetchOnce([]);
    await listProjectPlaybooks("proj-1");
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks", undefined);
  });

  it("getProjectPlaybook calls the right URL", async () => {
    mockFetchOnce({ slug: "hotfix", content: "..." });
    await getProjectPlaybook("proj-1", "hotfix");
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks/hotfix", undefined);
  });

  it("createProjectPlaybook POSTs name and content", async () => {
    mockFetchOnce({ slug: "hotfix" }, 201);
    await createProjectPlaybook("proj-1", { name: "Hotfix", content: "toml..." });
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: "Hotfix", content: "toml..." }),
    });
  });

  it("updateProjectPlaybook PUTs content", async () => {
    mockFetchOnce({ slug: "hotfix" });
    await updateProjectPlaybook("proj-1", "hotfix", { content: "toml..." });
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks/hotfix", {
      method: "PUT",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ content: "toml..." }),
    });
  });

  it("deleteProjectPlaybook DELETEs", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, status: 204 }),
    );
    await deleteProjectPlaybook("proj-1", "hotfix");
    expect(fetch).toHaveBeenCalledWith("/api/projects/proj-1/playbooks/hotfix", { method: "DELETE" });
  });

  it("getPackPlaybookContent calls the right URL and returns the content string", async () => {
    mockFetchOnce({ content: "[playbook]\nid = \"bugfix\"" });
    const content = await getPackPlaybookContent("default", "playbooks/bugfix.toml");
    expect(fetch).toHaveBeenCalledWith("/api/packs/default/playbooks/bugfix.toml", undefined);
    expect(content).toBe("[playbook]\nid = \"bugfix\"");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/api/projectPlaybooks.test.ts`
Expected: FAIL — `Failed to resolve import "./projectPlaybooks"`

- [ ] **Step 3: Add types and implement the client**

Add to `frontend/src/api/types.ts` (append at the end of the file):

```ts
export interface ProjectPlaybookSummary {
  slug: string;
  project_id: string;
  playbook_id: string;
  description: string;
  path: string;
  updated_at: string;
}

export interface ProjectPlaybookDetail extends ProjectPlaybookSummary {
  content: string;
}
```

```ts
// frontend/src/api/projectPlaybooks.ts
import { apiFetch } from "./client";
import type { ProjectPlaybookDetail, ProjectPlaybookSummary } from "./types";

export async function listProjectPlaybooks(projectId: string): Promise<ProjectPlaybookSummary[]> {
  const res = await apiFetch<ProjectPlaybookSummary[]>(`/api/projects/${projectId}/playbooks`);
  return res.data;
}

export async function getProjectPlaybook(projectId: string, slug: string): Promise<ProjectPlaybookDetail> {
  const res = await apiFetch<ProjectPlaybookDetail>(`/api/projects/${projectId}/playbooks/${slug}`);
  return res.data;
}

export async function createProjectPlaybook(
  projectId: string,
  input: { name: string; content: string },
): Promise<ProjectPlaybookDetail> {
  const res = await apiFetch<ProjectPlaybookDetail>(`/api/projects/${projectId}/playbooks`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}

export async function updateProjectPlaybook(
  projectId: string,
  slug: string,
  input: { content: string },
): Promise<ProjectPlaybookDetail> {
  const res = await apiFetch<ProjectPlaybookDetail>(`/api/projects/${projectId}/playbooks/${slug}`, {
    method: "PUT",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(input),
  });
  return res.data;
}

export async function deleteProjectPlaybook(projectId: string, slug: string): Promise<void> {
  await apiFetch<undefined>(`/api/projects/${projectId}/playbooks/${slug}`, { method: "DELETE" });
}

export async function getPackPlaybookContent(packId: string, relPath: string): Promise<string> {
  const res = await apiFetch<{ content: string }>(`/api/packs/${packId}/${relPath}`);
  return res.data.content;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- src/api/projectPlaybooks.test.ts`
Expected: PASS, 6/6

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/projectPlaybooks.ts frontend/src/api/projectPlaybooks.test.ts
git commit -m "feat(ui): add projectPlaybooks API client"
```

---

## Task D: Playbook editor page

**Files:**
- Create: `frontend/src/pages/ProjectPlaybookEditorPage.tsx`
- Modify: `frontend/src/App.tsx` (add two routes)
- Test: `frontend/src/pages/ProjectPlaybookEditorPage.test.tsx`

**Interfaces:**
- Consumes: everything from Task C (`frontend/src/api/projectPlaybooks.ts`), `listPacks` from `frontend/src/api/packs.ts` (existing), `ApiClientError` from `frontend/src/api/client.ts` (existing), `Button`/`Input`/`Label`/`Select`/`Textarea` primitives (existing, Phase 1/2).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/pages/ProjectPlaybookEditorPage.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import ProjectPlaybookEditorPage from "./ProjectPlaybookEditorPage";

function renderPage(initialPath: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[initialPath]}>
        <Routes>
          <Route path="/projects/:id/playbooks/new" element={<ProjectPlaybookEditorPage />} />
          <Route path="/projects/:id/playbooks/:slug" element={<ProjectPlaybookEditorPage />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("ProjectPlaybookEditorPage", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("create mode: shows a template picker and prefills the textarea on selection", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/packs") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [{ id: "default", version: "0.1.0", roles: [], playbooks: ["playbooks/bugfix.toml"] }],
            paging: {},
          }),
        });
      }
      if (url === "/api/packs/default/playbooks/bugfix.toml") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({ data: { content: "[playbook]\nid = \"bugfix\"" }, paging: {} }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderPage("/projects/proj-1/playbooks/new");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByLabelText(/start from/i)).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/start from/i), "default::playbooks/bugfix.toml");

    await waitFor(() =>
      expect(screen.getByLabelText(/playbook toml/i)).toHaveValue("[playbook]\nid = \"bugfix\""),
    );
  });

  it("create mode: shows the server's validation error on save failure", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url === "/api/packs") {
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }
      if (url === "/api/projects/proj-1/playbooks" && init?.method === "POST") {
        return Promise.resolve({
          ok: false, status: 400,
          json: async () => ({
            error: { code: "VALIDATION_ERROR", message: "duplicate step id(s)", status_code: 400, timestamp: "", path: "" },
          }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderPage("/projects/proj-1/playbooks/new");
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^name$/i), "My Flow");
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    await waitFor(() => expect(screen.getByText(/duplicate step id/i)).toBeInTheDocument());
  });

  it("edit mode: prefills the textarea from the existing playbook", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/projects/proj-1/playbooks/hotfix") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: {
              slug: "hotfix", project_id: "proj-1", playbook_id: "hotfix", description: "",
              path: "project_playbooks/proj-1/hotfix.toml", updated_at: "2026-08-03T00:00:00Z",
              content: "[playbook]\nid = \"hotfix\"",
            },
            paging: {},
          }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderPage("/projects/proj-1/playbooks/hotfix");

    await waitFor(() =>
      expect(screen.getByLabelText(/playbook toml/i)).toHaveValue("[playbook]\nid = \"hotfix\""),
    );
    expect(screen.queryByLabelText(/^name$/i)).not.toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/pages/ProjectPlaybookEditorPage.test.tsx`
Expected: FAIL — `Failed to resolve import "./ProjectPlaybookEditorPage"`

- [ ] **Step 3: Implement the page**

```tsx
// frontend/src/pages/ProjectPlaybookEditorPage.tsx
import { useEffect, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useParams } from "react-router-dom";
import { ApiClientError } from "../api/client";
import { listPacks } from "../api/packs";
import {
  createProjectPlaybook,
  getPackPlaybookContent,
  getProjectPlaybook,
  updateProjectPlaybook,
} from "../api/projectPlaybooks";
import { Button } from "../components/ui/forms/Button";
import { Input } from "../components/ui/forms/Input";
import { Label } from "../components/ui/forms/Label";
import { Select } from "../components/ui/forms/Select";
import { Textarea } from "../components/ui/forms/Textarea";

export default function ProjectPlaybookEditorPage() {
  const { id, slug } = useParams<{ id: string; slug?: string }>();
  const projectId = id!;
  const isEdit = !!slug;
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [error, setError] = useState<string | null>(null);

  const { data: existing } = useQuery({
    queryKey: ["project-playbook", projectId, slug],
    queryFn: () => getProjectPlaybook(projectId, slug!),
    enabled: isEdit,
  });

  useEffect(() => {
    if (existing) setContent(existing.content);
  }, [existing]);

  const { data: packs } = useQuery({ queryKey: ["packs"], queryFn: listPacks, enabled: !isEdit });
  const templateOptions = (packs ?? []).flatMap((p) =>
    p.playbooks.map((pb) => ({ value: `${p.id}::${pb}`, label: `${p.id} / ${pb}` })),
  );

  const applyTemplateMutation = useMutation({
    mutationFn: (value: string) => {
      const [packId, relPath] = value.split("::");
      return getPackPlaybookContent(packId, relPath);
    },
    onSuccess: (fetchedContent) => setContent(fetchedContent),
  });

  const saveMutation = useMutation({
    mutationFn: () =>
      isEdit
        ? updateProjectPlaybook(projectId, slug!, { content })
        : createProjectPlaybook(projectId, { name, content }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["project-playbooks", projectId] });
      navigate(`/projects/${projectId}`);
    },
    onError: (err) => {
      setError(err instanceof ApiClientError ? err.message : "Failed to save playbook.");
    },
  });

  return (
    <div className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold">{isEdit ? `Edit playbook: ${slug}` : "New playbook"}</h2>

      {error && (
        <div
          className="rounded-[var(--radius-md)] border border-[var(--destructive)] p-3 text-sm text-[var(--destructive)]"
          style={{ backgroundColor: "color-mix(in oklab, var(--destructive) 10%, transparent)" }}
        >
          {error}
        </div>
      )}

      {!isEdit && (
        <>
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="playbook-name">Name</Label>
            <Input id="playbook-name" value={name} onChange={(e) => setName(e.target.value)} required />
          </div>
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="playbook-template">Start from</Label>
            <Select
              id="playbook-template"
              defaultValue=""
              onChange={(e) => {
                if (e.target.value) applyTemplateMutation.mutate(e.target.value);
                else setContent("");
              }}
            >
              <option value="">Blank</option>
              {templateOptions.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </Select>
          </div>
        </>
      )}

      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="playbook-content">Playbook TOML</Label>
        <Textarea
          id="playbook-content"
          className="min-h-[32rem] font-mono text-xs"
          value={content}
          onChange={(e) => setContent(e.target.value)}
        />
      </div>

      <div className="flex gap-2">
        <Button
          variant="brand"
          disabled={saveMutation.isPending || (!isEdit && !name)}
          onClick={() => {
            setError(null);
            saveMutation.mutate();
          }}
        >
          Save
        </Button>
        <Button variant="outline" onClick={() => navigate(`/projects/${projectId}`)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
```

In `frontend/src/App.tsx`, add the import and two routes:

```tsx
import ProjectPlaybookEditorPage from "./pages/ProjectPlaybookEditorPage";
```

```tsx
            <Route path="/projects/:id/playbooks/new" element={<ProjectPlaybookEditorPage />} />
            <Route path="/projects/:id/playbooks/:slug" element={<ProjectPlaybookEditorPage />} />
```

(Insert both routes directly after the existing `<Route path="/projects/:id" element={<ProjectDetailPage />} />` line.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx tsc -b && npm run test -- src/pages/ProjectPlaybookEditorPage.test.tsx`
Expected: 0 tsc errors, 3/3 tests pass.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ProjectPlaybookEditorPage.tsx frontend/src/pages/ProjectPlaybookEditorPage.test.tsx frontend/src/App.tsx
git commit -m "feat(ui): add project playbook editor page"
```

---

## Task E: Playbooks section on ProjectDetailPage

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/pages/ProjectDetailPage.test.tsx` (extend)

**Interfaces:**
- Consumes: `listProjectPlaybooks`, `deleteProjectPlaybook` from Task C.

- [ ] **Step 1: Write the failing test**

Append to `frontend/src/pages/ProjectDetailPage.test.tsx`, inside the existing `describe("ProjectDetailPage", ...)` block (matches the file's exact existing pattern: `vi.stubGlobal("fetch", vi.fn().mockImplementation((url, init) => {...}))` with a URL if-chain and a final `{data: [], paging: {}}` fallback; project id `"p1"`, matching every other test in this file):

```tsx
  it("renders the project's playbooks and deletes one on confirm", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation((url: string, init?: RequestInit) => {
        if (url === "/api/projects/p1") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: { id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active", created_at: "2026-07-21T00:00:00Z" },
              paging: {},
            }),
          });
        }
        if (url === "/api/projects/p1/playbooks") {
          return Promise.resolve({
            ok: true, status: 200,
            json: async () => ({
              data: [
                {
                  slug: "hotfix", project_id: "p1", playbook_id: "hotfix",
                  description: "A minimal one-step playbook",
                  path: "project_playbooks/p1/hotfix.toml", updated_at: "2026-08-03T00:00:00Z",
                },
              ],
              paging: {},
            }),
          });
        }
        if (url === "/api/projects/p1/playbooks/hotfix" && init?.method === "DELETE") {
          return Promise.resolve({ ok: true, status: 204, json: async () => ({}) });
        }
        return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
      }),
    );

    renderWithProviders("p1");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByText("hotfix")).toBeInTheDocument());
    expect(screen.getByText(/a minimal one-step playbook/i)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /delete/i }));
    expect(window.confirm).toHaveBeenCalled();

    await waitFor(() =>
      expect(fetch).toHaveBeenCalledWith("/api/projects/p1/playbooks/hotfix", { method: "DELETE" }),
    );
  });
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- src/pages/ProjectDetailPage.test.tsx`
Expected: FAIL — no "Playbooks" section exists yet, `screen.getByText("hotfix")` never resolves.

- [ ] **Step 3: Add the Playbooks section**

In `frontend/src/pages/ProjectDetailPage.tsx`, add the import:

```tsx
import { deleteProjectPlaybook, listProjectPlaybooks } from "../api/projectPlaybooks";
```

Add the query and mutation alongside the existing ones (after the `memory` query):

```tsx
  const { data: playbooks } = useQuery({
    queryKey: ["project-playbooks", projectId],
    queryFn: () => listProjectPlaybooks(projectId),
    enabled: !!project,
  });

  const deletePlaybookMutation = useMutation({
    mutationFn: (slug: string) => deleteProjectPlaybook(projectId, slug),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["project-playbooks", projectId] }),
  });
```

Add the new section between the Settings section and the Runs section:

```tsx
      <div className="flex flex-col gap-3">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">Playbooks</h3>
          <Link to={`/projects/${projectId}/playbooks/new`} className="text-sm text-orange-400 hover:underline">
            New playbook →
          </Link>
        </div>
        {playbooks && playbooks.length === 0 && (
          <p className="text-sm text-[var(--muted-foreground)]">No project-specific playbooks yet.</p>
        )}
        <ul className="flex flex-col gap-2">
          {playbooks?.map((pb) => (
            <li key={pb.slug}>
              <Card className="flex items-center justify-between px-3 py-2">
                <div>
                  <Link
                    to={`/projects/${projectId}/playbooks/${pb.slug}`}
                    className="font-medium text-orange-400 hover:underline"
                  >
                    {pb.playbook_id}
                  </Link>
                  <span className="ml-2 text-sm text-[var(--muted-foreground)]">{pb.description}</span>
                </div>
                <Button
                  variant="outline"
                  size="xs"
                  onClick={() => {
                    if (window.confirm(`Delete playbook "${pb.slug}"?`)) {
                      deletePlaybookMutation.mutate(pb.slug);
                    }
                  }}
                >
                  Delete
                </Button>
              </Card>
            </li>
          ))}
        </ul>
      </div>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npx tsc -b && npm run test -- src/pages/ProjectDetailPage.test.tsx`
Expected: 0 tsc errors, all tests pass (including the new one).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/pages/ProjectDetailPage.test.tsx
git commit -m "feat(ui): add Playbooks section to ProjectDetailPage"
```

---

## Task F: Widen the two playbook-path inputs

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`
- Modify: `frontend/src/components/NewRunForm.tsx`

**Interfaces:** None — pure styling, no behavior change, no new test (this is a 2-line className diff; forcing failing-test ceremony onto a pure styling tweak has no TDD value here).

This task has no dependency on Tasks A-E and can ship independently, at any point (first, if you want the visible fix out fastest).

- [ ] **Step 1: Widen `ProjectDetailPage.tsx`'s playbook-path field**

In `frontend/src/pages/ProjectDetailPage.tsx`, find the settings form's playbook-path field:

```tsx
          <div className="flex flex-col gap-1 text-sm">
            <Label htmlFor="project-playbook-path">Default playbook path</Label>
```

Change the wrapping `className` to:

```tsx
          <div className="flex flex-col gap-1 text-sm flex-1 min-w-[24rem]">
            <Label htmlFor="project-playbook-path">Default playbook path</Label>
```

- [ ] **Step 2: Widen `NewRunForm.tsx`'s playbook-path field**

In `frontend/src/components/NewRunForm.tsx`, find:

```tsx
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-playbook">Playbook path</Label>
```

Change the wrapping `className` to:

```tsx
      <div className="flex flex-col gap-1 text-sm flex-1 min-w-[24rem]">
        <Label htmlFor="new-run-playbook">Playbook path</Label>
```

- [ ] **Step 3: Verify and commit**

Run: `cd frontend && npx tsc -b && npm run test -- src/pages/ProjectDetailPage.test.tsx src/components/NewRunForm.test.tsx`
Expected: 0 tsc errors, all existing tests still pass (pure className change, no query/role/text affected).

```bash
git add frontend/src/pages/ProjectDetailPage.tsx frontend/src/components/NewRunForm.tsx
git commit -m "fix(ui): widen the playbook-path inputs so a full path is readable"
```

---

## Verification (whole plan)

- Backend: `uv run pytest -v` — expect the pre-existing 279 plus this plan's ~28 new tests (14 in Task A, 11+3 in Task B), all green.
- Frontend: `cd frontend && npx tsc -b && npm run test` — expect the pre-existing 107 plus this plan's new tests (6 in Task C, 3 in Task D, 1 in Task E), all green. `npm run build` should also succeed.
- Manual end-to-end: `uv run foundry serve --db /tmp/foundry.db --port 8000` + `cd frontend && npm run dev` — register a project, open its detail page, confirm the widened playbook-path input (Task F) is visibly wider, click "New playbook", pick `default / playbooks/bugfix.toml` from "Start from", confirm the textarea fills with that template's TOML, change the `[playbook] id`, save, confirm it now appears in the Playbooks list, click Edit to confirm the change persisted, start a run from `NewRunForm` pasting that playbook's path (`project_playbooks/<id>/<slug>.toml`), confirm the run's detail page shows the run's pack version as `local`.
