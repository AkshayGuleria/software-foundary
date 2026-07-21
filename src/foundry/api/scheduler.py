from __future__ import annotations

import asyncio

from foundry.drivers.base import AgentDriver
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.schema import PlaybookSpec
from foundry.store.models import utcnow
from foundry.store.store import Store


class GlobalDispatchLimiter:
    """Cross-run / cross-project fairness gate.

    Tracks in-flight dispatch slots so one project's fan-out convoy (many
    concurrently-registered runs) can't starve every other project's runs of
    tick time, and so no single tick_all_once pass over-dispatches globally.
    Purely in-memory bookkeeping — no store access, no async — so it's testable
    in complete isolation from Scheduler/Orchestrator.
    """

    def __init__(self, global_cap: int = 20, per_project_cap: int = 8):
        self.global_cap = global_cap
        self.per_project_cap = per_project_cap
        self._in_flight_total = 0
        self._in_flight_by_project: dict[str, int] = {}

    def can_dispatch(self, project_id: str) -> bool:
        if self._in_flight_total >= self.global_cap:
            return False
        return self._in_flight_by_project.get(project_id, 0) < self.per_project_cap

    def record_dispatch(self, project_id: str) -> None:
        self._in_flight_total += 1
        self._in_flight_by_project[project_id] = self._in_flight_by_project.get(project_id, 0) + 1

    def release(self, project_id: str) -> None:
        self._in_flight_total = max(0, self._in_flight_total - 1)
        current = self._in_flight_by_project.get(project_id, 0)
        self._in_flight_by_project[project_id] = max(0, current - 1)


class Scheduler:
    def __init__(self, store: Store, interval: float = 0.2, limiter: GlobalDispatchLimiter | None = None):
        self.store = store
        self.interval = interval
        self.limiter = limiter or GlobalDispatchLimiter()
        self._orchestrators: dict[str, Orchestrator] = {}
        self._project_by_run: dict[str, str] = {}
        self._last_ticked_seq: dict[str, int] = {}
        self._tick_seq = 0
        self._task: asyncio.Task | None = None
        self._running = False

    def register(
        self, run_id: str, driver: AgentDriver, playbook: PlaybookSpec, project_id: str | None = None
    ) -> None:
        self._orchestrators[run_id] = Orchestrator(self.store, driver, playbook)
        if project_id is not None:
            self._project_by_run[run_id] = project_id

    def unregister(self, run_id: str) -> None:
        self._orchestrators.pop(run_id, None)
        self._project_by_run.pop(run_id, None)

    async def _project_for(self, run_id: str) -> str:
        # project_id is only known up front when register() was given one; runs
        # registered the old way (no project_id) are resolved lazily via the
        # store, once, and cached — avoids a re-query on every tick.
        cached = self._project_by_run.get(run_id)
        if cached is not None:
            return cached
        run = await self.store.get_run(run_id)
        project_id = run.project_id if run is not None else run_id
        self._project_by_run[run_id] = project_id
        return project_id

    async def _fairness_order(self, run_ids: list[str]) -> list[str]:
        # Weighted round-robin: the project that was least recently given a
        # dispatch slot goes first, so one project's many registered runs (e.g.
        # a fan-out convoy's worth) can't monopolize every tick_all_once pass
        # ahead of a different project's single run.
        projects = {run_id: await self._project_for(run_id) for run_id in run_ids}
        return sorted(
            run_ids,
            key=lambda run_id: (self._last_ticked_seq.get(projects[run_id], -1), run_ids.index(run_id)),
        )

    async def tick_all_once(self) -> None:
        ordered_run_ids = await self._fairness_order(list(self._orchestrators.keys()))

        for run_id in ordered_run_ids:
            orchestrator = self._orchestrators.get(run_id)
            if orchestrator is None:
                continue  # unregistered by an earlier iteration of this same pass

            project_id = await self._project_for(run_id)
            if not self.limiter.can_dispatch(project_id):
                continue

            self.limiter.record_dispatch(project_id)
            try:
                try:
                    await orchestrator.tick(run_id)
                except Exception as exc:  # noqa: BLE001 - isolate one run's failure from the rest
                    await self.store.append_event(run_id, None, "run.tick_error", {"error": str(exc)})
                    continue
            finally:
                self.limiter.release(project_id)
                self._tick_seq += 1
                self._last_ticked_seq[project_id] = self._tick_seq

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
