from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

STEP_TYPE_TO_UNIT_TYPE = {"task": "task", "derived_gate": "gate", "human_task": "human_task"}


class LoopSpec(BaseModel):
    back_to: str
    until: str = "verdict == approved"
    max_rounds: int = 5


class StepSpec(BaseModel):
    id: str
    role: str
    type: Literal["task", "derived_gate", "human_task"] = "task"
    needs: list[str] = Field(default_factory=list)
    produces: str | None = None
    gate: Literal["human", "agent", "none"] | None = "none"
    writes: bool = False
    fan_out: str | None = None
    fan_out_from: str | None = None
    loop: LoopSpec | None = None
    escalates_on: str | None = None


class PlaybookSpec(BaseModel):
    id: str
    description: str = ""
    steps: list[StepSpec]

    @model_validator(mode="after")
    def _validate_fan_out_and_loop(self) -> PlaybookSpec:
        ids = {s.id for s in self.steps}
        by_id = {s.id: s for s in self.steps}
        for step in self.steps:
            if step.fan_out and step.fan_out_from:
                raise ValueError(f"step {step.id!r}: fan_out and fan_out_from are mutually exclusive")
            if step.fan_out_from is not None:
                if step.fan_out_from not in ids:
                    raise ValueError(
                        f"step {step.id!r}: fan_out_from references unknown step {step.fan_out_from!r}"
                    )
                source = by_id[step.fan_out_from]
                if not source.fan_out:
                    raise ValueError(
                        f"step {step.id!r}: fan_out_from={step.fan_out_from!r} "
                        "must reference a step with fan_out set (one-hop chains only)"
                    )
            if step.loop is not None and step.loop.back_to not in ids:
                raise ValueError(
                    f"step {step.id!r}: loop.back_to references unknown step {step.loop.back_to!r}"
                )
        return self
