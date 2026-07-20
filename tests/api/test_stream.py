import pytest


@pytest.mark.asyncio
async def test_stream_replays_existing_events_then_new_ones(sse_api_client):
    client, store, _scheduler = sse_api_client

    project = await store.create_project("proj", "/tmp/proj")
    run = await store.create_run(project.id, "pb.toml", "stream test")
    await store.append_event(run.id, None, "run.created", {"note": "first"})

    lines: list[str] = []
    async with client.stream("GET", f"/api/stream/{run.id}", headers={"Last-Event-ID": "0"}) as response:
        assert response.status_code == 200
        async for line in response.aiter_lines():
            lines.append(line)
            # SSE events are multi-line (id/event/data) and terminated by a
            # blank line; wait for that terminator so the full event
            # (including its data: line) has been collected before we stop.
            if line == "" and any("run.created" in item for item in lines):
                break

    text = "\n".join(lines)
    assert "event: run.created" in text
    assert '"note": "first"' in text


@pytest.mark.asyncio
async def test_stream_resumes_from_last_event_id(sse_api_client):
    client, store, _scheduler = sse_api_client

    project = await store.create_project("proj2", "/tmp/proj2")
    run = await store.create_run(project.id, "pb.toml", "stream resume test")
    seq1 = await store.append_event(run.id, None, "event.one", {})
    await store.append_event(run.id, None, "event.two", {})

    lines: list[str] = []
    headers = {"Last-Event-ID": str(seq1)}
    async with client.stream("GET", f"/api/stream/{run.id}", headers=headers) as response:
        async for line in response.aiter_lines():
            lines.append(line)
            if line == "" and any("event.two" in item for item in lines):
                break

    text = "\n".join(lines)
    assert "event.one" not in text  # already seen, per Last-Event-ID
    assert "event.two" in text
