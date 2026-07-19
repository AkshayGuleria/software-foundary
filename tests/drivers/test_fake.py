import pytest

from foundry.drivers.base import SessionSpec
from foundry.drivers.fake import FakeDriver, FakeStepScript


def spec(unit_id: str, step_id: str) -> SessionSpec:
    return SessionSpec(
        cwd=".", prompt="p", model="fake", tool_policy={}, mcp_servers=[], env={},
        internal_endpoint="", internal_secret="", unit_id=unit_id, run_id="r1", step_id=step_id,
    )


@pytest.mark.asyncio
async def test_succeed_yields_tool_call_then_completed_with_artifact():
    driver = FakeDriver({"a": FakeStepScript(artifact={"x": 1})})
    handle = driver.spawn(spec("u1", "a"))

    events = [ev async for ev in driver.stream_events(handle)]

    assert [e.kind for e in events] == ["tool_call", "completed"]
    assert events[-1].payload["artifact"] == {"x": 1}


@pytest.mark.asyncio
async def test_fail_mode_yields_failed_event():
    driver = FakeDriver({"a": FakeStepScript(mode="fail", error="boom")})
    handle = driver.spawn(spec("u2", "a"))

    events = [ev async for ev in driver.stream_events(handle)]

    assert events[-1].kind == "failed"
    assert events[-1].payload["error"] == "boom"


@pytest.mark.asyncio
async def test_cancel_stops_stream_before_completion():
    driver = FakeDriver({"a": FakeStepScript(delay_s=1.0)})
    handle = driver.spawn(spec("u3", "a"))
    driver.cancel(handle)

    events = [ev async for ev in driver.stream_events(handle)]

    assert all(e.kind != "completed" for e in events)


def test_adopt_returns_all_known_handles_health_reflects_state():
    driver = FakeDriver()
    handle = driver.spawn(spec("u4", "a"))

    assert [h.id for h in driver.adopt()] == ["u4"]
    assert driver.health(handle).alive is True

    driver.cancel(handle)
    assert driver.health(handle).alive is False
