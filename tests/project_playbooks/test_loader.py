import os

import pytest

from foundry.packs.resolve import resolve_pack_manifest, resolve_pack_version
from foundry.project_playbooks.loader import (
    ProjectPlaybookError,
    ProjectPlaybookValidationError,
    delete_project_playbook,
    get_project_playbook_meta,
    list_project_playbooks,
    project_playbook_path,
    read_project_playbook,
    slugify,
    write_project_playbook_atomic,
)

VALID_TOML = """
[playbook]
id = "hotfix"
description = "A minimal one-step playbook"

[[step]]
id = "review"
role = "reviewer"
produces = "review_artifact"
gate = "human"
"""

WRITES_WITHOUT_GATE_TOML = """
[playbook]
id = "unsafe"
description = "writes=true with no upstream derived_gate"

[[step]]
id = "fix"
role = "developer"
produces = "code_diff_artifact"
gate = "none"
writes = true
"""

SYNTAX_ERROR_TOML = "[playbook\nid = broken"


def test_slugify_normalizes_names():
    assert slugify("My Hotfix Flow!") == "my-hotfix-flow"
    assert slugify("  spaced -- out  ") == "spaced-out"


def test_slugify_rejects_a_name_with_no_alphanumeric_characters():
    with pytest.raises(ProjectPlaybookError):
        slugify("!!!")


def test_list_returns_empty_for_a_project_with_no_playbooks_yet(tmp_path):
    assert list_project_playbooks(str(tmp_path), "proj-1") == []


def test_write_then_read_roundtrip(tmp_path):
    root = str(tmp_path)
    meta = write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    assert meta.slug == "hotfix"
    assert meta.playbook_id == "hotfix"
    assert meta.description == "A minimal one-step playbook"
    assert read_project_playbook(root, "proj-1", "hotfix") == VALID_TOML

    listed = list_project_playbooks(root, "proj-1")
    assert [m.slug for m in listed] == ["hotfix"]


def test_write_leaves_no_tmp_file_after_success(tmp_path):
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    final_path = project_playbook_path(root, "proj-1", "hotfix")
    assert os.path.exists(final_path)
    assert not os.path.exists(f"{final_path}.tmp")


def test_write_with_syntax_error_raises_and_leaves_no_tmp_file(tmp_path):
    root = str(tmp_path)
    with pytest.raises(ProjectPlaybookValidationError):
        write_project_playbook_atomic(root, "proj-1", "hotfix", SYNTAX_ERROR_TOML)
    final_path = project_playbook_path(root, "proj-1", "hotfix")
    assert not os.path.exists(final_path)
    assert not os.path.exists(f"{final_path}.tmp")


def test_failed_update_does_not_corrupt_the_previous_good_copy(tmp_path):
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    with pytest.raises(ProjectPlaybookValidationError):
        write_project_playbook_atomic(root, "proj-1", "hotfix", SYNTAX_ERROR_TOML)
    assert read_project_playbook(root, "proj-1", "hotfix") == VALID_TOML


def test_write_rejects_a_writes_step_not_downstream_of_a_derived_gate(tmp_path):
    """The platform's core safety invariant -- the easiest thing to
    accidentally bypass in a brand-new write path."""
    root = str(tmp_path)
    with pytest.raises(ProjectPlaybookValidationError):
        write_project_playbook_atomic(root, "proj-1", "unsafe", WRITES_WITHOUT_GATE_TOML)


def test_read_missing_playbook_raises(tmp_path):
    with pytest.raises(ProjectPlaybookError):
        read_project_playbook(str(tmp_path), "proj-1", "does-not-exist")


def test_get_meta_missing_playbook_raises(tmp_path):
    with pytest.raises(ProjectPlaybookError):
        get_project_playbook_meta(str(tmp_path), "proj-1", "does-not-exist")


def test_delete_removes_the_file(tmp_path):
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    delete_project_playbook(root, "proj-1", "hotfix")
    assert list_project_playbooks(root, "proj-1") == []


def test_delete_missing_playbook_raises(tmp_path):
    with pytest.raises(ProjectPlaybookError):
        delete_project_playbook(str(tmp_path), "proj-1", "does-not-exist")


def test_list_skips_a_file_that_fails_to_parse_rather_than_erroring_the_whole_list(tmp_path):
    """Same 'one bad file doesn't break the list' behavior M4b's review
    fixed for packs/loader.py's list_packs -- don't regress it here."""
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    project_dir = project_playbook_path(root, "proj-1", "broken")
    with open(project_dir, "w", encoding="utf-8") as f:
        f.write(SYNTAX_ERROR_TOML)  # written directly, bypassing the validation gate

    listed = list_project_playbooks(root, "proj-1")
    assert [m.slug for m in listed] == ["hotfix"]


def test_project_playbook_path_is_not_a_pack_regression_check(tmp_path):
    """Confirms the 'no pack.toml special-casing needed' design claim as
    code: resolve.py's parent-directory walk never finds one from inside
    project_playbooks/, so a project playbook gets the exact same
    pack_version_pin fallback as any other ad-hoc playbook path."""
    root = str(tmp_path)
    write_project_playbook_atomic(root, "proj-1", "hotfix", VALID_TOML)
    path = project_playbook_path(root, "proj-1", "hotfix")

    assert resolve_pack_version(path) == "local"
    assert resolve_pack_manifest(path) is None
