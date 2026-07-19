# M0 Durable Core (FakeDriver) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Foundry's durable engine core — store, playbook parser, DAG materializer, and orchestrator tick loop — proven end-to-end on a deterministic FakeDriver, including crash recovery, with a minimal CLI (`foundry run`, `foundry events`).

**Architecture:** SQLite (WAL) via SQLAlchemy 2 async ORM, all writes funneled through a single-writer asyncio queue (`Store`). Playbooks are TOML, parsed into a Pydantic `PlaybookSpec`, materialized into `WorkUnit`/`UnitDep` rows. `Orchestrator.tick()` runs reconcile → apply-gate-decisions → unblock → close-derived-gates → dispatch, sequentially (M0 is linear-playbook scope only; concurrent fan-out is M2). Agents run through the `AgentDriver` Protocol; `FakeDriver` is the only driver built in this plan — deterministic, scriptable, and what proves crash recovery without spending tokens or spawning real processes.

**Tech Stack:** Python 3.12+, SQLAlchemy 2 (async) + aiosqlite, Pydantic v2, `tomllib` (stdlib), Typer (CLI), python-ulid, pytest + pytest-asyncio.

## Global Constraints

- Backend stack is fixed by the design doc §2.3: Python + FastAPI/SQLAlchemy2 async/aiosqlite (WAL)/pytest — this plan builds the store/engine/CLI slice; FastAPI itself lands in the M0 follow-up plan (`/internal` API + ClaudeCodeDriver), not here.
- All IDs are ULIDs (`python-ulid`), stored as strings (design doc §6).
- SQLite discipline: WAL mode mandatory; all writes funnel through one single-writer task; reads are unrestricted (design doc §6).
- **FakeDriver first, always.** Every orchestrator feature (retry, crash recovery, gates) must have a FakeDriver-backed test before any real provider driver is written (design doc §8, M0 exit criterion).
- Artifacts are immutable and append-only; rework increments version (design doc §6) — version bumping on rework is out of scope for this plan (no gate rejection path exercised here beyond the data model supporting it); tracked as a gap for the M1 plan (gates/rework UI).
- No UI, no real driver, no `/internal` API, no fan-out/convoys, no KG, no memory in this plan — all explicitly M1+ per the roadmap (design doc §15).

---

### Task 1: Store schema + WAL-mode async engine

**Files:**
- Create: `src/foundry/store/models.py`
- Create: `src/foundry/store/db.py`
- Test: `tests/store/test_db.py`
- Test: `tests/store/__init__.py` (empty)

**Interfaces:**
- Produces: `Base` (SQLAlchemy `DeclarativeBase`), ORM classes `Project, Pack, Run, WorkUnit, UnitDep, Artifact, Gate, SessionRow, Event, Memory`; `new_id() -> str`; `utcnow() -> datetime`; `make_engine(db_path: str) -> AsyncEngine`; `init_db(engine: AsyncEngine) -> None` (async); `make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker`.

- [ ] **Step 1: Write the failing test**

```python
# tests/store/test_db.py
import pytest

from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.models import Project


@pytest.mark.asyncio
async def test_init_db_creates_tables_and_roundtrips_a_row(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    engine = make_engine(db_path)
    await init_db(engine)
    sessionmaker = make_sessionmaker(engine)

    async with sessionmaker() as session:
        session.add(Project(name="demo", path="/tmp/demo"))
        await session.commit()

    async with sessionmaker() as session:
        from sqlalchemy import select
        result = await session.execute(select(Project).where(Project.name == "demo"))
        project = result.scalar_one()
        assert project.path == "/tmp/demo"
        assert len(project.id) == 26  # ULID length
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/store/test_db.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.store.db'`

- [ ] **Step 3: Write `src/foundry/store/models.py`**

```python
from __future__ import annotations

import datetime as dt
from typing import Optional

from sqlalchemy import ForeignKey, JSON, Integer, String, DateTime
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from ulid import ULID


def new_id() -> str:
    return str(ULID())


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, unique=True)
    path: Mapped[str] = mapped_column(String)
    kg_status: Mapped[str] = mapped_column(String, default="none")
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Pack(Base):
    __tablename__ = "packs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String, unique=True)
    manifest_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(String, ForeignKey("projects.id"))
    playbook_ref: Mapped[str] = mapped_column(String)
    pack_version_pin: Mapped[str] = mapped_column(String, default="local")
    title: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="active")
    created_by: Mapped[str] = mapped_column(String, default="cli")
    token_budget: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkUnit(Base):
    __tablename__ = "work_units"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"))
    step_id: Mapped[str] = mapped_column(String)
    type: Mapped[str] = mapped_column(String)  # task|gate|human_task|session|convoy
    status: Mapped[str] = mapped_column(String, default="open")
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    owner_session_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    convoy_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    assignee: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class UnitDep(Base):
    __tablename__ = "unit_deps"
    unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"), primary_key=True)
    needs_unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"), primary_key=True)


class Artifact(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"))
    work_unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"))
    kind: Mapped[str] = mapped_column(String)
    version: Mapped[int] = mapped_column(Integer, default=1)
    produced_by_role: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    schema_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Gate(Base):
    __tablename__ = "gates"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    work_unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"))
    artifact_id: Mapped[Optional[str]] = mapped_column(String, ForeignKey("artifacts.id"), nullable=True)
    gate_type: Mapped[str] = mapped_column(String)  # human|agent|derived
    decision: Mapped[str] = mapped_column(String, default="pending")  # pending|approved|rejected
    feedback_json: Mapped[dict] = mapped_column(JSON, default=dict)
    decided_by: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    decided_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SessionRow(Base):
    __tablename__ = "sessions"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    work_unit_id: Mapped[str] = mapped_column(String, ForeignKey("work_units.id"))
    driver: Mapped[str] = mapped_column(String)
    provider_session_ref: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    model: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    status: Mapped[str] = mapped_column(String, default="intent")
    started_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[Optional[dt.datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)


class Event(Base):
    __tablename__ = "events"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, ForeignKey("runs.id"))
    unit_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    type: Mapped[str] = mapped_column(String)
    payload_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Memory(Base):
    __tablename__ = "memory"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=new_id)
    pack_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    scope: Mapped[str] = mapped_column(String)  # pack|project|role
    kind: Mapped[str] = mapped_column(String)  # lesson|pattern|pitfall
    title: Mapped[str] = mapped_column(String)
    body_md: Mapped[str] = mapped_column(String)
    source_run_id: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    embedding: Mapped[Optional[str]] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
```

- [ ] **Step 4: Write `src/foundry/store/db.py`**

```python
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from foundry.store.models import Base


def make_engine(db_path: str) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/store/test_db.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/foundry/store/models.py src/foundry/store/db.py tests/store/
git commit -m "feat(store): SQLAlchemy models + WAL-mode async engine"
```

---

### Task 2: Store — single-writer queue + domain CRUD

**Files:**
- Create: `src/foundry/store/store.py`
- Test: `tests/store/test_store.py`

**Interfaces:**
- Consumes: `make_engine`, `init_db`, `make_sessionmaker` (Task 1); ORM classes from `foundry.store.models`.
- Produces: `class Store` with `async start()`, `async stop()`, `async write(fn)`, `async read(fn)`, and domain helpers used by every later task:
  `create_project(name, path) -> Project`, `create_run(project_id, playbook_ref, title) -> Run`,
  `create_work_units(units: list[WorkUnit]) -> list[WorkUnit]`, `add_unit_deps(deps: list[UnitDep]) -> None`,
  `get_unit(unit_id) -> WorkUnit | None`, `list_units(run_id) -> list[WorkUnit]`, `list_deps(run_id) -> list[UnitDep]`,
  `update_unit(unit_id, **fields) -> None`, `get_ready_units(run_id) -> list[WorkUnit]`,
  `create_artifact(**fields) -> Artifact`, `list_artifacts(run_id) -> list[Artifact]`,
  `create_gate(**fields) -> Gate`, `list_gates_for_run(run_id) -> list[Gate]`, `decide_gate(gate_id, decision, feedback=None, decided_by="human") -> None`,
  `create_session_row(**fields) -> SessionRow`, `update_session_row(session_id, **fields) -> None`,
  `append_event(run_id, unit_id, type_, payload=None) -> int`, `list_events(run_id, after_seq=0) -> list[Event]`,
  `complete_human_task(unit_id) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/store/test_store.py
import pytest

from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.models import UnitDep, WorkUnit
from foundry.store.store import Store


async def make_store(tmp_path) -> Store:
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_ready_units_unblock_after_dependency_closes(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo", "/tmp/demo")
    run = await store.create_run(project.id, "pb.toml", "demo run")

    units = await store.create_work_units([
        WorkUnit(run_id=run.id, step_id="a", type="task", status="open"),
        WorkUnit(run_id=run.id, step_id="b", type="task", status="open"),
    ])
    unit_a, unit_b = units
    await store.add_unit_deps([UnitDep(unit_id=unit_b.id, needs_unit_id=unit_a.id)])

    ready = await store.get_ready_units(run.id)
    assert [u.id for u in ready] == [unit_a.id]

    await store.update_unit(unit_a.id, status="closed")
    ready = await store.get_ready_units(run.id)
    assert [u.id for u in ready] == [unit_b.id]

    await store.stop()


@pytest.mark.asyncio
async def test_event_log_is_monotonic_and_replayable_from_seq(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo2", "/tmp/demo2")
    run = await store.create_run(project.id, "pb.toml", "demo run 2")

    seq1 = await store.append_event(run.id, None, "run.created", {})
    seq2 = await store.append_event(run.id, None, "unit.ready", {"x": 1})
    assert seq2 == seq1 + 1

    all_events = await store.list_events(run.id)
    assert [e.seq for e in all_events] == [seq1, seq2]

    tail = await store.list_events(run.id, after_seq=seq1)
    assert [e.seq for e in tail] == [seq2]
    assert tail[0].payload_json == {"x": 1}

    await store.stop()


@pytest.mark.asyncio
async def test_complete_human_task_closes_unit(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo3", "/tmp/demo3")
    run = await store.create_run(project.id, "pb.toml", "demo run 3")
    units = await store.create_work_units([
        WorkUnit(run_id=run.id, step_id="approve", type="human_task", status="ready"),
    ])

    await store.complete_human_task(units[0].id)

    unit = await store.get_unit(units[0].id)
    assert unit.status == "closed"

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/store/test_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.store.store'`

- [ ] **Step 3: Write `src/foundry/store/store.py`**

```python
from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from foundry.store.models import (
    Artifact,
    Event,
    Gate,
    Project,
    Run,
    SessionRow,
    UnitDep,
    WorkUnit,
    utcnow,
)


class Store:
    def __init__(self, engine: AsyncEngine, sessionmaker: async_sessionmaker):
        self._engine = engine
        self._sessionmaker = sessionmaker
        self._queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None

    async def start(self) -> None:
        self._writer_task = asyncio.create_task(self._writer_loop())

    async def stop(self) -> None:
        if self._writer_task is not None:
            await self._queue.put((None, None))
            await self._writer_task

    async def _writer_loop(self) -> None:
        while True:
            fn, fut = await self._queue.get()
            if fn is None:
                break
            try:
                async with self._sessionmaker() as session:
                    result = await fn(session)
                    await session.commit()
                fut.set_result(result)
            except Exception as exc:  # noqa: BLE001 - propagate to caller via future
                fut.set_exception(exc)

    async def write(self, fn: Callable[[Any], Awaitable[Any]]) -> Any:
        fut = asyncio.get_event_loop().create_future()
        await self._queue.put((fn, fut))
        return await fut

    async def read(self, fn: Callable[[Any], Awaitable[Any]]) -> Any:
        async with self._sessionmaker() as session:
            return await fn(session)

    # --- projects / runs ---

    async def create_project(self, name: str, path: str) -> Project:
        async def _op(session):
            proj = Project(name=name, path=path)
            session.add(proj)
            await session.flush()
            return proj

        return await self.write(_op)

    async def create_run(self, project_id: str, playbook_ref: str, title: str) -> Run:
        async def _op(session):
            run = Run(project_id=project_id, playbook_ref=playbook_ref, title=title)
            session.add(run)
            await session.flush()
            return run

        return await self.write(_op)

    # --- work units / deps ---

    async def create_work_units(self, units: list[WorkUnit]) -> list[WorkUnit]:
        async def _op(session):
            session.add_all(units)
            await session.flush()
            return units

        return await self.write(_op)

    async def add_unit_deps(self, deps: list[UnitDep]) -> None:
        async def _op(session):
            session.add_all(deps)

        await self.write(_op)

    async def get_unit(self, unit_id: str) -> WorkUnit | None:
        async def _op(session):
            return await session.get(WorkUnit, unit_id)

        return await self.read(_op)

    async def list_units(self, run_id: str) -> list[WorkUnit]:
        async def _op(session):
            res = await session.execute(select(WorkUnit).where(WorkUnit.run_id == run_id))
            return list(res.scalars())

        return await self.read(_op)

    async def list_deps(self, run_id: str) -> list[UnitDep]:
        async def _op(session):
            res = await session.execute(
                select(UnitDep)
                .join(WorkUnit, WorkUnit.id == UnitDep.unit_id)
                .where(WorkUnit.run_id == run_id)
            )
            return list(res.scalars())

        return await self.read(_op)

    async def update_unit(self, unit_id: str, **fields) -> None:
        async def _op(session):
            unit = await session.get(WorkUnit, unit_id)
            for key, value in fields.items():
                setattr(unit, key, value)

        await self.write(_op)

    async def get_ready_units(self, run_id: str) -> list[WorkUnit]:
        units = await self.list_units(run_id)
        deps = await self.list_deps(run_id)
        by_id = {u.id: u for u in units}
        needs_map: dict[str, list[str]] = {}
        for dep in deps:
            needs_map.setdefault(dep.unit_id, []).append(dep.needs_unit_id)

        ready = []
        for unit in units:
            if unit.status != "open":
                continue
            needed = needs_map.get(unit.id, [])
            if all(by_id[n].status == "closed" for n in needed):
                ready.append(unit)
        return ready

    async def complete_human_task(self, unit_id: str) -> None:
        await self.update_unit(unit_id, status="closed")

    # --- artifacts / gates ---

    async def create_artifact(self, **fields) -> Artifact:
        async def _op(session):
            artifact = Artifact(**fields)
            session.add(artifact)
            await session.flush()
            return artifact

        return await self.write(_op)

    async def list_artifacts(self, run_id: str) -> list[Artifact]:
        async def _op(session):
            res = await session.execute(select(Artifact).where(Artifact.run_id == run_id))
            return list(res.scalars())

        return await self.read(_op)

    async def create_gate(self, **fields) -> Gate:
        async def _op(session):
            gate = Gate(**fields)
            session.add(gate)
            await session.flush()
            return gate

        return await self.write(_op)

    async def list_gates_for_run(self, run_id: str) -> list[Gate]:
        async def _op(session):
            res = await session.execute(
                select(Gate).join(WorkUnit, WorkUnit.id == Gate.work_unit_id).where(WorkUnit.run_id == run_id)
            )
            return list(res.scalars())

        return await self.read(_op)

    async def decide_gate(self, gate_id: str, decision: str, feedback: dict | None = None, decided_by: str = "human") -> None:
        async def _op(session):
            gate = await session.get(Gate, gate_id)
            gate.decision = decision
            gate.feedback_json = feedback or {}
            gate.decided_by = decided_by
            gate.decided_at = utcnow()

        await self.write(_op)

    # --- sessions ---

    async def create_session_row(self, **fields) -> SessionRow:
        async def _op(session):
            row = SessionRow(**fields)
            session.add(row)
            await session.flush()
            return row

        return await self.write(_op)

    async def update_session_row(self, session_id: str, **fields) -> None:
        async def _op(session):
            row = await session.get(SessionRow, session_id)
            for key, value in fields.items():
                setattr(row, key, value)

        await self.write(_op)

    # --- events ---

    async def append_event(self, run_id: str, unit_id: str | None, type_: str, payload: dict | None = None) -> int:
        async def _op(session):
            ev = Event(run_id=run_id, unit_id=unit_id, type=type_, payload_json=payload or {})
            session.add(ev)
            await session.flush()
            return ev.seq

        return await self.write(_op)

    async def list_events(self, run_id: str, after_seq: int = 0) -> list[Event]:
        async def _op(session):
            res = await session.execute(
                select(Event).where(Event.run_id == run_id, Event.seq > after_seq).order_by(Event.seq)
            )
            return list(res.scalars())

        return await self.read(_op)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/store/test_store.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/foundry/store/store.py tests/store/test_store.py
git commit -m "feat(store): single-writer Store with DAG readiness, events, gates, artifacts"
```

---

### Task 3: Playbook schema + TOML loader + plan-first lint

**Files:**
- Create: `src/foundry/playbook/schema.py`
- Create: `src/foundry/playbook/loader.py`
- Create: `src/foundry/playbook/lint.py`
- Test: `tests/playbook/__init__.py` (empty)
- Test: `tests/playbook/test_loader.py`
- Test: `tests/playbook/test_lint.py`
- Test fixture: `tests/playbook/fixtures/sdlc_mini.toml`

**Interfaces:**
- Produces: `class StepSpec(BaseModel)` with fields `id: str, role: str, type: Literal["task","derived_gate","human_task"]="task", needs: list[str]=[], produces: str|None=None, gate: Literal["human","agent","none"]|None="none", writes: bool=False`; `class PlaybookSpec(BaseModel)` with `id: str, description: str="", steps: list[StepSpec]`; `load_playbook(path: str) -> PlaybookSpec`; `class PlaybookLintError(Exception)`; `lint_plan_first(playbook: PlaybookSpec) -> None` (raises on violation).

- [ ] **Step 1: Write the fixture and the failing tests**

```toml
# tests/playbook/fixtures/sdlc_mini.toml
[playbook]
id = "sdlc_mini"
description = "requirement -> (architecture, test_plan) -> plan_approval -> implement"

[[step]]
id = "requirement"
role = "product_owner"
produces = "requirement_artifact"
gate = "human"

[[step]]
id = "architecture"
role = "architect"
needs = ["requirement"]
produces = "architecture_artifact"
gate = "human"

[[step]]
id = "test_plan"
role = "qa"
needs = ["requirement"]
produces = "test_plan_artifact"
gate = "human"

[[step]]
id = "plan_approval"
role = "system"
type = "derived_gate"
needs = ["requirement", "architecture", "test_plan"]

[[step]]
id = "implement"
role = "developer"
type = "task"
needs = ["plan_approval"]
produces = "code_diff_artifact"
gate = "human"
writes = true
```

```python
# tests/playbook/test_loader.py
from foundry.playbook.loader import load_playbook


def test_loads_steps_and_needs_edges():
    playbook = load_playbook("tests/playbook/fixtures/sdlc_mini.toml")

    assert playbook.id == "sdlc_mini"
    assert [s.id for s in playbook.steps] == [
        "requirement", "architecture", "test_plan", "plan_approval", "implement",
    ]

    implement = next(s for s in playbook.steps if s.id == "implement")
    assert implement.needs == ["plan_approval"]
    assert implement.writes is True
    assert implement.gate == "human"

    plan_approval = next(s for s in playbook.steps if s.id == "plan_approval")
    assert plan_approval.type == "derived_gate"
    assert plan_approval.needs == ["requirement", "architecture", "test_plan"]
```

```python
# tests/playbook/test_lint.py
import pytest

from foundry.playbook.loader import load_playbook
from foundry.playbook.lint import PlaybookLintError, lint_plan_first
from foundry.playbook.schema import PlaybookSpec, StepSpec


def test_valid_playbook_passes_lint():
    playbook = load_playbook("tests/playbook/fixtures/sdlc_mini.toml")
    lint_plan_first(playbook)  # must not raise


def test_writes_step_without_upstream_derived_gate_fails_lint():
    playbook = PlaybookSpec(
        id="bad",
        steps=[
            StepSpec(id="requirement", role="product_owner", produces="requirement_artifact"),
            StepSpec(id="implement", role="developer", needs=["requirement"], writes=True),
        ],
    )

    with pytest.raises(PlaybookLintError):
        lint_plan_first(playbook)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/playbook/ -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.playbook.loader'`

- [ ] **Step 3: Write `src/foundry/playbook/schema.py`**

```python
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class StepSpec(BaseModel):
    id: str
    role: str
    type: Literal["task", "derived_gate", "human_task"] = "task"
    needs: list[str] = Field(default_factory=list)
    produces: Optional[str] = None
    gate: Optional[Literal["human", "agent", "none"]] = "none"
    writes: bool = False


class PlaybookSpec(BaseModel):
    id: str
    description: str = ""
    steps: list[StepSpec]
```

- [ ] **Step 4: Write `src/foundry/playbook/loader.py`**

```python
from __future__ import annotations

import tomllib

from foundry.playbook.schema import PlaybookSpec, StepSpec


def load_playbook(path: str) -> PlaybookSpec:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    meta = data["playbook"]
    steps = [StepSpec(**raw_step) for raw_step in data.get("step", [])]
    return PlaybookSpec(id=meta["id"], description=meta.get("description", ""), steps=steps)
```

- [ ] **Step 5: Write `src/foundry/playbook/lint.py`**

```python
from __future__ import annotations

from foundry.playbook.schema import PlaybookSpec, StepSpec


class PlaybookLintError(Exception):
    pass


def lint_plan_first(playbook: PlaybookSpec) -> None:
    steps_by_id = {s.id: s for s in playbook.steps}
    violations = [
        step.id
        for step in playbook.steps
        if step.writes and not _has_upstream_derived_gate(step, steps_by_id, set())
    ]
    if violations:
        raise PlaybookLintError(
            f"writes-capable step(s) not downstream of a derived_gate: {violations}"
        )


def _has_upstream_derived_gate(step: StepSpec, steps_by_id: dict[str, StepSpec], seen: set[str]) -> bool:
    for need_id in step.needs:
        if need_id in seen:
            continue
        seen.add(need_id)
        need_step = steps_by_id[need_id]
        if need_step.type == "derived_gate":
            return True
        if _has_upstream_derived_gate(need_step, steps_by_id, seen):
            return True
    return False
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/playbook/ -v`
Expected: PASS (3 tests)

- [ ] **Step 7: Commit**

```bash
git add src/foundry/playbook/schema.py src/foundry/playbook/loader.py src/foundry/playbook/lint.py tests/playbook/
git commit -m "feat(playbook): TOML schema, loader, plan-first lint invariant"
```

---

### Task 4: DAG materializer

**Files:**
- Create: `src/foundry/playbook/materializer.py`
- Test: `tests/playbook/test_materializer.py`

**Interfaces:**
- Consumes: `PlaybookSpec`, `StepSpec` (Task 3); `Store.create_work_units`, `Store.add_unit_deps` (Task 2); `WorkUnit`, `UnitDep` (Task 1).
- Produces: `async def materialize(playbook: PlaybookSpec, run_id: str, store: Store) -> dict[str, str]` — returns `{step_id: work_unit_id}`.

- [ ] **Step 1: Write the failing test**

```python
# tests/playbook/test_materializer.py
import pytest

from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_materialize_creates_units_and_dep_edges(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/playbook/fixtures/sdlc_mini.toml")
    run = await store.create_run(project.id, "sdlc_mini.toml", "demo run")

    step_to_unit = await materialize(playbook, run.id, store)
    assert set(step_to_unit) == {"requirement", "architecture", "test_plan", "plan_approval", "implement"}

    units = await store.list_units(run.id)
    assert len(units) == 5
    plan_approval_unit = next(u for u in units if u.step_id == "plan_approval")
    assert plan_approval_unit.type == "gate"
    implement_unit = next(u for u in units if u.step_id == "implement")
    assert implement_unit.type == "task"
    assert implement_unit.status == "open"

    deps = await store.list_deps(run.id)
    implement_deps = [d.needs_unit_id for d in deps if d.unit_id == step_to_unit["implement"]]
    assert implement_deps == [step_to_unit["plan_approval"]]

    plan_approval_deps = {d.needs_unit_id for d in deps if d.unit_id == step_to_unit["plan_approval"]}
    assert plan_approval_deps == {
        step_to_unit["requirement"], step_to_unit["architecture"], step_to_unit["test_plan"],
    }

    await store.stop()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/playbook/test_materializer.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.playbook.materializer'`

- [ ] **Step 3: Write `src/foundry/playbook/materializer.py`**

```python
from __future__ import annotations

from foundry.playbook.schema import PlaybookSpec
from foundry.store.models import UnitDep, WorkUnit
from foundry.store.store import Store

_TYPE_MAP = {"task": "task", "derived_gate": "gate", "human_task": "human_task"}


async def materialize(playbook: PlaybookSpec, run_id: str, store: Store) -> dict[str, str]:
    units = [
        WorkUnit(run_id=run_id, step_id=step.id, type=_TYPE_MAP[step.type], status="open")
        for step in playbook.steps
    ]
    created = await store.create_work_units(units)
    step_to_unit = {step.id: unit.id for step, unit in zip(playbook.steps, created)}

    deps = [
        UnitDep(unit_id=step_to_unit[step.id], needs_unit_id=step_to_unit[need_id])
        for step in playbook.steps
        for need_id in step.needs
    ]
    if deps:
        await store.add_unit_deps(deps)

    return step_to_unit
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/playbook/test_materializer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/foundry/playbook/materializer.py tests/playbook/test_materializer.py
git commit -m "feat(playbook): materialize playbook into work-unit DAG"
```

---

### Task 5: AgentDriver protocol + FakeDriver

**Files:**
- Create: `src/foundry/drivers/base.py`
- Create: `src/foundry/drivers/fake.py`
- Test: `tests/drivers/__init__.py` (empty)
- Test: `tests/drivers/test_fake.py`

**Interfaces:**
- Produces: `@dataclass SessionSpec(cwd, prompt, model, tool_policy, mcp_servers, env, internal_endpoint, internal_secret, unit_id, run_id, step_id)`; `@dataclass SessionHandle(id, pid=None)`; `@dataclass DriverEvent(kind: Literal["tool_call","text","usage","completed","failed"], payload: dict={})`; `@dataclass SessionHealth(alive: bool, detail: str="")`; `class AgentDriver(Protocol)` with `spawn, stream_events, cancel, adopt, health`; `@dataclass FakeStepScript(mode: Literal["succeed","fail","delay"]="succeed", artifact: dict={}, delay_s: float=0.0, error: str="scripted failure")`; `class FakeDriver` implementing `AgentDriver`, constructed as `FakeDriver(script: dict[str, FakeStepScript] | None = None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/drivers/test_fake.py
import pytest

from foundry.drivers.base import SessionSpec
from foundry.drivers.fake import FakeDriver, FakeStepScript


def spec(unit_id: str, step_id: str) -> SessionSpec:
    return SessionSpec(
        cwd=".", prompt="p", model="fake", tool_policy={}, mcp_servers=[], env={},
        internal_endpoint="", internal_secret="", unit_id=unit_id, run_id="r1", step_id=step_id,
    )


@pytest.mark.asyncio
async def test_succeed_yields_tool_call_then_completed_with_artifact():
    driver = FakeDriver({"a": FakeStepScript(artifact={"x": 1})})
    handle = driver.spawn(spec("u1", "a"))

    events = [ev async for ev in driver.stream_events(handle)]

    assert [e.kind for e in events] == ["tool_call", "completed"]
    assert events[-1].payload["artifact"] == {"x": 1}


@pytest.mark.asyncio
async def test_fail_mode_yields_failed_event():
    driver = FakeDriver({"a": FakeStepScript(mode="fail", error="boom")})
    handle = driver.spawn(spec("u2", "a"))

    events = [ev async for ev in driver.stream_events(handle)]

    assert events[-1].kind == "failed"
    assert events[-1].payload["error"] == "boom"


@pytest.mark.asyncio
async def test_cancel_stops_stream_before_completion():
    driver = FakeDriver({"a": FakeStepScript(delay_s=1.0)})
    handle = driver.spawn(spec("u3", "a"))
    driver.cancel(handle)

    events = [ev async for ev in driver.stream_events(handle)]

    assert all(e.kind != "completed" for e in events)


def test_adopt_returns_all_known_handles_health_reflects_state():
    driver = FakeDriver()
    handle = driver.spawn(spec("u4", "a"))

    assert [h.id for h in driver.adopt()] == ["u4"]
    assert driver.health(handle).alive is True

    driver.cancel(handle)
    assert driver.health(handle).alive is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/drivers/test_fake.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.drivers.base'`

- [ ] **Step 3: Write `src/foundry/drivers/base.py`**

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol


@dataclass
class SessionSpec:
    cwd: str
    prompt: str
    model: str
    tool_policy: dict
    mcp_servers: list[str]
    env: dict[str, str]
    internal_endpoint: str
    internal_secret: str
    unit_id: str
    run_id: str
    step_id: str


@dataclass
class SessionHandle:
    id: str
    pid: int | None = None


@dataclass
class DriverEvent:
    kind: Literal["tool_call", "text", "usage", "completed", "failed"]
    payload: dict = field(default_factory=dict)


@dataclass
class SessionHealth:
    alive: bool
    detail: str = ""


class AgentDriver(Protocol):
    def spawn(self, spec: SessionSpec) -> SessionHandle: ...
    def stream_events(self, handle: SessionHandle) -> AsyncIterator[DriverEvent]: ...
    def cancel(self, handle: SessionHandle, tree_kill: bool = True) -> None: ...
    def adopt(self) -> list[SessionHandle]: ...
    def health(self, handle: SessionHandle) -> SessionHealth: ...
```

- [ ] **Step 4: Write `src/foundry/drivers/fake.py`**

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import AsyncIterator, Literal

from foundry.drivers.base import DriverEvent, SessionHandle, SessionHealth, SessionSpec


@dataclass
class FakeStepScript:
    mode: Literal["succeed", "fail", "delay"] = "succeed"
    artifact: dict = field(default_factory=dict)
    delay_s: float = 0.0
    error: str = "scripted failure"


class FakeDriver:
    def __init__(self, script: dict[str, FakeStepScript] | None = None):
        self.script = script or {}
        self._known: dict[str, SessionHandle] = {}
        self._handle_step: dict[str, str] = {}
        self._cancelled: set[str] = set()

    def spawn(self, spec: SessionSpec) -> SessionHandle:
        handle = SessionHandle(id=spec.unit_id, pid=None)
        self._known[handle.id] = handle
        self._handle_step[handle.id] = spec.step_id
        return handle

    async def stream_events(self, handle: SessionHandle) -> AsyncIterator[DriverEvent]:
        step_script = self.script.get(self._handle_step.get(handle.id, ""), FakeStepScript())
        yield DriverEvent(kind="tool_call", payload={"tool": "noop"})

        if step_script.delay_s:
            await asyncio.sleep(step_script.delay_s)

        if handle.id in self._cancelled:
            return
        if step_script.mode == "fail":
            yield DriverEvent(kind="failed", payload={"error": step_script.error})
        else:
            yield DriverEvent(kind="completed", payload={"artifact": step_script.artifact})

    def cancel(self, handle: SessionHandle, tree_kill: bool = True) -> None:
        self._cancelled.add(handle.id)

    def adopt(self) -> list[SessionHandle]:
        return list(self._known.values())

    def health(self, handle: SessionHandle) -> SessionHealth:
        alive = handle.id in self._known and handle.id not in self._cancelled
        return SessionHealth(alive=alive)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/drivers/test_fake.py -v`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/drivers/base.py src/foundry/drivers/fake.py tests/drivers/
git commit -m "feat(drivers): AgentDriver protocol + deterministic FakeDriver"
```

---

### Task 6: Orchestrator tick loop + crash recovery

**Files:**
- Create: `src/foundry/orchestrator/tick.py`
- Test: `tests/orchestrator/__init__.py` (empty)
- Test: `tests/orchestrator/test_tick.py`
- Test fixture: `tests/orchestrator/fixtures/linear_demo.toml`

**Interfaces:**
- Consumes: `Store` (Task 2), `PlaybookSpec`/`StepSpec` (Task 3), `materialize` (Task 4), `AgentDriver`/`SessionSpec`/`DriverEvent` (Task 5).
- Produces: `@dataclass TickResult(dispatched: int, closed: int, failed: int)`; `class Orchestrator(store: Store, driver: AgentDriver, playbook: PlaybookSpec, concurrency: int = 5)` with `async reconcile(run_id)`, `async apply_gate_decisions(run_id)`, `async unblock(run_id)`, `async dispatch(run_id) -> int`, `async tick(run_id) -> TickResult`, `async run_to_completion(run_id, max_ticks=100) -> TickResult`.

This task proves M0's crash-recovery exit criterion: an in-flight session is interrupted mid-collection (via `asyncio.wait_for` timeout — the deterministic equivalent of `kill -9` against a FakeDriver, since no tokens or real processes exist to lose), a **fresh** `Orchestrator` + `FakeDriver` pair (simulating process restart with no in-memory state) is pointed at the **same** on-disk store, and the run completes with no duplicate artifacts.

- [ ] **Step 1: Write the fixture and the failing test**

```toml
# tests/orchestrator/fixtures/linear_demo.toml
[playbook]
id = "linear_demo"
description = "3-step linear demo: plan -> implement -> review"

[[step]]
id = "plan"
role = "planner"
produces = "plan_artifact"
gate = "none"

[[step]]
id = "implement"
role = "developer"
needs = ["plan"]
produces = "code_diff_artifact"
gate = "none"

[[step]]
id = "review"
role = "reviewer"
needs = ["implement"]
produces = "review_artifact"
gate = "none"
```

```python
# tests/orchestrator/test_tick.py
import asyncio

import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store

FIXTURE = "tests/orchestrator/fixtures/linear_demo.toml"


async def make_store(tmp_path) -> Store:
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_linear_playbook_runs_to_completion_on_fake_driver(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(artifact={"steps": ["a", "b"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)

    result = await orchestrator.run_to_completion(run.id)

    assert result.failed == 0
    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    assert len(task_units) == 3
    assert all(u.status == "closed" for u in task_units)

    artifacts = await store.list_artifacts(run.id)
    assert {a.kind for a in artifacts} == {"plan_artifact", "code_diff_artifact", "review_artifact"}

    await store.stop()


@pytest.mark.asyncio
async def test_crash_mid_session_recovers_on_restart_with_no_duplicate_artifacts(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo2", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run 2")
    await materialize(playbook, run.id, store)

    slow_script = {
        "plan": FakeStepScript(artifact={"steps": ["a"]}),
        "implement": FakeStepScript(artifact={"diff": "..."}, mode="delay", delay_s=5.0),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    orch1 = Orchestrator(store, FakeDriver(slow_script), playbook)

    await orch1.tick(run.id)  # closes "plan"

    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(orch1.tick(run.id), timeout=0.05)  # "kill -9" mid-"implement" session

    units = await store.list_units(run.id)
    implement_task = next(u for u in units if u.step_id == "implement" and u.type == "task")
    assert implement_task.status == "in_progress"
    implement_session = next(u for u in units if u.type == "session" and u.step_id == "implement")
    assert implement_session.status == "running"

    fast_script = {**slow_script, "implement": FakeStepScript(artifact={"diff": "..."})}
    orch2 = Orchestrator(store, FakeDriver(fast_script), playbook)  # fresh driver: adopt() -> []

    result = await orch2.run_to_completion(run.id)

    assert result.failed == 0
    task_units = [u for u in await store.list_units(run.id) if u.type == "task"]
    assert all(u.status == "closed" for u in task_units)

    artifacts = await store.list_artifacts(run.id)
    implement_artifacts = [a for a in artifacts if a.kind == "code_diff_artifact"]
    assert len(implement_artifacts) == 1  # no duplicate from the crashed attempt

    retried_events = await store.list_events(run.id)
    assert any(e.type == "unit.retried" for e in retried_events)

    await store.stop()


@pytest.mark.asyncio
async def test_failed_session_retries_then_blocks_after_max_attempts(tmp_path):
    store = await make_store(tmp_path)
    project = await store.create_project("demo3", str(tmp_path))
    playbook = load_playbook(FIXTURE)
    run = await store.create_run(project.id, FIXTURE, "demo run 3")
    await materialize(playbook, run.id, store)

    script = {
        "plan": FakeStepScript(mode="fail", error="always fails"),
        "implement": FakeStepScript(artifact={"diff": "..."}),
        "review": FakeStepScript(artifact={"verdict": "ok"}),
    }
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)

    await orchestrator.run_to_completion(run.id, max_ticks=10)

    units = await store.list_units(run.id)
    plan_task = next(u for u in units if u.step_id == "plan" and u.type == "task")
    assert plan_task.status == "blocked"
    assert plan_task.attempt == plan_task.max_attempts

    gates = await store.list_gates_for_run(run.id)
    assert any(g.work_unit_id == plan_task.id and g.decision == "pending" for g in gates)

    await store.stop()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/orchestrator/test_tick.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.orchestrator.tick'`

- [ ] **Step 3: Write `src/foundry/orchestrator/tick.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

from foundry.drivers.base import AgentDriver, SessionSpec
from foundry.playbook.schema import PlaybookSpec, StepSpec
from foundry.store.models import WorkUnit
from foundry.store.store import Store


@dataclass
class TickResult:
    dispatched: int
    closed: int
    failed: int


class Orchestrator:
    def __init__(self, store: Store, driver: AgentDriver, playbook: PlaybookSpec, concurrency: int = 5):
        self.store = store
        self.driver = driver
        self.playbook = playbook
        self.concurrency = concurrency
        self._steps_by_id: dict[str, StepSpec] = {s.id: s for s in playbook.steps}

    async def tick(self, run_id: str) -> TickResult:
        await self.reconcile(run_id)
        await self.apply_gate_decisions(run_id)
        await self.unblock(run_id)
        await self._close_derived_gates(run_id)
        dispatched = await self.dispatch(run_id)

        units = await self.store.list_units(run_id)
        closed = sum(1 for u in units if u.status == "closed")
        failed = sum(1 for u in units if u.status == "failed")
        return TickResult(dispatched=dispatched, closed=closed, failed=failed)

    async def run_to_completion(self, run_id: str, max_ticks: int = 100) -> TickResult:
        result = TickResult(0, 0, 0)
        for _ in range(max_ticks):
            result = await self.tick(run_id)
            units = await self.store.list_units(run_id)
            pending = [u for u in units if u.status not in ("closed", "failed", "blocked")]
            if not pending:
                break
        return result

    async def reconcile(self, run_id: str) -> None:
        units = await self.store.list_units(run_id)
        live_ids = {h.id for h in self.driver.adopt()}

        for unit in units:
            if unit.type != "session" or unit.status not in ("intent", "running"):
                continue
            if unit.id in live_ids:
                continue  # still alive, nothing to reconcile

            owner_task = next((u for u in units if u.owner_session_id == unit.id), None)
            await self.store.update_unit(unit.id, status="failed")
            if owner_task is None:
                continue

            next_attempt = owner_task.attempt + 1
            if next_attempt >= owner_task.max_attempts:
                await self.store.update_unit(owner_task.id, status="blocked", attempt=next_attempt)
                await self.store.create_gate(work_unit_id=owner_task.id, gate_type="human", decision="pending")
                await self.store.append_event(run_id, owner_task.id, "unit.blocked", {"reason": "max_attempts"})
            else:
                await self.store.update_unit(
                    owner_task.id, status="ready", attempt=next_attempt, owner_session_id=None
                )
                await self.store.append_event(run_id, owner_task.id, "unit.retried", {"attempt": next_attempt})

    async def apply_gate_decisions(self, run_id: str) -> None:
        units = {u.id: u for u in await self.store.list_units(run_id)}
        gates = await self.store.list_gates_for_run(run_id)

        for gate in gates:
            if gate.decision == "pending":
                continue
            unit = units.get(gate.work_unit_id)
            if unit is None or unit.status != "blocked":
                continue
            if gate.decision == "approved":
                await self.store.update_unit(unit.id, status="closed")
                await self.store.append_event(run_id, unit.id, "gate.approved", {"gate_id": gate.id})
            elif gate.decision == "rejected":
                await self.store.update_unit(unit.id, status="ready", attempt=unit.attempt + 1)
                await self.store.append_event(run_id, unit.id, "gate.rejected", {"gate_id": gate.id})

    async def unblock(self, run_id: str) -> None:
        ready = await self.store.get_ready_units(run_id)
        for unit in ready:
            await self.store.update_unit(unit.id, status="ready")
            await self.store.append_event(run_id, unit.id, "unit.ready", {})

    async def _close_derived_gates(self, run_id: str) -> None:
        units = await self.store.list_units(run_id)
        for unit in units:
            if unit.type == "gate" and unit.status == "ready":
                await self.store.update_unit(unit.id, status="closed")
                await self.store.append_event(run_id, unit.id, "gate.derived_approved", {})

    async def dispatch(self, run_id: str) -> int:
        units = await self.store.list_units(run_id)
        ready_tasks = [u for u in units if u.status == "ready" and u.type == "task"]
        in_progress = sum(1 for u in units if u.status == "in_progress" and u.type == "task")
        slots = max(0, self.concurrency - in_progress)

        dispatched = 0
        for task_unit in ready_tasks[:slots]:
            step = self._steps_by_id[task_unit.step_id]
            session_unit = (
                await self.store.create_work_units(
                    [WorkUnit(run_id=run_id, step_id=task_unit.step_id, type="session", status="intent")]
                )
            )[0]
            await self.store.update_unit(task_unit.id, owner_session_id=session_unit.id)
            await self.store.append_event(run_id, session_unit.id, "session.intent", {})

            spec = SessionSpec(
                cwd=".", prompt=f"step:{step.id}", model="fake", tool_policy={}, mcp_servers=[],
                env={}, internal_endpoint="", internal_secret="",
                unit_id=session_unit.id, run_id=run_id, step_id=step.id,
            )
            handle = self.driver.spawn(spec)
            await self.store.update_unit(session_unit.id, status="running")
            await self.store.create_session_row(
                id=session_unit.id, work_unit_id=session_unit.id,
                driver=type(self.driver).__name__, status="running",
            )
            await self.store.update_unit(task_unit.id, status="in_progress")
            await self.store.append_event(run_id, session_unit.id, "session.spawned", {"handle_id": handle.id})
            dispatched += 1

            await self._collect(run_id, task_unit, session_unit, step, handle)

        return dispatched

    async def _collect(self, run_id: str, task_unit: WorkUnit, session_unit: WorkUnit, step: StepSpec, handle) -> None:
        artifact_payload: dict = {}
        failed = False
        error_payload: dict = {}

        async for ev in self.driver.stream_events(handle):
            await self.store.append_event(run_id, session_unit.id, f"driver.{ev.kind}", ev.payload)
            if ev.kind == "completed":
                artifact_payload = ev.payload.get("artifact", {})
            elif ev.kind == "failed":
                failed = True
                error_payload = ev.payload

        await self.store.update_unit(session_unit.id, status="failed" if failed else "closed")
        await self.store.update_session_row(session_unit.id, status="ended")

        if failed:
            next_attempt = task_unit.attempt + 1
            if next_attempt >= task_unit.max_attempts:
                await self.store.update_unit(task_unit.id, status="blocked", attempt=next_attempt)
                await self.store.create_gate(work_unit_id=task_unit.id, gate_type="human", decision="pending")
                await self.store.append_event(
                    run_id, task_unit.id, "unit.blocked", {"reason": "failed", "error": error_payload}
                )
            else:
                await self.store.update_unit(
                    task_unit.id, status="ready", attempt=next_attempt, owner_session_id=None
                )
                await self.store.append_event(run_id, task_unit.id, "unit.retried", {"attempt": next_attempt})
            return

        artifact = await self.store.create_artifact(
            run_id=run_id, work_unit_id=task_unit.id, kind=step.produces or "artifact",
            version=1, produced_by_role=step.role, payload_json=artifact_payload,
        )
        await self.store.append_event(run_id, task_unit.id, "artifact.produced", {"artifact_id": artifact.id})

        if step.gate in (None, "none"):
            await self.store.update_unit(task_unit.id, status="closed")
            await self.store.append_event(run_id, task_unit.id, "unit.closed", {})
        else:
            gate = await self.store.create_gate(
                work_unit_id=task_unit.id, artifact_id=artifact.id, gate_type=step.gate, decision="pending",
            )
            await self.store.update_unit(task_unit.id, status="blocked")
            await self.store.append_event(run_id, task_unit.id, "gate.created", {"gate_id": gate.id})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/orchestrator/test_tick.py -v`
Expected: PASS (3 tests, including crash recovery)

- [ ] **Step 5: Run the full suite so far**

Run: `uv run pytest -v`
Expected: PASS (all tests across Tasks 1-6)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/orchestrator/tick.py tests/orchestrator/
git commit -m "feat(orchestrator): tick loop (reconcile/unblock/dispatch/collect/retry) + crash recovery"
```

---

### Task 7: CLI — `foundry run` and `foundry events`

**Files:**
- Create: `src/foundry/cli.py`
- Test: `tests/test_cli.py`
- Test fixture: `tests/fixtures/cli_demo.toml`

**Interfaces:**
- Consumes: everything from Tasks 1-6.
- Produces: `app = typer.Typer()` with commands `run(playbook_path: str, project_path: str = ".", db: str = "foundry.db")` (prints the run id to stdout) and `events(run_id: str, db: str = "foundry.db", once: bool = False)` (prints new events; `--once` exits after draining current events instead of polling forever — used by tests and by scripting, real interactive use omits it).

- [ ] **Step 1: Write the fixture and the failing test**

```toml
# tests/fixtures/cli_demo.toml
[playbook]
id = "cli_demo"
description = "single-step smoke test playbook"

[[step]]
id = "plan"
role = "planner"
produces = "plan_artifact"
gate = "none"
```

```python
# tests/test_cli.py
from typer.testing import CliRunner

from foundry.cli import app

runner = CliRunner()


def test_run_then_events_smoke(tmp_path):
    db_path = str(tmp_path / "foundry.db")

    run_result = runner.invoke(app, ["run", "tests/fixtures/cli_demo.toml", "--db", db_path])
    assert run_result.exit_code == 0, run_result.output
    run_id = run_result.output.strip()
    assert len(run_id) == 26  # ULID

    events_result = runner.invoke(app, ["events", run_id, "--db", db_path, "--once"])
    assert events_result.exit_code == 0, events_result.output
    assert "unit.closed" in events_result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'foundry.cli'`

- [ ] **Step 3: Write `src/foundry/cli.py`**

```python
from __future__ import annotations

import asyncio

import typer

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.lint import lint_plan_first
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store

app = typer.Typer()


@app.command()
def run(playbook_path: str, project_path: str = ".", db: str = "foundry.db") -> None:
    run_id = asyncio.run(_run(playbook_path, project_path, db))
    typer.echo(run_id)


async def _run(playbook_path: str, project_path: str, db: str) -> str:
    engine = make_engine(db)
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    playbook = load_playbook(playbook_path)
    lint_plan_first(playbook)

    project = await store.create_project(playbook.id, project_path)
    run_row = await store.create_run(project.id, playbook_path, playbook.description or playbook.id)
    await materialize(playbook, run_row.id, store)

    script = {step.id: FakeStepScript(artifact={"ok": True}) for step in playbook.steps}
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)
    await orchestrator.run_to_completion(run_row.id)

    await store.stop()
    return run_row.id


@app.command()
def events(run_id: str, db: str = "foundry.db", once: bool = False) -> None:
    asyncio.run(_events(run_id, db, once))


async def _events(run_id: str, db: str, once: bool) -> None:
    engine = make_engine(db)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    last_seq = 0
    while True:
        new_events = await store.list_events(run_id, after_seq=last_seq)
        for ev in new_events:
            typer.echo(f"[{ev.seq}] {ev.type} unit={ev.unit_id} {ev.payload_json}")
            last_seq = ev.seq
        if once:
            break
        await asyncio.sleep(0.2)

    await store.stop()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Run the entire suite**

Run: `uv run pytest -v`
Expected: PASS (all tests, Tasks 1-7)

- [ ] **Step 6: Commit**

```bash
git add src/foundry/cli.py tests/test_cli.py tests/fixtures/
git commit -m "feat(cli): foundry run + foundry events against FakeDriver"
```

---

## Out of scope for this plan (tracked, not forgotten)

- **`/internal` FastAPI + ClaudeCodeDriver + real end-to-end run** — M0 exit criterion (b). Needs its own plan: HTTP artifact submission, shared-secret auth, subprocess driver with `stream-json`, log-file-based session transport (design doc §8 driver spec requirements 1-4).
- **Fan-out/convoys, worktrees-per-unit, concurrent dispatch** — explicitly M2 (design doc §15). `Orchestrator.dispatch` is sequential by design in this plan; the loop structure is written so swapping the synchronous `await self._collect(...)` for a background task per session is the M2 change, not a rewrite.
- **Artifact JSON-schema validation, rework/version-increment on gate rejection, `notes_addressed` contract** — M1.
- **Dashboard, SSE, `/api`** — M1.
- **Knowledge graph (F8), compounding memory (F9), packs (F10), portfolio/cross-project fair scheduling (F11)** — M3/M4 per the roadmap; this plan creates the `projects` table (Task 1) so runs are project-namespaced from day one, per design doc §15 M1 exit note, but no portfolio UI or multi-project scheduling logic.
