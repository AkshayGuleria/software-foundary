from __future__ import annotations

import tomllib
from pathlib import Path

from fastapi import APIRouter
from pydantic import ValidationError

from foundry.api.errors import NotFoundError
from foundry.api.schemas import ApiResponse, Paging
from foundry.packs.loader import PackLoadError, list_packs, load_pack
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


def _find_pack_dir(packs_root: str, pack_id: str) -> Path | None:
    root = Path(packs_root)
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or not (entry / "pack.toml").exists():
            continue
        try:
            manifest = load_pack(str(entry))
        except (PackLoadError, tomllib.TOMLDecodeError, ValidationError, TypeError):
            continue
        if manifest.id == pack_id:
            return entry
    return None


@router.get("/packs/{pack_id}/{rel_path:path}")
async def get_pack_playbook_content(pack_id: str, rel_path: str) -> ApiResponse[dict]:
    pack_dir = _find_pack_dir(PACKS_ROOT, pack_id)
    if pack_dir is None:
        raise NotFoundError(f"Pack {pack_id!r} not found")

    manifest = load_pack(str(pack_dir))
    if rel_path not in manifest.playbooks:
        raise NotFoundError(f"Pack {pack_id!r} has no playbook {rel_path!r}")

    with open(pack_dir / rel_path, encoding="utf-8") as f:
        content = f.read()
    return ApiResponse[dict](data={"content": content}, paging=Paging.none())
