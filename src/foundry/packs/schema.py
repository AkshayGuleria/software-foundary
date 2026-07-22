from __future__ import annotations

from pydantic import BaseModel


class RoleSpec(BaseModel):
    id: str
    model: str = "fake"


class PackManifest(BaseModel):
    id: str
    version: str
    roles: list[RoleSpec]
    playbooks: list[str]
