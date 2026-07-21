from __future__ import annotations

from foundry.playbook.schema import STEP_TYPE_TO_UNIT_TYPE, PlaybookSpec, StepSpec
from foundry.store.models import UnitDep, WorkUnit
from foundry.store.store import Store


def is_dynamic_step(step: StepSpec, steps_by_id: dict[str, StepSpec]) -> bool:
    if step.fan_out or step.fan_out_from:
        return True
    return any(is_dynamic_step(steps_by_id[need_id], steps_by_id) for need_id in step.needs)


async def materialize(playbook: PlaybookSpec, run_id: str, store: Store) -> dict[str, str]:
    steps_by_id = {s.id: s for s in playbook.steps}
    static_steps = [s for s in playbook.steps if not is_dynamic_step(s, steps_by_id)]

    units = [
        WorkUnit(run_id=run_id, step_id=step.id, type=STEP_TYPE_TO_UNIT_TYPE[step.type], status="open")
        for step in static_steps
    ]
    created = await store.create_work_units(units)
    step_to_unit = {step.id: unit.id for step, unit in zip(static_steps, created, strict=True)}

    deps = [
        UnitDep(unit_id=step_to_unit[step.id], needs_unit_id=step_to_unit[need_id])
        for step in static_steps
        for need_id in step.needs
        if need_id in step_to_unit
    ]
    if deps:
        await store.add_unit_deps(deps)

    return step_to_unit
