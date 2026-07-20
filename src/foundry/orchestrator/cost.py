from __future__ import annotations

from foundry.playbook.schema import PlaybookSpec

DEFAULT_TOKENS_PER_STEP = 30_000


def estimate_plan_cost(playbook: PlaybookSpec, gate_step_id: str) -> dict:
    """Heuristic cost estimate for a derived (plan-approval) gate: count of
    writes-capable steps transitively downstream of it, times a flat per-step
    token estimate. Replace with a real historical per-project rollup once M2+
    has actual session token usage to draw on (design doc §11.1)."""
    steps_by_id = {s.id: s for s in playbook.steps}
    downstream_ids = _downstream_step_ids(playbook, gate_step_id)
    writes_steps = [sid for sid in downstream_ids if steps_by_id[sid].writes]
    estimated_tokens = len(writes_steps) * DEFAULT_TOKENS_PER_STEP
    return {
        "estimated_writes_steps": len(writes_steps),
        "estimated_tokens": estimated_tokens,
        "basis": (
            "heuristic: writes-steps-downstream x default-tokens-per-step; "
            "real historical per-project rollup lands in M2+"
        ),
    }


def _downstream_step_ids(playbook: PlaybookSpec, from_step_id: str) -> set[str]:
    forward: dict[str, list[str]] = {}
    for step in playbook.steps:
        for need_id in step.needs:
            forward.setdefault(need_id, []).append(step.id)

    seen: set[str] = set()
    stack = [from_step_id]
    while stack:
        current = stack.pop()
        for nxt in forward.get(current, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen
