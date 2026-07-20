from __future__ import annotations

import asyncio

from foundry.drivers.base import AgentDriver
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.schema import PlaybookSpec
from foundry.store.models import utcnow
from foundry.store.store import Store


class Scheduler:
    def __init__(self, store: Store, interval: float = 0.2):
        self.store = store
        self.interval = interval
        self._orchestrators: dict[str, Orchestrator] = {}
        self._task: asyncio.Task | None = None
        self._running = False

    def register(self, run_id: str, driver: AgentDriver, playbook: PlaybookSpec) -> None:
        self._orchestrators[run_id] = Orchestrator(self.store, driver, playbook)

    def unregister(self, run_id: str) -> None:
        self._orchestrators.pop(run_id, None)

    async def tick_all_once(self) -> None:
        for run_id, orchestrator in list(self._orchestrators.items()):
            try:
                await orchestrator.tick(run_id)
            except Exception as exc:  # noqa: BLE001 - isolate one run's failure from the rest
                await self.store.append_event(run_id, None, "run.tick_error", {"error": str(exc)})
                continue

            if await self._is_finished(run_id):
                await self.store.update_run(run_id, status="closed", closed_at=utcnow())
                self.unregister(run_id)

    async def _is_finished(self, run_id: str) -> bool:
        units = await self.store.list_units(run_id)
        task_units = [u for u in units if u.type == "task"]
        return bool(task_units) and all(u.status == "closed" for u in task_units)

    async def start(self) -> None:
        self._running = True
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        self._running = False
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while self._running:
            await self.tick_all_once()
            await asyncio.sleep(self.interval)
