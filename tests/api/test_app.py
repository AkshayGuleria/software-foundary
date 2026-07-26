import pytest

from foundry.api.app import create_app
from foundry.api.scheduler import Scheduler
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_create_app_defaults_current_db_path_to_original_db_path(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)

    app = create_app(store, scheduler, engine=engine, original_db_path=str(tmp_path / "foundry.db"))

    assert app.state.current_db_path == str(tmp_path / "foundry.db")
    assert app.state.demo_db_path == ".foundry-demo/demo.db"
    assert app.state.demo_repos_dir == ".foundry-demo/repos"
    assert app.state.demo_swap_lock is not None

    await store.stop()
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_app_without_original_db_path_defaults_to_none(tmp_path):
    # Every existing caller that doesn't care about demo mode (most test
    # fixtures) keeps working unchanged -- engine/original_db_path default
    # to None, current_db_path follows original_db_path (also None).
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    scheduler = Scheduler(store)

    app = create_app(store, scheduler)

    assert app.state.engine is None
    assert app.state.original_db_path is None
    assert app.state.current_db_path is None

    await store.stop()
    await engine.dispose()
