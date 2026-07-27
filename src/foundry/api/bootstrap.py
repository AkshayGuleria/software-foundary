from __future__ import annotations

import asyncio
import os
import shutil

from sqlalchemy.ext.asyncio import AsyncEngine

from foundry.api.scheduler import Scheduler
from foundry.drivers.factory import make_driver
from foundry.kg.service import build_kg
from foundry.orchestrator.worktrees import WorktreeManager
from foundry.packs.resolve import resolve_pack_manifest
from foundry.playbook.lint import PlaybookLintError
from foundry.playbook.loader import PlaybookLoadError, load_playbook
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


async def recover_active_runs(store: Store, scheduler: Scheduler) -> None:
    """Re-register every `status="active"` run with the scheduler on startup.

    This is the code path responsible for rehydrating each run's persisted
    `gate_overrides_json` back into its Orchestrator (via `Scheduler.register`'s
    `gate_overrides` kwarg) after a restart or a database hot-swap -- without
    it, a run created with gate overrides would silently lose them and any
    gate for a step created after the restart would revert to requiring
    manual approval.
    """
    active_runs = await store.list_runs(status="active")
    for active_run in active_runs:
        try:
            playbook = load_playbook(active_run.playbook_ref)
        except (PlaybookLoadError, PlaybookLintError):
            continue  # playbook file moved/changed since the run started; skip, don't crash startup
        project = await store.get_project(active_run.project_id)
        project_path = project.path if project is not None else "."
        scheduler.register(
            active_run.id,
            make_driver(active_run.driver, playbook),
            playbook,
            gate_overrides=active_run.gate_overrides_json or None,
            project_path=project_path,
            worktree_manager=WorktreeManager(base_dir=os.path.join(project_path, ".foundry", "worktrees")),
            kg_snapshot=await asyncio.to_thread(build_kg, project_path),
            pack=resolve_pack_manifest(active_run.playbook_ref),
        )


async def build_store_and_scheduler(db_path: str) -> tuple[AsyncEngine, Store, Scheduler]:
    """Stand up a fresh engine/Store/Scheduler for `db_path`, recovering any
    active runs and starting the scheduler's tick loop.

    Shared by `foundry serve`'s startup and the demo-mode hot-swap routes
    (`src/foundry/api/routes/demo.py`) so both paths recover runs identically.
    Auto-creates `db_path`'s parent directory if missing (e.g. the demo db's
    default `.foundry-demo/demo.db` won't exist on first activation).

    Raises `foundry.store.db.SchemaDriftError` (uncaught here -- propagates
    to the caller) if `db_path` already exists with a table missing columns
    the current models declare.
    """
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    engine = make_engine(db_path)
    await init_db(engine, db_path)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    scheduler = Scheduler(store)
    await recover_active_runs(store, scheduler)
    await scheduler.start()

    return engine, store, scheduler


def reset_sqlite_db(db_path: str, repos_dir: str | None = None) -> None:
    """Delete a sqlite db file (and its WAL/SHM sidecars) and, if given, a
    repos directory tree -- for idempotent re-seeding. Shared by `foundry
    demo-seed --reset` and `POST /api/demo/reseed`.
    """
    for path in (db_path, f"{db_path}-wal", f"{db_path}-shm"):
        if os.path.exists(path):
            os.remove(path)
    if repos_dir is not None:
        shutil.rmtree(repos_dir, ignore_errors=True)
