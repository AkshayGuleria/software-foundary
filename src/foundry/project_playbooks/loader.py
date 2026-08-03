from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from foundry.playbook.lint import PlaybookLintError, lint_plan_first
from foundry.playbook.loader import PlaybookLoadError, load_playbook
from foundry.playbook.schema import PlaybookSpec

_VALIDATION_ERRORS = (
    PlaybookLoadError,
    PlaybookLintError,
    tomllib.TOMLDecodeError,
    ValidationError,
    KeyError,
    ValueError,
    TypeError,
)


class ProjectPlaybookError(Exception):
    pass


class ProjectPlaybookValidationError(ProjectPlaybookError):
    pass


def project_playbook_dir(root: str, project_id: str) -> Path:
    return Path(root) / project_id


def project_playbook_path(root: str, project_id: str, slug: str) -> str:
    if slug != slugify(slug):
        raise ProjectPlaybookError(f"invalid playbook slug: {slug!r}")
    return str(project_playbook_dir(root, project_id) / f"{slug}.toml")


def slugify(name: str) -> str:
    lowered = name.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    if not slug:
        raise ProjectPlaybookError(f"name {name!r} produces an empty slug")
    return slug


@dataclass
class ProjectPlaybookMeta:
    slug: str
    project_id: str
    playbook_id: str
    description: str
    path: str
    updated_at: str


def _meta_from_playbook(project_id: str, slug: str, path: str, playbook: PlaybookSpec) -> ProjectPlaybookMeta:
    mtime = os.stat(path).st_mtime
    updated_at = datetime.fromtimestamp(mtime, tz=UTC).isoformat()
    return ProjectPlaybookMeta(
        slug=slug,
        project_id=project_id,
        playbook_id=playbook.id,
        description=playbook.description,
        path=path,
        updated_at=updated_at,
    )


def list_project_playbooks(root: str, project_id: str) -> list[ProjectPlaybookMeta]:
    directory = project_playbook_dir(root, project_id)
    if not directory.is_dir():
        return []

    metas: list[ProjectPlaybookMeta] = []
    for entry in sorted(directory.iterdir()):
        if entry.suffix != ".toml":
            continue
        try:
            if entry.stem != slugify(entry.stem):
                continue
        except ProjectPlaybookError:
            continue
        try:
            playbook = load_playbook(str(entry))
        except _VALIDATION_ERRORS:
            continue
        metas.append(_meta_from_playbook(project_id, entry.stem, str(entry), playbook))
    return metas


def read_project_playbook(root: str, project_id: str, slug: str) -> str:
    path = project_playbook_path(root, project_id, slug)
    if not os.path.exists(path):
        raise ProjectPlaybookError(f"project playbook {slug!r} not found for project {project_id!r}")
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except UnicodeDecodeError as e:
        raise ProjectPlaybookError(f"project playbook {slug!r} is not valid UTF-8: {e}") from e


def get_project_playbook_meta(root: str, project_id: str, slug: str) -> ProjectPlaybookMeta:
    path = project_playbook_path(root, project_id, slug)
    if not os.path.exists(path):
        raise ProjectPlaybookError(f"project playbook {slug!r} not found for project {project_id!r}")
    try:
        playbook = load_playbook(path)
    except _VALIDATION_ERRORS as e:
        raise ProjectPlaybookError(f"project playbook {slug!r} is corrupted: {e}") from e
    return _meta_from_playbook(project_id, slug, path, playbook)


def write_project_playbook_atomic(root: str, project_id: str, slug: str, content: str) -> ProjectPlaybookMeta:
    directory = project_playbook_dir(root, project_id)
    directory.mkdir(parents=True, exist_ok=True)
    final_path = project_playbook_path(root, project_id, slug)
    tmp_path = f"{final_path}.tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(content)

    try:
        playbook = load_playbook(tmp_path)
        lint_plan_first(playbook)
    except _VALIDATION_ERRORS as e:
        os.remove(tmp_path)
        raise ProjectPlaybookValidationError(str(e)) from e

    os.replace(tmp_path, final_path)
    return _meta_from_playbook(project_id, slug, final_path, playbook)


def delete_project_playbook(root: str, project_id: str, slug: str) -> None:
    path = project_playbook_path(root, project_id, slug)
    if not os.path.exists(path):
        raise ProjectPlaybookError(f"project playbook {slug!r} not found for project {project_id!r}")
    os.remove(path)
