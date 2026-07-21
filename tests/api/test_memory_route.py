import pytest


@pytest.mark.asyncio
async def test_list_memory_returns_empty_with_no_items(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/memory")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_list_memory_filters_by_project_id(api_client):
    client, store, _scheduler = api_client
    await store.create_memory_item(scope="project", kind="lesson", title="A", body_md="x", project_id="p1")
    await store.create_memory_item(scope="project", kind="lesson", title="B", body_md="x", project_id="p2")

    resp = await client.get("/api/memory?project_id=p1")
    data = resp.json()["data"]
    assert [item["title"] for item in data] == ["A"]


@pytest.mark.asyncio
async def test_list_memory_filters_by_scope_and_kind(api_client):
    client, store, _scheduler = api_client
    await store.create_memory_item(scope="project", kind="lesson", title="L", body_md="x", project_id="p1")
    await store.create_memory_item(scope="project", kind="pattern", title="P", body_md="x", project_id="p1")

    resp = await client.get("/api/memory?project_id=p1&kind=pattern")
    data = resp.json()["data"]
    assert [item["title"] for item in data] == ["P"]
