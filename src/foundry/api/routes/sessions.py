from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging

router = APIRouter()


class SessionOut(BaseModel):
    id: str
    work_unit_id: str
    run_id: str
    step_id: str
    driver: str
    status: str
    model: str | None
    tokens_in: int
    tokens_out: int
    started_at: str | None


@router.get("/sessions")
async def list_active_sessions(request: Request) -> ApiResponse[list[SessionOut]]:
    store = _get_store(request)
    rows = await store.list_active_sessions()
    sessions = [SessionOut(**row) for row in rows]
    return ApiResponse[list[SessionOut]](data=sessions, paging=Paging.unpaginated(len(sessions)))
