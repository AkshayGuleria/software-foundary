import asyncio
import os
import subprocess

from typer.testing import CliRunner

from foundry.cli import app
from foundry.orchestrator.worktrees import _git_env
from foundry.store.db import make_engine, make_sessionmaker
from foundry.store.store import Store

runner = CliRunner()


def _init_git_repo(path):
    # Strip repo-scoped GIT_* env vars (GIT_DIR in particular) so `-C <path>`
    # is authoritative even when this test itself runs inside this repo's own
    # pre-commit hook, which sets GIT_DIR for its linked-worktree context.
    # See worktrees.py's _git_env() docstring for the real incident this
    # guards against.
    subprocess.run(["git", "init", "-q", str(path)], check=True, env=_git_env())
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "t@example.com"], check=True, env=_git_env()
    )
    subprocess.run(["git", "-C", str(path), "config", "user.name", "t"], check=True, env=_git_env())
    (path / "README.md").write_text("hi")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, env=_git_env())
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "init"], check=True, env=_git_env())


def test_run_then_events_smoke(tmp_path):
    db_path = str(tmp_path / "foundry.db")

    run_result = runner.invoke(app, ["run", "tests/fixtures/cli_demo.toml", "--db", db_path])
    assert run_result.exit_code == 0, run_result.output
    run_id = run_result.output.strip()
    assert len(run_id) == 26  # ULID

    events_result = runner.invoke(app, ["events", run_id, "--db", db_path, "--once"])
    assert events_result.exit_code == 0, events_result.output
    assert "unit.closed" in events_result.output


def test_run_reports_incomplete_run_as_failure_not_success(tmp_path):
    # A human_task step with no needs is never processed by dispatch() (M0 only
    # dispatches type=="task" units), so it stays "ready" forever and the run never
    # completes. The CLI must not print the run id as if this succeeded.
    db_path = str(tmp_path / "foundry.db")

    run_result = runner.invoke(app, ["run", "tests/fixtures/stuck_human_task.toml", "--db", db_path])

    assert run_result.exit_code != 0
    assert "pending" in run_result.stderr
    # stdout should not contain what looks like a bare successful run id
    assert run_result.stdout.strip() == ""


def test_run_with_bad_playbook_reports_error_not_traceback(tmp_path):
    db_path = str(tmp_path / "foundry.db")

    run_result = runner.invoke(app, ["run", "tests/fixtures/dangling_needs.toml", "--db", db_path])

    assert run_result.exit_code != 0
    assert "does_not_exist" in run_result.stderr
    assert "Traceback" not in run_result.output


def test_run_auto_approves_gated_steps_for_local_fake_driver_convenience(tmp_path):
    db_path = str(tmp_path / "foundry.db")

    result = runner.invoke(app, ["run", "tests/orchestrator/fixtures/gated_demo.toml", "--db", db_path])

    assert result.exit_code == 0, result.output
    run_id = result.output.strip()
    assert len(run_id) == 26


def test_archive_events_command_runs_without_error(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    archive_dir = str(tmp_path / "archive")
    result = runner.invoke(
        app,
        ["archive-events", "--db", db_path, "--archive-dir", archive_dir, "--older-than-days", "30"],
    )
    assert result.exit_code == 0


def test_run_wires_a_real_worktree_manager_for_writes_true_steps(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_git_repo(repo)
    db_path = str(tmp_path / "foundry.db")

    result = runner.invoke(
        app,
        ["run", "tests/fixtures/writes_demo.toml", "--project-path", str(repo), "--db", db_path],
    )

    assert result.exit_code == 0, result.output
    assert os.path.isdir(repo / ".foundry" / "worktrees")


def test_run_wires_the_default_pack_when_playbook_lives_inside_one(tmp_path):
    db_path = str(tmp_path / "foundry.db")

    result = runner.invoke(
        app,
        ["run", "packs/default/playbooks/sdlc_story.toml", "--db", db_path, "--project-path", "."],
    )

    assert result.exit_code == 0, result.output


def test_demo_seed_command_populates_a_fresh_db(tmp_path):
    db_path = str(tmp_path / "demo.db")
    repos_dir = str(tmp_path / "demo-repos")

    result = runner.invoke(app, ["demo-seed", "--db", db_path, "--repos-dir", repos_dir])

    assert result.exit_code == 0, result.output
    assert "seeded" in result.output.lower()


def test_demo_seed_refuses_to_run_without_an_explicit_db_path():
    result = runner.invoke(app, ["demo-seed"])

    # Typer's own missing-required-option handling is enough here -- no
    # default that could silently point at a real foundry.db.
    assert result.exit_code != 0


async def _count_projects_and_runs(db_path: str) -> tuple[int, int]:
    engine = make_engine(db_path)
    store = Store(engine, make_sessionmaker(engine))
    await store.start()
    projects = await store.list_projects()
    runs = await store.list_runs()
    await store.stop()
    return len(projects), len(runs)


def test_run_accepts_requirement_text(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    result = runner.invoke(
        app,
        [
            "run",
            "tests/fixtures/cli_demo.toml",
            "--db",
            db_path,
            "--requirement-text",
            "Add a login page.",
        ],
    )
    assert result.exit_code == 0, result.output
    run_id = result.output.strip()

    # Verify that requirement_text actually persisted to the Run row
    async def _verify_persistence(db_path: str) -> str | None:
        engine = make_engine(db_path)
        store = Store(engine, make_sessionmaker(engine))
        await store.start()
        run = await store.get_run(run_id)
        await store.stop()
        return run.requirement_text if run else None

    persisted_text = asyncio.run(_verify_persistence(db_path))
    assert persisted_text == "Add a login page."


def test_run_rejects_both_requirement_text_and_requirement_path(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    result = runner.invoke(
        app,
        [
            "run",
            "tests/fixtures/cli_demo.toml",
            "--db",
            db_path,
            "--requirement-text",
            "Add a login page.",
            "--requirement-path",
            "docs/REQUIREMENTS.md",
        ],
    )
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_demo_seed_reset_flag_reseeds_idempotently_instead_of_doubling_rows(tmp_path):
    db_path = str(tmp_path / "demo.db")
    repos_dir = str(tmp_path / "demo-repos")

    first = runner.invoke(app, ["demo-seed", "--db", db_path, "--repos-dir", repos_dir])
    assert first.exit_code == 0, first.output
    first_projects, first_runs = asyncio.run(_count_projects_and_runs(db_path))
    assert first_projects == 5

    # Without --reset, seeding again on the same db file blows up on
    # `projects.name`'s UNIQUE constraint -- confirming the pre-fix bug is
    # even worse than silent row doubling, it's a hard crash.
    second = runner.invoke(app, ["demo-seed", "--db", db_path, "--repos-dir", repos_dir])
    assert second.exit_code != 0

    # --reset wipes the db (and repos dir) first, so this is equivalent to a
    # fresh, first-time seed -- project/run counts match the first seed
    # exactly, not doubled and not left in the crashed second attempt's
    # partial state.
    third = runner.invoke(app, ["demo-seed", "--db", db_path, "--repos-dir", repos_dir, "--reset"])
    assert third.exit_code == 0, third.output
    third_projects, third_runs = asyncio.run(_count_projects_and_runs(db_path))
    assert third_projects == first_projects == 5
    assert third_runs == first_runs
