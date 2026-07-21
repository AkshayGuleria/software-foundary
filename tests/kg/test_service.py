from pathlib import Path

from foundry.kg.service import blast_radius, build_kg

FIXTURE_ROOT = str(Path(__file__).parent / "fixtures")


def test_build_kg_finds_all_python_files():
    snapshot = build_kg(FIXTURE_ROOT)
    assert "sample_project/a.py" in snapshot.nodes
    assert "sample_project/b.py" in snapshot.nodes
    assert "sample_project/c.py" in snapshot.nodes
    assert "sample_project/isolated.py" in snapshot.nodes


def test_build_kg_resolves_intra_project_imports():
    snapshot = build_kg(FIXTURE_ROOT)
    assert "sample_project/b.py" in snapshot.imports["sample_project/a.py"]
    assert "sample_project/c.py" in snapshot.imports["sample_project/b.py"]


def test_build_kg_drops_external_stdlib_imports():
    snapshot = build_kg(FIXTURE_ROOT)
    # "os" has no project-relative resolution; isolated.py's import edge set
    # for an unresolvable module must simply not appear, not crash.
    assert snapshot.imports.get("sample_project/isolated.py", set()) == set()


def test_blast_radius_direct_hit_is_included():
    snapshot = build_kg(FIXTURE_ROOT)
    radius = blast_radius(snapshot, ["sample_project/c.py"], depth=1)
    assert "sample_project/c.py" in radius


def test_blast_radius_follows_reverse_edges_within_depth():
    snapshot = build_kg(FIXTURE_ROOT)
    # c.py changed; b.py imports c.py (1 hop reverse); a.py imports b.py (2 hops reverse).
    radius = blast_radius(snapshot, ["sample_project/c.py"], depth=2)
    assert "sample_project/b.py" in radius
    assert "sample_project/a.py" in radius


def test_blast_radius_respects_depth_cutoff():
    snapshot = build_kg(FIXTURE_ROOT)
    radius = blast_radius(snapshot, ["sample_project/c.py"], depth=1)
    assert "sample_project/b.py" in radius  # 1 hop
    assert "sample_project/a.py" not in radius  # 2 hops — excluded at depth=1


def test_blast_radius_isolated_file_has_no_neighbors():
    snapshot = build_kg(FIXTURE_ROOT)
    radius = blast_radius(snapshot, ["sample_project/isolated.py"], depth=2)
    assert radius == {"sample_project/isolated.py"}
