from typer.testing import CliRunner

from foundry.cli import app

runner = CliRunner()


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
