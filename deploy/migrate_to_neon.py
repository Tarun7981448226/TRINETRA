"""ONE-TIME: copy TRINETRA's memory from the local SQLite file into Postgres (Neon).

    ../.venv/bin/python deploy/migrate_to_neon.py "postgresql://...neon.tech/trinetra?sslmode=require"

Copies every table (conversations, memories, timetable, events, emotions, neural core, push devices),
then fixes Postgres id counters. Refuses to run if the target already has conversations, so it can't
clobber the cloud copy by accident.
"""
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import func, insert, select, text  # noqa: E402

from app.db.models import Base, Message  # noqa: E402
from app.db.session import init_db, make_engine  # noqa: E402


def main(target_url: str, source: Path = ROOT / "trinetra.db") -> None:
    src = make_engine(f"sqlite:///{source}")
    dst = make_engine(target_url)
    init_db(dst)
    with dst.connect() as conn:
        if conn.execute(select(func.count()).select_from(Message)).scalar():
            sys.exit("Target already has conversations — refusing to overwrite. (Empty it first if you mean it.)")

    # Snapshot first so a running local server can't change rows mid-copy.
    snap = source.with_suffix(".migrate.db")
    with sqlite3.connect(source) as s, sqlite3.connect(snap) as d:
        s.backup(d)
    src = make_engine(f"sqlite:///{snap}")

    with src.connect() as read, dst.begin() as write:
        for table in Base.metadata.sorted_tables:  # parents before children (goals before tasks)
            rows = [dict(r._mapping) for r in read.execute(select(table))]
            if rows:
                write.execute(insert(table), rows)
            if "id" in table.c and rows and write.dialect.name == "postgresql":
                write.execute(text(
                    f"SELECT setval(pg_get_serial_sequence('{table.name}', 'id'), (SELECT MAX(id) FROM {table.name}))"
                ))
            print(f"  {table.name:20s} {len(rows):6d} rows")
    snap.unlink()
    print("✅ TRINETRA's memory is in Postgres.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
