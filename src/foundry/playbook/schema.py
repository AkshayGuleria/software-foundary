from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

STEP_TYPE_TO_UNIT_TYPE = {"task": "task", "derived_gate": "gate", "human_task": "human_task"}


class LoopSpec(BaseModel):
    back_to: str = Field(description="Step id this loop jumps back to when `until` isn't yet satisfied.")
    until: str = Field(
        default="verdict == approved",
        description="Boolean expression evaluated against the gate outcome; loop stops when true.",
    )
    max_rounds: int = Field(
        default=5,
        description="Hard cap on how many times this loop can re-run before it's forced to stop.",
    )


class StepSpec(BaseModel):
    id: str = Field(description="Unique step id; referenced by needs, fan_out_from, loop.back_to.")
    role: str = Field(
        description="Pack role (see the pack's `pack.toml`) that runs this step's agent session."
    )
    type: Literal["task", "derived_gate", "human_task"] = Field(
        default="task",
        description="Work unit type: task, derived gate, or human task.",
    )
    needs: list[str] = Field(
        default_factory=list,
        description="Step ids that must complete before this step can start.",
    )
    produces: str | None = Field(
        default=None,
        description="Artifact key this step's output is stored under, for later steps to reference.",
    )
    gate: Literal["human", "agent", "none"] | None = Field(
        default="none",
        description="Gate type before output use: human, agent, or none.",
    )
    writes: bool = Field(
        default=False,
        description="Whether this step writes to codebase; must be downstream of derived_gate.",
    )
    fan_out: str | None = Field(
        default=None,
        description="Artifact field path whose list items this step expands into.",
    )
    fan_out_from: str | None = Field(
        default=None,
        description="Step id to fan out alongside. Mutually exclusive with fan_out.",
    )
    loop: LoopSpec | None = Field(
        default=None,
        description="Loop configuration to re-run this step until until condition is met.",
    )
    escalates_on: str | None = Field(
        default=None,
        description="Condition to escalate to human instead of looping.",
    )


class PlaybookSpec(BaseModel):
    id: str = Field(description="Unique id for this playbook, e.g. 'bugfix' or 'sdlc_story'.")
    description: str = Field(default="", description="Human-readable summary of what this playbook is for.")
    steps: list[StepSpec] = Field(description="The ordered set of steps that make up this playbook's DAG.")

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
