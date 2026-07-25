from __future__ import annotations

import os


def generate_toy_repo(dest_dir: str, num_files: int = 12) -> None:
    """Generate a small synthetic Python package with real import edges.

    Uses plain `import module_N` statements (not `from . import module_N`)
    because `foundry.kg.service.build_kg`'s import resolver only follows
    `ast.Import` nodes and `ast.ImportFrom` nodes with a non-empty `module`
    -- a pure relative `from . import X` has `node.module is None` and is
    silently skipped, which would make every generated file look edge-less
    to the knowledge graph despite genuinely importing its neighbor.
    """
    os.makedirs(dest_dir, exist_ok=True)

    for i in range(num_files):
        lines = []
        if i < num_files - 1:
            lines.append(f"import module_{i + 1}")
        # One diamond edge partway through the chain, so the graph isn't
        # purely linear -- gives the Knowledge view something more
        # interesting to render than a single straight line.
        if i == 2 and num_files > 5:
            lines.append(f"import module_{num_files - 1}")
        lines.append("")
        lines.append("")
        lines.append(f"def demo_function_{i}():")
        lines.append(f"    return {i}")
        lines.append("")

        with open(os.path.join(dest_dir, f"module_{i}.py"), "w") as f:
            f.write("\n".join(lines))

    with open(os.path.join(dest_dir, "__init__.py"), "w") as f:
        f.write("")
