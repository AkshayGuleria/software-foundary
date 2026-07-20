# Software Foundary (Foundry)

Autonomous, plan-first, phase-gated agent orchestration platform. Runs fleets
of coding agents (Claude Code, Codex CLI, ...) through declarative playbooks
with durable work, human approval gates, live visualization, and compounding
knowledge across runs.

Design doc: [`docs/software-foundary-design.md`](docs/software-foundary-design.md)

## Status

**M0 (durable core): shipped.** Store schema, TOML playbook parser + plan-first
lint, DAG materializer, orchestrator tick loop (reconcile/unblock/dispatch/
retry) with proven crash recovery, a deterministic `FakeDriver`, and a CLI —
all tested (28 passing) against `FakeDriver`, no tokens spent. Implementation
plan: [`docs/superpowers/plans/2026-07-20-m0-durable-core.md`](docs/superpowers/plans/2026-07-20-m0-durable-core.md).

Not yet built: real agent driver (`ClaudeCodeDriver`) + `/internal` API,
fan-out/parallel slices, dashboard, knowledge graph, memory/packs. See the
design doc's roadmap (§15) for the full milestone sequence.

## Stack

Python 3.12+, SQLAlchemy 2 (async) + aiosqlite (WAL), Pydantic v2, Typer,
pytest + pytest-asyncio. FastAPI/Alembic are dependencies for milestones not
yet built. Dashboard (from M1): React/Vite/TS/Tailwind.

## Project layout

```
src/foundry/
  store/        SQLAlchemy models, WAL-mode engine, single-writer Store
  playbook/     TOML schema, loader (+ plan-first lint), DAG materializer
  drivers/      AgentDriver protocol, FakeDriver
  orchestrator/ tick loop: reconcile -> unblock -> dispatch -> collect -> retry
  cli.py        `foundry run`, `foundry events`
packs/default/  built-in SDLC playbook (not yet wired to a role/prompt system)
```

## Development

```bash
uv sync
uv run pytest -v
```

## Try it

Run a playbook end-to-end against `FakeDriver` (no real agents, no tokens):

```bash
uv run foundry run tests/playbook/fixtures/sdlc_mini.toml --db /tmp/foundry.db
uv run foundry events <run-id-printed-above> --db /tmp/foundry.db --once
```

`foundry run` exits non-zero and prints a clear error if the playbook fails
plan-first lint, has a bad reference, or the run gets stuck (e.g. an
unresolved `human_task` step).
