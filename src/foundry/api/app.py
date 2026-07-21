from __future__ import annotations

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from foundry.api.errors import (
    FoundryApiError,
    foundry_api_error_handler,
    request_validation_error_handler,
)
from foundry.api.routes.gates import router as gates_router
from foundry.api.routes.metrics import router as metrics_router
from foundry.api.routes.projects import router as projects_router
from foundry.api.routes.runs import router as runs_router
from foundry.api.routes.sessions import router as sessions_router
from foundry.api.routes.stream import router as stream_router
from foundry.api.scheduler import Scheduler
from foundry.store.store import Store


def create_app(store: Store, scheduler: Scheduler) -> FastAPI:
    app = FastAPI(title="Foundry API")
    app.state.store = store
    app.state.scheduler = scheduler

    app.add_exception_handler(FoundryApiError, foundry_api_error_handler)
    app.add_exception_handler(RequestValidationError, request_validation_error_handler)

    app.include_router(projects_router, prefix="/api")
    app.include_router(runs_router, prefix="/api")
    app.include_router(gates_router, prefix="/api")
    app.include_router(stream_router, prefix="/api")
    app.include_router(metrics_router, prefix="/api")
    app.include_router(sessions_router, prefix="/api")

    @app.get("/api/_health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
