# Software Foundary (Foundry)

Autonomous, plan-first, phase-gated agent orchestration platform. Runs fleets
of coding agents (Claude Code, Codex CLI, ...) through declarative playbooks
with durable work, human approval gates, live visualization, and compounding
knowledge across runs.

Design doc: [`docs/software-foundary-design.md`](docs/software-foundary-design.md)

## Status

M0 (durable core) in progress — see `docs/superpowers/plans/`.

## Stack

Python 3.12+, FastAPI, SQLAlchemy 2 (async) + Alembic + aiosqlite (WAL),
pytest. Dashboard (from M1): React/Vite/TS/Tailwind.

## Development

```bash
uv sync
uv run pytest
uv run foundry --help
```
