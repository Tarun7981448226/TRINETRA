import time
from collections.abc import Iterator
from contextvars import ContextVar

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool, StaticPool

from app.config import get_settings
from app.db.models import Base


def make_engine(url: str):
    # Neon / Vercel hand out "postgres://" or "postgresql://"; use the psycopg 3 driver either way.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix):]
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool
        return create_engine(url, **kwargs)
    # Serverless: every invocation may be a fresh process, so don't hold pooled connections open
    # (Neon's own pooler does the pooling).
    return create_engine(url, poolclass=NullPool)


engine = make_engine(get_settings().database_url)

# How many new database connections this request opened, and the time spent opening them (the Server-Timing header).
connects: ContextVar[list | None] = ContextVar("connects", default=None)


@event.listens_for(engine, "do_connect")
def _connect_started(dialect, conn_rec, cargs, cparams):
    conn_rec.info["t0"] = time.perf_counter()


@event.listens_for(engine, "connect")
def _connected(dbapi_conn, conn_rec):
    if (log := connects.get()) is not None:
        log.append(time.perf_counter() - conn_rec.info.pop("t0", time.perf_counter()))
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db(bind=None) -> None:
    bind = bind or engine
    Base.metadata.create_all(bind=bind)
    _add_missing_columns(bind)


def _add_missing_columns(bind) -> None:
    """Tiny forward-only migration: new model columns get added to existing tables,
    so TRINETRA's memory survives upgrades. (Alembic takes over once we're on Postgres.)"""
    insp = inspect(bind)
    with bind.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in existing:
                    ddl = col.type.compile(dialect=bind.dialect)
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" {ddl}'))


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
