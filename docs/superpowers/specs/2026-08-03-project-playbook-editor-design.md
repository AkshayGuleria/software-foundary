# Project-Specific Playbook Editor — Design

## Summary

Foundry's playbooks (the declarative TOML "pipelines" that drive every run)
are 100% filesystem-based today — the only ones that exist are the two
shipped in `packs/default/`, and starting a run means typing an exact file
path into a plain text `<Input>`. Two real problems fall out of that: the
path input is visually too narrow to comfortably read/edit a path like
`packs/default/playbooks/sdlc_story.toml`, and there is no way to create or
tweak a playbook without editing files on the server's disk by hand. This
adds a proper in-dashboard editor: each project gets its own library of
playbook copies, clonable from any existing pack playbook as a starting
template, editable as raw TOML, validated with the exact same rules a real
run already enforces (schema + plan-first lint) before anything is saved.

This design was developed and approved via Claude Code's native plan mode
(exploration of the existing filesystem-based playbook/pack architecture,
one design-validation pass, three clarifying questions to the user) rather
than through `superpowers:brainstorming`'s own dialogue flow — the outcome
is equivalent (explored codebase, proposed approach, user-approved design),
recorded here to keep this project's spec-per-feature convention intact
before `superpowers:writing-plans` turns it into a task-by-task plan.

## Goals

- Widen the two existing playbook-path text inputs (`ProjectDetailPage`
  Settings, `NewRunForm`) — currently shrink to browser-default width inside
  an unconstrained flex row.
- Let a project accumulate its own library of playbook copies, each clonable
  from any playbook already shipped in a pack (starting with `packs/default`'s
  two), editable as raw TOML, and re-savable.
- Validate every save with the exact same rules a real run already enforces
  — `load_playbook` (schema) and `lint_plan_first` (the plan-first invariant:
  every `writes=true` step must be transitively downstream of a
  `derived_gate`) — no new validation logic, no client-side reimplementation.
- Keep zero new database schema (this codebase has no migration tooling —
  `create_all` only adds new tables, never columns to existing ones — so
  avoiding a new table for this feature is a deliberate risk reduction).

## Non-Goals

- A structured step-by-step form/DAG-builder editor — raw TOML only, per the
  user's explicit choice.
- A code-editor dependency (CodeMirror/Monaco) — plain `Textarea`, no new
  npm dependency, consistent with this project's build history.
- A picker dropdown on `NewRunForm` sourced from a project's own playbooks —
  explicit fast-follow, out of scope for this pass.
- Reviving the dormant `Pack` ORM table (`store/models.py`, unused since
  M4b) — different granularity (whole pack, no project scoping), out of
  scope.
- Reference-counting deletes against past `Run.playbook_ref` rows, or any
  `created_at`/clone-lineage metadata beyond filesystem `mtime` — both
  explicitly deferred to keep playbook files fully portable/export-clean.

## Architecture

### Storage: pure filesystem, no new DB table

New tree, relative to server CWD, identical convention to the existing
`PACKS_ROOT = "packs"` constant in `src/foundry/api/routes/packs.py`:

```
project_playbooks/<project_id>/<slug>.toml
```

No `pack.toml` sibling is ever written alongside these files. This is
deliberate: `resolve_pack_version()`/`resolve_pack_manifest()`
(`src/foundry/packs/resolve.py`) walk up to 5 parent directories from a
playbook's path looking for `pack.toml`; from a `project_playbooks/...` path
that walk finds nothing in a normal deployment, so both already fall back to
`"local"` / `None` — the exact same behavior every other ad-hoc playbook path
gets today. No special-casing needed anywhere in the existing resolve/run
pipeline.

A new module, `src/foundry/project_playbooks/loader.py`, mirrors
`src/foundry/packs/loader.py`'s shape (pure filesystem I/O, root passed in by
the caller, "skip a file that fails to parse rather than erroring the whole
list" — the same fix M4b shipped for `list_packs`). Its write path is the
single validation gate: it writes to a `.tmp` file, calls the *existing*
`load_playbook`/`lint_plan_first` unchanged, and only atomically replaces the
real file (`os.replace`, atomic on POSIX) on success — a failed save never
corrupts a previously-good copy.

### API surface

New router `src/foundry/api/routes/project_playbooks.py`, registered in
`src/foundry/api/app.py` alongside the existing 12: full CRUD under
`/api/projects/{project_id}/playbooks[/{slug}]`, following this codebase's
established `ApiResponse`/`FoundryApiError` envelope pattern exactly — a
load/lint failure on save surfaces as the same `400 VALIDATION_ERROR` shape
`POST /api/runs` already produces, so the frontend's existing
`ApiClientError` parsing needs zero new code.

One more small read-only endpoint, added to the existing `packs.py` router:
`GET /api/packs/{pack_id}/playbooks/{rel_path:path}` returning a template's
raw TOML text, for the clone flow's preview-before-save step (below).

`POST /api/runs` and `Project.default_playbook_path` need **zero changes** —
both already just store/consume an opaque path string, and a project
playbook's stable path slots in unmodified, exactly like any `packs/...`
path today.

### Frontend

- Two width-fix `className` changes (`ProjectDetailPage.tsx`,
  `NewRunForm.tsx`) — independent, ship first, no dependency on anything
  else here.
- A new `frontend/src/api/projectPlaybooks.ts` client, mirroring the existing
  `packs.ts`/`projects.ts` thin-wrapper pattern.
- A new `ProjectPlaybookEditorPage.tsx` at `/projects/:id/playbooks/new` and
  `/projects/:id/playbooks/:slug` (one component, branches on route params):
  create mode offers a template `Select` (sourced from `listPacks()`) that
  previews the chosen template's content into the `Textarea` before anything
  is saved (the clone-preview endpoint above exists for exactly this); edit
  mode prefills from the existing copy. Save surfaces server validation
  errors inline; no client-side TOML/lint logic.
- A new "Playbooks" section on `ProjectDetailPage.tsx`, following the same
  `Card`-list pattern already used for that page's Runs section.

## Decisions made with the user

- **Storage location:** Foundry-side directory outside any project's own
  repo (not inside `Project.path`) — keeps target repos clean, matches how
  `packs/` already works.
- **Editor complexity:** raw TOML text editor, not a structured form/DAG
  builder.
- **Clone flow:** preview-first (small new read-only endpoint) rather than
  save-immediately-on-select.
- **Slug collisions:** reject with `409 Conflict`, matching this codebase's
  existing `pause`/`archive`/`activate` conflict-error usage, rather than
  auto-suffixing.
- **`NewRunForm` picker:** fast-follow, not this pass.

## Testing

TDD-first per this project's house style. `FakeDriver`-first doesn't apply
(no orchestrator/driver involvement — this is filesystem CRUD + a page), but
plan-first-lint-as-enforced-invariant does: the single highest-value test in
the eventual plan is proving that saving a `writes=true` step not downstream
of a `derived_gate` is rejected, exactly as it already is for real runs — the
easiest thing to accidentally bypass in a brand-new write path. An
end-to-end test (create a project playbook via the API, then start a real
run against its returned path) proves the full-stack integration claim, not
just the storage-layer one.
