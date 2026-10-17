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
