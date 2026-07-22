from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.store.models import utcnow

router = APIRouter()

_TERMINAL_RUN_STATUSES = {"closed", "cancelled", "failed"}
_STALENESS_CAP_HOURS = 168.0  # one week; staleness contributes at most this much


class ProjectHealthOut(BaseModel):
    project_id: str
    name: str
    status: str
    active_run_count: int
    pending_gate_count: int
    last_run_status: str | None
    last_run_at: str | None
    rework_rate: float | None
    budget_burn_ratio: float | None
    attention_score: float


@router.get("/portfolio")
async def get_portfolio(request: Request) -> ApiResponse[list[ProjectHealthOut]]:
    store = _get_store(request)

    projects = await store.list_projects()
    all_runs = await store.list_runs()

    runs_by_project: dict[str, list] = {}
    for run in all_runs:
        runs_by_project.setdefault(run.project_id, []).append(run)

    now = utcnow()
    rows: list[ProjectHealthOut] = []
    for project in projects:
        project_runs = runs_by_project.get(project.id, [])
        active_runs = [r for r in project_runs if r.status not in _TERMINAL_RUN_STATUSES]

        pending_gate_count = 0
        total_gate_count = 0
        rejected_count = 0
        for run in active_runs:
            gates = await store.list_gates_for_run(run.id)
            for gate in gates:
                total_gate_count += 1
                if gate.decision == "pending":
                    pending_gate_count += 1
                elif gate.decision == "rejected":
                    rejected_count += 1

        rework_rate = (rejected_count / total_gate_count) if total_gate_count else None

        total_budget = sum(r.token_budget for r in project_runs)
        total_used = sum(r.tokens_used for r in project_runs)
        budget_burn_ratio = (total_used / total_budget) if total_budget else None

        last_run = max(project_runs, key=lambda r: r.created_at) if project_runs else None
        last_run_status = last_run.status if last_run else None
        last_run_at = last_run.created_at.isoformat() if last_run else None

        if last_run is None:
            attention_score = 0.0
        else:
            staleness_hours = min((now - last_run.created_at).total_seconds() / 3600, _STALENESS_CAP_HOURS)
            attention_score = (
                pending_gate_count * 10.0
                + (rework_rate or 0.0) * 20.0
                + (budget_burn_ratio or 0.0) * 15.0
                + staleness_hours * 0.5
            )

        rows.append(
            ProjectHealthOut(
                project_id=project.id,
                name=project.name,
                status=project.status,
                active_run_count=len(active_runs),
                pending_gate_count=pending_gate_count,
                last_run_status=last_run_status,
                last_run_at=last_run_at,
                rework_rate=rework_rate,
                budget_burn_ratio=budget_burn_ratio,
                attention_score=attention_score,
            )
        )

    rows.sort(key=lambda r: r.attention_score, reverse=True)
    return ApiResponse[list[ProjectHealthOut]](data=rows, paging=Paging.unpaginated(len(rows)))
