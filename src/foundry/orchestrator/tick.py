from __future__ import annotations

from dataclasses import dataclass

from foundry.drivers.base import AgentDriver, SessionSpec
from foundry.playbook.schema import STEP_TYPE_TO_UNIT_TYPE, PlaybookSpec, StepSpec
from foundry.store.models import Artifact, Gate, UnitDep, WorkUnit
from foundry.store.store import Store


@dataclass
class TickResult:
    dispatched: int
    closed: int
    failed: int
    complete: bool = True


def _resolve_fan_out_slices(artifacts: list[Artifact], kind: str, field: str) -> list:
    matching = [a for a in artifacts if a.kind == kind]
    if not matching:
        raise ValueError(f"fan-out: no artifact of kind {kind!r} found yet")
    latest = max(matching, key=lambda a: a.version)
    value = latest.payload_json.get(field)
    if not isinstance(value, list):
        raise ValueError(f"fan-out source {kind}.{field} is not a list (got {type(value).__name__})")
    return value


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
        await self._gate_derived_units(run_id)
        await self._fan_out(run_id)
        await self._close_convoys(run_id)
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

        units = await self.store.list_units(run_id)
        pending = [u for u in units if u.status not in ("closed", "failed", "blocked")]
        result.complete = not pending
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
                await self.store.create_gate(
                    work_unit_id=owner_task.id, gate_type="human", decision="pending"
                )
                await self.store.append_event(
                    run_id, owner_task.id, "unit.blocked", {"reason": "max_attempts"}
                )
            else:
                await self.store.update_unit(
                    owner_task.id, status="ready", attempt=next_attempt, owner_session_id=None
                )
                await self.store.append_event(
                    run_id, owner_task.id, "unit.retried", {"attempt": next_attempt}
                )

        # Second pass: recover tasks orphaned in the crash window between a session
        # reaching a terminal status (closed/failed) and the owning task being
        # finalized (artifact creation + task close/block). Re-fetch units since the
        # first pass above may have changed state.
        units = await self.store.list_units(run_id)
        for unit in units:
            if unit.type != "task" or unit.status != "in_progress":
                continue
            session_unit = next((u for u in units if u.id == unit.owner_session_id), None)
            if session_unit is None or session_unit.status not in ("closed", "failed"):
                continue

            step = self._steps_by_id[unit.step_id]
            artifacts = await self.store.list_artifacts(run_id)
            existing = next((a for a in artifacts if a.work_unit_id == unit.id), None)

            if existing is not None:
                if step.gate in (None, "none"):
                    await self.store.update_unit(unit.id, status="closed")
                    await self.store.append_event(run_id, unit.id, "unit.closed", {"recovered": True})
                else:
                    gates = await self.store.list_gates_for_run(run_id)
                    existing_gate = next((g for g in gates if g.work_unit_id == unit.id), None)
                    gate_id: str | None = None
                    if existing_gate is None:
                        gate = await self.store.create_gate(
                            work_unit_id=unit.id,
                            artifact_id=existing.id,
                            gate_type=step.gate,
                            decision="pending",
                        )
                        gate_id = gate.id
                    else:
                        gate = existing_gate
                    await self.store.update_unit(unit.id, status="blocked")
                    payload = {"recovered": True}
                    if gate_id is not None:
                        payload["gate_id"] = gate_id
                    await self.store.append_event(run_id, unit.id, "gate.created", payload)
            else:
                next_attempt = unit.attempt + 1
                if next_attempt >= unit.max_attempts:
                    await self.store.update_unit(unit.id, status="blocked", attempt=next_attempt)
                    await self.store.create_gate(work_unit_id=unit.id, gate_type="human", decision="pending")
                    await self.store.append_event(
                        run_id, unit.id, "unit.blocked", {"reason": "orphaned_after_session_finalized"}
                    )
                else:
                    await self.store.update_unit(
                        unit.id, status="ready", attempt=next_attempt, owner_session_id=None
                    )
                    await self.store.append_event(
                        run_id,
                        unit.id,
                        "unit.retried",
                        {"attempt": next_attempt, "reason": "orphaned_after_session_finalized"},
                    )

    async def apply_gate_decisions(self, run_id: str) -> None:
        units = {u.id: u for u in await self.store.list_units(run_id)}
        gates = await self.store.list_gates_for_run(run_id)

        # A rejected gate reopens its unit, which (on rework) gets a brand-new gate
        # for the same work_unit_id. Only the most-recently-created gate per unit
        # (ids are ULIDs, so lexicographic == chronological) is "live" — without
        # this, a stale already-actioned rejection would be replayed against the
        # unit forever once it cycles back through "blocked", reopening it on every
        # subsequent tick and duplicating rework indefinitely.
        latest_by_unit: dict[str, Gate] = {}
        for gate in gates:
            current = latest_by_unit.get(gate.work_unit_id)
            if current is None or gate.id > current.id:
                latest_by_unit[gate.work_unit_id] = gate

        for gate in latest_by_unit.values():
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

    async def _gate_derived_units(self, run_id: str) -> None:
        units = await self.store.list_units(run_id)
        gates = await self.store.list_gates_for_run(run_id)
        already_gated = {g.work_unit_id for g in gates}

        for unit in units:
            if unit.type != "gate" or unit.status != "ready":
                continue
            if unit.id in already_gated:
                continue
            await self.store.create_gate(work_unit_id=unit.id, gate_type="derived", decision="pending")
            await self.store.update_unit(unit.id, status="blocked")
            await self.store.append_event(run_id, unit.id, "gate.created", {"gate_type": "derived"})

    async def _fan_out(self, run_id: str) -> None:
        units = await self.store.list_units(run_id)
        static_unit_by_step = {u.step_id: u for u in units if u.convoy_id is None and u.type != "convoy"}
        expanded_steps = {u.step_id for u in units if u.type == "convoy"}

        for step in self.playbook.steps:
            if not step.fan_out or step.id in expanded_steps:
                continue
            need_units = [static_unit_by_step.get(n) for n in step.needs]
            if any(u is None or u.status != "closed" for u in need_units):
                continue

            artifacts = await self.store.list_artifacts(run_id)
            kind, _, field = step.fan_out.partition(".")
            slices = _resolve_fan_out_slices(artifacts, kind, field)

            convoy = (
                await self.store.create_work_units(
                    [WorkUnit(run_id=run_id, step_id=step.id, type="convoy", status="open")]
                )
            )[0]
            await self.store.append_event(run_id, convoy.id, "convoy.created", {"size": len(slices)})

            chain = [step] + [s for s in self.playbook.steps if s.fan_out_from == step.id]
            units_by_step_index: dict[str, list[WorkUnit]] = {}

            for chain_step in chain:
                payloads = [
                    {"slice_index": i, "slice": slices[i]} if chain_step is step else {"slice_index": i}
                    for i in range(len(slices))
                ]
                max_attempts = chain_step.loop.max_rounds if chain_step.loop else 3
                new_units = await self.store.create_work_units(
                    [
                        WorkUnit(
                            run_id=run_id,
                            step_id=chain_step.id,
                            type=STEP_TYPE_TO_UNIT_TYPE[chain_step.type],
                            status="open",
                            convoy_id=convoy.id,
                            payload_json=payloads[i],
                            max_attempts=max_attempts,
                        )
                        for i in range(len(slices))
                    ]
                )
                deps: list[UnitDep] = []
                if chain_step is step:
                    for unit in new_units:
                        for need_id in chain_step.needs:
                            deps.append(
                                UnitDep(
                                    unit_id=unit.id,
                                    needs_unit_id=need_units[chain_step.needs.index(need_id)].id,
                                )
                            )
                else:
                    source_units = units_by_step_index[chain_step.fan_out_from]
                    for i, unit in enumerate(new_units):
                        deps.append(UnitDep(unit_id=unit.id, needs_unit_id=source_units[i].id))
                if deps:
                    await self.store.add_unit_deps(deps)
                units_by_step_index[chain_step.id] = new_units
                await self.store.append_event(
                    run_id, convoy.id, "unit.created", {"step_id": chain_step.id, "count": len(new_units)}
                )

            chain_ids = {s.id for s in chain}
            already_materialized = {u.step_id for u in units if u.convoy_id is None and u.type != "convoy"}
            downstream = [
                s
                for s in self.playbook.steps
                if s.id not in chain_ids
                and s.id not in already_materialized
                and any(n in chain_ids for n in s.needs)
            ]
            for ds_step in downstream:
                ds_unit = (
                    await self.store.create_work_units(
                        [
                            WorkUnit(
                                run_id=run_id,
                                step_id=ds_step.id,
                                type=STEP_TYPE_TO_UNIT_TYPE[ds_step.type],
                                status="open",
                            )
                        ]
                    )
                )[0]
                dep_rows = [UnitDep(unit_id=ds_unit.id, needs_unit_id=convoy.id)]
                for need_id in ds_step.needs:
                    if need_id in chain_ids:
                        continue
                    other = static_unit_by_step.get(need_id)
                    if other is not None:
                        dep_rows.append(UnitDep(unit_id=ds_unit.id, needs_unit_id=other.id))
                await self.store.add_unit_deps(dep_rows)

    async def _close_convoys(self, run_id: str) -> None:
        units = await self.store.list_units(run_id)
        convoys = [u for u in units if u.type == "convoy" and u.status not in ("closed", "failed")]
        for convoy in convoys:
            step = self._steps_by_id[convoy.step_id]
            leaf_step_id = step.id
            for candidate in self.playbook.steps:
                if candidate.fan_out_from == step.id:
                    leaf_step_id = candidate.id  # last step in chain wins; one-hop chains only (Task 1)

            leaf_units = [u for u in units if u.step_id == leaf_step_id and u.convoy_id == convoy.id]
            if not leaf_units:
                continue
            if any(u.status == "failed" for u in leaf_units):
                await self.store.update_unit(convoy.id, status="failed")
                await self.store.append_event(run_id, convoy.id, "convoy.closed", {"status": "failed"})
            elif all(u.status == "closed" for u in leaf_units):
                await self.store.update_unit(convoy.id, status="closed")
                await self.store.append_event(run_id, convoy.id, "convoy.closed", {"status": "closed"})

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
                cwd=".",
                prompt=f"step:{step.id}",
                model="fake",
                tool_policy={},
                mcp_servers=[],
                env={},
                internal_endpoint="",
                internal_secret="",
                unit_id=session_unit.id,
                run_id=run_id,
                step_id=step.id,
            )
            handle = self.driver.spawn(spec)
            await self.store.update_unit(session_unit.id, status="running")
            await self.store.create_session_row(
                id=session_unit.id,
                work_unit_id=session_unit.id,
                driver=type(self.driver).__name__,
                status="running",
            )
            await self.store.update_unit(task_unit.id, status="in_progress")
            await self.store.append_event(
                run_id, session_unit.id, "session.spawned", {"handle_id": handle.id}
            )
            dispatched += 1

            await self._collect(run_id, task_unit, session_unit, step, handle)

        return dispatched

    async def _collect(
        self, run_id: str, task_unit: WorkUnit, session_unit: WorkUnit, step: StepSpec, handle
    ) -> None:
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
            run_id=run_id,
            work_unit_id=task_unit.id,
            kind=step.produces or "artifact",
            version=await self.store.get_next_artifact_version(task_unit.id),
            produced_by_role=step.role,
            payload_json=artifact_payload,
        )
        await self.store.append_event(run_id, task_unit.id, "artifact.produced", {"artifact_id": artifact.id})

        if step.gate in (None, "none"):
            await self.store.update_unit(task_unit.id, status="closed")
            await self.store.append_event(run_id, task_unit.id, "unit.closed", {})
        else:
            gate = await self.store.create_gate(
                work_unit_id=task_unit.id,
                artifact_id=artifact.id,
                gate_type=step.gate,
                decision="pending",
            )
            # M1: the gate stays pending. A human (or, for local FakeDriver smoke
            # runs, the CLI's own auto-approve convenience loop) decides via
            # Store.decide_gate — apply_gate_decisions() picks it up next tick.
            await self.store.update_unit(task_unit.id, status="blocked")
            await self.store.append_event(run_id, task_unit.id, "gate.created", {"gate_id": gate.id})
