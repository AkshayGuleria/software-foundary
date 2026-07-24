# Deviation fixes — design

Source: `docs/design-deviations.md` (audit at `master @ 7f67412`). This spec covers
the subset of findings selected for a fix pass; everything else is explicitly out
of scope (see below) and stays documented as an accepted deviation.

## In scope

### 1. Worktree wiring (deviation C1)

`WorktreeManager` is fully built and tested (M2b) but never constructed into either
production `Orchestrator(...)` call site:

- `src/foundry/cli.py:57` — `foundry run` command
- `src/foundry/api/scheduler.py:74` — `Scheduler.register()`

Fix: pass a `WorktreeManager` instance through at both sites. No new mechanism —
wiring only.

### 2. KG interference wiring (deviation C3)

Blast-radius / interference warnings are computed and tested on demand but never
consulted during dispatch. Fix: call the existing check from the dispatch loop in
`tick.py` before scheduling a unit, and emit the result as a warning event (matches
today's proven-on-demand behavior — this does not block dispatch, only surfaces the
warning into the event stream where the dashboard/chat can see it).

### 3. Alembic cleanup (deviation D1)

Drop the unused `alembic>=1.13` dependency from `pyproject.toml`. Every schema
change so far (M0–M4) has shipped as a direct SQLAlchemy model edit; there is no
migration and no `versions/` directory. Retrofitting migration tooling with nothing
to migrate is speculative. Revisit when M5 (Postgres) actually needs it — Alembic
becomes load-bearing there, not before.

### 4. Real prompt rendering + driver plumbing (deviation E1, widened)

Both spawn sites in `tick.py` (:568 task dispatch, :763 agent-gate review) build a
stub prompt string:

```python
prompt=f"step:{step.id} files:{len(bundle_files)} memory:{len(memory_items)}"
```

`bundle_files` and `memory_items` are already computed by `_compose_context_bundle`
at that point — only their counts get used. Fix: add `render_prompt()` and call it
at both sites, producing real content per the design doc §8 prompt contract:

- role definition (from the pack's `RoleSpec`)
- input artifacts the step needs
- KG context bundle content (not just file count)
- memory item content (not just item count)
- the JSON schema of the artifact the step must produce

**Explicitly excluded from the template:** a chat-notes / `notes_addressed`
section. That's deviation A4 — no chat/notes subsystem exists to source notes from,
and building one is out of scope here. The template has no placeholder for it;
this isn't a partial stub, it's a section that doesn't apply yet.

The `integrator` role's template additionally includes explicit merge/conflict-
resolution instructions — this is what makes deviation E1 (integrate step has no
real behavior behind it) meaningful, since a role's prompt is the only mechanism by
which the engine tells an agent what to do.

Also fix two related hardcoded values at the same call sites:

- `SessionSpec.model` is hardcoded `"fake"` at both spawn sites. Thread
  `RoleSpec.model` (from the step's role in the pack manifest) through instead.
- Add a `--driver fake|codex|claude` flag to the `foundry run` CLI command
  (`cli.py`), defaulting to `fake`. Currently there is no way to select a driver in
  production at all — `CodexDriver` has zero non-test references anywhere in the
  codebase despite being fully built since M2, the exact same dormant pattern as
  `WorktreeManager` (C1). Without this flag, task 5 below would ship a third
  unreachable driver.

### 5. ClaudeCodeDriver (deviation A2)

Mirrors `CodexDriver` (`src/foundry/drivers/codex.py`) exactly — same shape, same
driver-spec requirements (process exit authoritative, log-file tailing from a
persisted offset, process-group reap on every session end, ≥1MB readline limit):

- `claude -p --output-format stream-json` subprocess
- new `src/foundry/drivers/claude_code.py`, structurally parallel to `codex.py`
- normalization function mapping Claude's stream-json shape to the shared
  `DriverEvent` kinds (`tool_call | text | usage | completed | failed`)
- tests mirror `tests/drivers/test_codex.py`, driven by a new
  `tests/fixtures/fake_claude_cli.sh` fixture script standing in for the real
  `claude` binary — no live-API calls in CI, same as the existing Codex test suite
- selectable via the `--driver claude` flag added in task 4

MCP server injection (`.mcp.json`, per design doc §8) is scoped down: every current
caller passes `mcp_servers=[]` (`tick.py:571`, `tick.py:766`), so there's nothing to
inject yet. The driver accepts the field and would write `.mcp.json` if the list
were non-empty, but no workspace file generation is built now — YAGNI, since no
caller ever populates it. Revisit if/when a role config starts declaring MCP
servers.

## Explicitly out of scope (documented for later)

- **A1 — `/internal` HTTP API.** Not needed by anything in this fix pass; context
  bundling stays in-process. Revisit if a future milestone needs the HTTP boundary
  (e.g., a driver or tool running outside the orchestrator's process).
- **Per-role multi-driver dispatch.** Today one driver instance serves an entire
  `Orchestrator`/run. The design doc's per-role `model` field implies a role could
  route to a different driver/model than its siblings — that's real architecture
  work (driver registry, per-spawn driver selection), not a fix. This spec only
  makes the existing single-driver-per-run model's metadata correct (task 4's
  `RoleSpec.model` threading), it does not add multi-driver support.
- **A4 — chat-to-role / `notes_addressed`.** No chat/notes subsystem exists. Stays
  deferred; task 4's prompt template has no placeholder for it (see above).
- **A3 — `ApiDriver`.** v1.5 per roadmap, not due yet.
- **A5 — My-queue / batch-approve, A6 — Packs & settings/Project view pages.**
  Frontend scope, unrelated to this backend-focused fix pass.
- **B1 — KG via stdlib `ast` instead of `code-review-graph`.** Current behavior is
  functional and tested; swapping the underlying library is a substitution, not a
  bug, and out of scope here.
- **B2 — memory retrieval via keyword overlap instead of embeddings.** Same
  reasoning as B1 — functional, tested, substitution not a defect.
- **B4 — no OpenAPI-to-TypeScript codegen.** Tooling/CI addition, unrelated to this
  fix pass's backend scope.

## Testing

Standard project pattern throughout: FakeDriver-backed test first for any
orchestrator-facing change (worktree wiring, KG-warning wiring, prompt rendering),
then a fixture-script-backed test for the driver itself (mirroring
`tests/drivers/test_codex.py`). No task in this spec requires live network/API
access to test.

## Sequencing

1, 2, 3 are independent — any order, can even run in parallel. 4 must land before
5 (a real driver against stub prompts is pointless, and 5 needs 4's `--driver` flag
to be reachable). Recommended order: 1, 2, 3, 4, 5.
