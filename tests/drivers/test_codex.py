import os
import stat
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
