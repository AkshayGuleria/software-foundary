# Requirement Injection for Run Prompts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a run be started with an optional requirement (inline text or
a repo file-path reference), injected into the prompt of every playbook
entry step (a step with no `needs`) — closing design-deviations.md's A4/G1
gap.

**Architecture:** Two new nullable `Run` columns carry the input from
creation time. `render_prompt()` gains two optional params rendering a new
`# Requirement` section. `tick.py`'s dispatch loop already computes, per
task unit, whether it has upstream deps (`needed_ids`) — `not needed_ids`
is exactly "entry step," so the existing per-unit loop passes the run's
requirement through only for those units. API route and CLI both accept
the two fields (mutually exclusive), pass-through to `Store.create_run()`.
Dashboard gets matching mutually-exclusive form fields.

**Tech Stack:** Python 3.12+, SQLAlchemy 2 async, FastAPI, Typer (backend);
React + TypeScript (frontend) — no new dependencies.

## Global Constraints

- `requirement_text` and `requirement_path` are mutually exclusive — both
  set is a validation error (400 at the API layer, exit 1 at the CLI
  layer, disabled-input pairing in the UI). Both are optional; neither set
  reproduces today's behavior byte-for-byte (regression-tested).
- `requirement_path` is a path *reference* only — never read, validated, or
  checked for existence server-side. It renders as a reference line in the
  prompt, exactly like `input_files` already does (paths listed, not
  content inlined).
- Injection targets **entry steps only** (`not needed_ids` in
  `tick.py`'s `_compose_context_bundle`) — never downstream steps.
- No `RunOut` change, no run-detail-page display — out of scope this pass.
- No migration tooling — new nullable `Run` columns rely on the existing
  `SchemaDriftError` check (`src/foundry/store/db.py`) to surface a clear
  error against a pre-existing db, same as any other schema change in this
  codebase (`design-deviations.md` D1).

---

### Task 1: Core mechanism — model, store, prompt rendering, dispatch wiring

**Files:**
- Modify: `src/foundry/store/models.py` (`Run` class)
- Modify: `src/foundry/store/store.py` (`create_run`)
- Modify: `src/foundry/orchestrator/prompt.py` (`render_prompt`)
- Modify: `src/foundry/orchestrator/tick.py` (`_compose_context_bundle`, `dispatch`)
- Test: `tests/orchestrator/test_prompt.py`
- Test: `tests/orchestrator/test_tick.py`

**Interfaces:**
- Produces: `Run.requirement_text: str | None`, `Run.requirement_path: str | None`
  (columns); `Store.create_run(..., requirement_text: str | None = None, requirement_path: str | None = None)`;
  `render_prompt(role, step_id, produces, input_files, memory_items, requirement_text: str | None = None, requirement_path: str | None = None) -> str`.
  Tasks 2 and 3 (API route, CLI) call `store.create_run(...)` with these
  two new kwargs.

- [ ] **Step 1: Write the failing tests**

Append to `tests/orchestrator/test_prompt.py`:

```python
def test_render_prompt_includes_requirement_text():
    prompt = render_prompt(None, "diagnose", None, [], [], requirement_text="Fix the login bug.")
    assert "# Requirement" in prompt
    assert "Fix the login bug." in prompt


def test_render_prompt_includes_requirement_path_as_a_reference_not_content():
    prompt = render_prompt(None, "diagnose", None, [], [], requirement_path="docs/REQUIREMENTS.md")
    assert "# Requirement" in prompt
    assert "docs/REQUIREMENTS.md" in prompt


def test_render_prompt_omits_requirement_section_when_neither_is_set():
    prompt = render_prompt(None, "diagnose", None, [], [])
    assert "# Requirement" not in prompt


def test_render_prompt_unaffected_by_explicit_none_requirement_params():
    before = render_prompt(None, "code", "code_diff_artifact", ["src/foo.py"], [])
    after = render_prompt(
        None, "code", "code_diff_artifact", ["src/foo.py"], [],
        requirement_text=None, requirement_path=None,
    )
    assert before == after
```

Append to `tests/orchestrator/test_tick.py` (reuses the existing
`CapturingDriver` class and `FIXTURE` constant already defined in this
file — `FIXTURE = "tests/orchestrator/fixtures/linear_demo.toml"`, a
3-step `plan -> implement -> review` playbook where `plan` has no `needs`
and is the only entry step):

```python
@pytest.mark.asyncio
async def test_dispatch_injects_requirement_into_entry_step_prompt_only(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo4", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(
        project.id, FIXTURE, "demo run 4", requirement_text="Add a login page."
    )
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a", "b"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    driver = CapturingDriver(script)
    orchestrator = Orchestrator(store, driver, playbook)

    await orchestrator.run_to_completion(run.id)

    entry_specs = [s for s in driver.captured_specs if s.step_id == "plan"]
    downstream_specs = [s for s in driver.captured_specs if s.step_id != "plan"]
    assert entry_specs and all("Add a login page." in s.prompt for s in entry_specs)
    assert downstream_specs
    assert not any("Add a login page." in s.prompt for s in downstream_specs)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_prompt.py tests/orchestrator/test_tick.py -v`
Expected: the 4 new `test_prompt.py` cases FAIL with `TypeError: render_prompt() got an unexpected keyword argument 'requirement_text'`;
the new `test_tick.py` case FAILS on the `entry_specs` assertion (the text
isn't in the prompt yet).

- [ ] **Step 3: Add the `Run` columns**

In `src/foundry/store/models.py`, inside the `Run` class, add these two
lines after the existing `gate_overrides_json` column:

```python
    requirement_text: Mapped[str | None] = mapped_column(String, nullable=True)
    requirement_path: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4: Extend `Store.create_run`**

In `src/foundry/store/store.py`, change the `create_run` signature and body to:

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
        async def _op(session):
            run = Run(
                project_id=project_id,
                playbook_ref=playbook_ref,
                title=title,
                pack_version_pin=pack_version_pin,
                driver=driver,
                token_budget=token_budget,
                requirement_text=requirement_text,
                requirement_path=requirement_path,
            )
            session.add(run)
            await session.flush()
            return run

        return await self.write(_op)
```

- [ ] **Step 5: Extend `render_prompt`**

Replace the full contents of `src/foundry/orchestrator/prompt.py`'s
`render_prompt` function with:

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

(Only the two new params and the new `if requirement_text or requirement_path:`
block are new — everything else in the function is unchanged.)

- [ ] **Step 6: Wire dispatch to pass the requirement for entry steps only**

In `src/foundry/orchestrator/tick.py`, change `_compose_context_bundle`'s
return type and final return line. Its current signature and tail:

```python
    async def _compose_context_bundle(
        self, run_id: str, task_unit: WorkUnit
    ) -> tuple[list[str], list[Memory], int]:
```

and its tail:

```python
        bundle_chars = sum(len(f) for f in bundle_files) + sum(len(m.body_md) for m in memory_items)
        return sorted(bundle_files), memory_items, bundle_chars
```

Change the signature to:

```python
    async def _compose_context_bundle(
        self, run_id: str, task_unit: WorkUnit
    ) -> tuple[list[str], list[Memory], int, bool]:
```

and change the tail to:

```python
        bundle_chars = sum(len(f) for f in bundle_files) + sum(len(m.body_md) for m in memory_items)
        # is_entry_step reuses needed_ids computed above: an entry step is
        # exactly one with no upstream deps.
        is_entry_step = not needed_ids
        return sorted(bundle_files), memory_items, bundle_chars, is_entry_step
```

Then in `dispatch()`, update the call site and the `render_prompt` call.
Current:

```python
            bundle_files, memory_items, bundle_chars = await self._compose_context_bundle(run_id, task_unit)
            await self.store.append_event(
                run_id,
                session_unit.id,
                "context.composed",
                {
                    "files_in_bundle": len(bundle_files),
                    "memory_items": len(memory_items),
                    "bundle_chars": bundle_chars,
                },
            )

            role_spec = self._roles_by_id.get(step.role)
            model = role_spec.model if role_spec is not None else "fake"
            prompt = render_prompt(role_spec, step.id, step.produces, bundle_files, memory_items)
```

Replace with:

```python
            bundle_files, memory_items, bundle_chars, is_entry_step = await self._compose_context_bundle(
                run_id, task_unit
            )
            await self.store.append_event(
                run_id,
                session_unit.id,
                "context.composed",
                {
                    "files_in_bundle": len(bundle_files),
                    "memory_items": len(memory_items),
                    "bundle_chars": bundle_chars,
                },
            )

            role_spec = self._roles_by_id.get(step.role)
            model = role_spec.model if role_spec is not None else "fake"
            requirement_text = run.requirement_text if (is_entry_step and run is not None) else None
            requirement_path = run.requirement_path if (is_entry_step and run is not None) else None
            prompt = render_prompt(
                role_spec,
                step.id,
                step.produces,
                bundle_files,
                memory_items,
                requirement_text=requirement_text,
                requirement_path=requirement_path,
            )
```

(`run` is already in scope in `dispatch()` — fetched earlier in the same
function via `run = await self.store.get_run(run_id)`, right before the
budget-check block. No new fetch is needed.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_prompt.py tests/orchestrator/test_tick.py -v`
Expected: all passing, including the 4 new prompt tests and the new
dispatch test.

- [ ] **Step 8: Run the full backend suite**

Run: `uv run pytest -v`
Expected: all passing (baseline 315 + 5 new = 320).

- [ ] **Step 9: Commit**

```bash
git add src/foundry/store/models.py src/foundry/store/store.py src/foundry/orchestrator/prompt.py src/foundry/orchestrator/tick.py tests/orchestrator/test_prompt.py tests/orchestrator/test_tick.py
git commit -m "feat(orchestrator): inject an optional run requirement into entry-step prompts"
```

---

### Task 2: API layer — `RunCreate` + validation + route test

**Files:**
- Modify: `src/foundry/api/routes/runs.py`
- Test: `tests/api/test_runs.py`

**Interfaces:**
- Consumes: `Store.create_run(..., requirement_text=..., requirement_path=...)`
  from Task 1.
- Produces: `RunCreate.requirement_text: str | None`, `RunCreate.requirement_path: str | None`
  on `POST /api/runs`. Task 4 (frontend) sends these two fields.

- [ ] **Step 1: Write the failing tests**

Append to `tests/api/test_runs.py`:

```python
@pytest.mark.asyncio
async def test_create_run_with_both_requirement_fields_returns_400(api_client):
    client, _store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "requirement_text": "Fix the bug.",
            "requirement_path": "docs/REQUIREMENTS.md",
        },
    )
    assert run_resp.status_code == 400, run_resp.text
    assert run_resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_run_persists_requirement_text_on_the_run_row(api_client):
    client, store, _scheduler = api_client

    proj_resp = await client.post("/api/projects", json={"name": "proj", "path": "/tmp/proj"})
    project_id = proj_resp.json()["data"]["id"]

    run_resp = await client.post(
        "/api/runs",
        json={
            "project_id": project_id,
            "playbook_path": "tests/orchestrator/fixtures/linear_demo.toml",
            "requirement_text": "Add a login page.",
        },
    )
    assert run_resp.status_code == 201, run_resp.text
    run_id = run_resp.json()["data"]["id"]

    run_row = await store.get_run(run_id)
    assert run_row.requirement_text == "Add a login page."
    assert run_row.requirement_path is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/api/test_runs.py -v -k requirement`
Expected: FAIL — the 400 case currently returns 201 (no validation exists
yet); the persistence case fails on `run_row.requirement_text` (attribute
exists once Task 1 lands, but is never set since the route doesn't pass it
yet — will be `None` instead of the expected string).

- [ ] **Step 3: Add the fields and validation**

In `src/foundry/api/routes/runs.py`, add two fields to `RunCreate`:

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

In `create_run`, add the mutual-exclusivity check right after the
project-active check (before the playbook load/lint try/except block):

```python
    if body.requirement_text and body.requirement_path:
        raise ValidationApiError("requirement_text and requirement_path are mutually exclusive")
```

And pass both fields through to `store.create_run(...)`:

```python
    run = await store.create_run(
        project.id,
        body.playbook_path,
        title,
        pack_version_pin=pack_version_pin,
        driver=body.driver,
        token_budget=effective_token_budget,
        requirement_text=body.requirement_text,
        requirement_path=body.requirement_path,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/api/test_runs.py -v`
Expected: all passing.

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -v`
Expected: all passing (baseline 320 + 2 new = 322).

- [ ] **Step 6: Commit**

```bash
git add src/foundry/api/routes/runs.py tests/api/test_runs.py
git commit -m "feat(api): accept requirement_text/requirement_path on POST /runs"
```

---

### Task 3: CLI layer — `foundry run` flags

**Files:**
- Modify: `src/foundry/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `Store.create_run(..., requirement_text=..., requirement_path=...)`
  from Task 1.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py` (this file already has a `runner = CliRunner()`
and an `app` import at module scope, and `tests/fixtures/cli_demo.toml`
already exists as the fixture used by `test_run_then_events_smoke`):

```python
def test_run_accepts_requirement_text(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    result = runner.invoke(
        app,
        [
            "run", "tests/fixtures/cli_demo.toml", "--db", db_path,
            "--requirement-text", "Add a login page.",
        ],
    )
    assert result.exit_code == 0, result.output


def test_run_rejects_both_requirement_text_and_requirement_path(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    result = runner.invoke(
        app,
        [
            "run", "tests/fixtures/cli_demo.toml", "--db", db_path,
            "--requirement-text", "Add a login page.",
            "--requirement-path", "docs/REQUIREMENTS.md",
        ],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v -k requirement`
Expected: FAIL with a Typer "no such option: --requirement-text" error (or
equivalent usage error).

- [ ] **Step 3: Add the CLI flags**

In `src/foundry/cli.py`, change the `run` command and `_run` function.
Current `run` command:

```python
@app.command()
def run(playbook_path: str, project_path: str = ".", db: str = "foundry.db", driver: str = "fake") -> None:
    run_id, complete, pending_count = asyncio.run(_run(playbook_path, project_path, db, driver))
```

Replace with:

```python
@app.command()
def run(
    playbook_path: str,
    project_path: str = ".",
    db: str = "foundry.db",
    driver: str = "fake",
    requirement_text: str | None = typer.Option(None, "--requirement-text"),
    requirement_path: str | None = typer.Option(None, "--requirement-path"),
) -> None:
    run_id, complete, pending_count = asyncio.run(
        _run(playbook_path, project_path, db, driver, requirement_text, requirement_path)
    )
```

Current `_run` signature and its first lines:

```python
async def _run(
    playbook_path: str, project_path: str, db: str, driver_name: str = "fake"
) -> tuple[str, bool, int]:
    engine = make_engine(db)
```

Replace with:

```python
async def _run(
    playbook_path: str,
    project_path: str,
    db: str,
    driver_name: str = "fake",
    requirement_text: str | None = None,
    requirement_path: str | None = None,
) -> tuple[str, bool, int]:
    if requirement_text and requirement_path:
        typer.echo("requirement_text and requirement_path are mutually exclusive", err=True)
        raise typer.Exit(1)

    engine = make_engine(db)
```

And in `_run`'s `store.create_run(...)` call, currently:

```python
    run_row = await store.create_run(
        project.id,
        playbook_path,
        playbook.description or playbook.id,
        pack_version_pin=pack_version_pin,
        driver=driver_name,
    )
```

add the two new kwargs:

```python
    run_row = await store.create_run(
        project.id,
        playbook_path,
        playbook.description or playbook.id,
        pack_version_pin=pack_version_pin,
        driver=driver_name,
        requirement_text=requirement_text,
        requirement_path=requirement_path,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all passing.

- [ ] **Step 5: Run the full backend suite**

Run: `uv run pytest -v`
Expected: all passing (baseline 322 + 2 new = 324).

- [ ] **Step 6: Commit**

```bash
git add src/foundry/cli.py tests/test_cli.py
git commit -m "feat(cli): add --requirement-text/--requirement-path to foundry run"
```

---

### Task 4: Frontend — `NewRunForm` fields

**Files:**
- Modify: `frontend/src/api/runs.ts`
- Modify: `frontend/src/components/NewRunForm.tsx`
- Modify: `frontend/src/components/NewRunForm.test.tsx`

**Interfaces:**
- Consumes: `POST /api/runs` accepting `requirement_text`/`requirement_path`
  from Task 2.

- [ ] **Step 1: Write the failing tests**

Add these two `it(...)` blocks inside the existing `describe("NewRunForm", ...)`
block in `frontend/src/components/NewRunForm.test.tsx` (after the existing
three tests, before the closing `});`):

```tsx
  it("requirement text and requirement path fields are mutually exclusive", async () => {
    stubFetch();
    renderForm(vi.fn());
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^requirement \(optional\)/i), "Add a login page.");
    expect(screen.getByLabelText(/file path in the repo/i)).toBeDisabled();

    await user.clear(screen.getByLabelText(/^requirement \(optional\)/i));
    await user.type(screen.getByLabelText(/file path in the repo/i), "docs/REQUIREMENTS.md");
    expect(screen.getByLabelText(/^requirement \(optional\)/i)).toBeDisabled();
  });

  it("submits requirement_text on the payload when set", async () => {
    stubFetch();
    const onSubmit = vi.fn();
    renderForm(onSubmit);
    const user = userEvent.setup();

    await user.type(screen.getByLabelText(/^requirement \(optional\)/i), "Add a login page.");
    await user.click(screen.getByRole("button", { name: /start run/i }));

    expect(onSubmit).toHaveBeenCalledWith(
      expect.objectContaining({ requirement_text: "Add a login page.", requirement_path: undefined }),
    );
  });
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm run test -- NewRunForm.test.tsx`
Expected: FAIL — `getByLabelText(/^requirement \(optional\)/i)` finds no
element (the fields don't exist yet).

- [ ] **Step 3: Add the fields**

In `frontend/src/components/NewRunForm.tsx`, add the `Textarea` import
alongside the existing imports:

```tsx
import { Textarea } from "./ui/forms/Textarea";
```

Change the `onSubmit` prop type and add two new state variables. Current:

```tsx
  onSubmit: (input: { project_id: string; playbook_path: string; title?: string; driver?: string }) => void;
}) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? "");
  const [playbookPath, setPlaybookPath] = useState("");
  const [title, setTitle] = useState("");
  const [driver, setDriver] = useState("fake");
```

Replace with:

```tsx
  onSubmit: (input: {
    project_id: string;
    playbook_path: string;
    title?: string;
    driver?: string;
    requirement_text?: string;
    requirement_path?: string;
  }) => void;
}) {
  const [projectId, setProjectId] = useState(defaultProjectId ?? projects[0]?.id ?? "");
  const [playbookPath, setPlaybookPath] = useState("");
  const [title, setTitle] = useState("");
  const [driver, setDriver] = useState("fake");
  const [requirementText, setRequirementText] = useState("");
  const [requirementPath, setRequirementPath] = useState("");

  const handleRequirementTextChange = (value: string) => {
    setRequirementText(value);
    if (value) setRequirementPath("");
  };

  const handleRequirementPathChange = (value: string) => {
    setRequirementPath(value);
    if (value) setRequirementText("");
  };
```

Change the submit handler. Current:

```tsx
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({ project_id: projectId, playbook_path: playbookPath, title: title || undefined, driver });
        setPlaybookPath("");
        setTitle("");
      }}
```

Replace with:

```tsx
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit({
          project_id: projectId,
          playbook_path: playbookPath,
          title: title || undefined,
          driver,
          requirement_text: requirementText || undefined,
          requirement_path: requirementPath || undefined,
        });
        setPlaybookPath("");
        setTitle("");
        setRequirementText("");
        setRequirementPath("");
      }}
```

Add the two new fields to the JSX, right after the playbook picker's
closing `</div>` and before the Title field's `<div>`. Current:

```tsx
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-title">Title (optional)</Label>
```

Replace with:

```tsx
      <div className="flex flex-col gap-1 text-sm flex-1 min-w-[20rem]">
        <Label htmlFor="new-run-requirement-text">Requirement (optional)</Label>
        <Textarea
          id="new-run-requirement-text"
          value={requirementText}
          onChange={(e) => handleRequirementTextChange(e.target.value)}
          disabled={!!requirementPath}
          placeholder="Describe what this run should accomplish..."
        />
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-requirement-path">...or a file path in the repo (optional)</Label>
        <Input
          id="new-run-requirement-path"
          value={requirementPath}
          onChange={(e) => handleRequirementPathChange(e.target.value)}
          disabled={!!requirementText}
          placeholder="docs/REQUIREMENTS.md"
        />
      </div>
      <div className="flex flex-col gap-1 text-sm">
        <Label htmlFor="new-run-title">Title (optional)</Label>
```

- [ ] **Step 4: Update the API client type**

In `frontend/src/api/runs.ts`, change `createRun`'s input type. Current:

```ts
export async function createRun(input: {
  project_id: string;
  playbook_path: string;
  title?: string;
  driver?: string;
}): Promise<Run> {
```

Replace with:

```ts
export async function createRun(input: {
  project_id: string;
  playbook_path: string;
  title?: string;
  driver?: string;
  requirement_text?: string;
  requirement_path?: string;
}): Promise<Run> {
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd frontend && npm run test -- NewRunForm.test.tsx`
Expected: 5 passed (3 pre-existing + 2 new).

- [ ] **Step 6: Type-check and full frontend suite**

Run: `cd frontend && npx tsc -b && npm run test`
Expected: 0 type errors; full suite passing (baseline 122 + 2 new = 124).

- [ ] **Step 7: Commit**

```bash
git add frontend/src/api/runs.ts frontend/src/components/NewRunForm.tsx frontend/src/components/NewRunForm.test.tsx
git commit -m "feat(ui): add a mutually-exclusive requirement text/path field to NewRunForm"
```

---

## Verification

- Backend: `uv run pytest -v` (baseline 315, expect 324 after all 3 backend tasks).
- Frontend: `cd frontend && npx tsc -b && npm run test && npm run build`
  (baseline 122, expect 124).
- Manual: `uv run foundry serve --db /tmp/foundry.db --port 8000` +
  `cd frontend && npm run dev` — start a run from the dashboard with a
  requirement typed into the new textarea, confirm the run completes
  (FakeDriver) and re-run the same flow with the CLI
  (`uv run foundry run <playbook> --requirement-text "..."`) to confirm
  parity.
