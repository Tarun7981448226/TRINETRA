from datetime import date, datetime, time, timedelta, timezone

from app.core import push
from app.core.timeutil import to_utc
from app.db.models import Task, WakeSession
from app.ml import insights

TODAY = date.today()


def add(db, title, d, hh, status, category="study", hours=2, actual_min=None):
    s = to_utc(datetime.combine(d, time(hh)))
    t = Task(title=title, category=category, planned_start=s, planned_end=s + timedelta(hours=hours), status=status)
    if actual_min:
        t.actual_start, t.actual_end = s, s + timedelta(minutes=actual_min)
    db.add(t)
    return t


def history(db):
    for i in range(1, 22):  # three weeks
        d = TODAY - timedelta(days=i)
        gym = i % 3 == 0  # the gym on a third of days; evenings only get done then
        add(db, "Gym", d, 6, "done" if gym else "skipped", category="fitness", hours=1)
        add(db, "TUF DSA (1/2)", d, 8, "done", actual_min=150)         # mornings: done, and 2.5 h not 2
        add(db, "TUF DSA (2/2)", d, 20, "done" if gym else "skipped")  # evenings: only on gym days
        db.add(WakeSession(day=d.isoformat(), rings=1 if gym else 3, solved_at=to_utc(datetime.combine(d, time(6, 5))), questions=[]))
    db.commit()


def test_history_becomes_insights(client):
    with client.session_factory() as db:
        history(db)
        ins = insights.refresh(db)
        db.commit()
    assert ins["durations"]["dsa"]["ratio"] == 1.25 and ins["durations"]["dsa"]["n"] >= 20
    assert ins["energy"]["peak"] == "08:00–10:00" and ins["energy"]["slump"] in ("20:00–22:00", "06:00–08:00")
    blocks = {p["block"] for p in ins["procrastination"]}
    assert "TUF DSA (2/2)" in blocks
    links = {p["link"]: p for p in ins["patterns"]}
    assert links["gym"]["diff"] > 0 and "on gym days" in links["gym"]["text"]
    assert "wake" in links
    assert client.get("/insights").json()["energy"]["peak"] == "08:00–10:00"


def test_new_block_planned_too_short_gets_a_realistic_length(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    with client.session_factory() as db:
        history(db)
        insights.refresh(db)
        db.commit()
    start = to_utc(datetime.combine(TODAY + timedelta(days=2), time(10)))
    t = client.post("/tasks", json={"title": "TUF DSA — extra", "planned_start": start.isoformat(),
                                    "planned_end": (start + timedelta(hours=2)).isoformat()}).json()
    prop = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "schedule_proposal"][-1]
    assert prop["meta"]["ops"] == [{"op": "move", "id": t["id"], "date": (TODAY + timedelta(days=2)).isoformat(),
                                    "start": "10:00", "duration_min": 150}]
    assert "1.25×" in prop["content"]
    client.post(prop["meta"]["respond"], json={"action": "approve"})
    moved = next(x for x in client.get("/tasks").json() if x["id"] == t["id"])
    assert (datetime.fromisoformat(moved["planned_end"]) - datetime.fromisoformat(moved["planned_start"])) == timedelta(minutes=150)


def test_a_habitual_skip_is_named_in_the_why(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    with client.session_factory() as db:
        history(db)
        insights.refresh(db)
        db.commit()
    g = client.post("/goals", json={"title": "DSA", "why": "the internship"}).json()
    s = to_utc(datetime.combine(TODAY, time(20)))
    t = client.post("/tasks", json={"title": "TUF DSA (2/2)", "priority": 5, "goal_id": g["id"], "planned_start": s.isoformat(),
                                    "planned_end": (s + timedelta(hours=2)).isoformat()}).json()
    client.post(f"/tasks/{t['id']}/respond", json={"action": "skip"})
    prompts = " ".join(m["content"] for c in llm_calls for m in c["messages"])
    assert "I skip this one a lot" in prompts
