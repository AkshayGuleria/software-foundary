import pytest

from foundry.store.db import SchemaDriftError, init_db, make_engine, make_sessionmaker
from foundry.store.models import Project


@pytest.mark.asyncio
async def test_init_db_creates_tables_and_roundtrips_a_row(tmp_path):
    db_path = str(tmp_path / "foundry.db")
    engine = make_engine(db_path)
    await init_db(engine)
    sessionmaker = make_sessionmaker(engine)

    async with sessionmaker() as session:
        session.add(Project(name="demo", path="/tmp/demo"))
        await session.commit()

    async with sessionmaker() as session:
        from sqlalchemy import select

        result = await session.execute(select(Project).where(Project.name == "demo"))
        project = result.scalar_one()
        assert project.path == "/tmp/demo"
        assert len(project.id) == 26  # ULID length
        assert project.created_at.tzinfo is not None  # tz-aware round-trip


@pytest.mark.asyncio
async def test_init_db_raises_schema_drift_error_for_a_table_missing_columns(tmp_path):
    import sqlite3

    db_path = str(tmp_path / "stale.db")
    # Hand-craft a `projects` table matching the OLD schema (pre-G4 --
    # missing default_driver/default_token_budget/default_playbook_path),
    # bypassing create_all entirely so it's NOT the current shape -- this
    # simulates exactly the real incident: a db file whose table already
    # exists, just with fewer columns than the current model declares.
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

    engine = make_engine(db_path)

    with pytest.raises(SchemaDriftError) as exc_info:
        await init_db(engine, db_path)

    message = str(exc_info.value)
    assert "projects.default_driver" in message
    assert "projects.default_token_budget" in message
    assert "projects.default_playbook_path" in message
    assert db_path in message


@pytest.mark.asyncio
async def test_init_db_does_not_raise_on_a_second_call_against_an_up_to_date_db(tmp_path):
    db_path = str(tmp_path / "current.db")
    engine = make_engine(db_path)

    await init_db(engine, db_path)
    # Second call against the same, now-existing, fully-current db --
    # every table already exists with every column the model declares.
    # This must NOT raise: the check only flags MISSING columns, it
    # should never flag a table that's already fully up to date.
    await init_db(engine, db_path)
