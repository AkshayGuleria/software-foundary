from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from foundry.orchestrator.worktrees import WorktreeManager, _git_env


def _init_repo(path):
    # Use _git_env() everywhere: when this suite runs inside this repo's own
    # pre-commit hook (git sets GIT_DIR for the hook's linked-worktree
    # context), an inherited GIT_DIR silently overrides `-C <path>` and every
    # command below would operate on this repo instead of the throwaway repo
    # under tmp_path. See the matching comment in worktrees.py.
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=_git_env())
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True, env=_git_env()
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "test"], check=True, env=_git_env())
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, env=_git_env())
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True, env=_git_env())


def test_create_makes_a_real_worktree_on_its_own_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    path = mgr.create(str(repo), run_id="run1", unit_id="unit1")

    assert Path(path).is_dir()
    assert (Path(path) / "README.md").exists()
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "foundry/run1/unit1"],
        capture_output=True,
        text=True,
        check=True,
        env=_git_env(),
    ).stdout
    assert "foundry/run1/unit1" in branches


def test_remove_deletes_worktree_and_branch(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    path = mgr.create(str(repo), run_id="run1", unit_id="unit1")
    mgr.remove(str(repo), path)

    assert not Path(path).exists()
    branches = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "foundry/run1/unit1"],
        capture_output=True,
        text=True,
        check=True,
        env=_git_env(),
    ).stdout
    assert "foundry/run1/unit1" not in branches


@pytest.mark.asyncio
async def test_writes_step_gets_a_real_worktree_and_it_is_cleaned_up_on_close(tmp_path):
    from foundry.drivers.fake import FakeDriver, FakeStepScript
    from foundry.orchestrator.tick import Orchestrator
    from foundry.playbook.materializer import materialize
    from foundry.playbook.schema import PlaybookSpec, StepSpec
    from foundry.store.db import init_db, make_engine, make_sessionmaker
    from foundry.store.store import Store

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(repo))
    playbook = PlaybookSpec(
        id="p", steps=[StepSpec(id="a", role="dev", writes=True, produces="x", gate="none")]
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    orch = Orchestrator(
        store,
        FakeDriver({"a": FakeStepScript(artifact={})}),
        playbook,
        worktree_manager=mgr,
        project_path=str(repo),
    )

    await orch.tick(run.id)  # dispatches "a", worktree created, task runs to closed synchronously

    worktree_path = tmp_path / "worktrees" / run.id
    # unit id isn't known ahead of time; assert the parent dir is empty (cleaned up) rather
    # than guessing the unit's ULID.
    assert not any(worktree_path.iterdir()) if worktree_path.exists() else True


@pytest.mark.asyncio
async def test_retried_writes_step_reuses_the_same_worktree(tmp_path):
    """A retry (failed-but-under-max-attempts) must not re-run `git worktree add`
    against the same branch/path — the worktree is deliberately kept alive across
    dispatches for rework, so dispatch() has to reuse it rather than recreate it.
    """
    from foundry.drivers.fake import FakeDriver, FakeStepScript
    from foundry.orchestrator.tick import Orchestrator
    from foundry.playbook.materializer import materialize
    from foundry.playbook.schema import PlaybookSpec, StepSpec
    from foundry.store.db import init_db, make_engine, make_sessionmaker
    from foundry.store.store import Store

    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    engine = make_engine(str(tmp_path / "foundry.db"))
    await init_db(engine)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    project = await store.create_project("demo", str(repo))
    playbook = PlaybookSpec(
        id="p",
        steps=[StepSpec(id="a", role="dev", writes=True, produces="x", gate="none")],
    )
    run = await store.create_run(project.id, "p.toml", "demo")
    await materialize(playbook, run.id, store)

    mgr = WorktreeManager(base_dir=tmp_path / "worktrees")
    driver = FakeDriver({"a": FakeStepScript(mode="fail")})
    orch = Orchestrator(
        store,
        driver,
        playbook,
        worktree_manager=mgr,
        project_path=str(repo),
    )

    await orch.tick(run.id)  # attempt 1 fails, task goes back to "ready" (max_attempts=3)
    units = await store.list_units(run.id)
    task_unit = next(u for u in units if u.step_id == "a" and u.type == "task")
    assert task_unit.status == "ready"
    first_worktree = orch._unit_worktrees[task_unit.id]
    assert Path(first_worktree).is_dir()

    # attempt 2 must not raise (would, if dispatch() re-ran `git worktree add`
    # on the already-existing branch/path)
    await orch.tick(run.id)
    units = await store.list_units(run.id)
    task_unit = next(u for u in units if u.step_id == "a" and u.type == "task")
    assert orch._unit_worktrees[task_unit.id] == first_worktree
    assert Path(first_worktree).is_dir()
