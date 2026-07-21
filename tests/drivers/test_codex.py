import os
import stat
import subprocess
from pathlib import Path

import pytest

from foundry.drivers.base import SessionSpec
from foundry.drivers.codex import CodexDriver

FIXTURE = str(Path(__file__).parent.parent / "fixtures" / "fake_codex_cli.sh")


def _spec(unit_id="u1", run_id="r1", step_id="s1") -> SessionSpec:
    return SessionSpec(
        cwd=".",
        prompt="do the thing",
        model="codex-fake",
        tool_policy={},
        mcp_servers=[],
        env={},
        internal_endpoint="",
        internal_secret="",
        unit_id=unit_id,
        run_id=run_id,
        step_id=step_id,
    )


@pytest.mark.asyncio
async def test_spawn_and_stream_events_normalizes_the_fixture_output(tmp_path):
    os.chmod(FIXTURE, os.stat(FIXTURE).st_mode | stat.S_IEXEC)
    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())

    kinds = []
    async for ev in driver.stream_events(handle):
        kinds.append(ev.kind)

    assert "tool_call" in kinds
    assert kinds[-1] == "completed"


@pytest.mark.asyncio
async def test_process_exit_is_authoritative_not_stream_eof(tmp_path):
    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())

    events = [ev async for ev in driver.stream_events(handle)]
    health = driver.health(handle)
    assert health.alive is False  # process has exited; driver must reflect that, not hang
    assert events


def test_adopt_returns_empty_when_no_sessions_recorded(tmp_path):
    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    assert driver.adopt() == []


def test_cancel_is_safe_on_already_finished_session(tmp_path):
    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())
    driver.cancel(handle)  # must not raise even though nothing is running yet


def _pid_alive(pid: int) -> bool:
    # Deliberately not os.kill(pid, 0): once the grandchild's own parent (this
    # fixture's leader) has exited, the grandchild gets reparented to the
    # system's subreaper (launchd on macOS / PID 1 elsewhere). When our SIGTERM
    # then kills it, it briefly sits as a zombie until its *new* parent gets
    # around to wait()-ing on it — and os.kill(pid, 0) reports zombies as alive,
    # which would make this test flaky on a busy machine even though the
    # process has, in every sense that matters here, already been terminated by
    # the driver. Read `ps`'s STAT column instead and treat a zombie ("Z") the
    # same as "gone" — reaping the zombie itself is unrelated housekeeping the
    # driver was never responsible for.
    result = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    state = result.stdout.strip()
    return bool(state) and "Z" not in state


@pytest.mark.asyncio
async def test_reap_sweeps_the_whole_process_group_not_just_the_leader(tmp_path, monkeypatch):
    # Regression test for the _reap() dead-code bug: stream_events only calls
    # _reap() after observing the leader process has already exited, so gating
    # the SIGTERM/SIGKILL sweep on the *leader's own* poll() status meant the
    # cleanup body could never run — orphaned descendants under the session's
    # process group were never reaped. The fixture spawns a real detached
    # grandchild (`sleep 30`, sharing the leader's pgid since start_new_session
    # only creates one new group at the leader) and records its pid; this test
    # asserts that grandchild is gone once stream_events() — which calls
    # _reap() on session end — has finished.
    marker = tmp_path / "grandchild.pid"
    monkeypatch.setenv("CODEX_TEST_GRANDCHILD_PID_FILE", str(marker))

    driver = CodexDriver(cli_path=FIXTURE, session_log_dir=tmp_path)
    handle = driver.spawn(_spec())

    async for _ in driver.stream_events(handle):
        pass

    assert marker.exists(), "fixture never wrote the grandchild pid marker"
    grandchild_pid = int(marker.read_text().strip())
    assert not _pid_alive(grandchild_pid), (
        "grandchild survived stream_events()'s _reap() call — process group was not swept"
    )
