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
