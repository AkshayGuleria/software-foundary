from __future__ import annotations

from foundry.store.models import Artifact, Event, Gate, SessionRow, WorkUnit


def compute_project_metrics(
    events: list[Event],
    gates: list[Gate],
    units: list[WorkUnit],
    sessions: list[SessionRow],
    artifacts: list[Artifact] | None = None,
) -> dict:
    """Pure rollup over a project's event log (§11.1 of the design doc).

    No store access, no async — callers gather `events`/`gates`/`units`/
    `sessions`/`artifacts` across a project's runs and pass them in.
    """
    artifacts = artifacts or []

    created_by_gate: dict[str, Event] = {}
    decided_by_gate: dict[str, Event] = {}
    for ev in events:
        gate_id = ev.payload_json.get("gate_id")
        if gate_id is None:
            continue
        if ev.type == "gate.created":
            created_by_gate[gate_id] = ev
        elif ev.type in ("gate.approved", "gate.rejected"):
            decided_by_gate[gate_id] = ev

    latencies = [
        (decided_by_gate[gid].created_at - created_by_gate[gid].created_at).total_seconds()
        for gid in created_by_gate
        if gid in decided_by_gate
    ]
    approval_latency_seconds = sum(latencies) / len(latencies) if latencies else 0

    decided_gates = [g for g in gates if g.decision in ("approved", "rejected")]
    rejected_gates = [g for g in decided_gates if g.decision == "rejected"]
    rework_rate = len(rejected_gates) / len(decided_gates) if decided_gates else 0

    retry_count = sum(1 for ev in events if ev.type == "unit.retried")
    crash_count = sum(1 for s in sessions if s.status == "failed")

    integration_artifacts = [a for a in artifacts if a.kind == "integration_artifact"]
    auto_resolved_count = sum(len(a.payload_json.get("auto_resolved", [])) for a in integration_artifacts)
    escalated_count = sum(len(a.payload_json.get("escalated", [])) for a in integration_artifacts)

    return {
        "approval_latency_seconds": approval_latency_seconds,
        "rework_rate": rework_rate,
        "retry_count": retry_count,
        "crash_count": crash_count,
        "auto_resolved_count": auto_resolved_count,
        "escalated_count": escalated_count,
    }
