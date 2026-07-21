import pytest


@pytest.mark.asyncio
async def test_get_metrics_for_project_with_no_runs_returns_zeroed_metrics(api_client):
    client, _store, _scheduler = api_client

    resp = await client.post("/api/projects", json={"name": "demo", "path": "/tmp/demo"})
    project_id = resp.json()["data"]["id"]

    resp = await client.get(f"/api/metrics/{project_id}")
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["rework_rate"] == 0
    assert body["retry_count"] == 0


@pytest.mark.asyncio
async def test_get_metrics_for_unknown_project_404s(api_client):
    client, _store, _scheduler = api_client

    resp = await client.get("/api/metrics/01JUNKNOWN")
    assert resp.status_code == 404
