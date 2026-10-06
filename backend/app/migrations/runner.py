import hashlib
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

MIGRATIONS_DIR = Path(__file__).parent
MIGRATION_LOCK = "provision_manager_migrations"
MIGRATION_LOCK_TIMEOUT_SECONDS = 30


async def run_migrations(engine: AsyncEngine) -> None:
    """Apply pending migrations and reject modified applied migrations."""
    async with engine.connect() as connection:
        await _acquire_lock(connection)
        try:
            await _ensure_migrations_table(connection)
            for migration_file in _migration_files():
                await _apply_migration(connection, migration_file)
        finally:
            await connection.execute(
                text("SELECT RELEASE_LOCK(:lock_name)"),
                {"lock_name": MIGRATION_LOCK},
            )


async def _acquire_lock(connection: AsyncConnection) -> None:
    result = await connection.execute(
        text("SELECT GET_LOCK(:lock_name, :timeout)"),
        {
            "lock_name": MIGRATION_LOCK,
            "timeout": MIGRATION_LOCK_TIMEOUT_SECONDS,
        },
    )
    if result.scalar_one() != 1:
        raise RuntimeError("Could not acquire the database migration lock")


async def _ensure_migrations_table(connection: AsyncConnection) -> None:
    await connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version VARCHAR(255) PRIMARY KEY,
                checksum CHAR(64) NOT NULL,
                applied_at DATETIME NOT NULL
            )
            """
        )
    )
    await connection.commit()


def _migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


async def _apply_migration(
    connection: AsyncConnection,
    migration_file: Path,
) -> None:
    sql = migration_file.read_text(encoding="utf-8").strip()
    if not sql:
        return

    version = migration_file.name
    checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
    applied_checksum = await _get_applied_checksum(connection, version)

    if applied_checksum is not None:
        if applied_checksum != checksum:
            raise RuntimeError(
                f"Migration {version} was modified after being applied"
            )
        return

    for statement in _split_statements(sql):
        await connection.execute(text(statement))

    await connection.execute(
        text(
            """
            INSERT INTO schema_migrations (version, checksum, applied_at)
            VALUES (:version, :checksum, NOW())
            """
        ),
        {"version": version, "checksum": checksum},
    )
    await connection.commit()


async def _get_applied_checksum(
    connection: AsyncConnection,
    version: str,
) -> str | None:
    result = await connection.execute(
        text(
            """
            SELECT checksum
            FROM schema_migrations
            WHERE version = :version
            """
        ),
        {"version": version},
    )
    return result.scalar_one_or_none()


def _split_statements(sql: str) -> list[str]:
    return [
        statement.strip()
        for statement in sql.split(";")
        if statement.strip()
    ]
