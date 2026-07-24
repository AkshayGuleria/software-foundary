from __future__ import annotations

from foundry.packs.schema import RoleSpec
from foundry.store.models import Memory


def _role_header(role: RoleSpec | None, fallback_id: str) -> str:
    if role is not None and role.description:
        return f"# Role: {role.id}\n{role.description}"
    return f"# Role: {role.id if role is not None else fallback_id}"


def render_prompt(
    role: RoleSpec | None,
    step_id: str,
    produces: str | None,
    input_files: list[str],
    memory_items: list[Memory],
) -> str:
    lines = [_role_header(role, "unknown"), f"\n# Step: {step_id}"]
    if produces:
        lines.append(f"Produce an artifact of kind: {produces}")
    if input_files:
        lines.append("\n# Input files in context:")
        lines.extend(f"- {f}" for f in input_files)
    if memory_items:
        lines.append("\n# Relevant memory:")
        for m in memory_items:
            lines.append(f"## {m.title}\n{m.body_md}")
    return "\n".join(lines)


def render_review_prompt(
    role: RoleSpec | None,
    step_id: str,
    gate_id: str,
    artifact_kind: str | None,
    artifact_payload: dict,
) -> str:
    lines = [_role_header(role, "reviewer"), f"\n# Review step: {step_id} (gate {gate_id})"]
    if artifact_kind:
        lines.append(f"Artifact under review (kind: {artifact_kind}):")
    lines.append(str(artifact_payload))
    return "\n".join(lines)
