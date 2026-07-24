from foundry.packs.resolve import resolve_pack_manifest, resolve_pack_version


def test_resolve_pack_version_finds_pack_toml_in_parent_dir():
    pin = resolve_pack_version("packs/default/playbooks/sdlc_story.toml")
    assert pin == "default@0.1.0"


def test_resolve_pack_version_returns_local_when_no_pack_toml(tmp_path):
    playbook_file = tmp_path / "standalone.toml"
    playbook_file.write_text('[playbook]\nid = "x"\n')
    assert resolve_pack_version(str(playbook_file)) == "local"


def test_resolve_pack_version_returns_local_for_nonexistent_path():
    assert resolve_pack_version("/does/not/exist.toml") == "local"


def test_resolve_pack_manifest_returns_the_manifest_for_a_pack_playbook():
    manifest = resolve_pack_manifest("packs/default/playbooks/sdlc_story.toml")
    assert manifest is not None
    assert manifest.id == "default"


def test_resolve_pack_manifest_returns_none_outside_any_pack():
    assert resolve_pack_manifest("tests/fixtures/cli_demo.toml") is None
