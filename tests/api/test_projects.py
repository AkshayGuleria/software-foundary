import pytest


@pytest.mark.asyncio
async def test_create_and_get_project(api_client):
    client, _store, _scheduler = api_client

    create_resp = await client.post("/api/projects", json={"name": "acme", "path": "/repos/acme"})
    assert create_resp.status_code == 201
    body = create_resp.json()
    assert body["data"]["name"] == "acme"
    expected_paging = {
        "offset": None,
        "limit": None,
        "total": None,
        "total_pages": None,
        "has_next": None,
        "has_prev": None,
    }
    assert body["paging"] == expected_paging
    project_id = body["data"]["id"]

    get_resp = await client.get(f"/api/projects/{project_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["path"] == "/repos/acme"


@pytest.mark.asyncio
async def test_get_missing_project_returns_404_envelope(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/projects/does-not-exist")

    assert resp.status_code == 404
    body = resp.json()
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["path"] == "/api/projects/does-not-exist"


@pytest.mark.asyncio
async def test_list_projects_is_paginated(api_client):
    client, _store, _scheduler = api_client

    for i in range(3):
        await client.post("/api/projects", json={"name": f"proj-{i}", "path": f"/tmp/{i}"})

    resp = await client.get("/api/projects?offset=0&limit=2")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["data"]) == 2
    assert body["paging"]["total"] == 3
    assert body["paging"]["has_next"] is True


@pytest.mark.asyncio
async def test_list_projects_rejects_limit_over_100(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/projects?limit=101")

    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"
