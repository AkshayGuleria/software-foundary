from foundry.orchestrator.cost import estimate_plan_cost
from foundry.playbook.schema import PlaybookSpec, StepSpec


def test_estimate_counts_only_downstream_writes_steps():
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="requirement", role="po", produces="requirement_artifact"),
            StepSpec(
                id="architecture", role="architect", needs=["requirement"], produces="architecture_artifact"
            ),
            StepSpec(id="test_plan", role="qa", needs=["requirement"], produces="test_plan_artifact"),
            StepSpec(
                id="plan_approval",
                role="system",
                type="derived_gate",
                needs=["requirement", "architecture", "test_plan"],
            ),
            StepSpec(
                id="implement",
                role="developer",
                needs=["plan_approval"],
                produces="code_diff_artifact",
                writes=True,
            ),
            StepSpec(id="agent_review", role="reviewer", needs=["implement"], produces="review_artifact"),
        ],
    )

    result = estimate_plan_cost(playbook, "plan_approval")

    assert result["estimated_writes_steps"] == 1  # only "implement" has writes=True
    assert result["estimated_tokens"] == 30_000
    assert "basis" in result


def test_estimate_is_zero_for_a_gate_with_no_downstream_writes_steps():
    playbook = PlaybookSpec(
        id="p",
        steps=[
            StepSpec(id="a", role="x", type="derived_gate"),
            StepSpec(id="b", role="x", needs=["a"], produces="x_artifact"),  # writes defaults False
        ],
    )

    result = estimate_plan_cost(playbook, "a")

    assert result["estimated_writes_steps"] == 0
    assert result["estimated_tokens"] == 0
