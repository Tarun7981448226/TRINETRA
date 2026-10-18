from datetime import datetime, timedelta, timezone

from app.core import autonomy
from app.db.models import Decision, Message


def _sent(db, kind, outcome, n, hours_ago=48):
    t = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    for _ in range(n):
        db.add(Decision(kind=kind, action="sent", outcome=outcome, created_at=t))
    db.commit()


def test_a_new_kind_gets_a_fair_try(client):
    with client.session_factory() as db:
        v = autonomy.decide(db, "free_checkin")
        assert v.send and "P(engage) 0.75" in v.reason


def test_a_nudge_he_keeps_ignoring_fades_and_one_he_answers_stays(client):
    with client.session_factory() as db:
        _sent(db, "streak", "ignored", 8)
        _sent(db, "lag", "engaged", 6)
        assert not autonomy.decide(db, "streak").send
        assert autonomy.decide(db, "lag").send


def test_care_always_gets_through_when_he_is_low(client):
    with client.session_factory() as db:
        _sent(db, "wellbeing", "ignored", 20)
        assert not autonomy.decide(db, "wellbeing").send
        assert autonomy.decide(db, "wellbeing", label="comforting").send


def test_explores_after_five_holds(client):
    with client.session_factory() as db:
        _sent(db, "streak", "ignored", 10)
        for _ in range(5):
            v = autonomy.decide(db, "streak")
            assert not v.send
            autonomy.record(db, "streak", v)
        assert autonomy.decide(db, "streak").send  # tries once: maybe he's changed


def test_different_nudges_dont_pile_up(client):
    with client.session_factory() as db:
        _sent(db, "wellbeing", None, 3, hours_ago=1)
        v = autonomy.decide(db, "free_checkin")
        assert not v.send and "3 recent" in v.reason


def test_settling_learns_from_his_answers(client):
    with client.session_factory() as db:
        t = datetime.now(timezone.utc) - timedelta(hours=2)
        a = Decision(kind="lag", action="sent", created_at=t)
        b = Decision(kind="lag", action="sent", created_at=t - timedelta(hours=3))
        db.add_all([a, b, Message(role="user", content="ok on it", created_at=t + timedelta(minutes=5))])
        db.commit()
        assert autonomy.settle(db) == 2
        assert (a.outcome, b.outcome) == ("engaged", "ignored")
        pol = autonomy.policy(db)
        lag = next(k for k in pol["kinds"] if k["kind"] == "lag")
        assert lag["engaged"] == 1 and lag["settled"] == 2


def test_held_nudges_send_nothing(client, llm_calls, monkeypatch):
    """A held optional nudge from the scheduler: no message, a logged reason."""
    import asyncio
    from app.core.orchestrator import IncomingEvent
    with client.session_factory() as db:
        _sent(db, "wellbeing", "ignored", 30)
        before = db.query(Message).count()
        r = asyncio.run(client.app.state.orchestrator.dispatch(
            IncomingEvent("wellbeing.nudge", {"kind": "hydrate", "minutes": 120}, "scheduler"), db))
        assert db.query(Message).count() == before and r.notes.get("held_back", {}).get("kind") == "wellbeing"
        assert db.query(Decision).filter(Decision.action == "held").count() == 1
    assert client.get("/autonomy").status_code == 200
