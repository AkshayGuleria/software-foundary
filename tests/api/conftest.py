import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from foundry.api.app import create_app
from foundry.api.scheduler import Scheduler
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest_asyncio.fixture
async def api_client(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)

    app = create_app(store, scheduler)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client, store, scheduler

    await store.stop()
