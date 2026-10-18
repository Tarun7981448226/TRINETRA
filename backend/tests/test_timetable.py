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


def test_the_day_he_named_wins(client, builder_llm):
    """Seen live: 'push my dsa to 10pm tmrw' on a Sunday moved Tuesday's copy. The block on the day he said is moved."""
    today = now_local().date()
    timetable_ids = {}
    with client.session_factory() as db:
        timetable.create_block(db, "TUF DSA", today, time(21), time(22), recurrence="daily")
        db.commit()
        for t in db.scalars(select(Task)):
            timetable_ids[local(t.planned_start).date()] = t.id
    wrong = timetable_ids[today + timedelta(days=2)]
    builder_llm["ops"] = [{"op": "move", "id": wrong, "date": (today + timedelta(days=2)).isoformat(), "start": "22:00"}]
    client.post("/chat", json={"text": "cn u push my dsa to 10pm tmrw"})
    with client.session_factory() as db:
        moved = db.get(Task, timetable_ids[today + timedelta(days=1)])
        assert local(moved.planned_start).time() == time(22)
        assert local(db.get(Task, wrong).planned_start).time() == time(21)  # the other day's copy is untouched


def test_naming_a_day_never_wipes_the_whole_routine(client, builder_llm):
    """Seen live: 'free up my evening tomorrow' deleted the whole Gym routine. Only tomorrow's block goes."""
    today = now_local().date()
    with client.session_factory() as db:
        timetable.create_block(db, "Gym", today, time(18), time(19), recurrence="daily")
        db.commit()
        ids = {local(t.planned_start).date(): t.id for t in db.scalars(select(Task))}
    builder_llm["ops"] = [{"op": "delete", "id": ids[today + timedelta(days=3)], "whole_series": True}]
    client.post("/chat", json={"text": "free up my evening tomorrow"})
    with client.session_factory() as db:
        left = {local(t.planned_start).date() for t in db.scalars(select(Task))}
    assert today + timedelta(days=1) not in left  # tomorrow's block is gone
    assert today + timedelta(days=3) in left and len(left) >= 10  # the routine stays


def test_tomorrow_is_in_view(client, llm_calls):
    from tests.conftest import trinetra_prompt
    with client.session_factory() as db:
        timetable.create_block(db, "Gym", now_local().date() + timedelta(days=1), time(18), time(19))
        db.commit()
    client.post("/chat", json={"text": "what's on tomorrow?"})
    assert "Tomorrow's timetable:\n- 18:00–19:00 Gym" in trinetra_prompt(llm_calls)


def test_the_confirmation_matches_what_really_changed():
    from app.agents.command import _true_to_changes
    ch = ["moved to #1 Mon 19 Oct 21:00–22:00 Gym [planned, repeats weekdays]",
          "moved to #13 Mon 19 Oct 18:00–19:00 TUF DSA [planned, repeats daily]"]
    assert _true_to_changes("Swapped them—Gym now 18:00–19:00 tomorrow.", ch) == \
        "Swapped them—Gym now 18:00–19:00 tomorrow. (Exact: Gym 21:00–22:00; TUF DSA 18:00–19:00.)"
    for ok in ("Swapped—gym is at 9 pm now and DSA at 6 pm.", "Swapped: gym 21:00, DSA 18:00.", "Swapped them, all set.",
               "Done, DSA at 6.", "Done. Gym 9–10 pm tomorrow.", "DSA for 2 hours from 6 pm", "Gym moved to 9:00 pm",
               "Done—Gym’s set for 9\u202fpm tomorrow."):
        assert _true_to_changes(ok, ch) == ok, ok


def test_guards_never_damage_a_correct_plan():
    """Third review: the guards themselves must never turn a right change into a wrong one."""
    from app.agents.planning import _keep_his_time, said_day
    cases = [  # (text, model's correct op) → must stay exactly as the model had it
        ("gym 6-7pm tomorrow", {"op": "create", "start": "18:00", "end": "19:00"}),
        ("dsa from 9 to 11pm", {"op": "create", "start": "21:00", "end": "23:00"}),
        ("study till 7pm", {"op": "create", "start": "17:00", "end": "19:00"}),
        ("move gym from 6pm to 7", {"op": "move", "id": 1, "start": "19:00"}),
        ("I'm busy at 5pm so move gym to 6", {"op": "move", "id": 1, "start": "18:00"}),
        ("from now on I wake up at 6am", {"op": "set_sleep", "start": "23:30", "end": "06:00"}),
        ("finish the essay by 7pm", {"op": "create", "start": "17:00", "end": "19:00"}),
    ]
    for text, op in cases:
        assert _keep_his_time(text, [dict(op)]) == [op], text
    fixed = _keep_his_time("Go to bed by 12:30 am", [{"op": "set_sleep", "start": "23:30", "end": "06:00"}])[0]
    assert (fixed["start"], fixed["end"]) == ("00:30", "06:00")
    moved = _keep_his_time("gym at 7pm tomorrow", [{"op": "create", "start": "18:00", "end": "19:00"}])[0]
    assert (moved["start"], moved["end"]) == ("19:00", "20:00")  # the length is kept
    assert said_day("add reading at 12:30 am tonight") == now_local().date() + timedelta(days=1)


def test_the_destination_day_is_not_retargeted(client, builder_llm):
    """'can't make gym, do it tomorrow at 7am instead': today's block is the one that moves."""
    today = now_local().date()
    with client.session_factory() as db:
        timetable.create_block(db, "Gym", today, time(23), time(23, 30), recurrence="daily")
        db.commit()
        ids = {local(t.planned_start).date(): t.id for t in db.scalars(select(Task))}
    builder_llm["ops"] = [{"op": "move", "id": ids[today], "date": (today + timedelta(days=1)).isoformat(), "start": "07:00"}]
    client.post("/chat", json={"text": "can't make gym, do it tomorrow at 7am instead"})
    with client.session_factory() as db:
        assert local(db.get(Task, ids[today]).planned_start).date() == today + timedelta(days=1)
        assert local(db.get(Task, ids[today + timedelta(days=1)]).planned_start).time() == time(23)


def test_everyday_all_doesnt_wipe_routines():
    from app.agents.planning import _no_surprise_wipes
    ops = _no_surprise_wipes("cancel all my plans tomorrow", [{"op": "delete", "id": 1, "whole_series": True}])
    assert ops[0]["whole_series"] is False
    ops = _no_surprise_wipes("move all my gym sessions to 7am", [{"op": "delete", "id": 1, "whole_series": True}])
    assert ops[0]["whole_series"] is True
