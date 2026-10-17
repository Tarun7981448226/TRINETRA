import asyncio
from datetime import datetime, timedelta, timezone

from app.core import push, scheduler

MON = datetime(2026, 10, 19, 15, 30, tzinfo=timezone.utc)  # Monday 08:30 in LA


def course(client, key):
    return next(c for c in client.get("/courses").json() if c["key"] == key)


def block(client, title, start, hours=2):
    return client.post("/tasks", json={"title": title, "planned_start": start.isoformat(),
                                       "planned_end": (start + timedelta(hours=hours)).isoformat(), "priority": 4}).json()


def test_starter_courses_and_your_own_syllabus(client):
    tuf, ml = course(client, "tuf"), course(client, "ml")
    assert tuf["starter"] and tuf["total"] > 40 and tuf["now_at"]["title"].startswith("Things to know")
    assert ml["total"] == 10 and ml["now_at"]["section"].startswith("Course 1")
    r = client.put(f"/courses/{tuf['id']}/outline", json={"text": "# Step 3 · Arrays\n1. Largest element\n2. Second largest\n- Check sorted\n\n# Step 4\nLower bound"})
    c = r.json()
    assert not c["starter"] and [i["title"] for i in c["items"]] == ["Largest element", "Second largest", "Check sorted", "Lower bound"]
    assert c["items"][3]["section"] == "Step 4"
    here = c["items"][2]["id"]
    c = client.post(f"/courses/{tuf['id']}/position", json={"item_id": here}).json()  # "I'm at Check sorted"
    assert c["done"] == 2 and c["now_at"]["title"] == "Check sorted"
    assert client.put(f"/courses/{tuf['id']}/outline", json={"text": "   \n"}).status_code == 422
    assert client.patch(f"/courses/{tuf['id']}", json={"per_block": 2}).json()["per_block"] == 2


def test_block_gets_a_target_and_proof_at_the_end(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    tuf = course(client, "tuf")
    client.put(f"/courses/{tuf['id']}/outline", json={"text": "Largest element\nSecond largest\nCheck sorted\nRemove duplicates"})
    client.patch(f"/courses/{tuf['id']}", json={"per_block": 2})
    t = block(client, "TUF DSA (1/2)", MON)
    with client.session_factory() as db:
        asyncio.run(scheduler.tick(db, client.app.state.orchestrator, MON - timedelta(minutes=4)))
    assert any("Today's target: Largest element; Second largest" in m["content"]
               for c in llm_calls for m in c["messages"])  # the reminder names the target
    client.post(f"/tasks/{t['id']}/respond", json={"action": "start"})
    with client.session_factory() as db:
        asyncio.run(scheduler.tick(db, client.app.state.orchestrator, MON + timedelta(hours=2, minutes=1)))
    ask = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "proof"][-1]
    assert ask["meta"]["proof"] == f"/proof/{t['id']}"
    form = client.get(f"/proof/{t['id']}").json()
    assert [i["title"] for i in form["aimed"]] == ["Largest element", "Second largest"] and form["more"][0]["title"] == "Check sorted"
    first = form["aimed"][0]["id"]
    r = client.post(f"/proof/{t['id']}", json={"done_ids": [first], "note": "halfway through second largest"})
    assert r.status_code == 200 and r.json()["spoke"] == "proof_of_work_verifier"
    tasks = {x["id"]: x for x in client.get("/tasks").json()}
    assert tasks[t["id"]]["status"] == "done"  # partly: some of the target
    c = course(client, "tuf")
    assert c["done"] == 1 and c["now_at"]["title"] == "Second largest"
    log = client.get("/messages").json()
    assert any(m["role"] == "user" and "📋 TUF DSA (1/2): ✅ Largest element" in m["content"] for m in log)
    assert (log[-1]["meta"] or {}).get("outcome") == "some"


def test_nothing_done_counts_as_skipped_and_blocks_before_monday_are_ordinary(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    t = block(client, "TUF DSA (1/2)", MON + timedelta(days=1))
    r = client.post(f"/proof/{t['id']}", json={"done_ids": []})
    assert r.status_code == 200 and {x["id"]: x for x in client.get("/tasks").json()}[t["id"]]["status"] == "skipped"
    early = block(client, "TUF DSA (1/2)", MON - timedelta(days=2))  # this weekend: still testing
    assert client.get(f"/proof/{early['id']}").status_code == 404
    other = block(client, "Gym", MON + timedelta(days=1))
    assert client.get(f"/proof/{other['id']}").status_code == 404


def test_import_a_dated_plan_fills_blocks_by_minutes_and_rebuilds_the_roadmap(client, llm_calls):
    g = client.post("/goals", json={"title": "Finish DSA (NeetCode)"}).json()
    tuf = course(client, "tuf")
    with client.session_factory() as db:
        from app.db.models import Course
        db.get(Course, tuf["id"]).goal_id = g["id"]
        db.commit()
    rows = [{"section": "Sprint 1 · Day 1 · 2026-10-05", "title": "Pattern 1", "kind": "dsa", "est_min": 30, "planned_date": "2026-10-05", "done": True},
            {"section": "Sprint 1 · Day 7 · 2026-10-16", "title": "Basic Hashing", "kind": "dsa", "est_min": 90, "planned_date": "2026-10-16"},
            {"section": "Sprint 1 · Day 7 · 2026-10-16", "title": "Basic String", "kind": "dsa", "est_min": 20, "planned_date": "2026-10-16"},
            {"section": "Sprint 2 · Day 1 · 2026-10-17", "title": "Palindrome Check", "kind": "dsa", "est_min": 20, "planned_date": "2026-10-17"},
            {"section": "Sprint 2 · Day 1 · 2026-10-17", "title": "ACID properties", "kind": "dbms", "est_min": 40, "planned_date": "2026-10-17"}]
    r = client.post(f"/courses/{tuf['id']}/import", json={"items": rows, "title": "TUF RED_CHIP", "active_from": "2026-10-17",
                                                          "roadmap_title": "Finish TUF RED_CHIP by Jan 1, 2027"}).json()
    assert r["title"] == "TUF RED_CHIP" and r["done"] == 1 and not r["starter"] and r["milestones"] == 2
    assert [s["name"] for s in r["sprints"]] == ["Sprint 1", "Sprint 2"] and r["sprints"][0]["done"] == 1
    goal = next(x for x in client.get("/goals").json() if x["id"] == g["id"])
    assert goal["title"] == "Finish TUF RED_CHIP by Jan 1, 2027"
    ms = goal["milestones"]
    assert [m["title"].split(" · ")[0] for m in ms] == ["Sprint 1", "Sprint 2"] and ms[1]["depends_on"] == [ms[0]["id"]]
    assert ms[0]["effort_hours"] == 2.3 and ms[0]["title"] == "Sprint 1 · DSA (Pattern 1 → Basic String)"
    # a 2-hour Saturday block: the backlog first, filled by minutes (90 + 20 + 20 = 130 ≥ 120)
    t = block(client, "TUF DSA — catch-up", datetime(2026, 10, 17, 17, 0, tzinfo=timezone.utc))
    form = client.get(f"/proof/{t['id']}").json()
    assert [i["title"] for i in form["aimed"]] == ["Basic Hashing", "Basic String", "Palindrome Check"]


def test_weekly_analyst_feeds_course_progress_into_the_report(client, llm_calls, monkeypatch):
    from datetime import date

    from app.core import report

    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    tuf = course(client, "tuf")
    rows = [{"section": "Sprint 1 · Day 1 · 2026-10-19", "title": "Pattern 1", "kind": "dsa", "est_min": 60, "planned_date": "2026-10-19"},
            {"section": "Sprint 1 · Day 2 · 2026-10-20", "title": "Pattern 2", "kind": "dsa", "est_min": 60, "planned_date": "2026-10-20"}]
    client.post(f"/courses/{tuf['id']}/import", json={"items": rows, "active_from": "2026-10-19"})
    t = block(client, "TUF DSA (1/2)", MON)
    form = client.get(f"/proof/{t['id']}").json()
    client.post(f"/proof/{t['id']}", json={"done_ids": [form["aimed"][0]["id"]]})
    with client.session_factory() as db:  # it happened during that Monday's block
        from app.db.models import StudyItem
        db.get(StudyItem, form["aimed"][0]["id"]).done_at = MON + timedelta(hours=1)
        db.commit()
    r = client.post("/events", json={"type": "cron.weekly", "payload": {"week_of": "2026-10-19"}, "source": "test"})
    assert "weekly_analyst" in r.json()["ran"]
    with client.session_factory() as db:
        m = report.compute_metrics(db, date(2026, 10, 19))
    tufa = next(c for c in m["analysis"]["courses"] if c["course"] == tuf["title"])
    assert tufa["done_this_week"] == 1 and tufa["planned_this_week"] == 2 and tufa["current_sprint"]["name"] == "Sprint 1"
    page = client.get("/agents").json()
    voice = next(a for ms in page["councils"].values() for a in ms if a["id"] == "voice_agent")
    assert voice["status"] == "active"  # built into the voice pipeline


def _tuf_plan(client, rows):
    tuf = course(client, "tuf")
    client.post(f"/courses/{tuf['id']}/import", json={"items": rows, "active_from": "2026-10-19"})
    return tuf


def test_nightly_planner_briefs_and_proposes_catch_up_that_you_approve(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    day = "2026-10-20"  # Tuesday
    _tuf_plan(client, [{"section": "Sprint 2 · Day 2 · 2026-10-20", "title": f"Topic {n}", "kind": "dsa", "est_min": 60,
                        "planned_date": day} for n in range(5)])  # 5 h of TUF due…
    block(client, "TUF DSA (1/2)", datetime(2026, 10, 20, 15, 30, tzinfo=timezone.utc), hours=2)  # …2 h of blocks (08:30 LA)
    r = client.post("/events", json={"type": "plan.nightly", "payload": {"date": day}, "source": "test"}).json()
    assert r["spoke"] == "daily_planner"
    prop = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "schedule_proposal"][-1]
    ops = prop["meta"]["ops"]
    assert prop["meta"]["buttons"] == ["approve", "reject"] and prop["meta"]["respond"] == f"/proposals/{prop['id']}/respond"
    assert ops and all(o["title"] == "TUF DSA — catch-up" and o["date"] == day for o in ops)
    assert sum(o["duration_min"] for o in ops) >= 120 and all(o["duration_min"] <= 120 for o in ops)
    before = len(client.get("/tasks").json())
    assert len(client.get("/tasks").json()) == before  # nothing added yet
    client.post(prop["meta"]["respond"], json={"action": "approve"})
    assert len(client.get("/tasks").json()) == before + len(ops)
    assert any((m["meta"] or {}).get("kind") == "explained" for m in client.get("/messages").json())


def test_free_gaps_skip_blocks_and_respect_bedtime(client):
    from datetime import date, time

    from app.core import planner
    from app.core.timeutil import to_utc
    block(client, "Class", to_utc(datetime(2026, 10, 20, 10, 0)), hours=3)  # 10:00–13:00 local
    with client.session_factory() as db:
        gaps = planner.free_gaps(db, date(2026, 10, 20), time(6, 0))
    from app.core.timeutil import local
    spans = [(f"{local(a):%H:%M}", f"{local(b):%H:%M}") for a, b in gaps]
    assert spans == [("06:00", "09:55"), ("13:05", "23:00")]


def test_weekly_planner_proposes_weekend_blocks_when_short(client, llm_calls, monkeypatch):
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    rows = [{"section": f"Sprint 3 · Day {n + 1} · 2026-10-2{6 + n % 4}", "title": f"Topic {n}", "kind": "dsa", "est_min": 120,
             "planned_date": f"2026-10-2{6 + n % 4}"} for n in range(6)]  # 12 h next week, no TUF blocks at all
    _tuf_plan(client, rows)
    client.post("/events", json={"type": "cron.weekly", "payload": {"week_of": "2026-10-19"}, "source": "test"})
    prop = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "schedule_proposal"][-1]
    days = {o["date"] for o in prop["meta"]["ops"]}
    assert days <= {"2026-10-31", "2026-11-01"} and days  # Saturday / Sunday of next week
    assert "Sprint 3" in prop["content"]


def test_evening_wrap_waits_for_the_last_block(client):
    from datetime import date, time

    from app.core import scheduler
    from app.core.timeutil import to_utc
    d = date(2026, 10, 21)
    with client.session_factory() as db:
        assert scheduler.wrap_time(db, d) == time(21, 0)  # nothing on: 9 pm
    block(client, "TUF DSA (2/2)", to_utc(datetime(2026, 10, 21, 20, 45)), hours=2)
    with client.session_factory() as db:
        assert scheduler.wrap_time(db, d) == time(22, 50)  # after the 20:45–22:45 block
    block(client, "NumPy & Pandas", to_utc(datetime(2026, 10, 21, 22, 50)), hours=1)
    with client.session_factory() as db:
        assert scheduler.wrap_time(db, d) == time(23, 50)  # never later than 23:50


def test_review_lag_and_what_to_do_now(client, llm_calls, monkeypatch):
    from app.config import get_settings
    monkeypatch.setattr(push, "send", lambda *a, **k: 1)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")
    monkeypatch.setattr(get_settings(), "groq_api_key", "")
    from datetime import date
    today = date.today()
    rows = [{"section": f"Sprint 1 · Day 1 · {today}", "title": f"Topic {n}", "kind": "dsa", "est_min": 30,
             "planned_date": (today.fromordinal(today.toordinal() + n // 10)).isoformat()} for n in range(100)]
    tuf = course(client, "tuf")
    client.post(f"/courses/{tuf['id']}/import", json={"items": rows, "active_from": "2026-10-01"})
    r = client.post("/events", json={"type": "day.review", "payload": {"date": today.isoformat()}, "source": "test"}).json()
    assert "lag_detector" in r["ran"]
    lag = [m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "lag"]
    assert lag and "never finishes" in lag[-1]["content"]  # nothing done in a week: say it plainly
    client.post("/events", json={"type": "day.review", "payload": {"date": today.isoformat()}, "source": "test"})
    assert len([m for m in client.get("/messages").json() if (m["meta"] or {}).get("kind") == "lag"]) == 1  # not every night
    r = client.post("/chat", json={"text": "what should I do now?"}).json()
    assert r["notes"].get("focus_pick", "").startswith("Topic 0 (~30 min")


def test_quiz_cycle_with_spaced_repetition(client, llm_calls, monkeypatch):
    import json as _json
    from datetime import date

    from app.config import get_settings
    from app.core import llm
    monkeypatch.setattr(get_settings(), "gemini_api_key", "x")

    async def fake(messages, tier="smart", **kw):
        sys = messages[0]["content"]
        if "interview-style question" in sys:
            return _json.dumps({"question": "Why is GCD(a, b) = GCD(b, a mod b)?", "key_points": ["common divisors are preserved"]})
        if "Grade a student" in sys:
            return _json.dumps({"correct": True, "feedback": "Right: every common divisor of a and b divides a mod b."})
        return "ok"

    monkeypatch.setattr(llm, "complete", fake)
    tuf = course(client, "tuf")
    old = (date.today().fromordinal(date.today().toordinal() - 3)).isoformat()
    client.post(f"/courses/{tuf['id']}/import", json={"items": [
        {"section": "Sprint 1 · Day 7", "title": "GCD of Two Numbers", "kind": "dsa", "est_min": 13, "planned_date": old, "done": True}]})
    with client.session_factory() as db:  # finished three days ago
        from app.db.models import StudyItem
        it = db.query(StudyItem).filter_by(title="GCD of Two Numbers").one()
        it.done_at = datetime.now(timezone.utc) - timedelta(days=3)
        db.commit()
    r = client.post("/chat", json={"text": "quiz me"}).json()
    assert r["notes"]["coach"]["mode"] == "quiz" and "GCD(a, b)" in r["notes"]["coach"]["question"]
    r = client.post("/chat", json={"text": "because any number dividing both a and b also divides a minus a multiple of b"}).json()
    c = r["notes"]["coach"]
    from app.core.timeutil import local  # TRINETRA's calendar (IST), not this machine's
    today = local(datetime.now(timezone.utc)).date()
    assert c["mode"] == "graded" and c["correct"] and c["next"] == (today + timedelta(days=3)).isoformat()
    r = client.post("/chat", json={"text": "quiz me"}).json()
    assert r["notes"]["coach"]["mode"] == "nothing_yet"  # GCD isn't due again for 3 days
    assert client.post("/chat", json={"text": "explain sliding window"}).json()["notes"]["coach"] == {"mode": "explain", "topic": "sliding window"}
