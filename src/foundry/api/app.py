from __future__ import annotations

from fastapi import FastAPI

from foundry.api.errors import FoundryApiError, foundry_api_error_handler
from foundry.api.scheduler import Scheduler
from foundry.store.store import Store


def create_app(store: Store, scheduler: Scheduler) -> FastAPI:
    app = FastAPI(title="Foundry API")
    app.state.store = store
    app.state.scheduler = scheduler

    app.add_exception_handler(FoundryApiError, foundry_api_error_handler)

    @app.get("/api/_health")
    async def health() -> dict:
        return {"status": "ok"}

    return app
