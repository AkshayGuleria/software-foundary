from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import ConflictError, NotFoundError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.store.models import Gate

router = APIRouter()

_QUEUE_GATE_TYPES = ("human", "derived")


class GateQueueItemOut(BaseModel):
    id: str
    work_unit_id: str
    gate_type: str
    project_id: str
    project_name: str
    run_id: str
    run_title: str
    step_id: str
    created_at: str


class HumanTaskQueueItemOut(BaseModel):
    id: str
    project_id: str
    project_name: str
    run_id: str
    run_title: str
    step_id: str
    reason: str
    created_at: str


class QueueOut(BaseModel):
    gates: list[GateQueueItemOut]
    human_tasks: list[HumanTaskQueueItemOut]


def _human_task_reason(step_id: str) -> str:
    if step_id == "_budget":
        return "Budget exceeded"
    if step_id.endswith(".escalation"):
        return f"Escalated: {step_id.removesuffix('.escalation')}"
    return step_id


@router.get("/queue")
async def get_queue(request: Request) -> ApiResponse[QueueOut]:
    store = _get_store(request)

    projects = await store.list_projects()
    projects_by_id = {p.id: p for p in projects}
    all_runs = await store.list_runs()

    gate_items: list[GateQueueItemOut] = []
    human_task_items: list[HumanTaskQueueItemOut] = []

    for run in all_runs:
        project = projects_by_id.get(run.project_id)
        if project is None:
            continue

        units = await store.list_units(run.id)
        units_by_id = {u.id: u for u in units}

        gates = await store.list_gates_for_run(run.id)
        for gate in gates:
            if gate.gate_type not in _QUEUE_GATE_TYPES or gate.decision != "pending":
                continue
            unit = units_by_id.get(gate.work_unit_id)
            if unit is None:
                continue
            gate_items.append(
                GateQueueItemOut(
                    id=gate.id,
                    work_unit_id=gate.work_unit_id,
                    gate_type=gate.gate_type,
                    project_id=project.id,
                    project_name=project.name,
                    run_id=run.id,
                    run_title=run.title,
                    step_id=unit.step_id,
                    created_at=unit.created_at.isoformat(),
                )
            )

        for unit in units:
            if unit.type != "human_task" or unit.status != "open":
                continue
            human_task_items.append(
                HumanTaskQueueItemOut(
                    id=unit.id,
                    project_id=project.id,
                    project_name=project.name,
                    run_id=run.id,
                    run_title=run.title,
                    step_id=unit.step_id,
                    reason=_human_task_reason(unit.step_id),
                    created_at=unit.created_at.isoformat(),
                )
            )

    gate_items.sort(key=lambda g: g.created_at)
    human_task_items.sort(key=lambda h: h.created_at)

    return ApiResponse[QueueOut](
        data=QueueOut(gates=gate_items, human_tasks=human_task_items), paging=Paging.none()
    )


class BatchDecideIn(BaseModel):
    gate_ids: list[str]


class BatchDecideOut(BaseModel):
    approved: list[str]
    skipped: list[str]


@router.post("/gates/batch-decide")
async def batch_decide_gates(body: BatchDecideIn, request: Request) -> ApiResponse[BatchDecideOut]:
    store = _get_store(request)

    approved: list[str] = []
    skipped: list[str] = []

    for gate_id in body.gate_ids:
        # _fetch_gate is defined and immediately awaited within this same
        # iteration (not deferred), so it always sees the current gate_id --
        # no late-binding closure risk despite being redefined every loop pass.
        # Matches the existing single-fetch idiom in routes/gates.py's decide_gate.
        async def _fetch_gate(session, gate_id: str = gate_id):
            return await session.get(Gate, gate_id)

        gate = await store.read(_fetch_gate)
        if gate is None or gate.decision != "pending":
            skipped.append(gate_id)
            continue
        await store.decide_gate(gate_id, "approved", decided_by="api")
        approved.append(gate_id)

    return ApiResponse[BatchDecideOut](
        data=BatchDecideOut(approved=approved, skipped=skipped), paging=Paging.none()
    )


class HumanTaskCompleteOut(BaseModel):
    id: str
    status: str


@router.post("/human-tasks/{unit_id}/complete")
async def complete_human_task(unit_id: str, request: Request) -> ApiResponse[HumanTaskCompleteOut]:
    store = _get_store(request)

    unit = await store.get_unit(unit_id)
    if unit is None:
        raise NotFoundError(f"Work unit {unit_id} not found")
    if unit.type != "human_task" or unit.status != "open":
        raise ConflictError(f"Work unit {unit_id} is not an open human_task")

    await store.complete_human_task(unit_id)

    return ApiResponse[HumanTaskCompleteOut](
        data=HumanTaskCompleteOut(id=unit_id, status="closed"), paging=Paging.none()
    )
