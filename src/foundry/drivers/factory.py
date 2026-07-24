from __future__ import annotations

from foundry.drivers.base import AgentDriver
from foundry.drivers.codex import CodexDriver
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.playbook.schema import PlaybookSpec

VALID_DRIVER_NAMES = ("fake", "codex", "claude")


def make_driver(name: str, playbook: PlaybookSpec | None = None) -> AgentDriver:
    if name == "fake":
        steps = playbook.steps if playbook is not None else []
        script = {step.id: FakeStepScript(artifact={"ok": True}) for step in steps}
        return FakeDriver(script)
    if name == "codex":
        return CodexDriver()
    if name == "claude":
        from foundry.drivers.claude_code import ClaudeCodeDriver  # deferred: see Task 6

        return ClaudeCodeDriver()
    raise ValueError(f"unknown driver {name!r}, expected one of {VALID_DRIVER_NAMES}")
