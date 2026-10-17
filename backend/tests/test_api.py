from sqlalchemy import func, select

from app.core.timeutil import now_local
from app.db.models import Event, Message
from tests.conftest import trinetra_prompt


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "awake"


def test_agents_listing(client):
    body = client.get("/agents").json()
    assert body["total"] >= 64
    assert body["active"] == 23


def test_chat_flows_through_agents_and_is_remembered(client, llm_calls):
    r = client.post("/chat", json={"text": "I skipped the gym today"})
    body = r.json()
    assert r.status_code == 200
    assert body["reply"] == "Got it, I'm on it."
    assert body["spoke"] == "core_orchestrator"
    assert body["ran"][:2] == ["data_collector", "router"]
    assert body["notes"]["intent"] == "slacking"
    assert "firm" in body["mood"]

    with client.session_factory() as db:
        assert db.scalar(select(func.count()).select_from(Message)) == 2
        assert db.scalar(select(func.count()).select_from(Event)) == 1


def test_distress_switches_to_care(client, llm_calls):
    body = client.post("/chat", json={"text": "I skipped everything, I feel hopeless"}).json()
    assert body["notes"]["distress"] is True
    assert "no pressure" in body["mood"]
    system = trinetra_prompt(llm_calls)
    assert "no pressure" in system


def test_today_timetable_reaches_the_brain(client, llm_calls):
    start = now_local().replace(hour=23, minute=0, second=0, microsecond=0)
    r = client.post(
        "/tasks",
        json={"title": "DSA practice", "planned_start": start.isoformat(),
              "planned_end": start.replace(minute=50).isoformat()},
    )
    assert r.status_code == 201, r.text
    client.post("/chat", json={"text": "what's on today?"})
    system = trinetra_prompt(llm_calls)
    assert "23:00–23:50 DSA practice [planned]" in system


def test_naive_times_are_read_as_local_and_returned_in_utc(client):
    r = client.post(
        "/tasks",
        json={"title": "Gym", "planned_start": "2026-10-20T06:00:00", "planned_end": "2026-10-20T07:00:00"},
    )
    # Asia/Kolkata is UTC+5:30
    assert r.json()["planned_start"].startswith("2026-10-20T00:30:00")


def test_task_lifecycle_emits_events(client):
    task = client.post(
        "/tasks",
        json={"title": "Read", "planned_start": "2026-10-20T21:00:00", "planned_end": "2026-10-20T21:30:00"},
    ).json()
    r = client.patch(f"/tasks/{task['id']}", json={"status": "done", "rating": 4})
    assert r.status_code == 200
    assert r.json()["actual_end"] is not None
    with client.session_factory() as db:
        types = db.scalars(select(Event.type).order_by(Event.id)).all()
    assert types == ["task.created", "task.done"]


def test_bad_task_times_rejected(client):
    r = client.post(
        "/tasks",
        json={"title": "X", "planned_start": "2026-10-20T10:00:00", "planned_end": "2026-10-20T09:00:00"},
    )
    assert r.status_code == 422


def test_external_event_ingest(client):
    r = client.post("/events", json={"type": "shortcut.app_opened", "payload": {"app": "Instagram"}, "source": "shortcut"})
    assert r.status_code == 200
    assert r.json()["ran"] == ["data_collector", "emotion_engine"]
    assert client.post("/events", json={"type": "BAD TYPE"}).status_code == 422
