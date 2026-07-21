import pytest

from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def _store(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    return store


@pytest.mark.asyncio
async def test_create_and_list_memory_item(tmp_path):
    store = await _store(tmp_path)
    item = await store.create_memory_item(
        scope="project",
        kind="lesson",
        title="Watch the budget",
        body_md="Token budgets pause dispatch, not kill in-flight work.",
        project_id="proj1",
        source_run_id="run1",
    )
    assert item.id

    items = await store.list_memory_items(project_id="proj1")
    assert len(items) == 1
    assert items[0].title == "Watch the budget"
    await store.stop()


@pytest.mark.asyncio
async def test_list_memory_items_filters_by_project(tmp_path):
    store = await _store(tmp_path)
    await store.create_memory_item(scope="project", kind="lesson", title="A", body_md="x", project_id="p1")
    await store.create_memory_item(scope="project", kind="lesson", title="B", body_md="x", project_id="p2")

    items = await store.list_memory_items(project_id="p1")
    assert [i.title for i in items] == ["A"]
    await store.stop()


@pytest.mark.asyncio
async def test_list_memory_items_filters_by_kind_and_scope(tmp_path):
    store = await _store(tmp_path)
    await store.create_memory_item(scope="project", kind="lesson", title="L", body_md="x", project_id="p1")
    await store.create_memory_item(scope="project", kind="pattern", title="P", body_md="x", project_id="p1")

    items = await store.list_memory_items(project_id="p1", kind="pattern")
    assert [i.title for i in items] == ["P"]
    await store.stop()


@pytest.mark.asyncio
async def test_list_memory_items_with_no_filters_returns_all(tmp_path):
    store = await _store(tmp_path)
    await store.create_memory_item(scope="pack", kind="pattern", title="X", body_md="x", pack_id="pk1")
    items = await store.list_memory_items()
    assert len(items) == 1
    await store.stop()
