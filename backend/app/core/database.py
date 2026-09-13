import logging
from pathlib import Path
from typing import Generator
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker, Session
from app.core.config import settings

from sqlalchemy import create_engine, event

logger = logging.getLogger(__name__)


def _ensure_sqlite_directory(db_url: str) -> None:
    """Ensure parent directory exists for SQLite database file."""
    if db_url.startswith("sqlite:///"):
        db_path_str = db_url.replace("sqlite:///", "", 1)
        db_path = Path(db_path_str)
        if db_path.parent:
            db_path.parent.mkdir(parents=True, exist_ok=True)


# Ensure database directory exists before engine initialization
_ensure_sqlite_directory(settings.DATABASE_URL)

# Configure engine for SQLite multithreaded operation & WAL concurrency
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    connect_args["timeout"] = 30  # 30-second busy timeout for acquiring locks

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=settings.DEBUG,
)


@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """Enable WAL journal mode and busy_timeout pragma for SQLite connections."""
    if settings.DATABASE_URL.startswith("sqlite"):
        try:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=30000;")
            cursor.close()
        except Exception as exc:
            logger.warning("Could not set SQLite WAL/busy_timeout pragma: %s", exc)


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


class Base(DeclarativeBase):
    """Declarative base class for SQLAlchemy models."""
    pass


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding database sessions."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _migrate_sqlite_columns() -> None:
    """Inspect SQLite database and safely add any missing columns declared in SQLAlchemy models."""
    if not str(engine.url).startswith("sqlite"):
        return
    try:
        from sqlalchemy import inspect, text
        inspector = inspect(engine)
        existing_tables = inspector.get_table_names()
        with engine.begin() as conn:
            for table_name, table in Base.metadata.tables.items():
                if table_name in existing_tables:
                    existing_cols = {col["name"] for col in inspector.get_columns(table_name)}
                    for col in table.columns:
                        if col.name not in existing_cols:
                            col_type = col.type.compile(engine.dialect)
                            sql = f'ALTER TABLE "{table_name}" ADD COLUMN "{col.name}" {col_type}'
                            logger.info("Auto-migrating SQLite column: %s.%s (%s)", table_name, col.name, col_type)
                            conn.execute(text(sql))
    except Exception as exc:
        logger.warning("SQLite auto-migration encountered error: %s", exc)


def init_db() -> None:
    """Initialize database schemas and tables."""
    _ensure_sqlite_directory(settings.DATABASE_URL)
    import app.models  # noqa: F401 - ensure models are registered
    Base.metadata.create_all(bind=engine)
    _migrate_sqlite_columns()
    logger.info("Database initialized")
