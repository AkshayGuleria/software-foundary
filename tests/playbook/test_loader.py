from foundry.playbook.loader import load_playbook


def test_loads_steps_and_needs_edges():
    playbook = load_playbook("tests/playbook/fixtures/sdlc_mini.toml")

    assert playbook.id == "sdlc_mini"
    assert [s.id for s in playbook.steps] == [
        "requirement", "architecture", "test_plan", "plan_approval", "implement",
    ]

    implement = next(s for s in playbook.steps if s.id == "implement")
    assert implement.needs == ["plan_approval"]
    assert implement.writes is True
    assert implement.gate == "human"

    plan_approval = next(s for s in playbook.steps if s.id == "plan_approval")
    assert plan_approval.type == "derived_gate"
    assert plan_approval.needs == ["requirement", "architecture", "test_plan"]
