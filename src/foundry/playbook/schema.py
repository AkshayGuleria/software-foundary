from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class StepSpec(BaseModel):
    id: str
    role: str
    type: Literal["task", "derived_gate", "human_task"] = "task"
    needs: list[str] = Field(default_factory=list)
    produces: str | None = None
    gate: Literal["human", "agent", "none"] | None = "none"
    writes: bool = False


class PlaybookSpec(BaseModel):
    id: str
    description: str = ""
    steps: list[StepSpec]
