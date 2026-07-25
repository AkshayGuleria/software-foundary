from foundry.demo.toy_repo import generate_toy_repo
from foundry.kg.service import build_kg


def test_generate_toy_repo_creates_the_requested_number_of_modules(tmp_path):
    dest = tmp_path / "toy_repo"
    generate_toy_repo(str(dest), num_files=10)

    module_files = sorted(p.name for p in dest.iterdir() if p.name.startswith("module_"))
    assert module_files == [f"module_{i}.py" for i in range(10)]
    assert (dest / "__init__.py").exists()


def test_generate_toy_repo_produces_a_real_resolvable_import_graph(tmp_path):
    dest = tmp_path / "toy_repo"
    generate_toy_repo(str(dest), num_files=10)

    snapshot = build_kg(str(dest))

    # Every module_i (except the last) imports module_{i+1} -- confirm at
    # least the first link resolves to a real edge, not an unresolvable
    # import build_kg silently drops.
    assert "module_1.py" in snapshot.imports.get("module_0.py", set())
    # A genuinely non-trivial graph: more than just the linear chain (the
    # diamond edge described in Step 3), so build_kg has something more
    # interesting than "one big line" to render.
    total_edges = sum(len(targets) for targets in snapshot.imports.values())
    assert total_edges > 9  # linear chain alone is 9 edges for 10 files; the diamond adds one more
