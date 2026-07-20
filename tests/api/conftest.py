import asyncio

import pytest_asyncio
import uvicorn
from httpx import ASGITransport, AsyncClient

from foundry.api.app import create_app
from foundry.api.scheduler import Scheduler
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def _make_store_scheduler_app(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)
    app = create_app(store, scheduler)
    return engine, store, scheduler, app


@pytest_asyncio.fixture
async def api_client(tmp_path):
    engine, store, scheduler, app = await _make_store_scheduler_app(tmp_path)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, store, scheduler

    await store.stop()
    await engine.dispose()


@pytest_asyncio.fixture
async def sse_api_client(tmp_path):
    """Like `api_client`, but serves the app over a real TCP socket.

    `httpx.ASGITransport` runs the whole ASGI app to completion inside a
    single `await` and only returns a `Response` once that finishes; the body
    is fully buffered before the client ever sees a byte (see
    `httpx._transports.asgi.ASGITransport.handle_async_request` /
    `ASGIResponseStream`). An endpoint that streams until
    `Request.is_disconnected()` fires can therefore never terminate under
    ASGITransport: `is_disconnected()` learns about a disconnect via the ASGI
    `receive()` channel, which only yields `http.disconnect` after the
    response is complete — but the response can't complete until the
    generator sees the disconnect. That's a hard deadlock, independent of
    timeouts, and it is why SSE routes need a real socket (uvicorn here) to
    be exercised by tests: a real server can observe the client's socket
    close out-of-band, decoupled from whether the app coroutine has
    returned.
    """
    engine, store, scheduler, app = await _make_store_scheduler_app(tmp_path)

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning", lifespan="off")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.01)
    port = server.servers[0].sockets[0].getsockname()[1]

    async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as client:
        yield client, store, scheduler

    server.should_exit = True
    await server_task

    await store.stop()
    await engine.dispose()
