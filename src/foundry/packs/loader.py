from __future__ import annotations

import tomllib
from pathlib import Path

from foundry.packs.schema import PackManifest, RoleSpec
from foundry.playbook.loader import PlaybookLoadError, load_playbook


class PackLoadError(Exception):
    pass


def load_pack(pack_dir: str) -> PackManifest:
    root = Path(pack_dir)
    manifest_path = root / "pack.toml"
    if not manifest_path.exists():
        raise PackLoadError(f"pack.toml not found under {pack_dir!r}")

    with open(manifest_path, "rb") as f:
        data = tomllib.load(f)

    pack_meta = data.get("pack", {})
    if "id" not in pack_meta or "version" not in pack_meta:
        raise PackLoadError(f"pack.toml at {manifest_path} must declare [pack] id and version")

    roles = [RoleSpec(**raw_role) for raw_role in data.get("role", [])]
    playbooks = data.get("playbooks", [])

    manifest = PackManifest(
        id=pack_meta["id"], version=pack_meta["version"], roles=roles, playbooks=playbooks
    )

    role_ids = {r.id for r in manifest.roles}
    for rel_path in manifest.playbooks:
        playbook_path = root / rel_path
        if not playbook_path.exists():
            raise PackLoadError(f"pack {manifest.id!r} references missing playbook file: {rel_path!r}")
        try:
            playbook = load_playbook(str(playbook_path))
        except PlaybookLoadError as e:
            raise PackLoadError(f"pack {manifest.id!r}: playbook {rel_path!r} failed to load: {e}") from e

        for step in playbook.steps:
            if step.role not in role_ids:
                raise PackLoadError(
                    f"pack {manifest.id!r}: playbook {rel_path!r} step {step.id!r} references "
                    f"undeclared role {step.role!r} (declared roles: {sorted(role_ids)})"
                )

    return manifest


def list_packs(packs_root: str) -> list[PackManifest]:
    root = Path(packs_root)
    if not root.is_dir():
        return []

    manifests: list[PackManifest] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir():
            continue
        if not (entry / "pack.toml").exists():
            continue
        try:
            manifests.append(load_pack(str(entry)))
        except (PackLoadError, tomllib.TOMLDecodeError):
            continue
    return manifests
