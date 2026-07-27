import sqlite3

import pytest
import typer

from foundry.cli import _run, _serve


def _write_stale_projects_table(db_path: str) -> None:
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute(
        """
        CREATE TABLE projects (
            id VARCHAR NOT NULL,
            name VARCHAR NOT NULL,
            path VARCHAR NOT NULL,
            kg_status VARCHAR NOT NULL,
            status VARCHAR NOT NULL,
            created_at DATETIME NOT NULL,
            PRIMARY KEY (id),
            UNIQUE (name)
        )
        """
    )
    raw_conn.commit()
    raw_conn.close()


@pytest.mark.asyncio
async def test_run_command_exits_cleanly_on_schema_drift(tmp_path):
    db_path = str(tmp_path / "stale.db")
    _write_stale_projects_table(db_path)

    fixture = "tests/orchestrator/fixtures/linear_demo.toml"
    with pytest.raises(typer.Exit) as exc_info:
        await _run(fixture, ".", db_path, "fake")

    assert exc_info.value.exit_code == 1


@pytest.mark.asyncio
async def test_serve_exits_cleanly_on_schema_drift(tmp_path):
    db_path = str(tmp_path / "stale.db")
    _write_stale_projects_table(db_path)

    with pytest.raises(typer.Exit) as exc_info:
        await _serve(db_path, "127.0.0.1", 0)

    assert exc_info.value.exit_code == 1
