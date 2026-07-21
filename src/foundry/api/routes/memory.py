from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.store.models import Memory

router = APIRouter()


class MemoryOut(BaseModel):
    id: str
    scope: str
    kind: str
    title: str
    body_md: str
    project_id: str | None
    pack_id: str | None
    source_run_id: str | None
    created_at: str


def _to_memory_out(m: Memory) -> MemoryOut:
    return MemoryOut(
        id=m.id,
        scope=m.scope,
        kind=m.kind,
        title=m.title,
        body_md=m.body_md,
        project_id=m.project_id,
        pack_id=m.pack_id,
        source_run_id=m.source_run_id,
        created_at=m.created_at.isoformat(),
    )


@router.get("/memory")
async def list_memory(
    request: Request,
    project_id: str | None = None,
    scope: str | None = None,
    kind: str | None = None,
) -> ApiResponse[list[MemoryOut]]:
    store = _get_store(request)
    items = await store.list_memory_items(scope=scope, project_id=project_id, kind=kind)
    memory_out = [_to_memory_out(m) for m in items]
    return ApiResponse[list[MemoryOut]](data=memory_out, paging=Paging.unpaginated(len(memory_out)))
