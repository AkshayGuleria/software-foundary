from __future__ import annotations

from foundry.playbook.schema import PlaybookSpec
from foundry.store.models import UnitDep, WorkUnit
from foundry.store.store import Store

_TYPE_MAP = {"task": "task", "derived_gate": "gate", "human_task": "human_task"}


async def materialize(playbook: PlaybookSpec, run_id: str, store: Store) -> dict[str, str]:
    units = [
        WorkUnit(run_id=run_id, step_id=step.id, type=_TYPE_MAP[step.type], status="open")
        for step in playbook.steps
    ]
    created = await store.create_work_units(units)
    step_to_unit = {step.id: unit.id for step, unit in zip(playbook.steps, created, strict=True)}

    deps = [
        UnitDep(unit_id=step_to_unit[step.id], needs_unit_id=step_to_unit[need_id])
        for step in playbook.steps
        for need_id in step.needs
    ]
    if deps:
        await store.add_unit_deps(deps)

    return step_to_unit
