import asyncio
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core import push, report, scheduler, voice, wake
from app.core.timeutil import now_local, user_tz
from app.core.voice import SILENT_MP3
from app.db.models import KeyValue, Message, Task, WakeSession, WeeklyReport

KEY = "sc-test-key"


@pytest.fixture(autouse=True)
def shortcut_key(monkeypatch):
    monkeypatch.setattr(get_settings(), "trinetra_shortcut_key", KEY)

    async def fake_speak(text, mood=None):
        return b"ID3" + text.encode()[:50]

    monkeypatch.setattr(voice, "speak", fake_speak)


def sc(client, path, **params):
    return client.get(path, params={"key": KEY, **params})


def test_shortcut_key_opens_only_shortcut_endpoints(client):
    assert client.get("/sc/wake/status", params={"key": "wrong"}).status_code == 401
    assert client.get("/sc/wake/status").status_code == 401
    assert sc(client, "/sc/wake/status").status_code == 200
    assert client.get("/memories", params={"key": KEY}).status_code == 200  # (unlocked in tests anyway)


def test_wake_protocol_three_questions_then_briefing(client, llm_calls):
    assert sc(client, "/sc/wake/start").text == ""  # empty = not awake yet
    q1 = sc(client, "/sc/wake/question").text
    assert q1.startswith("Question 1 of 3")
    assert sc(client, "/sc/wake/speech").headers["content-type"] == "audio/mpeg"

    assert sc(client, "/sc/wake/answer", a="-1").text == "wrong"
    with client.session_factory() as db:
        s = db.scalar(select(WakeSession))
        answers = [q["a"] for q in s.questions]
    assert sc(client, "/sc/wake/answer", a=str(answers[0])).text == "correct"
    assert sc(client, "/sc/wake/answer", a=f"{answers[1]}.0").text == "correct"
    assert sc(client, "/sc/wake/answer", a=str(answers[2])).text == "done"
    assert sc(client, "/sc/wake/status").text == "done"
    assert sc(client, "/sc/wake/start").text == "done"   # the 06:10 re-ring sees you're up and stays quiet

    [h] = client.get("/wake/history").json()
    assert h["solved"] and h["rings"] == 1 and h["wrong"] == 1
    with client.session_factory() as db:
        assert db.get(KeyValue, "wake_enabled").value == "1"


def test_medium_questions_are_actually_medium():
    import random
    rng = random.Random(1)
    for _ in range(50):
        q = wake.medium_question(rng)
        assert 10 <= q["a"] <= 200 and any(op in q["text"] for op in "×−+")


def test_rerings_make_trinetra_angrier(client, llm_calls):
    with client.session_factory() as db:
        s = wake.ring(db)
        assert "warm" in wake.mood_for(s)
        wake.ring(db)
        assert "angry" in wake.mood_for(s)
        wake.ring(db)
        assert wake.mood_for(s).startswith("ANGRY")


def test_lock_screen_nags_until_awake(client, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "send", lambda db, title, body, url="/", tag=None: sent.append(body) or 1)
    monkeypatch.setattr(scheduler, "now_local", lambda: datetime.now(user_tz()).replace(hour=6, minute=7))
    monkeypatch.setattr(wake, "now_local", lambda: datetime.now(user_tz()).replace(hour=6, minute=7))
    with client.session_factory() as db:
        assert asyncio.run(scheduler.wake_watch(db, datetime.now(timezone.utc))) is False  # not set up yet
        db.add(KeyValue(key="wake_enabled", value="1"))
        db.flush()
        now = datetime.now(timezone.utc)
        assert asyncio.run(scheduler.wake_watch(db, now)) is True
        assert asyncio.run(scheduler.wake_watch(db, now + timedelta(minutes=2))) is False  # 5-min spacing
        assert asyncio.run(scheduler.wake_watch(db, now + timedelta(minutes=5))) is True
        s = wake.today_session(db)
        s.last = "done"
        assert asyncio.run(scheduler.wake_watch(db, now + timedelta(minutes=10))) is False
    assert len(sent) == 2 and "Get up" in sent[0]


def test_ignored_reminder_gets_three_follow_ups(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    start = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    t = client.post("/tasks", json={"title": "TUF DSA", "planned_start": start.isoformat(),
                                    "planned_end": (start + timedelta(hours=2)).isoformat()}).json()
    fired = []
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        for minute in range(-5, 30):
            fired += asyncio.run(scheduler.tick(db, core, start + timedelta(minutes=minute)))
    nags = [f for f in fired if f.startswith("task.nag")]
    assert nags == [f"task.nag:{t['id']}:1", f"task.nag:{t['id']}:2", f"task.nag:{t['id']}:3"]
    assert client.get("/emotion").json()["frustration"] > 0  # ignoring all three stung


def test_starting_stops_the_nagging(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    start = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    t = client.post("/tasks", json={"title": "ML", "planned_start": start.isoformat(),
                                    "planned_end": (start + timedelta(hours=2)).isoformat()}).json()
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        asyncio.run(scheduler.tick(db, core, start - timedelta(minutes=4)))
    client.post(f"/tasks/{t['id']}/respond", json={"action": "start"})
    with client.session_factory() as db:
        out = asyncio.run(scheduler.tick(db, client.app.state.orchestrator, start + timedelta(minutes=10)))
    assert not [f for f in out if "nag" in f]


def test_now_speaks_only_when_something_is_due(client, llm_calls):
    assert sc(client, "/sc/now").content == SILENT_MP3  # nothing due → a moment of silence, never an error
    s = now_local() + timedelta(minutes=3)
    client.post("/tasks", json={"title": "TUF DSA", "planned_start": s.isoformat(),
                                "planned_end": (s + timedelta(hours=2)).isoformat()})
    r = sc(client, "/sc/now")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/mpeg"


def test_weekly_report_builds_in_steps_and_compares_weeks(client, llm_calls):
    with client.session_factory() as db:
        base = datetime.now(timezone.utc) - timedelta(days=1)
        for i, status in enumerate(["done", "done", "skipped"]):
            db.add(Task(title=f"Study {i}", category="study", planned_start=base + timedelta(hours=i),
                        planned_end=base + timedelta(hours=i, minutes=50), status=status))
        last_monday = (now_local().date() - timedelta(days=now_local().weekday() + 7)).isoformat()
        db.add(WeeklyReport(week_start=last_monday, status="ready", sections=[],
                            metrics={"blocks": {"rate": 0.5}, "hours_done": 3.0, "wake": {}}))
        db.commit()
    built = client.post("/reports/build").json()
    assert built["steps"] == ["measured"] + [f"chapter {i}" for i in range(1, 7)]
    latest = client.get("/reports").json()[0]
    assert latest["status"] == "ready" and len(latest["sections"]) == 6
    m = latest["metrics"]
    assert m["blocks"]["done"] >= 2 and m["compare"]["weeks_before"] == 1
    assert m["compare"]["change_vs_last_week"]["rate"] is not None
    r = sc(client, "/sc/report/audio", part=6)
    assert r.status_code == 200 and sc(client, "/sc/report/audio", part=7).content == SILENT_MP3


def test_report_is_announced_at_2330_sunday(client, llm_calls, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "send", lambda db, title, body, url="/", tag=None: sent.append(url) or 1)
    sunday_2331 = datetime(2026, 10, 18, 23, 31, tzinfo=user_tz())
    monkeypatch.setattr(scheduler, "now_local", lambda: sunday_2331)
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        steps = [asyncio.run(scheduler.weekly(db, core)) for _ in range(9)]
        db.commit()
    assert steps[:7] == ["measured"] + [f"chapter {i}" for i in range(1, 7)]
    assert steps[7] == "announced" and steps[8] == "ready"
    assert sent == ["/#report"]


def test_app_wake_screen_then_briefing_once_then_silence(client, llm_calls):
    st = client.get("/wake/state").json()
    assert not st["done"] and st["number"] == 1 and st["rings"] == 1
    assert client.post("/wake/answer", json={"a": "-1"}).json()["result"] == "wrong"
    with client.session_factory() as db:
        answers = [q["a"] for q in db.scalar(select(WakeSession)).questions]
    for a in answers:
        r = client.post("/wake/answer", json={"a": str(a)}).json()
    assert r["result"] == "done" and r["done"] and r["wrong"] == 1
    briefing = client.get("/wake/speech")
    assert briefing.headers["content-type"] == "audio/mpeg" and briefing.content != SILENT_MP3
    assert sc(client, "/sc/wake/speech").content == SILENT_MP3   # the 06:10 re-ring stays quiet


def _ignore(client, priority, minutes=70):
    start = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    t = client.post("/tasks", json={"title": "CSCI 570 study", "planned_start": start.isoformat(), "priority": priority,
                                    "planned_end": (start + timedelta(hours=2)).isoformat()}).json()
    fired = []
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        for minute in range(-5, minutes):
            fired += asyncio.run(scheduler.tick(db, core, start + timedelta(minutes=minute)))
            db.commit()
    return t, fired


def test_important_block_ignored_gets_two_red_alerts(client, llm_calls, monkeypatch):
    titles = []
    monkeypatch.setattr(push, "send", lambda db, title, body, url="/", tag=None: titles.append((title, tag)) or 1)
    t, fired = _ignore(client, priority=5)
    reds = [f for f in fired if f.startswith("task.escalate")]
    assert reds == [f"task.escalate:{t['id']}:1", f"task.escalate:{t['id']}:2"]
    assert ("🚨 TRINETRA", f"red-{t['id']}") in titles  # its own notification, not folded into the reminder
    alerts = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "red_alert"]
    assert len(alerts) == 2 and alerts[0]["meta"]["buttons"] == ["start", "skip"] and alerts[0]["mood"].startswith("ANGRY")
    page = client.get("/").text
    assert 'id="alertScreen"' in page and "Tap again to skip" in page


def test_ordinary_blocks_and_started_blocks_get_no_red_alert(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    _, fired = _ignore(client, priority=3)
    assert not [f for f in fired if "escalate" in f]
    t, fired = _ignore(client, priority=5, minutes=22)  # first red alert at +20 min…
    assert [f for f in fired if "escalate" in f] == [f"task.escalate:{t['id']}:1"]
    client.post(f"/tasks/{t['id']}/respond", json={"action": "start"})  # …then he starts it
    with client.session_factory() as db:
        out = asyncio.run(scheduler.tick(db, client.app.state.orchestrator,
                                         datetime(2026, 10, 20, 18, 50, tzinfo=timezone.utc)))
    assert not [f for f in out if "escalate" in f]


def _started_block(client, start, hours=3):
    t = client.post("/tasks", json={"title": "ORION build", "planned_start": start.isoformat(),
                                    "planned_end": (start + timedelta(hours=hours)).isoformat()}).json()
    with client.session_factory() as db:
        task = db.get(Task, t["id"])
        task.status, task.actual_start, task.reminded_at = "started", start, start
        db.commit()
    return t


def _watch(client, start, minutes):
    asked = []
    with client.session_factory() as db:
        for minute in range(0, minutes):
            if asyncio.run(scheduler.silence_watch(db, client.app.state.orchestrator, start + timedelta(minutes=minute))):
                asked.append(minute)
            db.commit()
    return asked


def test_silence_in_a_started_block_gets_a_light_check_twice_at_most(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    start = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    t = _started_block(client, start)
    assert _watch(client, start, 180) == [60, 120]  # an hour quiet → ask; again an hour later; never in the last 15 min
    m = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "silence"][-1]
    assert m["meta"]["buttons"] == ["onit", "done", "skipped"] and m["meta"]["task_id"] == t["id"]
    r = client.post(f"/tasks/{t['id']}/respond", json={"action": "onit"})
    assert r.status_code == 200 and client.get("/tasks").json()[0]["status"] == "started"  # still on it


def test_talking_counts_as_a_sign_of_life(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    start = datetime.now(timezone.utc) - timedelta(minutes=50)
    _started_block(client, start)
    client.post("/chat", json={"text": "working through the proofs"})  # 50 min in: resets the hour
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        assert not asyncio.run(scheduler.silence_watch(db, core, start + timedelta(minutes=70)))
        assert asyncio.run(scheduler.silence_watch(db, core, start + timedelta(minutes=115)))
