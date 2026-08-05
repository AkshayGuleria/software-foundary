from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from pydantic.fields import FieldInfo

from foundry.api.schemas import ApiResponse, Paging
from foundry.playbook.schema import LoopSpec, PlaybookSpec, StepSpec

router = APIRouter()


class SchemaFieldDoc(BaseModel):
    model: Literal["PlaybookSpec", "StepSpec", "LoopSpec"]
    field: str
    type: str
    default: str | None
    required: bool
    description: str


def _format_type(field_info: FieldInfo) -> str:
    return str(field_info.annotation).replace("typing.", "").replace("<class '", "").replace("'>", "")


def _field_docs(
    model_name: Literal["PlaybookSpec", "StepSpec", "LoopSpec"], model: type[BaseModel]
) -> list[SchemaFieldDoc]:
    docs = []
    for name, field_info in model.model_fields.items():
        required = field_info.is_required()
        docs.append(
            SchemaFieldDoc(
                model=model_name,
                field=name,
                type=_format_type(field_info),
                default=None if required else repr(field_info.default),
                required=required,
                description=field_info.description or "",
            )
        )
    return docs


@router.get("/playbooks/schema-help")
async def get_playbook_schema_help() -> ApiResponse[list[SchemaFieldDoc]]:
    docs = [
        *_field_docs("PlaybookSpec", PlaybookSpec),
        *_field_docs("StepSpec", StepSpec),
        *_field_docs("LoopSpec", LoopSpec),
    ]
    return ApiResponse[list[SchemaFieldDoc]](data=docs, paging=Paging.unpaginated(len(docs)))
