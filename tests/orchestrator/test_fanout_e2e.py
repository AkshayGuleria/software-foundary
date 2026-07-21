"""End-to-end proof of the M2 exit criterion: a 3-slice fan-out implemented by
"mixed providers", peer-reviewed with at least one real rejection+rework round,
and integrated with an escalation -- driven entirely on FakeDriver (no real
network calls; see this plan's Global Constraints).
"""

from __future__ import annotations

import subprocess

import pytest

from foundry.drivers.base import DriverEvent, SessionSpec
from foundry.drivers.fake import FakeDriver, FakeStepScript
from foundry.orchestrator.tick import Orchestrator
from foundry.orchestrator.worktrees import WorktreeManager, _git_env
from foundry.playbook.loader import load_playbook
from foundry.playbook.materializer import materialize
from foundry.store.db import init_db, make_engine, make_sessionmaker
from foundry.store.store import Store


def _init_repo(path):
    # Strip repo-scoped GIT_* env vars (GIT_DIR in particular) so `-C <path>`
    # is authoritative even when this suite runs inside this repo's own
    # pre-commit hook, which sets GIT_DIR for its linked-worktree context.
    # See worktrees.py's _git_env() docstring for the real incident this
    # guards against (Task 4's review).
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=_git_env())
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True, env=_git_env()
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True, env=_git_env())
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, env=_git_env())
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True, env=_git_env())


class _MixedProviderDriver(FakeDriver):
    """Tags each "implement" slice's session with a different simulated
    provider label, standing in for real mixed-provider dispatch (one slice
    on a Claude-style driver, one on a Codex-style driver, etc.) without
    spending tokens or making a network call, per this plan's Global
    Constraints.
    """

    PROVIDERS = ["claude-fake", "codex-fake", "claude-fake"]

    def __init__(self, script):
        super().__init__(script)
        self.provider_by_unit: dict[str, str] = {}
        self._implement_calls = 0

    def spawn(self, spec: SessionSpec):
        handle = super().spawn(spec)
        if spec.step_id == "implement":
            provider = self.PROVIDERS[self._implement_calls % len(self.PROVIDERS)]
            self._implement_calls += 1
        else:
            provider = "claude-fake"
        self.provider_by_unit[handle.id] = provider
        return handle


@pytest.mark.asyncio
async def test_full_fanout_review_integrate_cycle(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(repo))
    playbook = load_playbook("tests/orchestrator/fixtures/fanout_e2e.toml")
    run = await store.create_run(project.id, "fanout_e2e.toml", "demo run")
    await materialize(playbook, run.id, store)

    review_call_count = {"n": 0}

    # "integrate" is scripted with its escalation-shaped artifact from the
    # start -- not patched in mid-run -- so that whichever tick it actually
    # dispatches on (which depends on exactly how many rounds the review loop
    # below takes), it always produces the escalation payload we want to
    # assert on.
    script = {
        "architecture": FakeStepScript(artifact={"slices": ["auth", "billing", "notifications"]}),
        "implement": FakeStepScript(artifact={"diff": "ok"}),
        "integrate": FakeStepScript(
            artifact={
                "auto_resolved": ["package-lock.json"],
                "escalated": [{"file": "auth.py", "reason": "semantic overlap"}],
            }
        ),
    }
    driver = _MixedProviderDriver(script)

    # FakeDriver scripts purely by step_id, but the "review" step is dispatched
    # through two entirely different session flows that both carry step_id ==
    # "review": (1) the review task's own artifact-producing session (normal
    # dispatch()/_collect(), handle.id == session_unit.id), and (2)
    # _dispatch_agent_reviews's separate verdict-determination session
    # (handle.id == gate.id). Only the second is the one whose "verdict"
    # decides approve/reject -- distinguishing them by step_id alone would
    # wrongly intercept #1 too and burn through the reject-then-approve
    # script on the wrong session (this is the same ambiguity Task 6's review
    # caught for the fan-out-vs-convoy slice matching; test_review_loop.py's
    # `test_agent_gate_rejection_reworks_the_matching_slice_in_a_fan_out_convoy`
    # uses the same gate-id-matching fix). Match on gate id instead.
    original_stream = driver.stream_events

    async def _review_aware_stream(handle):
        gates = await store.list_gates_for_run(run.id)
        gate = next((g for g in gates if g.id == handle.id), None)
        if gate is None:
            async for ev in original_stream(handle):
                yield ev
            return
        review_call_count["n"] += 1
        yield DriverEvent(kind="tool_call", payload={"tool": "noop"})
        if review_call_count["n"] <= 1:
            yield DriverEvent(kind="completed", payload={"artifact": {"verdict": "needs_changes"}})
        else:
            yield DriverEvent(kind="completed", payload={"artifact": {"verdict": "approved"}})

    driver.stream_events = _review_aware_stream

    worktree_mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    orch = Orchestrator(
        store, driver, playbook, concurrency=10, worktree_manager=worktree_mgr, project_path=str(repo)
    )

    # Drive architecture's human gate to approved.
    await orch.tick(run.id)
    gates = await store.list_gates_for_run(run.id)
    arch_gate = next(g for g in gates if g.artifact_id is not None)
    assert arch_gate.decision == "pending"
    await store.decide_gate(arch_gate.id, "approved")

    # Drive enough ticks for fan-out, implement, at-least-one review rejection
    # + rework, eventual approval, convoy close, and integrate's own dispatch
    # + escalation. Generous margin over the ~6 ticks the happy path needs.
    for _ in range(20):
        await orch.tick(run.id)

    units = await store.list_units(run.id)
    convoy = next(u for u in units if u.type == "convoy")
    assert convoy.status == "closed"

    # Filter by convoy_id, not just step_id: dispatch() spawns a "session" unit
    # per dispatched task sharing that task's step_id (see Orchestrator.dispatch),
    # so a step_id-only filter also picks up every review/implement session ever
    # spawned (including retries) -- convoy_id is only ever set on the fan-out
    # chain's own task/gate units, never on sessions, so it isolates exactly
    # the 3 real per-slice task units.
    review_units = [u for u in units if u.step_id == "review" and u.convoy_id == convoy.id]
    assert len(review_units) == 3

    implement_units = [u for u in units if u.step_id == "implement" and u.convoy_id == convoy.id]
    assert len(implement_units) == 3
    reworked = [u for u in implement_units if u.attempt >= 1]
    assert len(reworked) == 1, (
        "exactly one slice's review should have been rejected once (shared reject-once script)"
    )
    assert all(u.status == "closed" for u in implement_units)
    assert all(u.status == "closed" for u in review_units)

    # "mixed providers": at least two distinct simulated providers were used
    # across the three implement slices.
    assert len(set(driver.provider_by_unit.values())) >= 2

    artifacts = await store.list_artifacts(run.id)
    implement_artifacts = [a for a in artifacts if a.kind == "code_diff_artifact"]
    # 3 slices, one of which was reworked once -> 3 + 1 = 4 versions total.
    assert len(implement_artifacts) == 4

    # Worktrees existed (writes=true on "implement") and were cleaned up on
    # close for every implement slice unit, including the reworked one.
    worktree_root = tmp_path / "worktrees" / run.id
    assert not worktree_root.exists() or not any(worktree_root.iterdir())

    # integrate: dispatched once convoy closed, escalation payload triggers a
    # human_task per Task 5's generic "artifact says escalate" contract.
    integrate_unit = next(u for u in units if u.step_id == "integrate")
    assert integrate_unit.status == "blocked"

    events = await store.list_events(run.id)
    blocked_events = [e for e in events if e.type == "unit.blocked" and e.unit_id == integrate_unit.id]
    assert blocked_events
    assert blocked_events[-1].payload_json["reason"] == "escalated"
    assert blocked_events[-1].payload_json["escalated"] == [{"file": "auth.py", "reason": "semantic overlap"}]

    human_tasks = [u for u in units if u.type == "human_task"]
    assert len(human_tasks) == 1
    assert human_tasks[0].step_id == "integrate.escalation"

    # Integrate's own artifact was produced and recorded despite escalating.
    integration_artifacts = [a for a in artifacts if a.kind == "integration_artifact"]
    assert len(integration_artifacts) == 1
    assert integration_artifacts[0].payload_json["auto_resolved"] == ["package-lock.json"]

    await store.stop()
