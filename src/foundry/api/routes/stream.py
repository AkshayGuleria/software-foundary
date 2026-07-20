from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from foundry.api.routes.projects import _get_store

router = APIRouter()


@router.get("/stream/{run_id}")
async def stream_run(run_id: str, request: Request) -> EventSourceResponse:
    store = _get_store(request)
    last_seq = _parse_last_event_id(request)

    async def event_generator():
        seq = last_seq
        while True:
            if await request.is_disconnected():
                break
            events = await store.list_events(run_id, after_seq=seq)
            for ev in events:
                seq = ev.seq
                yield {"id": str(ev.seq), "event": ev.type, "data": json.dumps(ev.payload_json)}
            await asyncio.sleep(0.2)

    return EventSourceResponse(event_generator())


def _parse_last_event_id(request: Request) -> int:
    header = request.headers.get("last-event-id")
    if header is not None:
        try:
            return int(header)
        except ValueError:
            return 0
    param = request.query_params.get("after_seq")
    if param is not None:
        try:
            return int(param)
        except ValueError:
            return 0
    return 0
