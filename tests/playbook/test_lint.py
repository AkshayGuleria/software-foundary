import pytest

from foundry.playbook.loader import load_playbook
from foundry.playbook.lint import PlaybookLintError, lint_plan_first
from foundry.playbook.schema import PlaybookSpec, StepSpec


def test_valid_playbook_passes_lint():
    playbook = load_playbook("tests/playbook/fixtures/sdlc_mini.toml")
    lint_plan_first(playbook)  # must not raise


def test_writes_step_without_upstream_derived_gate_fails_lint():
    playbook = PlaybookSpec(
        id="bad",
        steps=[
            StepSpec(id="requirement", role="product_owner", produces="requirement_artifact"),
            StepSpec(id="implement", role="developer", needs=["requirement"], writes=True),
        ],
    )

    with pytest.raises(PlaybookLintError):
        lint_plan_first(playbook)
