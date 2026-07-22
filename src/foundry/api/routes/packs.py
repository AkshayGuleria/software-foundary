from __future__ import annotations

from fastapi import APIRouter

from foundry.api.errors import NotFoundError
from foundry.api.schemas import ApiResponse, Paging
from foundry.packs.loader import list_packs
from foundry.packs.schema import PackManifest

router = APIRouter()

PACKS_ROOT = "packs"


@router.get("/packs")
async def get_packs() -> ApiResponse[list[PackManifest]]:
    manifests = list_packs(PACKS_ROOT)
    return ApiResponse[list[PackManifest]](data=manifests, paging=Paging.unpaginated(len(manifests)))


@router.get("/packs/{pack_id}")
async def get_pack(pack_id: str) -> ApiResponse[PackManifest]:
    manifests = list_packs(PACKS_ROOT)
    for manifest in manifests:
        if manifest.id == pack_id:
            return ApiResponse[PackManifest](data=manifest, paging=Paging.none())
    raise NotFoundError(f"Pack {pack_id!r} not found")
