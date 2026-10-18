import asyncio
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.core import llm, mentor, scheduler
from app.core.timeutil import now_local
from app.db.models import Goal, Message, Promise, Task, TaskStatus
from tests.conftest import trinetra_prompt


@pytest.fixture
def mentor_llm(monkeypatch):
    """LLM stub that answers each agent by recognising its prompt."""
    calls = []
    plan = {"is_goal": True,
            "goal": {"title": "Land a software engineering internship", "why": "to support my family",
                     "horizon": "1y", "area": "career", "target_date": "2027-06-01"},
            "milestones": [{"title": "Finish 150 LeetCode problems", "due_date": "2026-12-31"},
                           {"title": "Build 2 portfolio projects", "due_date": "2027-02-28"},
                           {"title": "Apply to 60 companies", "due_date": "2027-04-30"}],
            "weekly_blocks": [{"title": "LeetCode practice", "days": "mon,wed,fri", "start": "07:00",
                               "duration_min": 60, "category": "study"}]}
    due = (now_local() + timedelta(days=2)).strftime("%Y-%m-%d 21:00")

    async def fake(messages, tier="smart", json_mode=False, **kw):
        sys_prompt = messages[0]["content"]
        calls.append(sys_prompt)
        if "goal architect" in sys_prompt:
            return json.dumps(plan)
        if "Extract commitments" in sys_prompt:
            return json.dumps({"promises": [{"text": "finish 20 LeetCode problems", "due": due}]})
        if json_mode:
            return json.dumps({"facts": [], "ops": [], "mood": "motivated", "intensity": 0.5})
        return "Love it. Let's build this."

    monkeypatch.setattr(llm, "complete", fake)
    return calls


def test_goal_becomes_milestones_and_a_plan_to_approve(client, mentor_llm):
    body = client.post("/chat", json={"text": "My goal is to land a software engineering internship by "
                                              "summer 2027, to support my family"}).json()
    assert body["notes"]["goal_created"]["title"] == "Land a software engineering internship"
    assert "You JUST saved their goal" in trinetra_prompt([{"messages": [{"content": c}]} for c in mentor_llm])

    [goal] = client.get("/goals").json()
    assert goal["why"] == "to support my family" and len(goal["milestones"]) == 3
    assert goal["target_date"].startswith("2027-06-0")

    msgs = client.get("/messages").json()
    assert msgs[-1]["meta"]["kind"] == "plan_proposal"   # the plan comes AFTER the reply
    assert msgs[-2]["role"] == "trinetra" and not msgs[-2]["meta"]
    assert client.get("/today?days=7").json() == []      # nothing added before approval

    r = client.post(f"/proposals/{msgs[-1]['id']}/respond", json={"action": "approve"})
    assert r.status_code == 200
    blocks = client.get("/today?days=14").json()
    assert blocks and all(b["start"] == "07:00" and b["recurrence"] == "mon,wed,fri" for b in blocks)
    with client.session_factory() as db:
        assert all(t.goal_id == goal["id"] for t in db.scalars(select(Task)))
    assert client.post(f"/proposals/{msgs[-1]['id']}/respond", json={"action": "approve"}).status_code == 409


def test_rejecting_a_plan_adds_nothing(client, mentor_llm):
    client.post("/chat", json={"text": "I want to become a strong runner by march"})
    proposal = client.get("/messages").json()[-1]
    client.post(f"/proposals/{proposal['id']}/respond", json={"action": "reject"})
    assert client.get("/today?days=14").json() == []


def test_milestones_drive_progress_and_pride(client, mentor_llm):
    client.post("/chat", json={"text": "My goal is to land a software engineering internship by summer 2027"})
    [goal] = client.get("/goals").json()
    first = goal["milestones"][0]["id"]
    g = client.patch(f"/milestones/{first}", json={"done": True}).json()
    assert g["progress"] == pytest.approx(0.33, abs=0.01)
    assert client.get("/emotion").json()["pride"] > 0.3
    for m in goal["milestones"]:
        g = client.patch(f"/milestones/{m['id']}", json={"done": True}).json()
    assert g["status"] == "achieved" and g["progress"] == 1.0


def test_promise_is_remembered_then_checked_at_deadline(client, mentor_llm):
    body = client.post("/chat", json={"text": "I'll finish 20 LeetCode problems by Saturday"}).json()
    assert body["notes"]["promises_saved"]
    [p] = client.get("/promises").json()
    assert p["status"] == "open"

    with client.session_factory() as db:
        promise = db.get(Promise, p["id"])
        from app.core.timeutil import from_db
        deadline = from_db(promise.due_at)  # Postgres returns it timezone-aware already
        fired = asyncio.run(scheduler.tick(db, client.app.state.orchestrator, deadline + timedelta(minutes=1)))
    assert fired == [f"promise.due:{p['id']}"]
    check = client.get("/messages").json()[-1]
    assert check["meta"]["kind"] == "promise_check" and check["meta"]["buttons"] == ["kept", "broken"]

    frustration_before = client.get("/emotion").json()["frustration"]
    body = client.post(check["meta"]["respond"], json={"action": "broken"}).json()
    assert client.get("/promises").json()[0]["status"] == "broken"
    assert client.get("/emotion").json()["frustration"] > frustration_before
    assert client.get("/messages").json()[-3]["meta"]["answered"] == "broken"


def test_stale_promises_dont_nag(client, llm_calls):
    with client.session_factory() as db:
        db.add(Promise(text="old thing", due_at=datetime.now(timezone.utc) - timedelta(days=3)))
        db.commit()
        assert asyncio.run(scheduler.tick(db, client.app.state.orchestrator)) == []


def _blocks(db, area, done, skipped, days_ago=3):
    base = datetime.now(timezone.utc) - timedelta(days=days_ago)
    for i in range(done + skipped):
        db.add(Task(title=f"{area} {i}", category=area, planned_start=base + timedelta(hours=i),
                    planned_end=base + timedelta(hours=i, minutes=45),
                    status=TaskStatus.DONE if i < done else TaskStatus.SKIPPED))
    db.commit()


def test_progressive_overload_verdicts(client):
    with client.session_factory() as db:
        _blocks(db, "study", done=9, skipped=1)     # 90% → raise the bar
        _blocks(db, "fitness", done=2, skipped=4)   # 33% → ease off
        _blocks(db, "reading", done=3, skipped=2)   # 60% → hold
        _blocks(db, "chores", done=1, skipped=1)    # too little data
        verdicts = {c["area"]: c["verdict"] for c in mentor.challenges(db)}
    assert verdicts == {"study": "raise", "fitness": "ease", "reading": "hold"}


def test_overlapping_plan_blocks_are_untangled(client):
    blocks = [
        {"title": "DSA", "days": "weekdays", "start": "19:00", "duration_min": 90, "category": "study"},
        {"title": "Apply to jobs", "days": "wed", "start": "20:00", "duration_min": 60, "category": "work"},
    ]
    with client.session_factory() as db:
        added = mentor.apply_plan(db, None, blocks)
        db.commit()
    assert added[1].startswith("Apply to jobs (wed 21:00")  # moved after DSA ends (20:30) + 30 min
    from app.core.timeutil import local
    with client.session_factory() as db:
        wed = [t for t in db.scalars(select(Task)) if local(t.planned_start).weekday() == 2]
        spans = sorted((local(t.planned_start), local(t.planned_end)) for t in wed if local(t.planned_start).date() == local(wed[0].planned_start).date())
        assert all(a[1] <= b[0] for a, b in zip(spans, spans[1:]))


def test_support_moves_explore_comfort_act(client, llm_calls):
    """A low moment over several messages: ask first, then comfort, then one small step (ESConv stages)."""
    from tests.conftest import trinetra_prompt
    stages = []
    for text in ("I feel so sad today", "everything went wrong, I feel so sad", "I'm still really sad and down"):
        body = client.post("/chat", json={"text": text}).json()
        stages.append(body["notes"].get("support_stage"))
    assert stages == [1, 2, 3]
    assert "Support stage 3, act" in trinetra_prompt(llm_calls)


def test_crisis_language_is_distress_but_everyday_frustration_isnt():
    from app.agents.command import DISTRESS
    for t in ("i dont see the point of anything anymore", "I want to die", "thinking about suicide", "i want it all to stop",
              "everyone would be better off without me", "I feel hopeless"):
        assert DISTRESS.search(t), t
    for t in ("I want to give up on this bug", "this point is wrong", "end the meeting", "I'm dying to see the new movie",
              "kill this process", "no pointers in python"):
        assert not DISTRESS.search(t), t


def test_practical_messages_skip_the_llm_mood_read(client, llm_calls):
    client.post("/chat", json={"text": "show my plan"})
    assert not any("emotional state" in c["messages"][0]["content"] for c in llm_calls)
    client.post("/chat", json={"text": "I feel so lost lately"})
    assert any("emotional state" in c["messages"][0]["content"] for c in llm_calls)


def test_crisis_always_gets_a_real_way_to_help(client, llm_calls):
    body = client.post("/chat", json={"text": "i dont see the point of anything anymore, i want it all to stop"}).json()
    assert "988" in body["reply"] and body["notes"]["distress"]
    body = client.post("/chat", json={"text": "what's on my plan today?"}).json()
    assert "988" not in body["reply"]


def test_everyday_phrases_never_get_the_crisis_line(client, llm_calls):
    for t in ("let's end it there", "this code is worthless", "I'm hopeless at cooking", "the battery is going to die"):
        assert "988" not in client.post("/chat", json={"text": t}).json()["reply"], t


def test_removing_a_butler_sentence_keeps_the_spacing():
    from app.core.persona import humanize
    assert humanize("Sounds like fun! Feel free to ask me anything. What brings you here?", strip_name=False) == \
        "Sounds like fun! What brings you here?"


def test_schedule_questions_are_answered_even_when_every_model_is_busy(client, monkeypatch):
    from datetime import time, timedelta
    from app.config import get_settings
    from app.core import llm, timetable
    from app.core.timeutil import now_local
    monkeypatch.setattr(get_settings(), "gemini_api_key", "x")

    async def down(*a, **k):
        raise llm.LLMUnavailable("all busy")
    monkeypatch.setattr(llm, "complete", down)
    with client.session_factory() as db:
        timetable.create_block(db, "Gym", now_local().date() + timedelta(days=1), time(18), time(19))
        db.commit()
    r = client.post("/chat", json={"text": "what's on tomorrow?"}).json()
    assert r["reply"].startswith("Tomorrow: Gym at 18:00")
    r = client.post("/chat", json={"text": "tell me a joke"}).json()
    assert "busy" in r["reply"]  # anything else still says so honestly


def test_hinglish_crisis_words_are_heard_too():
    from app.agents.command import DISTRESS
    for t in ("main marna chahta hoon", "jeena nahi chahta", "khud ko khatam kar dunga", "suicide karunga"):
        assert DISTRESS.search(t), t
    for t in ("has has ke mar gaya", "ye kaam khatam kar", "zindagi badi mast hai", "meeting khatam karo"):
        assert not DISTRESS.search(t), t


def test_whats_next_today_without_a_model_skips_what_is_over(client, monkeypatch):
    from datetime import timedelta
    from app.config import get_settings
    from app.core import llm, timetable
    from app.core.timeutil import now_local
    monkeypatch.setattr(get_settings(), "gemini_api_key", "x")

    async def down(*a, **k):
        raise llm.LLMUnavailable("all busy")
    monkeypatch.setattr(llm, "complete", down)
    now = now_local()
    with client.session_factory() as db:
        past_start = (now - timedelta(hours=3)).replace(second=0, microsecond=0)
        later = (now + timedelta(hours=1)).replace(second=0, microsecond=0)
        if past_start.date() == now.date() and later.date() == now.date():
            timetable.create_block(db, "Breakfast", now.date(), past_start.time(), (past_start + timedelta(minutes=30)).time())
            timetable.create_block(db, "DSA", now.date(), later.time(), (later + timedelta(minutes=50)).time())
            db.commit()
            r = client.post("/chat", json={"text": "what's next?"}).json()
            assert r["reply"].startswith("Still to come today: DSA at") and "Breakfast" not in r["reply"]
