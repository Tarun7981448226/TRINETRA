import asyncio
from datetime import date, datetime, time, timedelta

from app.core import push, scheduler, streaks
from app.core.timeutil import to_utc
from app.db.models import Task, WakeSession

DAY = date(2026, 10, 20)


def at(d: date, hh: int, mm: int = 0) -> datetime:
    return to_utc(datetime.combine(d, time(hh, mm)))


def done_block(db, title, d, hh, hours=2, category="study", status="done"):
    t = Task(title=title, category=category, planned_start=at(d, hh), planned_end=at(d, hh) + timedelta(hours=hours),
             status=status, actual_start=at(d, hh))
    db.add(t)
    db.flush()
    return t


def test_streaks_count_days_in_a_row_and_flag_risk(client):
    with client.session_factory() as db:
        for i in range(4):  # TUF on 4 days running, up to yesterday
            done_block(db, "TUF DSA (1/2)", DAY - timedelta(days=4 - i), 8)
        done_block(db, "Gym + fresh up", DAY - timedelta(days=9), 6, category="fitness")
        db.add(WakeSession(day=DAY.isoformat(), rings=1, solved_at=at(DAY, 6, 5), questions=[]))
        db.commit()
        s = {x["kind"]: x for x in streaks.all_streaks(db, DAY)}
    assert s["dsa"]["current"] == 4 and s["dsa"]["at_risk"] and not s["dsa"]["today"]
    assert s["wake"]["current"] == 1 and s["wake"]["today"]
    assert s["gym"]["current"] == 0 and s["gym"]["best"] == 1


def test_a_milestone_day_gets_celebrated_once(client, llm_calls, monkeypatch):
    monkeypatch.setattr(streaks, "now_local", lambda: datetime.combine(DAY, time(12)))
    with client.session_factory() as db:
        for i in range(1, 3):
            done_block(db, "TUF DSA (1/2)", DAY - timedelta(days=i), 8)
        t = done_block(db, "TUF DSA (1/2)", DAY, 8, status="planned")
        db.commit()
        tid = t.id
    client.post(f"/tasks/{tid}/respond", json={"action": "done"})  # third day in a row
    cheers = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "streak"]
    assert len(cheers) == 1 and cheers[0]["meta"]["days"] == 3


def test_long_unbroken_work_gets_water_then_a_real_break(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    with client.session_factory() as db:
        done_block(db, "TUF DSA (1/2)", DAY, 9, hours=2)                      # 09–11
        done_block(db, "ML Specialization", DAY, 11, hours=3, status="started")  # 11–14, back to back
        db.commit()
    fired = []
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        for minute in range(0, 300, 5):
            k = asyncio.run(scheduler.wellbeing_watch(db, core, at(DAY, 9) + timedelta(minutes=minute)))
            db.commit()
            if k:
                fired.append((minute, k))
    assert fired == [(120, "hydrate"), (180, "break"), (270, "hydrate")]  # the watch runs while a block is on
    kinds = [(m["meta"] or {}).get("nudge") for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "wellbeing"]
    assert kinds == ["hydrate", "break", "hydrate"]


def test_moods_are_kept_and_stress_lightens_tomorrow(client, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")  # the offline mood reader: keyword based
    monkeypatch.setattr(get_settings(), "groq_api_key", "")
    for text in ("I'm so stressed about the exam", "feeling overwhelmed with everything", "honestly exhausted today, so tired"):
        client.post("/chat", json={"text": text})
    days = client.get("/moods").json()
    assert sum(d["count"] for d in days) == 3 and days[-1]["low"] == 3
    tomorrow = DAY
    with client.session_factory() as db:
        done_block(db, "CSCI 570 class", tomorrow, 14, hours=3, status="planned")
        low = done_block(db, "NumPy & Pandas", tomorrow, 22, hours=1, status="planned")
        low.priority = 2
        db.commit()
        low_id = low.id
    client.post("/events", json={"type": "plan.nightly", "payload": {"date": tomorrow.isoformat()}, "source": "test"})
    prop = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "schedule_proposal"][-1]
    assert prop["meta"]["ops"] == [{"op": "delete", "id": low_id}] and "Drop NumPy & Pandas" in prop["content"]
    assert "stressed 3 times" in prop["content"]
    client.post(prop["meta"]["respond"], json={"action": "approve"})
    assert low_id not in [t["id"] for t in client.get("/tasks").json()]
