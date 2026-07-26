from __future__ import annotations

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel

from foundry.api.bootstrap import build_store_and_scheduler, recover_active_runs, reset_sqlite_db
from foundry.api.errors import ConflictError
from foundry.api.schemas import ApiResponse, Paging
from foundry.demo.seed import run_demo_seed

router = APIRouter()


class DemoStatusOut(BaseModel):
    active: bool
    db_path: str


def _status_out(app: FastAPI) -> DemoStatusOut:
    current = app.state.current_db_path
    original = app.state.original_db_path
    return DemoStatusOut(active=current != original, db_path=current)


async def _swap_database(
    app: FastAPI, target_db_path: str, *, reset: bool, seed_if_empty: bool, repos_dir: str | None = None
) -> None:
    """Stop the current Store/Scheduler, dispose the old engine, build a
    fresh engine/Store/Scheduler for `target_db_path` (recovering any active
    runs into it), seed it if empty, and reassign app.state -- all under a
    lock so two swap requests in flight at once can't race each other.
    """
    async with app.state.demo_swap_lock:
        await app.state.scheduler.stop()
        await app.state.store.stop()
        if app.state.engine is not None:
            await app.state.engine.dispose()

        if reset:
            reset_sqlite_db(target_db_path, repos_dir)

        engine, store, scheduler = await build_store_and_scheduler(target_db_path)

        if seed_if_empty:
            projects = await store.list_projects()
            if not projects:
                await run_demo_seed(store, repos_dir)
                # `build_store_and_scheduler` already ran recovery against the
                # (then-empty) db before seeding wrote any rows, so any run
                # the seed leaves in status="active" (pending-gate scenarios)
                # never got registered with the scheduler above. Recover
                # again now that those rows exist -- `Scheduler.register` is
                # safe to call against an already-started scheduler, it just
                # populates `_orchestrators`, read fresh on every tick.
                await recover_active_runs(store, scheduler)

        app.state.engine = engine
        app.state.store = store
        app.state.scheduler = scheduler
        app.state.current_db_path = target_db_path


@router.get("/demo/status")
async def demo_status(request: Request) -> ApiResponse[DemoStatusOut]:
    return ApiResponse[DemoStatusOut](data=_status_out(request.app), paging=Paging.none())


@router.post("/demo/activate")
async def activate_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    await _swap_database(
        app, app.state.demo_db_path, reset=False, seed_if_empty=True, repos_dir=app.state.demo_repos_dir
    )
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())


@router.post("/demo/deactivate")
async def deactivate_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    if app.state.original_db_path is None:
        raise ConflictError("no original database configured for this server")
    await _swap_database(app, app.state.original_db_path, reset=False, seed_if_empty=False)
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())


@router.post("/demo/reseed")
async def reseed_demo(request: Request) -> ApiResponse[DemoStatusOut]:
    app = request.app
    if app.state.current_db_path != app.state.demo_db_path:
        raise ConflictError("demo mode is not active")
    await _swap_database(
        app, app.state.demo_db_path, reset=True, seed_if_empty=True, repos_dir=app.state.demo_repos_dir
    )
    return ApiResponse[DemoStatusOut](data=_status_out(app), paging=Paging.none())
