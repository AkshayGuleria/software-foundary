from __future__ import annotations

import datetime as dt

from foundry.metrics.rollup import compute_project_metrics
from foundry.store.models import Artifact, Event, Gate, SessionRow, WorkUnit


def _ev(seq, unit_id, type_, payload=None, minutes_offset=0):
    return Event(
        seq=seq,
        run_id="r1",
        unit_id=unit_id,
        type=type_,
        payload_json=payload or {},
        created_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC) + dt.timedelta(minutes=minutes_offset),
    )


def pytest_approx(value, rel=1e-6):
    import pytest

    return pytest.approx(value, rel=rel)


def test_approval_latency_averages_created_to_decided_gap():
    events = [
        _ev(1, "u1", "gate.created", {"gate_id": "g1"}, minutes_offset=0),
        _ev(2, "u1", "gate.approved", {"gate_id": "g1"}, minutes_offset=10),
        _ev(3, "u2", "gate.created", {"gate_id": "g2"}, minutes_offset=0),
        _ev(4, "u2", "gate.rejected", {"gate_id": "g2"}, minutes_offset=20),
    ]
    metrics = compute_project_metrics(events=events, gates=[], units=[], sessions=[])
    assert metrics["approval_latency_seconds"] == pytest_approx(900)  # (600+1200)/2


def test_rework_rate_is_rejections_over_total_decisions():
    gates = [
        Gate(id="g1", work_unit_id="u1", gate_type="human", decision="approved"),
        Gate(id="g2", work_unit_id="u2", gate_type="human", decision="rejected"),
        Gate(id="g3", work_unit_id="u3", gate_type="human", decision="approved"),
        Gate(id="g4", work_unit_id="u4", gate_type="human", decision="pending"),
    ]
    metrics = compute_project_metrics(events=[], gates=gates, units=[], sessions=[])
    assert metrics["rework_rate"] == pytest_approx(1 / 3)  # pending excluded from the denominator


def test_retry_and_crash_counts():
    events = [
        _ev(1, "u1", "unit.retried", {}),
        _ev(2, "u2", "unit.retried", {}),
    ]
    sessions = [
        SessionRow(id="s1", work_unit_id="u1", driver="FakeDriver", status="ended"),
        SessionRow(id="s2", work_unit_id="u2", driver="FakeDriver", status="failed"),
    ]
    metrics = compute_project_metrics(events=events, gates=[], units=[], sessions=sessions)
    assert metrics["retry_count"] == 2
    assert metrics["crash_count"] == 1


def test_auto_resolved_vs_escalated_from_integration_artifacts():
    units = [WorkUnit(id="u1", run_id="r1", step_id="integrate", type="task", status="closed")]
    metrics = compute_project_metrics(
        events=[],
        gates=[],
        units=units,
        sessions=[],
        artifacts=[
            Artifact(
                id="a1",
                run_id="r1",
                work_unit_id="u1",
                kind="integration_artifact",
                version=1,
                produced_by_role="integrator",
                payload_json={"auto_resolved": ["lockfile", "imports"], "escalated": [{"file": "x.py"}]},
            )
        ],
    )
    assert metrics["auto_resolved_count"] == 2
    assert metrics["escalated_count"] == 1


def test_empty_input_returns_zeroed_metrics_not_a_crash():
    metrics = compute_project_metrics(events=[], gates=[], units=[], sessions=[])
    assert metrics["approval_latency_seconds"] == 0
    assert metrics["rework_rate"] == 0
    assert metrics["retry_count"] == 0
    assert metrics["crash_count"] == 0
