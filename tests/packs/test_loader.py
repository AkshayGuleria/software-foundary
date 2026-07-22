from pathlib import Path

import pytest

from foundry.packs.loader import PackLoadError, list_packs, load_pack

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


def test_list_packs_scans_subdirectories_and_skips_broken_ones(tmp_path):
    good_dir = tmp_path / "good_pack"
    good_dir.mkdir()
    (good_dir / "pack.toml").write_text('playbooks = []\n\n[pack]\nid = "good"\nversion = "1.0.0"\n')

    broken_dir = tmp_path / "broken_pack"
    broken_dir.mkdir()
    (broken_dir / "pack.toml").write_text("not valid toml [[[")

    not_a_pack_dir = tmp_path / "not_a_pack"
    not_a_pack_dir.mkdir()  # no pack.toml at all

    manifests = list_packs(str(tmp_path))
    assert [m.id for m in manifests] == ["good"]


def test_list_packs_skips_schema_invalid_pack_toml(tmp_path):
    good_dir = tmp_path / "good_pack"
    good_dir.mkdir()
    (good_dir / "pack.toml").write_text('playbooks = []\n\n[pack]\nid = "good"\nversion = "1.0.0"\n')

    # Syntactically valid TOML, but the [[role]] block is missing the
    # required "id" field, so RoleSpec(**raw_role) raises a Pydantic
    # ValidationError rather than PackLoadError or a TOML syntax error.
    schema_invalid_dir = tmp_path / "schema_invalid_pack"
    schema_invalid_dir.mkdir()
    (schema_invalid_dir / "pack.toml").write_text(
        'playbooks = []\n\n[pack]\nid = "schema_invalid"\nversion = "1.0.0"\n\n[[role]]\nmodel = "fake"\n'
    )

    manifests = list_packs(str(tmp_path))
    assert [m.id for m in manifests] == ["good"]
