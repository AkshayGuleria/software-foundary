from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import NotFoundError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.kg.service import blast_radius, build_kg

router = APIRouter()


class KgGraphOut(BaseModel):
    nodes: list[str]
    edges: list[dict]


@router.get("/projects/{project_id}/kg-graph")
async def get_project_kg_graph(project_id: str, request: Request) -> ApiResponse[KgGraphOut]:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    snapshot = build_kg(project.path)
    edges = [{"from": src, "to": target} for src, targets in snapshot.imports.items() for target in targets]
    graph = KgGraphOut(nodes=sorted(snapshot.nodes), edges=edges)
    return ApiResponse[KgGraphOut](data=graph, paging=Paging.unpaginated(len(graph.nodes)))


class BlastRadiusOut(BaseModel):
    changed_files: list[str]
    radius: list[str]


@router.get("/runs/{run_id}/blast-radius")
async def get_run_blast_radius(run_id: str, request: Request) -> ApiResponse[BlastRadiusOut]:
    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    project = await store.get_project(run.project_id)
    artifacts = await store.list_artifacts(run_id)
    changed_files: list[str] = []
    for a in artifacts:
        changed_files.extend(a.payload_json.get("files", []))
    changed_files = sorted(set(changed_files))

    radius: list[str] = []
    if changed_files and project is not None:
        snapshot = build_kg(project.path)
        radius = sorted(blast_radius(snapshot, changed_files))

    out = BlastRadiusOut(changed_files=changed_files, radius=radius)
    return ApiResponse[BlastRadiusOut](data=out, paging=Paging.none())
