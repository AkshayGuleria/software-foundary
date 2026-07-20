from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import NotFoundError, validate_paging
from foundry.api.schemas import ApiResponse, Paging
from foundry.store.models import Project
from foundry.store.store import Store

router = APIRouter()


def _get_store(request: Request) -> Store:
    return request.app.state.store


class ProjectCreate(BaseModel):
    name: str
    path: str


class ProjectOut(BaseModel):
    id: str
    name: str
    path: str
    kg_status: str
    created_at: str


def _to_project_out(p: Project) -> ProjectOut:
    return ProjectOut(
        id=p.id,
        name=p.name,
        path=p.path,
        kg_status=p.kg_status,
        created_at=p.created_at.isoformat(),
    )


@router.post("/projects", status_code=201)
async def create_project(body: ProjectCreate, request: Request) -> ApiResponse[ProjectOut]:
    store = _get_store(request)
    project = await store.create_project(body.name, body.path)
    return ApiResponse[ProjectOut](data=_to_project_out(project), paging=Paging.none())


@router.get("/projects")
async def list_projects(request: Request, offset: int = 0, limit: int = 20) -> ApiResponse[list[ProjectOut]]:
    validate_paging(offset, limit)
    store = _get_store(request)
    all_projects = await store.list_projects()
    total = len(all_projects)
    page = all_projects[offset : offset + limit]
    return ApiResponse[list[ProjectOut]](
        data=[_to_project_out(p) for p in page], paging=Paging.for_page(offset, limit, total)
    )


@router.get("/projects/{project_id}")
async def get_project(project_id: str, request: Request) -> ApiResponse[ProjectOut]:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")
    return ApiResponse[ProjectOut](data=_to_project_out(project), paging=Paging.none())
