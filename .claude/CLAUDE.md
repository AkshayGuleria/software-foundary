# CLAUDE.md

## SDLC Workflow

```
superpowers:brainstorming (new work) → superpowers:writing-plans → superpowers:using-git-worktrees
  → superpowers:subagent-driven-development (per task: implement → task review → fix loop)
  → final whole-branch review → superpowers:finishing-a-development-branch
```

One worktree + branch per plan/milestone (not per task) — see `.claude/git-workflow.md`.
Plans live in `docs/superpowers/plans/`. Even when every per-task review is clean, run
the final whole-branch review anyway — it is the only pass that sees cross-task
integration bugs (M0 found two this way: a crash-recovery window and a silent-failure
gate bug, both invisible to any single task's diff).

## Stack

Python 3.12+, uv (packaging/venv), SQLAlchemy 2 async + aiosqlite (WAL), Pydantic v2,
Typer (CLI), pytest + pytest-asyncio, ruff (lint + format). FastAPI + Alembic are
declared dependencies for milestones not yet built (`/internal` API, migrations) — do
not wire them in ahead of the plan that needs them.

## Quality Gate

`.git/hooks/pre-commit` runs (only when staged `.py` files exist): `ruff check` →
`ruff format --check` → `pytest -q`. Never skip with `--no-verify` unless the user
explicitly asks.

## Git Workflow

Worktree-per-plan via `superpowers:using-git-worktrees` (native `EnterWorktree` if
available). Branch name = plan slug (e.g. `m0-durable-core`). Conventional commits
(`feat:`, `fix:`, `docs:`, `chore:`) — one commit per plan task, extra `fix:` commits
for review rounds. Regular merge to master (not squash — the task-by-task history is
the value, not noise), then delete branch + remove worktree. Never commit directly to
master for anything beyond trivial one-line fixes. Full detail: `.claude/git-workflow.md`.

## Key Constraints (from design doc)

1. SQLite WAL mandatory; all writes funnel through one single-writer asyncio task
   (`Store`); reads are unrestricted under WAL.
2. **FakeDriver-first, always.** Every orchestrator feature (retry, crash recovery,
   gates) needs a FakeDriver-backed test before any real provider driver is touched.
3. Plan-first is an enforced invariant, not a convention: a playbook is invalid unless
   every `writes=true` step is transitively downstream of a `derived_gate` — linted at
   load time (`PlaybookLintError`), not just documented.
4. All IDs are ULIDs (`python-ulid`), stored as strings.
5. Artifacts are immutable/append-only; code artifacts are git pointers (branch, SHAs,
   stat summary), never raw diffs — git is the storage.
6. Contracts-first: the store schema, event taxonomy, and REST/SSE contracts are the
   real interface. Engine logic never leaks into the ORM layer.

## Testing

`uv run pytest -v` for the full suite; `uv run pytest tests/path/test_x.py -v` for one
file. TDD per task via `superpowers:test-driven-development` — write the failing test
from the plan brief first, watch it fail, then implement.

## Reference Docs

| Topic | File |
|-------|------|
| Full platform design (requirements, architecture, roadmap) | `docs/software-foundary-design.md` |
| Implementation plans (one per milestone) | `docs/superpowers/plans/` |
| Architecture decision records | `docs/adrs/` |
| Full git workflow | `.claude/git-workflow.md` |
| Build-status tracker (Artifact source — redeploy after each milestone) | `docs/status.html` |
