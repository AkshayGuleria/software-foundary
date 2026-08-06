# Requirement Injection for Run Prompts — Design

## Summary

Foundry's playbook engine has no way to feed a requirement or spec into a
run's first agent session. `RunCreate` has no such field; `render_prompt()`
only ever includes the role description, step id, the artifact kind to
produce, upstream input files, and keyword-matched memory items. For any
playbook's entry step (a step with no `needs`), `input_files` is empty and
nothing is injected at all — the agent gets a role header and "produce an
artifact of kind X," nothing about what the actual ask is. This is a known,
explicitly-deferred gap: `docs/design-deviations.md`'s A4/G1 flag the
design doc's §11 "chat-to-role" mechanism as never built, deferred since
M1a. This closes it with a minimal mechanism: an optional requirement
(inline text or a file-path reference) attached at run creation, injected
into entry steps' prompts only.

## Goals

- Add `requirement_text: str | None` and `requirement_path: str | None` to
  `RunCreate` and the `Run` model — optional, mutually exclusive.
- Inject the requirement into the prompt of every **entry step** (a step
  with no `needs` — computed today via `not needed_ids` in
  `tick.py`'s `_compose_context_bundle`/`dispatch`). Downstream steps see it
  only transitively through whatever artifact the entry step produces, same
  as the existing `input_files` model — no new plumbing for the rest of the
  DAG.
- `requirement_text` is inlined as literal prompt text.
  `requirement_path` is rendered as a path reference only (not read
  server-side) — consistent with how `input_files` already works: paths are
  listed in the prompt, the real driver resolves them against its own
  `cwd`.
- CLI parity: `foundry run` gains `--requirement-text`/`--requirement-path`
  flags alongside the existing `--driver` flag.
- Dashboard parity: `NewRunForm.tsx` gains a "Requirement" textarea and a
  "...or a file path in the repo" input, mutually exclusive in the UI
  (matching the backend's mutual-exclusivity validation).

## Non-Goals

- No display of the requirement on the run-detail page — `RunOut` is
  unchanged this pass.
- No server-side reading, validation, or existence-checking of
  `requirement_path` — it's a path reference only, exactly like
  `input_files`.
- No injection into non-entry steps — downstream steps rely on the
  artifact chain, as they already do today.
- No migration tooling added — this codebase has none (`design-deviations.md`
  D1, deferred to M5). New nullable `Run` columns on a pre-existing db will
  correctly trip the already-built `SchemaDriftError` check
  (`src/foundry/store/db.py`'s `init_db`) with a clear message naming the
  missing columns — the same safety net that already exists for this exact
  situation, not new risk introduced by this feature.

## Backend

### `Run` model — `src/foundry/store/models.py`

Two new nullable columns on the existing `Run` class:

```python
requirement_text: Mapped[str | None] = mapped_column(String, nullable=True)
requirement_path: Mapped[str | None] = mapped_column(String, nullable=True)
```

### `Store.create_run()` — `src/foundry/store/store.py`

Two new optional kwargs, threaded straight into the `Run(...)` constructor
call, defaulting to `None` — every existing caller (demo-seed, CLI, API,
tests) is unaffected unless it opts in:

```python
async def create_run(
    self,
    project_id: str,
    playbook_ref: str,
    title: str,
    pack_version_pin: str = "local",
    driver: str = "fake",
    token_budget: int = 0,
    requirement_text: str | None = None,
    requirement_path: str | None = None,
) -> Run:
```

### `render_prompt()` — `src/foundry/orchestrator/prompt.py`

Two new optional params. When either is set, a new `# Requirement` section
is rendered right after the step header, before `produces`:

```python
def render_prompt(
    role: RoleSpec | None,
    step_id: str,
    produces: str | None,
    input_files: list[str],
    memory_items: list[Memory],
    requirement_text: str | None = None,
    requirement_path: str | None = None,
) -> str:
    lines = [_role_header(role, "unknown"), f"\n# Step: {step_id}"]
    if requirement_text or requirement_path:
        lines.append("\n# Requirement")
        if requirement_text:
            lines.append(requirement_text)
        if requirement_path:
            lines.append(f"See `{requirement_path}` in the project repo for the full requirement.")
    if produces:
        lines.append(f"Produce an artifact of kind: {produces}")
    if input_files:
        lines.append("\n# Input files in context:")
        lines.extend(f"- {f}" for f in input_files)
    if memory_items:
        lines.append("\n# Relevant memory:")
        for m in memory_items:
            lines.append(f"## {m.title}\n{m.body_md}")
    return "\n".join(lines)
```

### `tick.py` dispatch — `src/foundry/orchestrator/tick.py`

`dispatch()`'s loop already computes, per task unit, whether it has
upstream deps (via `_compose_context_bundle`'s `needed_ids`). The single
`render_prompt(...)` call site (currently `prompt = render_prompt(role_spec, step.id, step.produces, bundle_files, memory_items)`)
needs the entry-step check threaded in: only pass `run.requirement_text`/
`run.requirement_path` when the task unit has no upstream deps. The exact
shape of this change (whether `_compose_context_bundle` returns an
`is_entry_step` bool alongside its existing tuple, or `dispatch` recomputes
`needed_ids` itself) is an implementation detail for the plan to pin down
by reading the current function bodies — the important constraint is: the
requirement is passed if and only if the dispatching unit has no `needs`.

### `RunCreate` / route — `src/foundry/api/routes/runs.py`

```python
class RunCreate(BaseModel):
    project_id: str
    playbook_path: str
    title: str | None = None
    gate_overrides: dict[str, Literal["approved", "rejected"]] | None = None
    driver: Literal["fake", "codex", "claude"] = "fake"
    token_budget: int | None = None
    requirement_text: str | None = None
    requirement_path: str | None = None
```

In the `POST /runs` handler, before creating the run: if both
`requirement_text` and `requirement_path` are set (non-empty), raise
`ValidationApiError("requirement_text and requirement_path are mutually exclusive")`
— same pattern as the existing `fan_out`/`fan_out_from` mutual-exclusivity
check in `playbook/schema.py`, and the existing `ValidationApiError` usage
already in this route for playbook load/lint failures. Pass both fields
through to `store.create_run(...)`.

### CLI — `src/foundry/cli.py`

`foundry run` gains two new `typer.Option`s, `--requirement-text` and
`--requirement-path`, both `str | None = None`, threaded through `_run()`'s
signature into its `store.create_run(...)` call. Same mutual-exclusivity
check as the API route, raising `typer.Exit(1)` with a stderr message on
violation (matching this command's existing error-handling style for
`PlaybookLoadError`/`PlaybookLintError`/`SchemaDriftError`).

## Frontend

### `NewRunForm.tsx`

Two new optional fields below the existing playbook picker: a `Textarea`
labeled "Requirement (optional)" and an `Input` labeled "...or a file path
in the repo (optional)". Mutually exclusive in the UI: typing into one
clears/disables the other (mirrors the backend's validation instead of
letting a user hit a 400 that could've been prevented client-side). Both
submitted as `requirement_text`/`requirement_path` on the existing
`onSubmit` payload, `undefined` when empty (matching the existing `title`
field's `|| undefined` pattern already in this component).

### `frontend/src/api/types.ts` / `frontend/src/api/runs.ts`

Whatever `createRun`'s input type currently is (read the actual file to
confirm) gains `requirement_text?: string` and `requirement_path?: string`.

## Testing

- `tests/orchestrator/test_prompt.py`: extend for the two new `render_prompt`
  params — a case with `requirement_text` set renders the `# Requirement`
  section with the literal text; a case with `requirement_path` set renders
  the path-reference line, not file content; a case with neither set
  renders identically to today (regression guard); a case asserting the
  section is *absent* entirely when neither is set (not an empty section).
- A dispatch-level test (`tests/orchestrator/` — find the right existing
  file for `Orchestrator`/`TickEngine` dispatch tests) proving: a run
  created with `requirement_text` set produces an entry step's session
  prompt containing that text, and a downstream (has-`needs`) step's prompt
  does not contain it directly.
- `tests/api/test_runs_route.py` (or wherever `POST /runs` is tested today):
  a 400 case for both fields set simultaneously, and a round-trip case
  proving a run created with `requirement_text` set actually reaches the
  dispatched session's prompt (via the store/orchestrator, not just that
  the field was accepted).
- `NewRunForm.test.tsx`: the two new fields render, are mutually exclusive
  (typing in one clears/disables the other), and submit correctly on the
  `onSubmit` payload.
- CLI: if `tests/test_cli*.py` already covers `foundry run`'s option
  parsing, extend it for the two new flags' happy path + the
  mutual-exclusivity error case.

## Verification

- Backend: `uv run pytest -v` full suite (baseline 315 passing before this
  work).
- Frontend: `cd frontend && npx tsc -b && npm run test && npm run build`
  (baseline 122 vitest tests).
- Manual: `uv run foundry serve --db /tmp/foundry.db --port 8000` +
  `cd frontend && npm run dev` — start a run from the dashboard with a
  requirement typed in, confirm (via the run's session/event detail view)
  that the entry step's session prompt actually contains the requirement
  text.
