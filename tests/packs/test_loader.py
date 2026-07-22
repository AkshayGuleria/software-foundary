from pathlib import Path

import pytest

from foundry.packs.loader import PackLoadError, load_pack

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_pack_parses_manifest_and_playbooks():
    manifest = load_pack(str(FIXTURES / "valid_pack"))
    assert manifest.id == "test_pack"
    assert manifest.version == "0.1.0"
    assert {r.id for r in manifest.roles} == {"dev", "reviewer"}
    assert manifest.playbooks == ["playbooks/simple.toml"]


def test_load_pack_rejects_unresolved_role():
    with pytest.raises(PackLoadError, match="nonexistent_role"):
        load_pack(str(FIXTURES / "invalid_role_pack"))


def test_load_pack_missing_manifest_raises():
    with pytest.raises(PackLoadError, match="pack.toml"):
        load_pack(str(FIXTURES / "does_not_exist"))


def test_load_pack_missing_referenced_playbook_raises(tmp_path):
    (tmp_path / "pack.toml").write_text(
        'playbooks = ["playbooks/missing.toml"]\n\n'
        '[pack]\nid = "p"\nversion = "0.1.0"\n\n'
        '[[role]]\nid = "dev"\n'
    )
    with pytest.raises(PackLoadError, match="missing.toml"):
        load_pack(str(tmp_path))
