from foundry.packs.loader import load_pack
from foundry.playbook.loader import load_playbook


def test_default_pack_loads_without_error():
    manifest = load_pack("packs/default")
    assert manifest.id == "default"
    assert "playbooks/sdlc_story.toml" in manifest.playbooks


def test_default_pack_sdlc_story_uses_fan_out_and_review_loop():
    playbook = load_playbook("packs/default/playbooks/sdlc_story.toml")
    steps_by_id = {s.id: s for s in playbook.steps}
    assert steps_by_id["implement"].fan_out is not None
    assert steps_by_id["review"].fan_out_from == "implement"
    assert steps_by_id["review"].loop is not None


def test_default_pack_includes_bugfix_playbook():
    manifest = load_pack("packs/default")
    assert "playbooks/bugfix.toml" in manifest.playbooks


def test_bugfix_playbook_has_a_diagnose_step_and_no_fan_out():
    playbook = load_playbook("packs/default/playbooks/bugfix.toml")
    steps_by_id = {s.id: s for s in playbook.steps}
    assert "diagnose" in steps_by_id
    assert all(s.fan_out is None for s in playbook.steps)
