import pytest

VALID_TOML = """
[playbook]
id = "hotfix"
description = "A minimal one-step playbook"

[[step]]
id = "review"
role = "reviewer"
produces = "review_artifact"
gate = "human"
"""

INVALID_TOML = "[playbook\nid = broken"


async def _create_project(client):
    resp = await client.post("/api/projects", json={"name": "acme", "path": "/tmp/acme"})
    return resp.json()["data"]["id"]


@pytest.mark.asyncio
async def test_list_playbooks_empty_for_a_fresh_project(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    resp = await client.get(f"/api/projects/{project_id}/playbooks")
    assert resp.status_code == 200
    assert resp.json()["data"] == []


@pytest.mark.asyncio
async def test_list_playbooks_unknown_project_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/projects/does-not-exist/playbooks")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_create_then_get_then_list_roundtrip(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    create_resp = await client.post(
        f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix Flow", "content": VALID_TOML}
    )
    assert create_resp.status_code == 201
    body = create_resp.json()["data"]
    assert body["slug"] == "hotfix-flow"
    assert body["playbook_id"] == "hotfix"
    assert body["content"] == VALID_TOML

    get_resp = await client.get(f"/api/projects/{project_id}/playbooks/hotfix-flow")
    assert get_resp.status_code == 200
    assert get_resp.json()["data"]["content"] == VALID_TOML

    list_resp = await client.get(f"/api/projects/{project_id}/playbooks")
    assert [p["slug"] for p in list_resp.json()["data"]] == ["hotfix-flow"]


@pytest.mark.asyncio
async def test_create_with_invalid_toml_returns_400(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    resp = await client.post(
        f"/api/projects/{project_id}/playbooks", json={"name": "Broken", "content": INVALID_TOML}
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_create_duplicate_slug_returns_409(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    await client.post(f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML})

    resp = await client.post(
        f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML}
    )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_update_unknown_slug_returns_404(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    resp = await client.put(
        f"/api/projects/{project_id}/playbooks/does-not-exist", json={"content": VALID_TOML}
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_update_persists_new_content(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    await client.post(f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML})

    updated_toml = VALID_TOML.replace("A minimal", "An updated minimal")
    resp = await client.put(f"/api/projects/{project_id}/playbooks/hotfix", json={"content": updated_toml})
    assert resp.status_code == 200
    assert resp.json()["data"]["content"] == updated_toml


@pytest.mark.asyncio
async def test_delete_then_list_is_empty(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    await client.post(f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML})

    del_resp = await client.delete(f"/api/projects/{project_id}/playbooks/hotfix")
    assert del_resp.status_code == 204

    list_resp = await client.get(f"/api/projects/{project_id}/playbooks")
    assert list_resp.json()["data"] == []


@pytest.mark.asyncio
async def test_delete_unknown_slug_returns_404(api_client):
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    resp = await client.delete(f"/api/projects/{project_id}/playbooks/does-not-exist")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_a_non_canonical_slug_returns_404_not_500_on_every_verb(api_client):
    """project_playbook_path() (Task A) rejects any slug that isn't already
    in canonical slugify() form -- e.g. one containing a dot-segment. FastAPI's
    plain {slug} path converter already excludes literal '/', but a slug like
    '..' alone is still non-canonical and must surface as a clean 404, not an
    unhandled 500, on every verb that accepts a slug from the URL.

    The dot-segment is percent-encoded ("%2e%2e") rather than literal ("..")
    because httpx applies RFC 3986 dot-segment removal client-side before
    ever issuing the request: a literal ".." collapses into the parent path
    (".../playbooks/.." becomes ".../projects/{id}") and never reaches this
    route at all, so the test would silently exercise the wrong endpoint.
    Percent-encoding bypasses that client-side normalization and delivers
    slug=".." to the handler as intended."""
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)

    get_resp = await client.get(f"/api/projects/{project_id}/playbooks/%2e%2e")
    assert get_resp.status_code == 404

    put_resp = await client.put(f"/api/projects/{project_id}/playbooks/%2e%2e", json={"content": VALID_TOML})
    assert put_resp.status_code == 404

    delete_resp = await client.delete(f"/api/projects/{project_id}/playbooks/%2e%2e")
    assert delete_resp.status_code == 404


@pytest.mark.asyncio
async def test_project_playbook_can_start_a_real_run(api_client):
    """End-to-end: a project playbook's returned path is a completely valid
    RunCreate.playbook_path -- proves the full-stack integration claim, not
    just the storage-layer one from Task A."""
    client, _store, _scheduler = api_client
    project_id = await _create_project(client)
    create_resp = await client.post(
        f"/api/projects/{project_id}/playbooks", json={"name": "Hotfix", "content": VALID_TOML}
    )
    path = create_resp.json()["data"]["path"]

    run_resp = await client.post(
        "/api/runs", json={"project_id": project_id, "playbook_path": path, "driver": "fake"}
    )
    assert run_resp.status_code == 201
    assert run_resp.json()["data"]["pack_version_pin"] == "local"
