import datetime
import gzip
import json

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
async def test_archive_run_events_writes_gzip_jsonl_and_prunes_hot_table(tmp_path):
    store = await _store(tmp_path)
    project = await store.create_project("demo", str(tmp_path))
    run = await store.create_run(project.id, "p.toml", "demo")
    await store.append_event(run.id, None, "run.created", {"x": 1})
    await store.append_event(run.id, None, "run.closed", {"y": 2})

    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    path = await store.archive_run_events(run.id, str(archive_dir))

    assert path.endswith(f"{run.id}.jsonl.gz")
    with gzip.open(path, "rt") as f:
        lines = [json.loads(line) for line in f]
    assert len(lines) == 2
    assert {line["type"] for line in lines} == {"run.created", "run.closed"}

    remaining = await store.list_events(run.id)
    assert remaining == []
    await store.stop()


@pytest.mark.asyncio
async def test_archive_run_events_second_invocation_does_not_destroy_archive(tmp_path):
    store = await _store(tmp_path)
    project = await store.create_project("demo", str(tmp_path))
    run = await store.create_run(project.id, "p.toml", "demo")
    await store.append_event(run.id, None, "run.created", {"x": 1})
    await store.append_event(run.id, None, "run.closed", {"y": 2})

    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()

    # First archival: writes the archive and prunes events from the hot table.
    first_path = await store.archive_run_events(run.id, str(archive_dir))
    with gzip.open(first_path, "rt") as f:
        first_lines = [json.loads(line) for line in f]
    assert len(first_lines) == 2

    # Second, redundant invocation (e.g. a cron re-run before the run ages out of
    # the eligibility window): events are already gone from the hot table, so this
    # must NOT truncate the previously-written archive.
    second_path = await store.archive_run_events(run.id, str(archive_dir))
    assert second_path == first_path

    with gzip.open(second_path, "rt") as f:
        second_lines = [json.loads(line) for line in f]
    assert len(second_lines) == 2
    assert {line["type"] for line in second_lines} == {"run.created", "run.closed"}
    await store.stop()


@pytest.mark.asyncio
async def test_list_closed_runs_older_than_excludes_recent_and_active_runs(tmp_path):
    store = await _store(tmp_path)
    project = await store.create_project("demo", str(tmp_path))

    recent_closed = await store.create_run(project.id, "p.toml", "recent")
    await store.update_run(recent_closed.id, status="closed", closed_at=datetime.datetime.now(datetime.UTC))

    still_active = await store.create_run(project.id, "p.toml", "active")
    await store.update_run(still_active.id, status="active")

    old_closed = await store.create_run(project.id, "p.toml", "old")
    old_time = datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=45)
    await store.update_run(old_closed.id, status="closed", closed_at=old_time)

    eligible = await store.list_closed_runs_older_than(30)
    assert [r.id for r in eligible] == [old_closed.id]
    await store.stop()
