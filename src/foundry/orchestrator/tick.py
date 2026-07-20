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
        closed = sum(1 for u in units if u.status == "closed" and u.type == "task")
        failed = sum(1 for u in units if u.status == "failed" and u.type == "task")
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
