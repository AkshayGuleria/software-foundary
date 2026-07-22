from __future__ import annotations

import ast
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class KGSnapshot:
    nodes: set[str] = field(default_factory=set)
    imports: dict[str, set[str]] = field(default_factory=dict)


def build_kg(project_root: str) -> KGSnapshot:
    root = Path(project_root)
    py_files = sorted(root.rglob("*.py"))
    rel_paths = {str(p.relative_to(root)) for p in py_files}

    snapshot = KGSnapshot(nodes=rel_paths)
    for path in py_files:
        rel = str(path.relative_to(root))
        snapshot.imports[rel] = _resolve_imports(path, root, rel_paths)
    return snapshot


def _resolve_imports(path: Path, root: Path, known_files: set[str]) -> set[str]:
    try:
        tree = ast.parse(path.read_text(), filename=str(path))
    except SyntaxError:
        return set()

    module_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module_names.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                module_names.add(node.module)
                # "from package import submodule" needs the joined dotted
                # path too, since `node.module` alone only resolves to
                # `package/__init__.py` and would miss `package/submodule.py`.
                for alias in node.names:
                    module_names.add(f"{node.module}.{alias.name}")

    resolved: set[str] = set()
    for module_name in module_names:
        candidate = _module_to_relpath(module_name, known_files, root.name)
        if candidate is not None:
            resolved.add(candidate)
    return resolved


def _module_to_relpath(module_name: str, known_files: set[str], root_name: str) -> str | None:
    # A project is often registered pointed directly at its own top-level
    # package directory (e.g. this repo's own `src/foundry`, not `src`), in
    # which case that package's internal modules import each other with
    # fully-qualified absolute imports rooted at the package's own name
    # (`from foundry.x import y`) rather than relative imports. `known_files`
    # in that scenario never carries the package's own name as a path prefix
    # (files are just "x/y.py", not "foundry/x/y.py"), so a leading
    # "<root-package-name>." component must be tried stripped as well as
    # left intact, or every self-referential absolute import silently fails
    # to resolve and the whole tree looks edge-less.
    candidates_names = [module_name]
    prefix = f"{root_name}."
    if module_name.startswith(prefix):
        candidates_names.append(module_name[len(prefix) :])

    for name in candidates_names:
        as_path = name.replace(".", "/")
        for candidate in (f"{as_path}.py", f"{as_path}/__init__.py"):
            if candidate in known_files:
                return candidate

    # Also try treating the module name as rooted one level below any known
    # top-level package (handles fixtures/tests laid out under a subdir).
    as_path = module_name.replace(".", "/")
    for known in known_files:
        if known.endswith(f"/{as_path}.py") or known.endswith(f"/{as_path}/__init__.py"):
            return known
    return None


def blast_radius(snapshot: KGSnapshot, changed_files: list[str], depth: int = 2) -> set[str]:
    reverse: dict[str, set[str]] = {}
    for src, targets in snapshot.imports.items():
        for target in targets:
            reverse.setdefault(target, set()).add(src)

    visited: set[str] = set(changed_files)
    frontier: deque[tuple[str, int]] = deque((f, 0) for f in changed_files)
    while frontier:
        current, dist = frontier.popleft()
        if dist >= depth:
            continue
        neighbors = snapshot.imports.get(current, set()) | reverse.get(current, set())
        for neighbor in neighbors:
            if neighbor not in visited:
                visited.add(neighbor)
                frontier.append((neighbor, dist + 1))
    return visited
