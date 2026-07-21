from __future__ import annotations

import asyncio
import json
import os
import signal
import subprocess
import time
from collections.abc import AsyncIterator
from pathlib import Path

from foundry.drivers.base import DriverEvent, SessionHandle, SessionHealth, SessionSpec

_READLINE_LIMIT = 1024 * 1024  # ≥1MB, per design doc §8 driver-spec requirement 4


class CodexDriver:
    def __init__(self, cli_path: str = "codex", session_log_dir: str | Path = "/tmp/foundry-codex-sessions"):
        self.cli_path = cli_path
        self.session_log_dir = Path(session_log_dir)
        self.session_log_dir.mkdir(parents=True, exist_ok=True)
        self._processes: dict[str, subprocess.Popen] = {}
        self._log_paths: dict[str, Path] = {}
        self._pgids: dict[str, int] = {}

    def spawn(self, spec: SessionSpec) -> SessionHandle:
        log_path = self.session_log_dir / f"{spec.unit_id}.jsonl"
        log_file = open(log_path, "wb")  # noqa: SIM115 - lifetime is the subprocess's, closed on reap
        process = subprocess.Popen(  # noqa: S603 - cli_path is operator-configured, not user input
            [self.cli_path],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,  # own process group, for tree-kill (driver-spec requirement 3)
        )
        self._processes[spec.unit_id] = process
        self._log_paths[spec.unit_id] = log_path
        # start_new_session=True makes this process the leader of a brand-new session
        # and process group, so its pid *is* the pgid for the lifetime of that group.
        # Capture it now: os.getpgid(process.pid) can no longer be resolved once the
        # leader itself has already been reaped (see _reap), which is exactly the
        # state we're in every time we need to clean up a finished session's group.
        self._pgids[spec.unit_id] = process.pid
        return SessionHandle(id=spec.unit_id, pid=process.pid)

    async def stream_events(self, handle: SessionHandle) -> AsyncIterator[DriverEvent]:
        process = self._processes.get(handle.id)
        log_path = self._log_paths.get(handle.id)
        if process is None or log_path is None:
            raise ValueError(f"unknown session handle: {handle.id}")

        offset = 0
        while True:
            # Process exit is authoritative for session end (driver-spec requirement 1)
            # — never wait on stream EOF, which grandchildren can hold open forever.
            exited = process.poll() is not None
            with open(log_path, "rb") as f:
                f.seek(offset)
                chunk = f.read()
                offset += len(chunk)
            for line in chunk.splitlines():
                if not line.strip():
                    continue
                if len(line) > _READLINE_LIMIT:
                    continue
                record = json.loads(line)
                yield _normalize(record)
            if exited:
                break
            await asyncio.sleep(0.01)

        self._reap(handle.id)

    def cancel(self, handle: SessionHandle, tree_kill: bool = True) -> None:
        process = self._processes.get(handle.id)
        if process is None or process.poll() is not None:
            return
        # Use the pgid captured at spawn time rather than a fresh os.getpgid() call:
        # querying it here would still be safe today (the process is confirmed alive
        # by the poll() check above), but sourcing it from the same place _reap does
        # keeps both call sites immune to the leader-already-reaped race (see _reap)
        # and avoids a second syscall for no benefit.
        pgid = self._pgids.get(handle.id) if tree_kill else None
        try:
            if pgid is not None:
                os.killpg(pgid, signal.SIGTERM)
            else:
                process.terminate()
        except ProcessLookupError:
            return

    def adopt(self) -> list[SessionHandle]:
        return [
            SessionHandle(id=unit_id, pid=p.pid) for unit_id, p in self._processes.items() if p.poll() is None
        ]

    def health(self, handle: SessionHandle) -> SessionHealth:
        process = self._processes.get(handle.id)
        if process is None:
            return SessionHealth(alive=False, detail="unknown session")
        alive = process.poll() is None
        return SessionHealth(alive=alive, detail="running" if alive else f"exited {process.returncode}")

    def _reap(self, unit_id: str) -> None:
        # Called on every session end (stream_events, not just cancel — driver-spec
        # requirement 3). By this point the tracked leader process has *always*
        # already exited and been poll()ed (that's how stream_events decided to stop
        # tailing), so gating this on `process.poll() is None` — as the leader's own
        # liveness — is always false and the cleanup below would never run. It also
        # can't fall back to os.getpgid(process.pid): once poll() has reaped the
        # leader's zombie, that pid can no longer be resolved to a pgid at all, even
        # though orphaned grandchildren under the same process group may still be
        # alive and holding resources open. Use the pgid captured at spawn time
        # instead, and always attempt the sweep — the whole point is to catch
        # descendants the leader's own exit status says nothing about.
        pgid = self._pgids.get(unit_id)
        if pgid is None:
            return
        try:
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            return  # process group already empty — nothing left to clean up

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)  # signal 0: probe liveness without disturbing the group
            except ProcessLookupError:
                return  # group exited within the grace period
            time.sleep(0.05)

        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _normalize(record: dict) -> DriverEvent:
    kind = record.get("type", "text")
    if kind not in ("tool_call", "text", "usage", "completed", "failed"):
        kind = "text"
    payload = {k: v for k, v in record.items() if k != "type"}
    return DriverEvent(kind=kind, payload=payload)
