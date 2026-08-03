from __future__ import annotations

import os

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from foundry.api.errors import ConflictError, NotFoundError, ValidationApiError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.project_playbooks.loader import (
    ProjectPlaybookError,
    ProjectPlaybookMeta,
    ProjectPlaybookValidationError,
    delete_project_playbook,
    get_project_playbook_meta,
    list_project_playbooks,
    project_playbook_path,
    read_project_playbook,
    slugify,
    write_project_playbook_atomic,
)

router = APIRouter()


def _get_root(request: Request) -> str:
    return request.app.state.project_playbooks_root


class ProjectPlaybookOut(BaseModel):
    slug: str
    project_id: str
    playbook_id: str
    description: str
    path: str
    updated_at: str


class ProjectPlaybookDetailOut(ProjectPlaybookOut):
    content: str


class ProjectPlaybookCreate(BaseModel):
    name: str
    content: str


class ProjectPlaybookUpdate(BaseModel):
    content: str


def _to_out(meta: ProjectPlaybookMeta) -> ProjectPlaybookOut:
    return ProjectPlaybookOut(
        slug=meta.slug,
        project_id=meta.project_id,
        playbook_id=meta.playbook_id,
        description=meta.description,
        path=meta.path,
        updated_at=meta.updated_at,
    )


async def _require_project(request: Request, project_id: str) -> None:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")


@router.get("/projects/{project_id}/playbooks")
async def list_playbooks(project_id: str, request: Request) -> ApiResponse[list[ProjectPlaybookOut]]:
    await _require_project(request, project_id)
    metas = list_project_playbooks(_get_root(request), project_id)
    out = [_to_out(m) for m in metas]
    return ApiResponse[list[ProjectPlaybookOut]](data=out, paging=Paging.unpaginated(len(out)))


@router.get("/projects/{project_id}/playbooks/{slug}")
async def get_playbook(project_id: str, slug: str, request: Request) -> ApiResponse[ProjectPlaybookDetailOut]:
    await _require_project(request, project_id)
    root = _get_root(request)
    try:
        meta = get_project_playbook_meta(root, project_id, slug)
        content = read_project_playbook(root, project_id, slug)
    except ProjectPlaybookError as e:
        raise NotFoundError(str(e)) from e
    out = ProjectPlaybookDetailOut(**_to_out(meta).model_dump(), content=content)
    return ApiResponse[ProjectPlaybookDetailOut](data=out, paging=Paging.none())


@router.post("/projects/{project_id}/playbooks", status_code=201)
async def create_playbook(
    project_id: str, body: ProjectPlaybookCreate, request: Request
) -> ApiResponse[ProjectPlaybookDetailOut]:
    await _require_project(request, project_id)
    root = _get_root(request)
    slug = slugify(body.name)

    try:
        already_exists = os.path.exists(project_playbook_path(root, project_id, slug))
    except ProjectPlaybookError as e:
        raise ValidationApiError(str(e)) from e
    if already_exists:
        raise ConflictError(f"Project {project_id} already has a playbook named {slug!r}")

    try:
        meta = write_project_playbook_atomic(root, project_id, slug, body.content)
    except ProjectPlaybookValidationError as e:
        raise ValidationApiError(str(e)) from e

    out = ProjectPlaybookDetailOut(**_to_out(meta).model_dump(), content=body.content)
    return ApiResponse[ProjectPlaybookDetailOut](data=out, paging=Paging.none())


@router.put("/projects/{project_id}/playbooks/{slug}")
async def update_playbook(
    project_id: str, slug: str, body: ProjectPlaybookUpdate, request: Request
) -> ApiResponse[ProjectPlaybookDetailOut]:
    await _require_project(request, project_id)
    root = _get_root(request)

    try:
        exists = os.path.exists(project_playbook_path(root, project_id, slug))
    except ProjectPlaybookError as e:
        raise NotFoundError(str(e)) from e
    if not exists:
        raise NotFoundError(f"Project playbook {slug!r} not found for project {project_id}")

    try:
        meta = write_project_playbook_atomic(root, project_id, slug, body.content)
    except ProjectPlaybookValidationError as e:
        raise ValidationApiError(str(e)) from e

    out = ProjectPlaybookDetailOut(**_to_out(meta).model_dump(), content=body.content)
    return ApiResponse[ProjectPlaybookDetailOut](data=out, paging=Paging.none())


@router.delete("/projects/{project_id}/playbooks/{slug}", status_code=204)
async def delete_playbook(project_id: str, slug: str, request: Request) -> Response:
    await _require_project(request, project_id)
    root = _get_root(request)
    try:
        delete_project_playbook(root, project_id, slug)
    except ProjectPlaybookError as e:
        raise NotFoundError(str(e)) from e
    return Response(status_code=204)
