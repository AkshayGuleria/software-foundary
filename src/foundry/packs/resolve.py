from __future__ import annotations

from pathlib import Path

from foundry.packs.loader import PackLoadError, load_pack
from foundry.packs.schema import PackManifest

_MAX_PARENT_WALK = 5


def resolve_pack_version(playbook_path: str) -> str:
    try:
        current = Path(playbook_path).resolve().parent
    except OSError:
        return "local"

    for _ in range(_MAX_PARENT_WALK):
        if (current / "pack.toml").exists():
            try:
                manifest = load_pack(str(current))
            except PackLoadError:
                return "local"
            return f"{manifest.id}@{manifest.version}"
        if current.parent == current:
            break
        current = current.parent

    return "local"


def resolve_pack_manifest(playbook_path: str) -> PackManifest | None:
    try:
        current = Path(playbook_path).resolve().parent
    except OSError:
        return None

    for _ in range(_MAX_PARENT_WALK):
        if (current / "pack.toml").exists():
            try:
                return load_pack(str(current))
            except PackLoadError:
                return None
        if current.parent == current:
            break
        current = current.parent

    return None
