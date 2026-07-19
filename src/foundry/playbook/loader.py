from __future__ import annotations

import tomllib

from foundry.playbook.schema import PlaybookSpec, StepSpec


class PlaybookLoadError(Exception):
    pass


def load_playbook(path: str) -> PlaybookSpec:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    meta = data["playbook"]
    steps = [StepSpec(**raw_step) for raw_step in data.get("step", [])]
    playbook = PlaybookSpec(id=meta["id"], description=meta.get("description", ""), steps=steps)

    _validate_structure(playbook)
    return playbook


def _validate_structure(playbook: PlaybookSpec) -> None:
    seen_ids: set[str] = set()
    duplicate_ids: set[str] = set()
    for step in playbook.steps:
        if step.id in seen_ids:
            duplicate_ids.add(step.id)
        seen_ids.add(step.id)
    if duplicate_ids:
        raise PlaybookLoadError(
            f"duplicate step id(s) in playbook: {sorted(duplicate_ids)}"
        )

    valid_ids = seen_ids
    for step in playbook.steps:
        for need_id in step.needs:
            if need_id not in valid_ids:
                raise PlaybookLoadError(
                    f"step '{step.id}' has a dangling needs reference: '{need_id}' "
                    f"does not match any step id in the playbook"
                )
