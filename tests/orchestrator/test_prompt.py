from foundry.orchestrator.prompt import render_prompt, render_review_prompt
from foundry.packs.schema import RoleSpec
from foundry.store.models import Memory


def test_render_prompt_includes_role_description():
    role = RoleSpec(id="developer", model="fake", description="Implement the assigned slice.")
    prompt = render_prompt(role, "code", "code_diff_artifact", [], [])
    assert "developer" in prompt
    assert "Implement the assigned slice." in prompt


def test_render_prompt_includes_input_files_and_memory():
    role = RoleSpec(id="developer", model="fake", description="Implement.")
    memory = Memory(
        id="m1",
        scope="project",
        kind="lesson",
        title="Watch the pgid",
        body_md="Always capture the pgid at spawn time.",
    )
    prompt = render_prompt(role, "code", "code_diff_artifact", ["src/foo.py"], [memory])
    assert "src/foo.py" in prompt
    assert "Watch the pgid" in prompt
    assert "Always capture the pgid at spawn time." in prompt


def test_render_prompt_handles_no_role():
    prompt = render_prompt(None, "code", "code_diff_artifact", [], [])
    assert "code" in prompt


def test_render_review_prompt_includes_role_and_artifact():
    role = RoleSpec(id="reviewer", model="fake", description="Review the diff.")
    prompt = render_review_prompt(role, "review", "gate1", "code_diff_artifact", {"diff": "x"})
    assert "reviewer" in prompt
    assert "Review the diff." in prompt
    assert "code_diff_artifact" in prompt


def test_render_prompt_includes_requirement_text():
    prompt = render_prompt(None, "diagnose", None, [], [], requirement_text="Fix the login bug.")
    assert "# Requirement" in prompt
    assert "Fix the login bug." in prompt


def test_render_prompt_includes_requirement_path_as_a_reference_not_content():
    prompt = render_prompt(None, "diagnose", None, [], [], requirement_path="docs/REQUIREMENTS.md")
    assert "# Requirement" in prompt
    assert "docs/REQUIREMENTS.md" in prompt


def test_render_prompt_omits_requirement_section_when_neither_is_set():
    prompt = render_prompt(None, "diagnose", None, [], [])
    assert "# Requirement" not in prompt


def test_render_prompt_unaffected_by_explicit_none_requirement_params():
    before = render_prompt(None, "code", "code_diff_artifact", ["src/foo.py"], [])
    after = render_prompt(
        None,
        "code",
        "code_diff_artifact",
        ["src/foo.py"],
        [],
        requirement_text=None,
        requirement_path=None,
    )
    assert before == after
