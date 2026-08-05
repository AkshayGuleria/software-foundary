# Playbook Picker + Schema-Help Reference — Design

## Summary

Starting a run requires an exact playbook TOML path, and today that path is
still a hand-typed free-text field in two places (`NewRunForm`, the project
Settings form's "Default playbook path") — a known gap, explicitly deferred
as a fast-follow when the project-specific playbook editor shipped
(`docs/superpowers/specs/2026-08-03-project-playbook-editor-design.md`).
This closes that gap with a shared dropdown picker sourced from what
already exists (a project's own playbooks + every pack's shipped
playbooks), plus a "New playbook" link for the case where neither list has
what's needed. It also adds a read-only reference panel to the playbook
editor page, so someone writing raw TOML can see every `PlaybookSpec`/
`StepSpec`/`LoopSpec` field, its type/default, and what it does, without
leaving the page.

## Goals

- Replace the free-text playbook-path input in `NewRunForm` and
  `ProjectDetailPage`'s Settings form with a shared `PlaybookPicker`
  component: a grouped dropdown (project playbooks / pack templates) plus a
  "New playbook" link to `/projects/:id/playbooks/new`.
- Resolve pack-playbook dropdown entries to real run-ready paths
  (`packs/<pack_id>/<rel_path>`) client-side — no new backend endpoint
  needed for this part, `listPacks()` already returns everything required.
- Preserve any already-set path that doesn't match a known option (legacy
  data, hand-edited DB rows) — show it as a synthetic leading "Custom: ..."
  option rather than silently blanking the field.
- Add `GET /api/playbooks/schema-help`, deriving field documentation
  directly from `PlaybookSpec`/`StepSpec`/`LoopSpec`'s own Pydantic
  `Field(description=...)` metadata — single source of truth, no
  hand-duplicated docs that can drift from the real schema.
- Add a read-only reference panel to `ProjectPlaybookEditorPage` showing
  that schema-help content grouped by model, visible alongside the TOML
  textarea.

## Non-Goals

- No manual free-text override alongside the dropdown — per the approved
  design, the dropdown is the only way to set the path in these two forms.
  (A custom/legacy value already in place is still preserved and shown, per
  the Goals section above — this only rules out *typing a new* arbitrary
  path going forward.)
- No snippet-insertion / "insert this step" editor interaction — read-only
  reference only.
- No schema-help caching layer, versioning, or admin editing — it's a thin
  read-only introspection endpoint over an already-existing Pydantic model.
- No changes to TOML validation itself (`load_playbook`/`lint_plan_first`
  unchanged) — this is discovery/UX only.

## Backend

### `GET /api/playbooks/schema-help` (new)

New route file `src/foundry/api/routes/playbook_schema.py`, registered in
`app.py` alongside the other 13 routers. No path/query params, no auth
beyond whatever the rest of `/api` already requires (none, today).

Response: `ApiResponse[list[SchemaFieldDoc]]` where

```python
class SchemaFieldDoc(BaseModel):
    model: Literal["PlaybookSpec", "StepSpec", "LoopSpec"]
    field: str
    type: str          # human-readable, e.g. "str", "bool", "list[str]", "'human' | 'agent' | 'none' | null"
    default: str | None  # repr of the default, or null if the field is required
    required: bool
    description: str
```

Built by iterating `PlaybookSpec.model_fields`, `StepSpec.model_fields`,
`LoopSpec.model_fields` (Pydantic v2's `model_fields` dict) — `type` derived
from `FieldInfo.annotation` formatted to a readable string, `default` from
`FieldInfo.default` (or `None`/required when `FieldInfo.is_required()`),
`description` from `FieldInfo.description`. This means every field on the
three models in `src/foundry/playbook/schema.py` needs a
`Field(description="...")` (or `Field(default=..., description="...")`)
added — currently none have descriptions since nothing has consumed them
until now. This is the only change to `schema.py`; validation behavior
(the `model_validator` in `PlaybookSpec`) is untouched.

## Frontend

### `PlaybookPicker` (new shared component)

`frontend/src/components/PlaybookPicker.tsx`:

```tsx
function PlaybookPicker({
  projectId,
  value,
  onChange,
}: {
  projectId: string;
  value: string;
  onChange: (path: string) => void;
}): JSX.Element
```

- `useQuery(["project-playbooks", projectId], () => listProjectPlaybooks(projectId), { enabled: !!projectId })`
  and `useQuery(["packs"], listPacks)` (already-existing API client
  functions — no new frontend API code beyond this component).
- Renders a `Select` with two `<optgroup>`s: "Project playbooks" (value =
  each `ProjectPlaybookSummary.path`, label = its `playbook_id` or `slug`)
  and "Pack templates" (value = `packs/${pack.id}/${relPath}` for each
  entry in `pack.playbooks`, label = `${pack.id} / ${relPath}`).
- If `value` is truthy and doesn't equal any rendered option's value, a
  leading `<option value={value}>Custom: {value}</option>` is prepended so
  the select's value always matches a real option and nothing already set
  gets silently discarded.
- Disabled (with placeholder text "Select a project first") when
  `!projectId`.
- A "New playbook" `<Link>` to `/projects/${projectId}/playbooks/new`
  rendered next to the `Select`, disabled/hidden under the same
  `!projectId` condition.

### `NewRunForm.tsx` — swap input for picker

Replace the `Input`/`Label` pair at `new-run-playbook` with
`<PlaybookPicker projectId={projectId} value={playbookPath} onChange={setPlaybookPath} />`.
No other state changes — `playbookPath` stays the same piece of state,
still submitted as `playbook_path` unchanged.

### `ProjectDetailPage.tsx` — swap Settings input for picker

Same swap at `project-playbook-path`: `<PlaybookPicker projectId={project.id} value={playbookPath} onChange={setPlaybookPath} />`
inside the existing Settings form. `PATCH` submission logic unchanged.

### `getPlaybookSchemaHelp` API client (new)

`frontend/src/api/playbookSchema.ts`:

```ts
export async function getPlaybookSchemaHelp(): Promise<SchemaFieldDoc[]> {
  const res = await apiFetch<SchemaFieldDoc[]>("/api/playbooks/schema-help");
  return res.data;
}
```

New `SchemaFieldDoc` type in `frontend/src/api/types.ts` matching the
backend shape above.

### Reference panel on `ProjectPlaybookEditorPage.tsx`

New collapsible panel rendered alongside the existing `Textarea` (side by
side in a `flex` row on wide viewports; the panel collapses to a
`<details>`-style toggle below the textarea on narrow ones — no new CSS
breakpoint system, just a flex-wrap the way the rest of this page already
handles width). `useQuery(["playbook-schema-help"], getPlaybookSchemaHelp, { staleTime: Infinity })`.
Content grouped by `model` (Playbook fields, Step fields, Loop fields),
each field row showing name, type, default (or "required"), and
description. Read-only — no interaction beyond expand/collapse.

## Testing

- Backend: `tests/api/test_playbook_schema_route.py` — asserts the response
  contains exactly one entry per real field on `PlaybookSpec`/`StepSpec`/
  `LoopSpec` (derived by comparing against `Model.model_fields.keys()`
  directly, so a future field added to the schema without a description
  fails this test rather than shipping silently undocumented), and spot
  checks a few known fields' `type`/`default`/`required` values (e.g.
  `StepSpec.gate` is optional with default `"none"`, `PlaybookSpec.steps`
  is required with no default).
- Frontend: `PlaybookPicker.test.tsx` — grouped-options rendering from
  mocked `listProjectPlaybooks`/`listPacks`, the custom-value-preserved
  case, the `!projectId` disabled case, `onChange` fires with the right
  path for both a project-playbook and a pack-template selection.
  `NewRunForm.test.tsx`/`ProjectDetailPage.test.tsx` updated to drive the
  picker instead of typing into a text input. `ProjectPlaybookEditorPage.test.tsx`
  gains a case asserting the reference panel renders fetched fields grouped
  by model.

## Dependency Order

Backend schema-help endpoint (adding `Field(description=...)` to
`schema.py` + the new route) has no dependency on anything else and can
ship first/independently. `PlaybookPicker` depends only on already-existing
`listProjectPlaybooks`/`listPacks` — independent of the schema-help work.
The reference panel depends on the schema-help endpoint. The two `PlaybookPicker`
call-site swaps depend only on the component itself.
