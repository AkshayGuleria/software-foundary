from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.errors import NotFoundError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.kg.service import build_kg

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
