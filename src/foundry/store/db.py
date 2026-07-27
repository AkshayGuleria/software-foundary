from __future__ import annotations

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from foundry.store.models import Base


class SchemaDriftError(Exception):
    """Raised when an existing db file's tables are missing columns the
    current SQLAlchemy models declare.

    `Base.metadata.create_all` only creates missing *tables* -- it never
    adds missing *columns* to a table that already exists. A db file
    created before a later model change (e.g. a new column added to
    `Project`) stays permanently out of date until this is caught. There
    is no migration tooling yet (see docs/design-deviations.md's D1,
    deliberately deferred to M5) -- this exists to make that failure
    mode a clear message instead of a cryptic `sqlite3.OperationalError:
    no such column` surfacing later from an unrelated query.
    """


def make_engine(db_path: str) -> AsyncEngine:
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)

    @event.listens_for(engine.sync_engine, "connect")
    def _set_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _find_schema_drift(sync_conn) -> list[str]:
    inspector = inspect(sync_conn)
    existing_tables = set(inspector.get_table_names())
    missing: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            continue  # create_all just created it fresh -- can't be missing columns
        actual_columns = {col["name"] for col in inspector.get_columns(table_name)}
        for column in table.columns:
            if column.name not in actual_columns:
                missing.append(f"{table_name}.{column.name}")
    return missing


async def init_db(engine: AsyncEngine, db_path: str | None = None) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        missing = await conn.run_sync(_find_schema_drift)
    if missing:
        raise SchemaDriftError(
            f"Schema drift in {db_path or '<unknown>'}: {', '.join(missing)} missing. "
            "Delete the db file and restart, or add the missing columns "
            "manually (no migration tooling yet)."
        )


def make_sessionmaker(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(engine, expire_on_commit=False)
