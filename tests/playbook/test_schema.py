import pytest
from pydantic import ValidationError

from foundry.playbook.schema import LoopSpec, PlaybookSpec, StepSpec


def test_step_spec_defaults_have_no_fan_out_or_loop():
    step = StepSpec(id="a", role="dev")
    assert step.fan_out is None
    assert step.fan_out_from is None
    assert step.loop is None
    assert step.escalates_on is None


def test_fan_out_and_fan_out_from_are_mutually_exclusive():
    with pytest.raises(ValidationError, match="mutually exclusive"):
        PlaybookSpec(
            id="p",
            steps=[
                StepSpec(id="a", role="dev", fan_out="x.slices", fan_out_from="b"),
                StepSpec(id="b", role="dev", fan_out="y.slices"),
            ],
        )


def test_fan_out_from_must_reference_a_fan_out_step():
    with pytest.raises(ValidationError, match="must reference a step with fan_out"):
        PlaybookSpec(
            id="p",
            steps=[
                StepSpec(id="a", role="dev"),
                StepSpec(id="b", role="dev", fan_out_from="a"),
            ],
        )


def test_fan_out_from_chain_deeper_than_one_hop_is_rejected():
    with pytest.raises(ValidationError, match="must reference a step with fan_out"):
        PlaybookSpec(
            id="p",
            steps=[
                StepSpec(id="a", role="dev", fan_out="x.slices"),
                StepSpec(id="b", role="dev", fan_out_from="a"),
                StepSpec(id="c", role="dev", fan_out_from="b"),  # b has fan_out_from, not fan_out
            ],
        )


def test_fan_out_from_unknown_step_rejected():
    with pytest.raises(ValidationError, match="unknown step"):
        PlaybookSpec(id="p", steps=[StepSpec(id="a", role="dev", fan_out_from="ghost")])


def test_loop_back_to_unknown_step_rejected():
    with pytest.raises(ValidationError, match="loop.back_to"):
        PlaybookSpec(
            id="p",
            steps=[StepSpec(id="a", role="dev", loop=LoopSpec(back_to="ghost"))],
        )


def test_valid_fan_out_playbook_parses():
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="architecture", role="architect", produces="architecture_artifact"),
            StepSpec(
                id="implement", role="dev", needs=["architecture"], fan_out="architecture_artifact.slices"
            ),
            StepSpec(
                id="review",
                role="reviewer",
                needs=["implement"],
                fan_out_from="implement",
                gate="agent",
                loop=LoopSpec(back_to="implement", max_rounds=5),
            ),
        ],
    )
    assert playbook.steps[2].loop.max_rounds == 5
