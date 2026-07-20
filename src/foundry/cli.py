from __future__ import annotations

import asyncio

import typer

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.lint import lint_plan_first
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store

app = typer.Typer()


@app.command()
def run(playbook_path: str, project_path: str = ".", db: str = "foundry.db") -> None:
    run_id = asyncio.run(_run(playbook_path, project_path, db))
    typer.echo(run_id)


async def _run(playbook_path: str, project_path: str, db: str) -> str:
    engine = make_engine(db)
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    playbook = load_playbook(playbook_path)
    lint_plan_first(playbook)

    project = await store.create_project(playbook.id, project_path)
    run_row = await store.create_run(project.id, playbook_path, playbook.description or playbook.id)
    await materialize(playbook, run_row.id, store)

    script = {step.id: FakeStepScript(artifact={"ok": True}) for step in playbook.steps}
    orchestrator = Orchestrator(store, FakeDriver(script), playbook)
    await orchestrator.run_to_completion(run_row.id)

    await store.stop()
    return run_row.id


@app.command()
def events(run_id: str, db: str = "foundry.db", once: bool = False) -> None:
    asyncio.run(_events(run_id, db, once))


async def _events(run_id: str, db: str, once: bool) -> None:
    engine = make_engine(db)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()

    last_seq = 0
    while True:
        new_events = await store.list_events(run_id, after_seq=last_seq)
        for ev in new_events:
            typer.echo(f"[{ev.seq}] {ev.type} unit={ev.unit_id} {ev.payload_json}")
            last_seq = ev.seq
        if once:
            break
        await asyncio.sleep(0.2)

    await store.stop()
