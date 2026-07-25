# Project settings (driver, budget, default playbook) — design

Source: `docs/design-deviations.md` finding G4 — design doc §11's "Packs &
settings" view names gate-policy defaults, driver config, and budgets as
settings a project should have. `PacksPage` today is pure view-only (zero
POST/PUT anywhere), and `Project` has no columns for any of this.

## Scope decisions (resolved during brainstorming, not re-litigated here)

- **Per-project, not per-pack.** Packs are shared, versioned, on-disk
  (`packs/default/`); the DB's `Pack` table is dormant by design (M4b
  decision, never populated). Projects are what's independently configured
  per F11. Building on the dormant `Pack` table would be reviving a second
  dormant mechanism to fix one deviation — not this scope.
- **No gate-policy defaults.** `gate_overrides` is a dict keyed by a
  specific playbook's step ids (`{"implement": "approved"}`); a generic
  per-project default doesn't have a stable shape independent of which
  playbook a given run uses. Needs its own design once there's a concrete
  playbook-aware UI to hang it on.
- **Store AND apply**, not store-only. A settings panel nothing reads from
  is exactly the "built but dormant" pattern this whole audit line exists
  to catch (see `docs/design-deviations.md` section C). Settings must
  actually affect run creation the moment they ship.

## In scope

**Backend:**
- `Project` gains 3 columns: `default_driver: str = "fake"`,
  `default_token_budget: int = 0`, `default_playbook_path: str | None = None`.
  Direct model edit — no Alembic (D1's resolution: unused until M5 actually
  needs migrations).
- New `PATCH /api/projects/{id}/settings` endpoint. Partial update — a
  request body may include any subset of the 3 fields; only provided fields
  change. Reuses `Store.update_project(id, **fields)`
  (`src/foundry/store/store.py:95-103`), already generic, no changes needed
  there.
- `ProjectOut` (`src/foundry/api/routes/projects.py`) gains the 3 new
  fields, so `GET /api/projects/{id}` and `GET /api/projects` both return
  them — `ProjectDetailPage` needs them to populate the settings form, and
  `NewRunForm` needs them (via the projects list it already fetches) to
  pre-fill.
- `Store.create_run` gains a `token_budget: int = 0` parameter, threaded
  into the `Run(...)` construction. `RunCreate`
  (`src/foundry/api/routes/runs.py`) gains `token_budget: int | None = None`.
  The `create_run` route resolves the effective value:
  `body.token_budget if body.token_budget is not None else project.default_token_budget`.
  This is the only run-creation-path change — `playbook_path` and `driver`
  stay exactly as required/optional as they are today; only their pre-filled
  *initial value* in the form changes (frontend-only), not their API
  contract.

**Frontend:**
- `ProjectDetailPage` (built in the G3 round) gains a "Settings" section:
  driver `<select>` (`fake`/`codex`/`claude`), token-budget number input,
  default-playbook-path text input. Submits via a new
  `updateProjectSettings(id, fields)` API client function calling `PATCH`,
  invalidates `["project", id]` on success (same query key the page's
  header/data already use, so the whole page reflects the new values
  immediately, not just the settings form).
- `NewRunForm` gains a driver `<select>` — currently missing entirely
  despite the backend supporting driver selection since the earlier
  deviation-fixes round. Both the driver select and the playbook-path input
  pre-fill from the selected project's `default_driver`/
  `default_playbook_path` when the project changes (via a `useEffect` or
  equivalent keyed on `projectId`), but remain freely editable before
  submit — a per-run override stays as easy as it is today, this only
  changes the *starting* value.

## Out of scope

- Gate-policy defaults (see above).
- Any Pack-table revival or pack-level settings.
- A `token_budget` field in `NewRunForm`'s UI — the default applies
  automatically server-side; overriding it per-run via the API remains
  possible (`RunCreate.token_budget`) but isn't exposed in this form this
  round, since there's no design-doc case motivating a per-run override in
  the common path.
- Any change to how `token_budget` is *enforced* — `orchestrator/budget.py`
  and its 80%/100% warning/exceeded thresholds are unchanged; this scope is
  only about how the number gets set at run-creation time, not how it's
  checked afterward.

## Testing

Backend: `Store.create_run` accepting/threading `token_budget`;
`PATCH /api/projects/{id}/settings` partial-update semantics (updating one
field leaves the others untouched); `create_run` route's default-resolution
logic (explicit override wins, falls back to project default when omitted).
Frontend: settings-form submit + query invalidation; `NewRunForm`'s pre-fill
behavior when project selection changes, and that it stays overridable.
