from __future__ import annotations

import asyncio
import gzip
import json
from collections.abc import Awaitable, Callable
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from foundry.store.models import (
    Artifact,
    Event,
    Gate,
    Memory,
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

    async def update_project(self, project_id: str, **fields) -> None:
        async def _op(session):
            project = await session.get(Project, project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            for key, value in fields.items():
                setattr(project, key, value)

        await self.write(_op)

    async def create_run(
        self, project_id: str, playbook_ref: str, title: str, pack_version_pin: str = "local"
    ) -> Run:
        async def _op(session):
            run = Run(
                project_id=project_id,
                playbook_ref=playbook_ref,
                title=title,
                pack_version_pin=pack_version_pin,
            )
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
            if run is None:
                raise ValueError(f"Run {run_id} not found")
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

    async def list_sessions_for_run(self, run_id: str) -> list[SessionRow]:
        async def _op(session):
            res = await session.execute(
                select(SessionRow)
                .join(WorkUnit, WorkUnit.id == SessionRow.work_unit_id)
                .where(WorkUnit.run_id == run_id)
            )
            return list(res.scalars())

        return await self.read(_op)

    async def list_active_sessions(self) -> list[dict]:
        async def _op(session):
            res = await session.execute(
                select(SessionRow, WorkUnit.run_id, WorkUnit.step_id)
                .join(WorkUnit, WorkUnit.id == SessionRow.work_unit_id)
                .where(SessionRow.status.in_(("intent", "running")))
            )
            rows = []
            for session_row, run_id, step_id in res.all():
                rows.append(
                    {
                        "id": session_row.id,
                        "work_unit_id": session_row.work_unit_id,
                        "run_id": run_id,
                        "step_id": step_id,
                        "driver": session_row.driver,
                        "status": session_row.status,
                        "model": session_row.model,
                        "tokens_in": session_row.tokens_in,
                        "tokens_out": session_row.tokens_out,
                        "started_at": session_row.started_at.isoformat() if session_row.started_at else None,
                    }
                )
            return rows

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

    async def list_closed_runs_older_than(self, days: int) -> list[Run]:
        async def _op(session):
            cutoff = utcnow() - timedelta(days=days)
            stmt = select(Run).where(
                Run.status.in_(("closed", "cancelled", "failed")),
                Run.closed_at.is_not(None),
                Run.closed_at < cutoff,
            )
            res = await session.execute(stmt)
            return list(res.scalars())

        return await self.read(_op)

    async def archive_run_events(self, run_id: str, archive_dir: str) -> str:
        events = await self.list_events(run_id)
        archive_path = Path(archive_dir) / f"{run_id}.jsonl.gz"
        with gzip.open(archive_path, "wt") as f:
            for ev in events:
                f.write(
                    json.dumps(
                        {
                            "seq": ev.seq,
                            "run_id": ev.run_id,
                            "unit_id": ev.unit_id,
                            "type": ev.type,
                            "payload_json": ev.payload_json,
                            "created_at": ev.created_at.isoformat(),
                        }
                    )
                    + "\n"
                )

        async def _op(session):
            await session.execute(delete(Event).where(Event.run_id == run_id))

        await self.write(_op)
        return str(archive_path)

    # --- memory ---

    async def create_memory_item(
        self,
        scope: str,
        kind: str,
        title: str,
        body_md: str,
        project_id: str | None = None,
        pack_id: str | None = None,
        source_run_id: str | None = None,
    ) -> Memory:
        async def _op(session):
            item = Memory(
                scope=scope,
                kind=kind,
                title=title,
                body_md=body_md,
                project_id=project_id,
                pack_id=pack_id,
                source_run_id=source_run_id,
            )
            session.add(item)
            await session.flush()
            return item

        return await self.write(_op)

    async def list_memory_items(
        self,
        scope: str | None = None,
        project_id: str | None = None,
        pack_id: str | None = None,
        kind: str | None = None,
    ) -> list[Memory]:
        async def _op(session):
            stmt = select(Memory)
            if scope is not None:
                stmt = stmt.where(Memory.scope == scope)
            if project_id is not None:
                stmt = stmt.where(Memory.project_id == project_id)
            if pack_id is not None:
                stmt = stmt.where(Memory.pack_id == pack_id)
            if kind is not None:
                stmt = stmt.where(Memory.kind == kind)
            res = await session.execute(stmt)
            return list(res.scalars())

        return await self.read(_op)
