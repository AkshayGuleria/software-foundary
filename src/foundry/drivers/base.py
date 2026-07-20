from __future__ import annotations

from dataclasses import dataclass, field
from typing import AsyncIterator, Literal, Protocol


@dataclass
class SessionSpec:
    cwd: str
    prompt: str
    model: str
    tool_policy: dict
    mcp_servers: list[str]
    env: dict[str, str]
    internal_endpoint: str
    internal_secret: str
    unit_id: str
    run_id: str
    step_id: str


@dataclass
class SessionHandle:
    id: str
    pid: int | None = None


@dataclass
class DriverEvent:
    kind: Literal["tool_call", "text", "usage", "completed", "failed"]
    payload: dict = field(default_factory=dict)


@dataclass
class SessionHealth:
    alive: bool
    detail: str = ""


class AgentDriver(Protocol):
    def spawn(self, spec: SessionSpec) -> SessionHandle: ...
    def stream_events(self, handle: SessionHandle) -> AsyncIterator[DriverEvent]: ...
    def cancel(self, handle: SessionHandle, tree_kill: bool = True) -> None: ...
    def adopt(self) -> list[SessionHandle]: ...
    def health(self, handle: SessionHandle) -> SessionHealth: ...
