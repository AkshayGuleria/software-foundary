from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import ConflictError, NotFoundError, ValidationApiError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.store.models import Gate

router = APIRouter()

_VALID_DECISIONS = {"approved", "rejected"}


class GateDecideIn(BaseModel):
    decision: str
    feedback_chips: list[str] = []
    feedback_text: str | None = None


class GateOut(BaseModel):
    id: str
    work_unit_id: str
    gate_type: str
    decision: str
    decided_by: str | None


def _to_gate_out(g: Gate) -> GateOut:
    return GateOut(
        id=g.id,
        work_unit_id=g.work_unit_id,
        gate_type=g.gate_type,
        decision=g.decision,
        decided_by=g.decided_by,
    )


@router.post("/gates/{gate_id}/decide")
async def decide_gate(gate_id: str, body: GateDecideIn, request: Request) -> ApiResponse[GateOut]:
    if body.decision not in _VALID_DECISIONS:
        raise ValidationApiError(f"decision must be one of {sorted(_VALID_DECISIONS)}, got {body.decision!r}")

    store = _get_store(request)

    async def _fetch(session):
        return await session.get(Gate, gate_id)

    gate = await store.read(_fetch)
    if gate is None:
        raise NotFoundError(f"Gate {gate_id} not found")
    if gate.decision != "pending":
        raise ConflictError(f"Gate {gate_id} was already {gate.decision}")

    feedback = (
        {"chips": body.feedback_chips, "text": body.feedback_text} if body.decision == "rejected" else None
    )
    await store.decide_gate(gate_id, body.decision, feedback=feedback, decided_by="api")

    updated = await store.read(_fetch)
    return ApiResponse[GateOut](data=_to_gate_out(updated), paging=Paging.none())
