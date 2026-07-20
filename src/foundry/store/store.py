from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any

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
from foundry.store.redaction import redact_event_payload


class Store:
    def __init__(self, engine: AsyncEngine, sessionmaker: async_sessionmaker):
        self._engine = engine
        self._sessionmaker = sessionmaker
        self._queue: asyncio.Queue = asyncio.Queue()
        self._writer_task: asyncio.Task | None = None
        self._running: bool = False

    async def start(self) -> None:
        self._writer_task = asyncio.create_task(self._writer_loop())
        self._running = True

    async def stop(self) -> None:
        if self._writer_task is not None:
            self._running = False
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
        if not self._running:
            raise RuntimeError("Store is not running — call start() first")
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

    async def list_projects(self) -> list[Project]:
        async def _op(session):
            res = await session.execute(select(Project))
            return list(res.scalars())

        return await self.read(_op)

    async def get_project(self, project_id: str) -> Project | None:
        async def _op(session):
            return await session.get(Project, project_id)

        return await self.read(_op)

    async def create_run(self, project_id: str, playbook_ref: str, title: str) -> Run:
        async def _op(session):
            run = Run(project_id=project_id, playbook_ref=playbook_ref, title=title)
            session.add(run)
            await session.flush()
            return run

        return await self.write(_op)

    async def get_run(self, run_id: str) -> Run | None:
        async def _op(session):
            return await session.get(Run, run_id)

        return await self.read(_op)

    async def list_runs(self, project_id: str | None = None, status: str | None = None) -> list[Run]:
        async def _op(session):
            stmt = select(Run)
            if project_id is not None:
                stmt = stmt.where(Run.project_id == project_id)
            if status is not None:
                stmt = stmt.where(Run.status == status)
            res = await session.execute(stmt)
            return list(res.scalars())

        return await self.read(_op)

    async def update_run(self, run_id: str, **fields) -> None:
        async def _op(session):
            run = await session.get(Run, run_id)
            for key, value in fields.items():
                setattr(run, key, value)

        await self.write(_op)

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

    async def get_next_artifact_version(self, work_unit_id: str) -> int:
        async def _op(session):
            res = await session.execute(
                select(Artifact.version)
                .where(Artifact.work_unit_id == work_unit_id)
                .order_by(Artifact.version.desc())
            )
            latest = res.scalars().first()
            return (latest or 0) + 1

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

    async def decide_gate(
        self, gate_id: str, decision: str, feedback: dict | None = None, decided_by: str = "human"
    ) -> None:
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

    async def get_session_row(self, session_id: str) -> SessionRow | None:
        async def _op(session):
            return await session.get(SessionRow, session_id)

        return await self.read(_op)

    # --- events ---

    async def append_event(
        self, run_id: str, unit_id: str | None, type_: str, payload: dict | None = None
    ) -> int:
        async def _op(session):
            redacted_payload = redact_event_payload(payload or {})
            ev = Event(run_id=run_id, unit_id=unit_id, type=type_, payload_json=redacted_payload)
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
