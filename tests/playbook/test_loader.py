import pytest

from foundry.playbook.loader import PlaybookLoadError, load_playbook


def test_loads_steps_and_needs_edges():
    playbook = load_playbook("tests/playbook/fixtures/sdlc_mini.toml")

    assert playbook.id == "sdlc_mini"
    assert [s.id for s in playbook.steps] == [
        "requirement",
        "architecture",
        "test_plan",
        "plan_approval",
        "implement",
    ]

    implement = next(s for s in playbook.steps if s.id == "implement")
    assert implement.needs == ["plan_approval"]
    assert implement.writes is True
    assert implement.gate == "human"

    plan_approval = next(s for s in playbook.steps if s.id == "plan_approval")
    assert plan_approval.type == "derived_gate"
    assert plan_approval.needs == ["requirement", "architecture", "test_plan"]


def test_duplicate_step_id_raises_load_error(tmp_path):
    toml_path = tmp_path / "dup_id.toml"
    toml_path.write_text(
        """
[playbook]
id = "dup_id"

[[step]]
id = "requirement"
role = "product_owner"

[[step]]
id = "requirement"
role = "architect"
"""
    )

    with pytest.raises(PlaybookLoadError) as exc_info:
        load_playbook(str(toml_path))

    assert "requirement" in str(exc_info.value)


def test_dangling_needs_reference_raises_load_error(tmp_path):
    toml_path = tmp_path / "dangling_needs.toml"
    toml_path.write_text(
        """
[playbook]
id = "dangling_needs"

[[step]]
id = "implement"
role = "developer"
needs = ["typo_id"]
"""
    )

    with pytest.raises(PlaybookLoadError) as exc_info:
        load_playbook(str(toml_path))

    message = str(exc_info.value)
    assert "implement" in message
    assert "typo_id" in message
