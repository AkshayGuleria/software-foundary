from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Literal

from foundry.drivers.base import DriverEvent, SessionHandle, SessionHealth, SessionSpec


@dataclass
class FakeStepScript:
    mode: Literal["succeed", "fail", "delay"] = "succeed"
    artifact: dict = field(default_factory=dict)
    delay_s: float = 0.0
    error: str = "scripted failure"


class FakeDriver:
    def __init__(self, script: dict[str, FakeStepScript] | None = None):
        self.script = script or {}
        self._known: dict[str, SessionHandle] = {}
        self._handle_step: dict[str, str] = {}
        self._cancelled: set[str] = set()

    def spawn(self, spec: SessionSpec) -> SessionHandle:
        handle = SessionHandle(id=spec.unit_id, pid=None)
        self._known[handle.id] = handle
        self._handle_step[handle.id] = spec.step_id
        return handle

    async def stream_events(self, handle: SessionHandle) -> AsyncIterator[DriverEvent]:
        if handle.id not in self._known:
            raise ValueError(f"unknown session handle: {handle.id}")
        step_script = self.script.get(self._handle_step.get(handle.id, ""), FakeStepScript())
        yield DriverEvent(kind="tool_call", payload={"tool": "noop"})

        if step_script.delay_s:
            await asyncio.sleep(step_script.delay_s)

        if handle.id in self._cancelled:
            return
        if step_script.mode == "fail":
            yield DriverEvent(kind="failed", payload={"error": step_script.error})
        else:
            yield DriverEvent(kind="completed", payload={"artifact": step_script.artifact})

    def cancel(self, handle: SessionHandle, tree_kill: bool = True) -> None:
        self._cancelled.add(handle.id)

    def adopt(self) -> list[SessionHandle]:
        return [h for h in self._known.values() if h.id not in self._cancelled]

    def health(self, handle: SessionHandle) -> SessionHealth:
        alive = handle.id in self._known and handle.id not in self._cancelled
        return SessionHealth(alive=alive)
