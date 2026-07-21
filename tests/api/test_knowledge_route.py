import pytest


@pytest.mark.asyncio
async def test_kg_graph_404s_for_unknown_project(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/projects/01JUNKNOWN/kg-graph")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_kg_graph_builds_from_project_path(api_client, tmp_path):
    client, store, _scheduler = api_client
    (tmp_path / "a.py").write_text("import b\n")
    (tmp_path / "b.py").write_text("X = 1\n")
    project = await store.create_project("demo", str(tmp_path))

    resp = await client.get(f"/api/projects/{project.id}/kg-graph")
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert set(data["nodes"]) == {"a.py", "b.py"}
    assert {"from": "a.py", "to": "b.py"} in data["edges"]


@pytest.mark.asyncio
async def test_kg_graph_empty_for_project_with_no_python_files(api_client, tmp_path):
    client, store, _scheduler = api_client
    project = await store.create_project("demo", str(tmp_path))

    resp = await client.get(f"/api/projects/{project.id}/kg-graph")
    assert resp.status_code == 200
    assert resp.json()["data"] == {"nodes": [], "edges": []}
