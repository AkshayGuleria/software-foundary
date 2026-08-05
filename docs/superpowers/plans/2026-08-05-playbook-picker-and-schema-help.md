# Playbook Picker + Schema-Help Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the free-text playbook-path inputs in `NewRunForm` and the
project Settings form with a shared dropdown picker sourced from real
playbooks (project-specific + pack templates), and add a read-only,
backend-derived field reference panel to the playbook editor page.

**Architecture:** A new `GET /api/playbooks/schema-help` route introspects
`PlaybookSpec`/`StepSpec`/`LoopSpec`'s own Pydantic field metadata (after
adding `description=` to every field) so the reference content can never
drift from the real schema. A new shared `PlaybookPicker` frontend
component wraps the existing `listProjectPlaybooks`/`listPacks` API clients
into a grouped `<Select>` + "New playbook" link, dropped into both
`NewRunForm` and `ProjectDetailPage`'s Settings form. A new
`PlaybookFieldReference` component on `ProjectPlaybookEditorPage` renders
the schema-help data grouped by model.

**Tech Stack:** FastAPI + Pydantic v2 (backend), React + TanStack Query +
React Router (frontend) — no new dependencies.

## Global Constraints

- No manual free-text override alongside the picker dropdown — the picker
  is the only way to set a new path. An already-set value that matches no
  known option must still be preserved and displayed (as a synthetic
  leading "Custom: `<path>`" option), never silently discarded.
- No snippet-insertion or other editor interaction in the reference panel —
  read-only display only.
- Schema-help field descriptions live in `src/foundry/playbook/schema.py`
  itself (via Pydantic `Field(description=...)`) — the backend endpoint
  derives its response from `model_fields` at request time. No
  hand-duplicated copy of field docs anywhere in the frontend.
- No changes to TOML validation behavior — `load_playbook`/`lint_plan_first`
  and `PlaybookSpec`'s `_validate_fan_out_and_loop` validator are untouched;
  only field-level `description=` metadata is added.
- Pack-template picker entries resolve to the path convention
  `packs/<pack_id>/<rel_path>` (matches `PACKS_ROOT = "packs"` in
  `src/foundry/api/routes/packs.py`). Project-playbook entries use the
  `path` field already returned by `GET /api/projects/{id}/playbooks`.

---

### Task 1: Backend `GET /api/playbooks/schema-help` endpoint

**Files:**
- Modify: `src/foundry/playbook/schema.py` (add `description=` to every
  field on `LoopSpec`, `StepSpec`, `PlaybookSpec`)
- Create: `src/foundry/api/routes/playbook_schema.py`
- Modify: `src/foundry/api/app.py` (register the new router)
- Test: `tests/api/test_playbook_schema_route.py`

**Interfaces:**
- Produces: `GET /api/playbooks/schema-help` → `ApiResponse[list[SchemaFieldDoc]]`
  where `SchemaFieldDoc = {model: "PlaybookSpec"|"StepSpec"|"LoopSpec", field: str, type: str, default: str | None, required: bool, description: str}`.
  Later tasks (frontend `getPlaybookSchemaHelp`) consume this exact shape.

- [ ] **Step 1: Write the failing test**

Create `tests/api/test_playbook_schema_route.py`:

```python
import pytest

from foundry.playbook.schema import LoopSpec, PlaybookSpec, StepSpec


@pytest.mark.asyncio
async def test_schema_help_covers_every_real_field(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/playbooks/schema-help")
    assert resp.status_code == 200
    body = resp.json()["data"]

    by_model: dict[str, set[str]] = {}
    for entry in body:
        by_model.setdefault(entry["model"], set()).add(entry["field"])

    assert by_model["PlaybookSpec"] == set(PlaybookSpec.model_fields.keys())
    assert by_model["StepSpec"] == set(StepSpec.model_fields.keys())
    assert by_model["LoopSpec"] == set(LoopSpec.model_fields.keys())


@pytest.mark.asyncio
async def test_schema_help_every_field_has_a_description(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/playbooks/schema-help")
    body = resp.json()["data"]
    for entry in body:
        assert entry["description"], f"{entry['model']}.{entry['field']} has no description"


@pytest.mark.asyncio
async def test_schema_help_reflects_real_required_and_default_values(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/playbooks/schema-help")
    body = resp.json()["data"]
    by_key = {(e["model"], e["field"]): e for e in body}

    steps_field = by_key[("PlaybookSpec", "steps")]
    assert steps_field["required"] is True
    assert steps_field["default"] is None

    gate_field = by_key[("StepSpec", "gate")]
    assert gate_field["required"] is False
    assert gate_field["default"] == "'none'"

    writes_field = by_key[("StepSpec", "writes")]
    assert writes_field["required"] is False
    assert writes_field["default"] == "False"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/api/test_playbook_schema_route.py -v`
Expected: FAIL with a 404 (route doesn't exist yet).

- [ ] **Step 3: Add field descriptions to the schema**

Replace the full contents of `src/foundry/playbook/schema.py` with:

```python
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

STEP_TYPE_TO_UNIT_TYPE = {"task": "task", "derived_gate": "gate", "human_task": "human_task"}


class LoopSpec(BaseModel):
    back_to: str = Field(
        description="Step id this loop jumps back to when `until` isn't yet satisfied."
    )
    until: str = Field(
        default="verdict == approved",
        description="Boolean expression evaluated against the loop's latest gate outcome; looping stops once true.",
    )
    max_rounds: int = Field(
        default=5,
        description="Hard cap on how many times this loop can re-run before it's forced to stop.",
    )


class StepSpec(BaseModel):
    id: str = Field(
        description="Unique id for this step within the playbook; referenced by `needs`, `fan_out_from`, and `loop.back_to`."
    )
    role: str = Field(
        description="Pack role (see the pack's `pack.toml`) that runs this step's agent session."
    )
    type: Literal["task", "derived_gate", "human_task"] = Field(
        default="task",
        description="What kind of work unit this step produces: an agent task, a derived (automatic) gate, or a human task.",
    )
    needs: list[str] = Field(
        default_factory=list,
        description="Step ids that must complete before this step can start.",
    )
    produces: str | None = Field(
        default=None,
        description="Artifact key this step's output is stored under, for later steps to reference.",
    )
    gate: Literal["human", "agent", "none"] | None = Field(
        default="none",
        description="Approval gate required before this step's output can be used: a human decision, an agent-derived decision, or none.",
    )
    writes: bool = Field(
        default=False,
        description="Whether this step writes to the project's codebase. Every writes=true step must be transitively downstream of a derived_gate step (enforced by lint_plan_first).",
    )
    fan_out: str | None = Field(
        default=None,
        description="Artifact field (e.g. 'architecture_artifact.slices') whose list items this step fans out one unit per item.",
    )
    fan_out_from: str | None = Field(
        default=None,
        description="Step id (which must itself have `fan_out` set) this step fans out alongside, one unit per sibling unit. Mutually exclusive with `fan_out`.",
    )
    loop: LoopSpec | None = Field(
        default=None,
        description="If set, re-runs this step (and the steps back to `loop.back_to`) until `loop.until` is satisfied or `max_rounds` is hit.",
    )
    escalates_on: str | None = Field(
        default=None,
        description="Condition under which this step escalates to a human rather than looping or continuing automatically.",
    )


class PlaybookSpec(BaseModel):
    id: str = Field(description="Unique id for this playbook, e.g. 'bugfix' or 'sdlc_story'.")
    description: str = Field(default="", description="Human-readable summary of what this playbook is for.")
    steps: list[StepSpec] = Field(description="The ordered set of steps that make up this playbook's DAG.")

    @model_validator(mode="after")
    def _validate_fan_out_and_loop(self) -> PlaybookSpec:
        ids = {s.id for s in self.steps}
        by_id = {s.id: s for s in self.steps}
        for step in self.steps:
            if step.fan_out and step.fan_out_from:
                raise ValueError(f"step {step.id!r}: fan_out and fan_out_from are mutually exclusive")
            if step.fan_out_from is not None:
                if step.fan_out_from not in ids:
                    raise ValueError(
                        f"step {step.id!r}: fan_out_from references unknown step {step.fan_out_from!r}"
                    )
                source = by_id[step.fan_out_from]
                if not source.fan_out:
                    raise ValueError(
                        f"step {step.id!r}: fan_out_from={step.fan_out_from!r} "
                        "must reference a step with fan_out set (one-hop chains only)"
                    )
            if step.loop is not None and step.loop.back_to not in ids:
                raise ValueError(
                    f"step {step.id!r}: loop.back_to references unknown step {step.loop.back_to!r}"
                )
        return self
```

(Only the `Field(...)` additions and their `description=` text are new;
`_validate_fan_out_and_loop` and every default/type are unchanged from the
current file — verify this with `git diff` after this step.)

- [ ] **Step 4: Create the route**

Create `src/foundry/api/routes/playbook_schema.py`:

```python
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from foundry.api.schemas import ApiResponse, Paging
from foundry.playbook.schema import LoopSpec, PlaybookSpec, StepSpec

router = APIRouter()


class SchemaFieldDoc(BaseModel):
    model: Literal["PlaybookSpec", "StepSpec", "LoopSpec"]
    field: str
    type: str
    default: str | None
    required: bool
    description: str


def _format_type(field_info: FieldInfo) -> str:
    return str(field_info.annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")


def _field_docs(model_name: Literal["PlaybookSpec", "StepSpec", "LoopSpec"], model: type[BaseModel]) -> list[SchemaFieldDoc]:
    docs = []
    for name, field_info in model.model_fields.items():
        required = field_info.is_required()
        docs.append(
            SchemaFieldDoc(
                model=model_name,
                field=name,
                type=_format_type(field_info),
                default=None if required else repr(field_info.default),
                required=required,
                description=field_info.description or "",
            )
        )
    return docs


@router.get("/playbooks/schema-help")
async def get_playbook_schema_help() -> ApiResponse[list[SchemaFieldDoc]]:
    docs = [
        *_field_docs("PlaybookSpec", PlaybookSpec),
        *_field_docs("StepSpec", StepSpec),
        *_field_docs("LoopSpec", LoopSpec),
    ]
    return ApiResponse[list[SchemaFieldDoc]](data=docs, paging=Paging.unpaginated(len(docs)))
```

- [ ] **Step 5: Register the router**

In `src/foundry/api/app.py`, add the import alongside the other route
imports (after the `packs_router` import line):

```python
from foundry.api.routes.playbook_schema import router as playbook_schema_router
```

And register it alongside the other `include_router` calls (after
`app.include_router(packs_router, prefix="/api")`):

```python
    app.include_router(playbook_schema_router, prefix="/api")
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/api/test_playbook_schema_route.py -v`
Expected: 3 passed

- [ ] **Step 7: Run the full backend suite**

Run: `uv run pytest -v`
Expected: all passing (baseline 310 + 3 new = 313)

- [ ] **Step 8: Commit**

```bash
git add src/foundry/playbook/schema.py src/foundry/api/routes/playbook_schema.py src/foundry/api/app.py tests/api/test_playbook_schema_route.py
git commit -m "feat(api): add GET /api/playbooks/schema-help, derived from the real Pydantic schema"
```

---

### Task 2: Frontend `PlaybookPicker` shared component

**Files:**
- Create: `frontend/src/components/PlaybookPicker.tsx`
- Test: `frontend/src/components/PlaybookPicker.test.tsx`

**Interfaces:**
- Consumes: `listProjectPlaybooks(projectId): Promise<ProjectPlaybookSummary[]>`
  and `listPacks(): Promise<PackManifest[]>` (both already exist,
  `frontend/src/api/projectPlaybooks.ts` / `frontend/src/api/packs.ts`).
  `ProjectPlaybookSummary.path` and `PackManifest.playbooks: string[]` are
  the fields used to build option values.
- Produces: `export default function PlaybookPicker(props: { id: string; projectId: string; value: string; onChange: (path: string) => void; required?: boolean }): JSX.Element`.
  Tasks 3 and 4 render this in place of the free-text `Input`.

- [ ] **Step 1: Write the failing test**

Create `frontend/src/components/PlaybookPicker.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import PlaybookPicker from "./PlaybookPicker";

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (url === "/api/packs") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [{ id: "default", version: "0.1.0", roles: [], playbooks: ["playbooks/bugfix.toml"] }],
            paging: {},
          }),
        });
      }
      if (url === "/api/projects/proj-1/playbooks") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [
              {
                slug: "hotfix", project_id: "proj-1", playbook_id: "hotfix", description: "",
                path: "project_playbooks/proj-1/hotfix.toml", updated_at: "2026-08-03T00:00:00Z",
              },
            ],
            paging: {},
          }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }),
  );
}

function renderPicker(overrides: { projectId?: string; value?: string } = {}, onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <PlaybookPicker
          id="playbook"
          projectId={overrides.projectId ?? "proj-1"}
          value={overrides.value ?? ""}
          onChange={onChange}
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return onChange;
}

describe("PlaybookPicker", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("disables the select and hides the New link when no project is selected", () => {
    stubFetch();
    renderPicker({ projectId: "" });

    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(screen.queryByRole("link", { name: /new playbook/i })).not.toBeInTheDocument();
  });

  it("lists project playbooks and pack templates as grouped options and reports the resolved path on selection", async () => {
    stubFetch();
    const onChange = renderPicker();

    await waitFor(() => expect(screen.getByRole("option", { name: /hotfix/i })).toBeInTheDocument());
    expect(screen.getByRole("option", { name: /default \/ playbooks\/bugfix\.toml/i })).toBeInTheDocument();

    const user = userEvent.setup();
    await user.selectOptions(screen.getByRole("combobox"), "packs/default/playbooks/bugfix.toml");
    expect(onChange).toHaveBeenCalledWith("packs/default/playbooks/bugfix.toml");

    expect(screen.getByRole("link", { name: /new playbook/i })).toHaveAttribute(
      "href",
      "/projects/proj-1/playbooks/new",
    );
  });

  it("preserves an already-set value that matches no known option as a leading Custom option", async () => {
    stubFetch();
    renderPicker({ value: "tests/orchestrator/fixtures/linear_demo.toml" });

    await waitFor(() =>
      expect(
        screen.getByRole("option", { name: /custom: tests\/orchestrator\/fixtures\/linear_demo\.toml/i }),
      ).toBeInTheDocument(),
    );
    expect(screen.getByRole("combobox")).toHaveValue("tests/orchestrator/fixtures/linear_demo.toml");
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && npm run test -- PlaybookPicker.test.tsx`
Expected: FAIL (module `./PlaybookPicker` does not exist)

- [ ] **Step 3: Write the implementation**

Create `frontend/src/components/PlaybookPicker.tsx`:

```tsx
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { listPacks } from "../api/packs";
import { listProjectPlaybooks } from "../api/projectPlaybooks";
import { Select } from "./ui/forms/Select";

export default function PlaybookPicker({
  id,
  projectId,
  value,
  onChange,
  required = false,
}: {
  id: string;
  projectId: string;
  value: string;
  onChange: (path: string) => void;
  required?: boolean;
}) {
  const { data: projectPlaybooks } = useQuery({
    queryKey: ["project-playbooks", projectId],
    queryFn: () => listProjectPlaybooks(projectId),
    enabled: !!projectId,
  });
  const { data: packs } = useQuery({ queryKey: ["packs"], queryFn: listPacks });

  const projectOptions = (projectPlaybooks ?? []).map((pb) => ({
    value: pb.path,
    label: pb.playbook_id || pb.slug,
  }));
  const packOptions = (packs ?? []).flatMap((pack) =>
    pack.playbooks.map((relPath) => ({
      value: `packs/${pack.id}/${relPath}`,
      label: `${pack.id} / ${relPath}`,
    })),
  );
  const isCustom = !!value && ![...projectOptions, ...packOptions].some((o) => o.value === value);

  return (
    <div className="flex items-center gap-2">
      <Select
        id={id}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={!projectId}
        required={required}
        wrapClassName="flex-1"
        className="w-full"
      >
        <option value="" disabled>
          {projectId ? "Select a playbook…" : "Select a project first"}
        </option>
        {isCustom && <option value={value}>Custom: {value}</option>}
        {projectOptions.length > 0 && (
          <optgroup label="Project playbooks">
            {projectOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        )}
        {packOptions.length > 0 && (
          <optgroup label="Pack templates">
            {packOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </optgroup>
        )}
      </Select>
      {projectId ? (
        <Link
          to={`/projects/${projectId}/playbooks/new`}
          className="whitespace-nowrap text-sm text-orange-400 hover:underline"
        >
          New playbook →
        </Link>
      ) : (
        <span className="whitespace-nowrap text-sm text-[var(--muted-foreground)]">New playbook →</span>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd frontend && npm run test -- PlaybookPicker.test.tsx`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/PlaybookPicker.tsx frontend/src/components/PlaybookPicker.test.tsx
git commit -m "feat(ui): add shared PlaybookPicker component"
```

---

### Task 3: Swap `NewRunForm`'s free-text input for `PlaybookPicker`

**Files:**
- Modify: `frontend/src/components/NewRunForm.tsx`
- Modify: `frontend/src/components/NewRunForm.test.tsx`

**Interfaces:**
- Consumes: `PlaybookPicker` from Task 2, unchanged signature.

- [ ] **Step 1: Update the component**

In `frontend/src/components/NewRunForm.tsx`, add the import:

```tsx
import PlaybookPicker from "./PlaybookPicker";
```

Replace this block:

```tsx
      <div className="flex flex-col gap-1 text-sm flex-1 min-w-[24rem]">
        <Label htmlFor="new-run-playbook">Playbook path</Label>
        <Input
          id="new-run-playbook"
          value={playbookPath}
          onChange={(e) => setPlaybookPath(e.target.value)}
          placeholder="tests/orchestrator/fixtures/linear_demo.toml"
          required
        />
      </div>
```

with:

```tsx
      <div className="flex flex-col gap-1 text-sm flex-1 min-w-[24rem]">
        <Label htmlFor="new-run-playbook">Playbook path</Label>
        <PlaybookPicker
          id="new-run-playbook"
          projectId={projectId}
          value={playbookPath}
          onChange={setPlaybookPath}
          required
        />
      </div>
```

(`Input` stays imported — the Title field below still uses it.)

- [ ] **Step 2: Rewrite the test file**

Replace the full contents of `frontend/src/components/NewRunForm.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import type { Project } from "../api/types";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import NewRunForm from "./NewRunForm";

const projects: Project[] = [
  {
    id: "p1", name: "acme", path: "/tmp/acme", kg_status: "none", status: "active",
    created_at: "2026-07-21T00:00:00Z", default_driver: "codex", default_token_budget: 10000,
    default_playbook_path: "packs/default/playbooks/bugfix.toml",
  },
];

function stubFetch() {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation((url: string) => {
      if (url === "/api/packs") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [{ id: "default", version: "0.1.0", roles: [], playbooks: ["playbooks/bugfix.toml"] }],
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
                slug: "hotfix", project_id: "p1", playbook_id: "hotfix", description: "",
                path: "project_playbooks/p1/hotfix.toml", updated_at: "2026-08-03T00:00:00Z",
              },
            ],
            paging: {},
          }),
        });
      }
      throw new Error(`unexpected fetch: ${url}`);
    }),
  );
}

function renderForm(onSubmit: (input: unknown) => void, projectsArg: Project[] = projects) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <NewRunForm projects={projectsArg} defaultProjectId="p1" onSubmit={onSubmit} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("NewRunForm", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("pre-fills driver and playbook path from the selected project's defaults", () => {
    stubFetch();
    renderForm(vi.fn());

    expect(screen.getByLabelText(/driver/i)).toHaveValue("codex");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("packs/default/playbooks/bugfix.toml");
  });

  it("still allows overriding the pre-filled values before submit", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText(/driver/i), "claude");
    await user.click(screen.getByRole("button", { name: /start run/i }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ project_id: "p1", driver: "claude" }),
    );
  });

  it("does not reset user edits when the projects array is replaced with an equivalent one (e.g. background refetch)", async () => {
    stubFetch();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { rerender } = render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <NewRunForm projects={projects} defaultProjectId="p1" onSubmit={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const user = userEvent.setup();

    await user.selectOptions(screen.getByLabelText(/driver/i), "claude");
    await waitFor(() => expect(screen.getByRole("option", { name: /hotfix/i })).toBeInTheDocument());
    await user.selectOptions(screen.getByLabelText(/playbook path/i), "project_playbooks/p1/hotfix.toml");

    expect(screen.getByLabelText(/driver/i)).toHaveValue("claude");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("project_playbooks/p1/hotfix.toml");

    const refetchedProjects: Project[] = projects.map((p) => ({ ...p }));
    rerender(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <NewRunForm projects={refetchedProjects} defaultProjectId="p1" onSubmit={vi.fn()} />
        </MemoryRouter>
      </QueryClientProvider>,
    );

    expect(screen.getByLabelText(/driver/i)).toHaveValue("claude");
    expect(screen.getByLabelText(/playbook path/i)).toHaveValue("project_playbooks/p1/hotfix.toml");
  });
});
```

- [ ] **Step 3: Run the tests**

Run: `cd frontend && npm run test -- NewRunForm.test.tsx`
Expected: 3 passed

- [ ] **Step 4: Type-check and full frontend suite**

Run: `cd frontend && npx tsc -b && npm run test`
Expected: 0 type errors; full suite passing

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/NewRunForm.tsx frontend/src/components/NewRunForm.test.tsx
git commit -m "feat(ui): use PlaybookPicker in NewRunForm instead of a free-text path"
```

---

### Task 4: Swap `ProjectDetailPage` Settings' free-text input for `PlaybookPicker`

**Files:**
- Modify: `frontend/src/pages/ProjectDetailPage.tsx`

**Interfaces:**
- Consumes: `PlaybookPicker` from Task 2, unchanged signature.

- [ ] **Step 1: Update the component**

In `frontend/src/pages/ProjectDetailPage.tsx`, add the import alongside the
other component imports:

```tsx
import PlaybookPicker from "../components/PlaybookPicker";
```

Replace this block:

```tsx
          <div className="flex flex-col gap-1 text-sm flex-1 min-w-[24rem]">
            <Label htmlFor="project-playbook-path">Default playbook path</Label>
            <Input
              id="project-playbook-path"
              value={playbookPath}
              onChange={(e) => setPlaybookPath(e.target.value)}
              placeholder="packs/default/playbooks/sdlc_story.toml"
            />
          </div>
```

with:

```tsx
          <div className="flex flex-col gap-1 text-sm flex-1 min-w-[24rem]">
            <Label htmlFor="project-playbook-path">Default playbook path</Label>
            <PlaybookPicker
              id="project-playbook-path"
              projectId={projectId}
              value={playbookPath}
              onChange={setPlaybookPath}
            />
          </div>
```

(`Input` stays imported — the Token budget field above still uses it.)

- [ ] **Step 2: Run the existing test suite for this page**

Run: `cd frontend && npm run test -- ProjectDetailPage.test.tsx`
Expected: all passing unchanged — every existing mock in this file already
has a catch-all fallback (`return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) })`)
for any unmatched URL, so the new `/api/packs` fetch this page now performs
resolves harmlessly to an empty list. No test rewrites needed here.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npx tsc -b`
Expected: 0 errors

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/ProjectDetailPage.tsx
git commit -m "feat(ui): use PlaybookPicker for the project's default playbook path"
```

---

### Task 5: Schema-help API client + read-only field reference panel

**Files:**
- Modify: `frontend/src/api/types.ts` (add `SchemaFieldDoc`)
- Create: `frontend/src/api/playbookSchema.ts`
- Modify: `frontend/src/pages/ProjectPlaybookEditorPage.tsx`
- Modify: `frontend/src/pages/ProjectPlaybookEditorPage.test.tsx`

**Interfaces:**
- Consumes: `GET /api/playbooks/schema-help` from Task 1, response shape
  `SchemaFieldDoc = {model, field, type, default, required, description}`.

- [ ] **Step 1: Add the type**

In `frontend/src/api/types.ts`, append:

```ts
export type SchemaFieldModel = "PlaybookSpec" | "StepSpec" | "LoopSpec";

export interface SchemaFieldDoc {
  model: SchemaFieldModel;
  field: string;
  type: string;
  default: string | null;
  required: boolean;
  description: string;
}
```

- [ ] **Step 2: Add the API client**

Create `frontend/src/api/playbookSchema.ts`:

```ts
import { apiFetch } from "./client";
import type { SchemaFieldDoc } from "./types";

export async function getPlaybookSchemaHelp(): Promise<SchemaFieldDoc[]> {
  const res = await apiFetch<SchemaFieldDoc[]>("/api/playbooks/schema-help");
  return res.data;
}
```

- [ ] **Step 3: Write the failing test**

Replace the full contents of `frontend/src/pages/ProjectPlaybookEditorPage.test.tsx`:

```tsx
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

const EMPTY_SCHEMA_HELP = { ok: true, status: 200, json: async () => ({ data: [], paging: {} }) };

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
      if (url === "/api/playbooks/schema-help") {
        return Promise.resolve(EMPTY_SCHEMA_HELP);
      }
      throw new Error(`unexpected fetch: ${url}`);
    });
    vi.stubGlobal("fetch", mockFetch);

    renderPage("/projects/proj-1/playbooks/new");
    const user = userEvent.setup();

    await waitFor(() => expect(screen.getByRole("option", { name: /bugfix/i })).toBeInTheDocument());
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
      if (url === "/api/playbooks/schema-help") {
        return Promise.resolve(EMPTY_SCHEMA_HELP);
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
      if (url === "/api/playbooks/schema-help") {
        return Promise.resolve(EMPTY_SCHEMA_HELP);
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

  it("renders the field reference panel grouped by model, from the schema-help endpoint", async () => {
    const mockFetch = vi.fn().mockImplementation((url: string) => {
      if (url === "/api/playbooks/schema-help") {
        return Promise.resolve({
          ok: true, status: 200,
          json: async () => ({
            data: [
              { model: "PlaybookSpec", field: "id", type: "str", default: null, required: true, description: "Unique id for this playbook." },
              { model: "StepSpec", field: "writes", type: "bool", default: "False", required: false, description: "Whether this step writes to the project's codebase." },
              { model: "LoopSpec", field: "max_rounds", type: "int", default: "5", required: false, description: "Hard cap on loop re-runs." },
            ],
            paging: {},
          }),
        });
      }
      return Promise.resolve({ ok: true, status: 200, json: async () => ({ data: [], paging: {} }) });
    });
    vi.stubGlobal("fetch", mockFetch);

    renderPage("/projects/proj-1/playbooks/new");

    await waitFor(() => expect(screen.getByText("writes")).toBeInTheDocument());
    expect(screen.getByText("Playbook fields")).toBeInTheDocument();
    expect(screen.getByText("Step fields")).toBeInTheDocument();
    expect(screen.getByText("Loop fields")).toBeInTheDocument();
    expect(screen.getByText(/whether this step writes to the project's codebase/i)).toBeInTheDocument();
  });
});
```

- [ ] **Step 4: Run the test to verify only the new case fails**

Run: `cd frontend && npm run test -- ProjectPlaybookEditorPage.test.tsx`
Expected: 3 passed (the pre-existing cases, now with the added
`/api/playbooks/schema-help` mock branch), 1 failed (the new reference-panel
case — the panel doesn't exist yet).

- [ ] **Step 5: Implement the reference panel**

In `frontend/src/pages/ProjectPlaybookEditorPage.tsx`, add these imports
alongside the existing ones:

```tsx
import { getPlaybookSchemaHelp } from "../api/playbookSchema";
import type { SchemaFieldDoc } from "../api/types";
import { Card } from "../components/ui/display/Card";
```

Add this component above `export default function ProjectPlaybookEditorPage()`:

```tsx
const FIELD_GROUPS: { model: SchemaFieldDoc["model"]; label: string }[] = [
  { model: "PlaybookSpec", label: "Playbook fields" },
  { model: "StepSpec", label: "Step fields" },
  { model: "LoopSpec", label: "Loop fields" },
];

function PlaybookFieldReference() {
  const { data: fields } = useQuery({
    queryKey: ["playbook-schema-help"],
    queryFn: getPlaybookSchemaHelp,
    staleTime: Infinity,
  });

  return (
    <details open className="w-full max-w-sm shrink-0">
      <summary className="cursor-pointer text-sm font-semibold uppercase tracking-wide text-[var(--muted-foreground)]">
        Playbook field reference
      </summary>
      <Card className="mt-2 flex flex-col gap-4 p-3 text-sm">
        {FIELD_GROUPS.map((group) => (
          <div key={group.model} className="flex flex-col gap-2">
            <h4 className="font-semibold">{group.label}</h4>
            {(fields ?? [])
              .filter((f) => f.model === group.model)
              .map((f) => (
                <div key={`${f.model}.${f.field}`} className="flex flex-col gap-0.5">
                  <div className="flex items-baseline gap-2 font-mono text-xs">
                    <span className="font-semibold">{f.field}</span>
                    <span className="text-[var(--muted-foreground)]">{f.type}</span>
                    <span className="text-[var(--muted-foreground)]">
                      {f.required ? "required" : `default: ${f.default}`}
                    </span>
                  </div>
                  <p className="text-xs text-[var(--muted-foreground)]">{f.description}</p>
                </div>
              ))}
          </div>
        ))}
      </Card>
    </details>
  );
}
```

Then change the component's `return` statement: wrap the existing
`{!isEdit && (...)}` block, the `Playbook TOML` field, and the Save/Cancel
button row in a new flex row alongside `<PlaybookFieldReference />`.
Replace:

```tsx
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
```

with:

```tsx
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

      <div className="flex flex-wrap gap-4">
      <div className="flex flex-1 min-w-[20rem] flex-col gap-4">

      {!isEdit && (
```

And replace the closing of the current outer `<div>` — i.e. this exact
tail of the file:

```tsx
        <Button variant="outline" onClick={() => navigate(`/projects/${projectId}`)}>
          Cancel
        </Button>
      </div>
    </div>
  );
}
```

with:

```tsx
        <Button variant="outline" onClick={() => navigate(`/projects/${projectId}`)}>
          Cancel
        </Button>
      </div>

      </div>
      <PlaybookFieldReference />
      </div>
    </div>
  );
}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd frontend && npm run test -- ProjectPlaybookEditorPage.test.tsx`
Expected: 4 passed

- [ ] **Step 7: Type-check and full frontend suite**

Run: `cd frontend && npx tsc -b && npm run test`
Expected: 0 type errors; full suite passing

- [ ] **Step 8: Commit**

```bash
git add frontend/src/api/types.ts frontend/src/api/playbookSchema.ts frontend/src/pages/ProjectPlaybookEditorPage.tsx frontend/src/pages/ProjectPlaybookEditorPage.test.tsx
git commit -m "feat(ui): add a read-only playbook field reference panel, backed by /api/playbooks/schema-help"
```

---

## Verification

- Backend: `uv run pytest -v` (baseline 310, expect 313 after Task 1).
- Frontend: `cd frontend && npx tsc -b && npm run test && npm run build`
  (baseline 117 vitest tests, expect 117 + 3 (PlaybookPicker) + 1
  (reference panel) − 0 removed = 121; `NewRunForm.test.tsx`'s 3 tests and
  `ProjectDetailPage.test.tsx`'s existing count are rewritten/unchanged in
  place, not added to).
- Manual: `uv run foundry serve --db /tmp/foundry.db --port 8000` +
  `cd frontend && npm run dev` — on the Runs page, confirm the playbook
  dropdown lists both a project's own playbooks and pack templates, and
  that picking one starts a run with the right path; on a project's
  Settings form, confirm the same dropdown sets the default; on the
  playbook editor page, confirm the reference panel lists every
  `PlaybookSpec`/`StepSpec`/`LoopSpec` field with its type/default/description.
