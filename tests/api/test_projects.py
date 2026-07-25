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


@pytest.mark.asyncio
async def test_create_project_with_malformed_body_returns_adr001_envelope(api_client):
    client, _store, _scheduler = api_client

    resp = await client.post("/api/projects", json={"name": "missing-path-field"})

    assert resp.status_code == 400
    body = resp.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["path"] == "/api/projects"


@pytest.mark.asyncio
async def test_pause_then_activate_project(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo", "path": "."})
    project_id = resp.json()["data"]["id"]

    resp = await client.post(f"/api/projects/{project_id}/pause")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "paused"

    resp = await client.post(f"/api/projects/{project_id}/activate")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "active"


@pytest.mark.asyncio
async def test_pausing_an_already_paused_project_409s(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo2", "path": "."})
    project_id = resp.json()["data"]["id"]
    await client.post(f"/api/projects/{project_id}/pause")

    resp = await client.post(f"/api/projects/{project_id}/pause")
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_archive_project(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo3", "path": "."})
    project_id = resp.json()["data"]["id"]

    resp = await client.post(f"/api/projects/{project_id}/archive")
    assert resp.status_code == 200
    assert resp.json()["data"]["status"] == "archived"


@pytest.mark.asyncio
async def test_creating_a_run_for_a_paused_project_409s(api_client):
    client, store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo4", "path": "."})
    project_id = resp.json()["data"]["id"]
    await client.post(f"/api/projects/{project_id}/pause")

    resp = await client.post(
        "/api/runs", json={"project_id": project_id, "playbook_path": "packs/default/playbooks/bugfix.toml"}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_new_project_has_default_settings(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo5", "path": "."})

    body = resp.json()["data"]
    assert body["default_driver"] == "fake"
    assert body["default_token_budget"] == 0
    assert body["default_playbook_path"] is None


@pytest.mark.asyncio
async def test_patch_settings_updates_only_provided_fields(api_client):
    client, _store, _scheduler = api_client
    resp = await client.post("/api/projects", json={"name": "demo6", "path": "."})
    project_id = resp.json()["data"]["id"]

    resp = await client.patch(f"/api/projects/{project_id}/settings", json={"driver": "codex"})
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["default_driver"] == "codex"
    assert body["default_token_budget"] == 0  # untouched
    assert body["default_playbook_path"] is None  # untouched

    resp = await client.patch(
        f"/api/projects/{project_id}/settings",
        json={"token_budget": 50000, "playbook_path": "packs/default/playbooks/bugfix.toml"},
    )
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["default_driver"] == "codex"  # still untouched by this second call
    assert body["default_token_budget"] == 50000
    assert body["default_playbook_path"] == "packs/default/playbooks/bugfix.toml"


@pytest.mark.asyncio
async def test_patch_settings_for_missing_project_404s(api_client):
    client, _store, _scheduler = api_client

    resp = await client.patch("/api/projects/does-not-exist/settings", json={"driver": "codex"})

    assert resp.status_code == 404
