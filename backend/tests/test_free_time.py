import asyncio
from datetime import date, datetime, time, timedelta

from sqlalchemy import select

from app.core import push, scheduler, timetable
from app.core.timeutil import to_utc, user_tz
from app.db.models import Message, TaskStatus

DAY = date(2026, 10, 20)


def at(hh: int, mm: int = 0) -> datetime:
    return to_utc(datetime.combine(DAY, time(hh, mm), user_tz()))


def run_minutes(client, start: datetime, end: datetime) -> list[str]:
    """Run the free-time watcher once a minute; returns the local times it asked."""
    asked = []
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        t = start
        while t <= end:
            if asyncio.run(scheduler.free_watch(db, core, t)):
                asked.append(f"{t.astimezone(user_tz()):%H:%M}")
            db.commit()
            t += timedelta(minutes=1)
    return asked


def test_asks_every_30_minutes_in_a_free_gap(client, llm_calls, monkeypatch):
    pushed = []
    monkeypatch.setattr(push, "send", lambda *a, **k: pushed.append(a[2]) or 1)
    with client.session_factory() as db:
        timetable.create_block(db, "TUF DSA", DAY, time(10), time(11))
        timetable.create_block(db, "ML lectures", DAY, time(13), time(14))
        db.commit()
    asked = run_minutes(client, at(10), at(14, 30))
    # 10–11 busy · 11:00–11:10 leaves room for "how did it go?" · quiet in the last 10 min before ML · 13–14 busy
    assert asked == ["11:10", "11:40", "12:10", "12:40", "14:10"]
    with client.session_factory() as db:
        msgs = db.scalars(select(Message).where(Message.channel == "reminder")).all()
    assert len(msgs) == 5 and all(m.meta["kind"] == "free_checkin" for m in msgs)
    assert msgs[0].meta["next"] == "ML lectures" and len(pushed) == 5


def test_short_gaps_and_sleep_are_left_alone(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    with client.session_factory() as db:
        timetable.create_block(db, "TUF DSA", DAY, time(10), time(11))
        timetable.create_block(db, "Lunch", DAY, time(11, 20), time(12), notify="none")  # a 20-minute gap
        timetable.create_block(db, "ML lectures", DAY, time(12), time(23, 0))
        db.commit()
    assert run_minutes(client, at(10), at(23, 0)) == []  # short gap; meals count as busy
    assert run_minutes(client, at(23, 30), at(23, 59)) == []  # winding down for bed
    assert run_minutes(client, at(3), at(5, 59)) == []  # before wake-up time


def test_skipped_block_becomes_free_time(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    with client.session_factory() as db:
        timetable.create_block(db, "TUF DSA", DAY, time(6), time(10))
        [ml] = timetable.create_block(db, "ML lectures", DAY, time(10), time(12))
        timetable.create_block(db, "Lunch", DAY, time(12), time(13), notify="none")
        ml.status = TaskStatus.SKIPPED
        db.commit()
    assert run_minutes(client, at(10), at(11, 59)) == ["10:10", "10:40", "11:10", "11:40"]
