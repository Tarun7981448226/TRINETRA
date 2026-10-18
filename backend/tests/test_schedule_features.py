import asyncio
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select

from app.core import deliberation, scheduler, timetable
from app.core.timeutil import local, now_local
from app.db.models import Goal, Milestone, Task


def test_routine_stops_on_its_until_date(client):
    start = now_local().date()
    until = start + timedelta(days=4)
    with client.session_factory() as db:
        created = timetable.create_block(db, "NumPy", start, time(20, 45), time(21, 45), recurrence="daily", until=until)
        assert len(created) == 5 and max(local(t.planned_start).date() for t in created) == until
        assert timetable.extend_series(db, horizon_days=30) == 0  # never grows past `until`


def test_until_flows_through_planner_ops(client):
    start = now_local().date() + timedelta(days=1)
    op = {"op": "create", "title": "570 study", "date": start.isoformat(), "start": "17:00", "duration_min": 120,
          "recurrence": "daily", "until": (start + timedelta(days=2)).isoformat(), "notify": "full"}
    with client.session_factory() as db:
        assert len(deliberation.build(db, [op]).slots) == 3
        deliberation.apply(db, [op])
        assert db.query(Task).count() == 3


def test_quiet_blocks_never_ping(client, llm_calls):
    s = datetime(2026, 10, 20, 19, 0, tzinfo=timezone.utc)
    with client.session_factory() as db:
        for title, notify in (("Lunch", "none"), ("Gym", "remind"), ("DSA", "full")):
            db.add(Task(title=title, planned_start=s, planned_end=s + timedelta(minutes=45), notify=notify))
        db.commit()
        core = client.app.state.orchestrator
        due = asyncio.run(scheduler.tick(db, core, s - timedelta(minutes=2)))
        ended = asyncio.run(scheduler.tick(db, core, s + timedelta(minutes=46)))
        ids = {t.title: t.id for t in db.scalars(select(Task))}
    assert sorted(due) == sorted([f"task.due:{ids['Gym']}", f"task.due:{ids['DSA']}"])
    assert ended == [f"task.ending:{ids['DSA']}"]


def test_roadmap_dependencies_come_back_from_the_api(client):
    with client.session_factory() as db:
        g = Goal(title="DSA")
        a, b = Milestone(title="Arrays", position=0), Milestone(title="Two Pointers", position=1)
        g.milestones += [a, b]
        db.add(g)
        db.flush()
        b.depends_on = [a.id]
        db.commit()
    [goal] = client.get("/goals").json()
    deps = {m["title"]: m["depends_on"] for m in goal["milestones"]}
    assert deps == {"Arrays": [], "Two Pointers": [deps and goal["milestones"][0]["id"]]}


def test_sleep_shows_on_the_timetable_and_moves_with_the_window(client):
    with client.session_factory() as db:
        deliberation.apply(db, [{"op": "set_sleep", "start": "00:00", "end": "06:00"}])
        sleeps = db.scalars(select(Task).where(Task.category == "sleep").order_by(Task.planned_start)).all()
        assert len(sleeps) >= 13 and all(t.notify == "remind" for t in sleeps)
        assert (local(sleeps[0].planned_start).time(), local(sleeps[0].planned_end).time()) == (time(0), time(6))
        deliberation.apply(db, [{"op": "set_sleep", "start": "23:30", "end": "06:30"}])
        sleeps = db.scalars(select(Task).where(Task.category == "sleep")).all()
        assert {local(t.planned_start).time() for t in sleeps} == {time(23, 30)}
        assert all((t.planned_end - t.planned_start) == timedelta(hours=7) for t in sleeps)


def test_bedtime_reminder_is_spoken_but_never_nags(client, llm_calls):
    s = datetime(2026, 10, 20, 18, 30, tzinfo=timezone.utc)  # midnight in the test timezone
    with client.session_factory() as db:
        db.add(Task(title="Sleep — rest up", category="sleep", planned_start=s, planned_end=s + timedelta(hours=6),
                    notify="remind"))
        db.commit()
        core = client.app.state.orchestrator
        fired = asyncio.run(scheduler.tick(db, core, s - timedelta(minutes=2)))
        later = asyncio.run(scheduler.tick(db, core, s + timedelta(minutes=20)))
    assert len(fired) == 1 and fired[0].startswith("task.due") and later == []
    assert any("bedtime" in c["messages"][-1]["content"] for c in llm_calls)


def test_a_day_review_missed_by_midnight_still_happens(client, llm_calls, monkeypatch):
    """Cron hiccup 23:50–00:10: yesterday's review runs just after midnight instead of being lost."""
    import asyncio
    from datetime import datetime, time as dtime, timedelta
    from app.core import scheduler
    from app.core.timeutil import user_tz
    from app.db.models import KeyValue
    just_after = datetime.combine(datetime.now(user_tz()).date(), dtime(0, 10), user_tz())
    monkeypatch.setattr(scheduler, "now_local", lambda: just_after)
    with client.session_factory() as db:
        assert asyncio.run(scheduler.plan_tomorrow(db, client.app.state.orchestrator)) is True
        yesterday = (just_after.date() - timedelta(days=1)).isoformat()
        assert db.get(KeyValue, f"planned:{yesterday}") is not None
        assert asyncio.run(scheduler.plan_tomorrow(db, client.app.state.orchestrator)) is False  # once
