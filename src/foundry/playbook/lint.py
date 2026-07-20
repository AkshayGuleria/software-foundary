from __future__ import annotations

from foundry.playbook.schema import PlaybookSpec, StepSpec


class PlaybookLintError(Exception):
    pass


def lint_plan_first(playbook: PlaybookSpec) -> None:
    steps_by_id = {s.id: s for s in playbook.steps}
    violations = [
        step.id
        for step in playbook.steps
        if step.writes and not _has_upstream_derived_gate(step, steps_by_id, set())
    ]
    if violations:
        raise PlaybookLintError(f"writes-capable step(s) not downstream of a derived_gate: {violations}")


def _has_upstream_derived_gate(step: StepSpec, steps_by_id: dict[str, StepSpec], seen: set[str]) -> bool:
    for need_id in step.needs:
        if need_id in seen:
            continue
        seen.add(need_id)
        need_step = steps_by_id[need_id]
        if need_step.type == "derived_gate":
            return True
        if _has_upstream_derived_gate(need_step, steps_by_id, seen):
            return True
    return False
