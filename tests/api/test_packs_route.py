import pytest


@pytest.mark.asyncio
async def test_list_packs_returns_the_shipped_default_pack(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs")
    assert resp.status_code == 200
    body = resp.json()["data"]
    ids = [p["id"] for p in body]
    assert "default" in ids


@pytest.mark.asyncio
async def test_get_pack_by_id_returns_full_manifest(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs/default")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["id"] == "default"
    role_ids = {r["id"] for r in body["roles"]}
    assert "developer" in role_ids
    assert "playbooks/sdlc_story.toml" in body["playbooks"]
    assert "playbooks/bugfix.toml" in body["playbooks"]


@pytest.mark.asyncio
async def test_get_pack_by_unknown_id_returns_404(api_client):
    client, _store, _scheduler = api_client
    resp = await client.get("/api/packs/does-not-exist")
    assert resp.status_code == 404
