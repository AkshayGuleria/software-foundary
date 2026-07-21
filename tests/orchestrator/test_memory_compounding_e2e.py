import pytest

from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


@pytest.mark.asyncio
async def test_second_run_context_bundle_includes_lesson_from_first_run(tmp_path):
    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(tmp_path))
    playbook = load_playbook("tests/orchestrator/fixtures/compounding_demo.toml")

    # Run 1: implement, then compound distills a lesson about this project's
    # implement step into the Memory table.
    run1 = await store.create_run(project.id, "compounding_demo.toml", "run 1")
    await materialize(playbook, run1.id, store)
    driver1 = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"files": ["auth.py"]}),
            "compound": FakeStepScript(
                artifact={
                    "items": [
                        {
                            "kind": "lesson",
                            "title": "auth.py implement lesson",
                            "body_md": "implement steps touching auth.py must handle token expiry edge cases",
                        }
                    ]
                }
            ),
        }
    )
    orch1 = Orchestrator(store, driver1, playbook)
    for _ in range(4):
        await orch1.tick(run1.id)

    memory_after_run1 = await store.list_memory_items(project_id=project.id)
    assert len(memory_after_run1) == 1

    # Run 2: a similar feature (same project, same playbook, implement again
    # touches auth.py) — its context bundle for the implement dispatch must
    # surface the lesson written by run 1.
    #
    # NOTE on *why* this matches: `implement` has no `needs`, so
    # `_compose_context_bundle`'s query text reduces to just the step_id,
    # "implement" -- the "touches auth.py" detail above plays no part in the
    # match (input_files is empty; "auth.py" never enters the query). The
    # match instead comes entirely from the word "implement" appearing
    # verbatim in both the query and the lesson's title/body below. This is
    # `select_relevant_memory`'s keyword-overlap scoring working exactly as
    # documented (172f7d4: "documented substitute for embedding similarity"),
    # not semantic understanding -- a lesson worded without the literal word
    # "implement" (e.g. one that only said "auth.py" and "token expiry")
    # would score 0 and this test would fail. That fragility is a known
    # property of the retrieval mechanism this milestone ships, not a defect
    # in this test; it's called out here so a future wording change to the
    # fixture lesson below doesn't accidentally break the cross-run proof for
    # a reason that looks unrelated.
    run2 = await store.create_run(project.id, "compounding_demo.toml", "run 2")
    await materialize(playbook, run2.id, store)
    driver2 = FakeDriver(
        {
            "implement": FakeStepScript(artifact={"files": ["auth.py"]}),
            "compound": FakeStepScript(artifact={"items": []}),
        }
    )
    orch2 = Orchestrator(store, driver2, playbook)
    await orch2.tick(run2.id)  # dispatches "implement" — this is the tick whose context.composed we check

    events = await store.list_events(run2.id)
    composed = [e for e in events if e.type == "context.composed"]
    implement_composed = composed[0]
    assert implement_composed.payload_json["memory_items"] >= 1, (
        "run 2's implement dispatch should have surfaced run 1's lesson via project-scoped memory retrieval"
    )
