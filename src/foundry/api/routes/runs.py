from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel

from foundry.api.errors import ConflictError, NotFoundError, ValidationApiError, validate_paging
from foundry.api.routes.projects import _get_store
from foundry.api.schemas import ApiResponse, Paging
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.cost import estimate_plan_cost
from foundry.packs.resolve import resolve_pack_version
from foundry.playbook.lint import PlaybookLintError, lint_plan_first
from foundry.playbook.loader import PlaybookLoadError, load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.models import Artifact, Run, WorkUnit, utcnow

router = APIRouter()


def _get_scheduler(request: Request):
    return request.app.state.scheduler


class RunCreate(BaseModel):
    project_id: str
    playbook_path: str
    title: str | None = None
    gate_overrides: dict[str, Literal["approved", "rejected"]] | None = None


class RunOut(BaseModel):
    id: str
    project_id: str
    playbook_ref: str
    title: str
    status: str
    created_at: str
    pack_version_pin: str


class WorkUnitOut(BaseModel):
    id: str
    step_id: str
    type: str
    status: str
    attempt: int
    owner_session_id: str | None
    convoy_id: str | None


class GateOut(BaseModel):
    id: str
    work_unit_id: str
    gate_type: str
    decision: str
    artifact_id: str | None
    cost_estimate: dict | None = None


class ArtifactOut(BaseModel):
    id: str
    work_unit_id: str
    kind: str
    version: int
    produced_by_role: str
    payload_json: dict


class RunDetailOut(BaseModel):
    run: RunOut
    units: list[WorkUnitOut]
    gates: list[GateOut]


class UnitDepOut(BaseModel):
    unit_id: str
    needs_unit_id: str


class GraphOut(BaseModel):
    units: list[WorkUnitOut]
    deps: list[UnitDepOut]


def _to_run_out(r: Run) -> RunOut:
    return RunOut(
        id=r.id,
        project_id=r.project_id,
        playbook_ref=r.playbook_ref,
        title=r.title,
        status=r.status,
        created_at=r.created_at.isoformat(),
        pack_version_pin=r.pack_version_pin,
    )


def _to_unit_out(u: WorkUnit) -> WorkUnitOut:
    return WorkUnitOut(
        id=u.id,
        step_id=u.step_id,
        type=u.type,
        status=u.status,
        attempt=u.attempt,
        owner_session_id=u.owner_session_id,
        convoy_id=u.convoy_id,
    )


def _to_artifact_out(a: Artifact) -> ArtifactOut:
    return ArtifactOut(
        id=a.id,
        work_unit_id=a.work_unit_id,
        kind=a.kind,
        version=a.version,
        produced_by_role=a.produced_by_role,
        payload_json=a.payload_json,
    )


@router.post("/runs", status_code=201)
async def create_run(body: RunCreate, request: Request) -> ApiResponse[RunOut]:
    store = _get_store(request)
    scheduler = _get_scheduler(request)

    project = await store.get_project(body.project_id)
    if project is None:
        raise NotFoundError(f"Project {body.project_id} not found")
    if project.status != "active":
        raise ConflictError(f"Project {body.project_id} is not active (status: {project.status})")

    try:
        playbook = load_playbook(body.playbook_path)
        lint_plan_first(playbook)
    except (PlaybookLoadError, PlaybookLintError) as e:
        raise ValidationApiError(str(e)) from e

    title = body.title or playbook.description or playbook.id
    pack_version_pin = resolve_pack_version(body.playbook_path)
    run = await store.create_run(project.id, body.playbook_path, title, pack_version_pin=pack_version_pin)
    await materialize(playbook, run.id, store)
    if body.gate_overrides:
        await store.update_run(run.id, gate_overrides_json=body.gate_overrides)

    script = {step.id: FakeStepScript(artifact={"ok": True}) for step in playbook.steps}
    scheduler.register(run.id, FakeDriver(script), playbook, gate_overrides=body.gate_overrides)

    return ApiResponse[RunOut](data=_to_run_out(run), paging=Paging.none())


@router.post("/runs/{run_id}/cancel", status_code=204)
async def cancel_run(run_id: str, request: Request) -> Response:
    store = _get_store(request)
    scheduler = _get_scheduler(request)

    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")
    if run.status in ("cancelled", "closed"):
        raise ConflictError(f"Run {run_id} is already {run.status}")

    units = await store.list_units(run_id)
    for unit in units:
        if unit.status not in ("closed", "failed", "killed", "cancelled"):
            await store.update_unit(unit.id, status="killed")

    await store.update_run(run_id, status="cancelled", closed_at=utcnow())
    scheduler.unregister(run_id)
    await store.append_event(run_id, None, "run.cancelled", {})

    return Response(status_code=204)


@router.get("/runs")
async def list_runs(
    request: Request,
    project_id: str | None = None,
    status: str | None = None,
    offset: int = 0,
    limit: int = 20,
) -> ApiResponse[list[RunOut]]:
    validate_paging(offset, limit)
    store = _get_store(request)
    all_runs = await store.list_runs(project_id=project_id, status=status)
    total = len(all_runs)
    page = all_runs[offset : offset + limit]
    return ApiResponse[list[RunOut]](
        data=[_to_run_out(r) for r in page], paging=Paging.for_page(offset, limit, total)
    )


@router.get("/runs/{run_id}")
async def get_run_detail(run_id: str, request: Request) -> ApiResponse[RunDetailOut]:
    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    scheduler = _get_scheduler(request)
    orchestrator = scheduler._orchestrators.get(run_id)
    playbook = orchestrator.playbook if orchestrator is not None else None

    units = await store.list_units(run_id)
    units_by_id = {u.id: u for u in units}
    gates = await store.list_gates_for_run(run_id)

    gate_outs = []
    for g in gates:
        cost_estimate = None
        if g.gate_type == "derived" and g.decision == "pending" and playbook is not None:
            gate_step_id = units_by_id[g.work_unit_id].step_id
            cost_estimate = estimate_plan_cost(playbook, gate_step_id)
        gate_outs.append(
            GateOut(
                id=g.id,
                work_unit_id=g.work_unit_id,
                gate_type=g.gate_type,
                decision=g.decision,
                artifact_id=g.artifact_id,
                cost_estimate=cost_estimate,
            )
        )

    return ApiResponse[RunDetailOut](
        data=RunDetailOut(run=_to_run_out(run), units=[_to_unit_out(u) for u in units], gates=gate_outs),
        paging=Paging.none(),
    )


@router.get("/runs/{run_id}/graph")
async def get_run_graph(run_id: str, request: Request) -> ApiResponse[GraphOut]:
    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    units = await store.list_units(run_id)
    deps = await store.list_deps(run_id)
    graph = GraphOut(
        units=[_to_unit_out(u) for u in units],
        deps=[UnitDepOut(unit_id=d.unit_id, needs_unit_id=d.needs_unit_id) for d in deps],
    )
    return ApiResponse[GraphOut](data=graph, paging=Paging.unpaginated(len(units)))


@router.get("/runs/{run_id}/artifacts")
async def get_run_artifacts(run_id: str, request: Request, latest: int = 0) -> ApiResponse[list[ArtifactOut]]:
    store = _get_store(request)
    run = await store.get_run(run_id)
    if run is None:
        raise NotFoundError(f"Run {run_id} not found")

    artifacts = await store.list_artifacts(run_id)
    if latest:
        best: dict[str, Artifact] = {}
        for a in artifacts:
            current = best.get(a.work_unit_id)
            if current is None or a.version > current.version:
                best[a.work_unit_id] = a
        artifacts = list(best.values())

    return ApiResponse[list[ArtifactOut]](
        data=[_to_artifact_out(a) for a in artifacts], paging=Paging.unpaginated(len(artifacts))
    )
