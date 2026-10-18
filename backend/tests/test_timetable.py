import json
from datetime import date, datetime, time, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core import llm, scheduler, timetable
from app.core.timeutil import local, now_local, to_utc
from app.db.models import Message, Task


def test_parse_recurrence():
    assert timetable.parse_recurrence("weekdays") == {0, 1, 2, 3, 4}
    assert timetable.parse_recurrence("daily") == set(range(7))
    assert timetable.parse_recurrence("Mon, Wed,fri") == {0, 2, 4}
    assert timetable.parse_recurrence("whenever") is None
    assert timetable.parse_recurrence(None) is None


def test_weekday_routine_materialises_two_weeks(client):
    with client.session_factory() as db:
        monday = date(2026, 10, 19)
        created = timetable.create_block(db, "Gym", monday, time(6), time(7), recurrence="weekdays")
        assert len(created) == 10
        assert {local(t.planned_start).weekday() for t in created} == {0, 1, 2, 3, 4}
        assert all(local(t.planned_start).time() == time(6) for t in created)
        assert len({t.series_id for t in created}) == 1


def test_block_crossing_midnight(client):
    with client.session_factory() as db:
        [t] = timetable.create_block(db, "Late study", date(2026, 10, 19), time(23), time(1))
        assert local(t.planned_end) - local(t.planned_start) == timedelta(hours=2)


def test_routines_are_topped_up(client):
    with client.session_factory() as db:
        timetable.create_block(db, "Read", now_local().date() - timedelta(days=10), time(21), time(21, 30),
                               recurrence="daily")
        added = timetable.extend_series(db)
        assert added == 10
        latest = max(local(t.planned_start).date() for t in db.scalars(select(Task)))
        assert latest == now_local().date() + timedelta(days=timetable.SERIES_HORIZON_DAYS - 1)
        assert timetable.extend_series(db) == 0  # idempotent


def test_moving_one_block_doesnt_move_the_routine(client):
    """Review bug: the newest occurrence was the template, so moving that one block moved every future one."""
    with client.session_factory() as db:
        timetable.create_block(db, "Read", now_local().date() - timedelta(days=3), time(21), time(21, 30), recurrence="daily")
        timetable.extend_series(db)
        last = max(db.scalars(select(Task)), key=lambda t: t.planned_start)
        s = local(last.planned_start).replace(hour=7)
        timetable.move(last, s, s + timedelta(minutes=30))  # a one-off
        db.commit()
        db.expire_all()
        # pretend a day passed: the horizon grows by one day
        from unittest.mock import patch
        tomorrow = now_local() + timedelta(days=1)
        with patch("app.core.timetable.now_local", lambda: tomorrow):
            assert timetable.extend_series(db) == 1
        db.commit()
        db.expire_all()
        newest = max(db.scalars(select(Task)), key=lambda t: local(t.planned_start))
        assert local(newest.planned_start).time() == time(21)  # the routine's usual time, not the one-off 07:00


@pytest.fixture
def builder_llm(monkeypatch):
    """LLM stub: the timetable builder gets `ops`, everyone else gets a plain reply."""
    state = {"ops": [], "prompts": []}

    async def fake(messages, tier="smart", json_mode=False, **kw):
        state["prompts"].append(messages[0]["content"])
        if json_mode and "timetable" in messages[0]["content"]:
            return json.dumps({"ops": state["ops"]})
        if json_mode:
            return json.dumps({"facts": []})
        return "Done. Your routine is set."

    monkeypatch.setattr(llm, "complete", fake)
    return state


def test_talking_creates_routine_and_core_confirms(client, builder_llm):
    tomorrow = (now_local() + timedelta(days=1)).date().isoformat()
    builder_llm["ops"] = [{"op": "create", "title": "Gym", "date": tomorrow, "start": "06:00", "end": None,
                           "duration_min": 45, "recurrence": "weekdays", "category": "fitness", "priority": 4}]
    body = client.post("/chat", json={"text": "gym at 6am every weekday, 45 minutes"}).json()
    assert body["ran"].index("timetable_builder") < body["ran"].index("core_orchestrator")
    [change] = body["notes"]["timetable_changes"]
    assert "Gym" in change and "repeats weekdays" in change
    core_prompt = [p for p in builder_llm["prompts"] if "You are TRINETRA" in p][-1]
    assert "You JUST made these timetable changes" in core_prompt

    days = client.get("/today?days=14").json()
    assert days and all(d["start"] == "06:00" and d["end"] == "06:45" for d in days)


def test_builder_moves_deletes_and_ignores_bad_ids(client, builder_llm):
    start = now_local().replace(hour=20, minute=0, second=0, microsecond=0) + timedelta(days=1)
    task = client.post("/tasks", json={"title": "DSA", "planned_start": start.isoformat(),
                                       "planned_end": (start + timedelta(hours=1)).isoformat()}).json()
    builder_llm["ops"] = [{"op": "move", "id": task["id"], "date": start.date().isoformat(), "start": "21:30"},
                          {"op": "delete", "id": 9999}]
    body = client.post("/chat", json={"text": "move DSA to 9:30 tonight"}).json()
    assert len(body["notes"]["timetable_changes"]) == 1
    [moved] = client.get("/today?days=3").json()
    assert (moved["start"], moved["end"]) == ("21:30", "22:30")

    builder_llm["ops"] = [{"op": "delete", "id": task["id"]}]
    client.post("/chat", json={"text": "cancel DSA tomorrow"})
    assert client.get("/today?days=3").json() == []


def test_small_talk_costs_no_planning_call(client, builder_llm):
    body = client.post("/chat", json={"text": "how are you doing?"}).json()
    assert "timetable_builder" in body["ran"]
    assert not any("timetable" in p and "Operations" in p for p in builder_llm["prompts"])


async def _tick(client, now):
    with client.session_factory() as db:
        return await scheduler.tick(db, client.app.state.orchestrator, now)


def test_heartbeat_reminds_then_checks_in_exactly_once(client, llm_calls):
    import asyncio

    start = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    task = client.post("/tasks", json={"title": "Study", "planned_start": start.isoformat(),
                                       "planned_end": (start + timedelta(hours=1)).isoformat()}).json()

    assert asyncio.run(_tick(client, start - timedelta(minutes=10))) == []
    assert asyncio.run(_tick(client, start - timedelta(minutes=4))) == [f"task.due:{task['id']}"]
    assert asyncio.run(_tick(client, start)) == []  # not twice
    assert asyncio.run(_tick(client, start + timedelta(hours=1, seconds=5))) == [f"task.ending:{task['id']}"]
    assert asyncio.run(_tick(client, start + timedelta(hours=1, minutes=1))) == []

    msgs = client.get("/messages").json()
    kinds = [m["meta"]["kind"] for m in msgs if m["meta"]]
    assert kinds == ["reminder", "checkin"]
    assert msgs[-1]["meta"]["buttons"] == ["done", "partly", "skipped"]


def test_old_blocks_dont_spam_after_downtime(client, llm_calls):
    import asyncio

    start = datetime(2026, 10, 20, 8, 0, tzinfo=timezone.utc)
    client.post("/tasks", json={"title": "Old", "planned_start": start.isoformat(),
                                "planned_end": (start + timedelta(hours=1)).isoformat()})
    assert asyncio.run(_tick(client, start + timedelta(days=1))) == []


def test_buttons_update_task_and_trinetra_reacts(client, llm_calls):
    start = now_local() + timedelta(hours=2)
    task = client.post("/tasks", json={"title": "DSA practice", "planned_start": start.isoformat(),
                                       "planned_end": (start + timedelta(hours=1)).isoformat()}).json()

    body = client.post(f"/tasks/{task['id']}/respond", json={"action": "snooze"}).json()
    [moved] = client.get("/today?days=2").json()
    assert moved["start"] == f"{start + timedelta(minutes=10):%H:%M}"

    body = client.post(f"/tasks/{task['id']}/respond", json={"action": "skip"}).json()
    assert "firm" in body["mood"]
    body = client.post(f"/tasks/{task['id']}/respond", json={"action": "done"}).json()
    assert body["mood"].startswith(("upbeat", "proud"))
    with client.session_factory() as db:
        t = db.get(Task, task["id"])
        assert t.status == "done" and t.actual_end is not None
    assert client.post(f"/tasks/{task['id']}/respond", json={"action": "explode"}).status_code == 422


def test_answered_buttons_are_remembered(client, llm_calls):
    import asyncio

    start = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    task = client.post("/tasks", json={"title": "Run", "planned_start": start.isoformat(),
                                       "planned_end": (start + timedelta(minutes=30)).isoformat()}).json()
    asyncio.run(_tick(client, start - timedelta(minutes=1)))
    client.post(f"/tasks/{task['id']}/respond", json={"action": "start"})
    reminder = next(m for m in client.get("/messages").json() if m["meta"])
    assert reminder["meta"]["answered"] == "start"


def test_his_exact_time_beats_a_misread():
    """The model once read '12:30 am' as 23:30: when he said one exact time, the single timed change uses it."""
    from app.agents.planning import _keep_his_time, said_times
    assert said_times("bed by 12:30 am, gym 7pm, class at 18:45, lunch 12pm") == ["00:30", "19:00", "18:45", "12:00"]
    assert _keep_his_time("Go to bed by 12:30 am", [{"op": "set_sleep", "start": "23:30", "end": "06:00"}])[0]["start"] == "00:30"
    two = [{"op": "move", "id": 1, "start": "19:00"}]
    assert _keep_his_time("move gym from 6pm to 7pm", two)[0]["start"] == "19:00"  # two times said: trust the model
    night = [{"op": "move", "id": 1, "start": "21:30"}]
    assert _keep_his_time("move DSA to 9:30 tonight", night)[0]["start"] == "21:30"  # a bare 9:30 is ambiguous
