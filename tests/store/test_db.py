import pytest

from foundry.store.db import init_db, make_engine, make_sessionmaker
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
