from __future__ import annotations

from fastapi import APIRouter, Request

from foundry.api.errors import NotFoundError
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.metrics.rollup import compute_project_metrics

router = APIRouter()


@router.get("/metrics/{project_id}")
async def get_project_metrics(project_id: str, request: Request) -> ApiResponse[dict]:
    store = _get_store(request)
    project = await store.get_project(project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    runs = await store.list_runs(project_id=project_id)
    all_events, all_gates, all_units, all_sessions, all_artifacts = [], [], [], [], []
    for run in runs:
        all_events += await store.list_events(run.id)
        all_gates += await store.list_gates_for_run(run.id)
        all_units += await store.list_units(run.id)
        all_artifacts += await store.list_artifacts(run.id)

    metrics = compute_project_metrics(
        events=all_events,
        gates=all_gates,
        units=all_units,
        sessions=all_sessions,
        artifacts=all_artifacts,
    )
    return ApiResponse[dict](data=metrics, paging=Paging.none())
