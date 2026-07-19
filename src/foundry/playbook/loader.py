from __future__ import annotations

import tomllib

from foundry.playbook.schema import PlaybookSpec, StepSpec


def load_playbook(path: str) -> PlaybookSpec:
    with open(path, "rb") as f:
        data = tomllib.load(f)

    meta = data["playbook"]
    steps = [StepSpec(**raw_step) for raw_step in data.get("step", [])]
    return PlaybookSpec(id=meta["id"], description=meta.get("description", ""), steps=steps)
