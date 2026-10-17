import json
from datetime import timedelta

import pytest

from app.core import deliberation, llm
from app.core.timeutil import now_local
from app.db.models import KeyValue


@pytest.fixture
def board(monkeypatch):
    """LLM stub: the Planner returns `ops`, the Critic returns `critic` (or junk)."""
    state = {"ops": [], "critic": None, "critic_calls": 0}

    async def fake(messages, tier="smart", json_mode=False, **kw):
        sys_prompt = messages[0]["content"]
        if "You manage a personal timetable" in sys_prompt:
            return json.dumps({"ops": state["ops"]})
        if "You are TRINETRA's Critic" in sys_prompt:
            state["critic_calls"] += 1
            return json.dumps(state["critic"]) if state["critic"] else "not json"
        if json_mode:
            return json.dumps({"facts": [], "mood": "neutral", "intensity": 0})
        return "On it."

    monkeypatch.setattr(llm, "complete", fake)
    return state


def tomorrow(fmt="%Y-%m-%d"):
    return (now_local() + timedelta(days=1)).strftime(fmt)


def create(title, start, minutes=60, recurrence=None, day=None):
    return {"op": "create", "title": title, "date": day or tomorrow(), "start": start, "end": None,
            "duration_min": minutes, "recurrence": recurrence, "category": "study", "priority": 3}


def test_clean_change_is_applied_without_bothering_the_critic(client, board):
    board["ops"] = [create("DSA", "18:00")]
    body = client.post("/chat", json={"text": "add DSA tomorrow at 6pm"}).json()
    assert body["notes"]["deliberation"]["action"] == "apply"
    assert body["notes"]["timetable_changes"]
    assert board["critic_calls"] == 0
    assert "sleep_guardian" not in body["ran"]  # review agents run inside the plan.proposed sub-dispatch


def test_cutting_into_sleep_is_never_silent(client, board):
    board["ops"] = [create("Gaming", "23:00", 120)]
    body = client.post("/chat", json={"text": "add gaming tomorrow at 11pm for 2 hours"}).json()
    d = body["notes"]["deliberation"]
    assert d["action"] == "ask" and any("sleep" in f for f in d["findings"])
    assert client.get("/today?days=3").json() == []  # nothing changed
    proposal = client.get("/messages").json()[-1]
    assert proposal["meta"]["kind"] == "schedule_proposal"
    assert proposal["meta"]["buttons"] == ["approve", "reject"]
    # they insist → it happens
    client.post(f"/proposals/{proposal['id']}/respond", json={"action": "approve"})
    assert [b["title"] for b in client.get("/today?days=3").json()] == ["Gaming"]


def test_clash_gets_fixed_by_the_critic_then_applied(client, board):
    board["ops"] = [create("Gym", "18:00")]
    client.post("/chat", json={"text": "gym tomorrow at 6pm"})
    board["ops"] = [create("DSA", "18:30")]
    board["critic"] = {"verdict": "adjust", "reasoning": "Gym runs till 7, so I put DSA right after.",
                       "ops": [create("DSA", "19:15")]}
    body = client.post("/chat", json={"text": "add DSA tomorrow at 6:30pm"}).json()
    d = body["notes"]["deliberation"]
    assert d["action"] == "apply_adjusted" and "clashes" in " ".join(d["findings"])
    starts = {b["title"]: b["start"] for b in client.get("/today?days=3").json()}
    assert starts == {"Gym": "18:00", "DSA": "19:15"}


def test_critic_fix_that_still_clashes_becomes_a_question(client, board):
    board["ops"] = [create("Gym", "18:00")]
    client.post("/chat", json={"text": "gym tomorrow at 6pm"})
    board["ops"] = [create("DSA", "18:30")]
    board["critic"] = {"verdict": "adjust", "reasoning": "Shifted.", "ops": [create("DSA", "18:45")]}
    body = client.post("/chat", json={"text": "add DSA tomorrow at 6:30pm"}).json()
    assert body["notes"]["deliberation"]["action"] == "ask"
    meta = client.get("/messages").json()[-1]["meta"]
    assert meta["buttons"] == ["accept", "original", "reject"]
    assert meta["ops"][0]["start"] == "18:45" and meta["original_ops"][0]["start"] == "18:30"


def test_whole_new_schedule_is_shown_before_it_goes_live(client, board):
    board["ops"] = [create("Classes", "09:00", 360, "weekdays"), create("Gym", "16:00", 60, "mon,wed,fri"),
                    create("DSA", "19:00", 90, "daily"), {"op": "set_sleep", "start": "00:00", "end": "07:30"}]
    body = client.post("/chat", json={"text": "here's my schedule: classes 9 to 3 weekdays, gym mon wed fri at 4, "
                                              "DSA every evening at 7 for 90 minutes, I sleep 12 to 7:30. " * 2}).json()
    assert body["notes"]["deliberation"]["action"] == "ask"
    assert client.get("/today?days=7").json() == []
    proposal = client.get("/messages").json()[-1]
    assert "Classes" in proposal["content"] and "sleep window 00:00–07:30" in proposal["content"]
    client.post(f"/proposals/{proposal['id']}/respond", json={"action": "approve"})
    titles = {b["title"] for b in client.get("/today?days=7").json()}
    assert titles == {"Classes", "Gym", "DSA", "Sleep — rest up"}  # sleep shows on the timetable too
    with client.session_factory() as db:
        assert db.get(KeyValue, "sleep_window").value == "00:00-07:30"


def test_marathons_and_overloaded_days_are_flagged(client):
    with client.session_factory() as db:
        p = deliberation.build(db, [create("Study block A", "08:00", 240), create("Study block B", "12:05", 240),
                                    create("Study block C", "16:10", 180)])
        msgs = [f.message for f in deliberation.check_buffers(db, p)]
    assert any("11h" in m or "a lot" in m for m in msgs)
    assert any("no break" in m for m in msgs)


def test_rejecting_a_schedule_change_changes_nothing(client, board):
    board["ops"] = [create("Gaming", "23:00", 120)]
    client.post("/chat", json={"text": "add gaming tomorrow at 11pm"})
    proposal = client.get("/messages").json()[-1]
    client.post(f"/proposals/{proposal['id']}/respond", json={"action": "reject"})
    assert client.get("/today?days=3").json() == []


def test_dashboard_can_delete_a_block_and_view_any_week(client, board):
    board["ops"] = [create("Read", "20:00", 30, "daily")]
    client.post("/chat", json={"text": "read every day at 8pm for 30 minutes"})
    week = client.get(f"/today?days=7&start_day={tomorrow()}").json()
    assert len(week) == 7 and all(b["routine"] for b in week)
    assert client.delete(f"/tasks/{week[0]['id']}?whole_routine=true").status_code == 204
    assert client.get("/today?days=14").json() == []
    assert client.get("/today?start_day=notadate").status_code == 422


def test_one_long_class_is_not_a_marathon_and_lunch_isnt_double_counted(client):
    with client.session_factory() as db:
        from app.core import timetable
        from datetime import time as t
        day = (now_local() + timedelta(days=1)).date()
        timetable.create_block(db, "Classes", day, t(9), t(15))
        timetable.create_block(db, "Lunch", day, t(12, 30), t(13))
        db.commit()
        p = deliberation.build(db, [create("Reading", "21:00", 30)])
        assert deliberation.check_buffers(db, p) == []
        p = deliberation.build(db, [create("Mock interview", "15:05", 90)])  # glued to classes → 7.5h straight
        assert any("back-to-back" in f.message for f in deliberation.check_buffers(db, p))


@pytest.mark.parametrize("window, start, minutes, blocked", [
    (("00:00", "06:00"), "06:00", 120, False),   # gym right after waking
    (("00:00", "06:00"), "23:05", 45, False),    # ends 23:50, before midnight bedtime
    (("00:00", "06:00"), "23:30", 60, True),     # runs past midnight
    (("00:00", "06:00"), "05:30", 60, True),     # starts before waking
    (("23:30", "06:00"), "06:00", 120, False),
    (("23:30", "06:00"), "23:00", 60, True),
    (("01:00", "07:30"), "00:15", 30, False),    # night owl: 12:15am is still awake time
])
def test_sleep_guardian_handles_any_bedtime(client, window, start, minutes, blocked):
    with client.session_factory() as db:
        deliberation.set_sleep_window(db, deliberation.parse_time(window[0]), deliberation.parse_time(window[1]))
        db.flush()
        p = deliberation.build(db, [create("X", start, minutes)])
        assert bool(deliberation.check_sleep(db, p)) is blocked
