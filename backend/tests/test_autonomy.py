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
        v = autonomy.decide(db, "why")
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
        v = autonomy.decide(db, "why")
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


def test_initiative_asks_first_and_a_yes_goes_through_the_pipeline(client, monkeypatch):
    """Its own idea for his good: one per evening, needs evidence, asked as a yes/no; a yes becomes his message."""
    import asyncio, json
    from app.config import get_settings
    from app.core import llm
    from app.core.orchestrator import IncomingEvent
    from app.db.models import Memory
    monkeypatch.setattr(get_settings(), "gemini_api_key", "x")
    seen = []

    async def model(messages, **kw):
        seen.append(messages[-1]["content"])
        if "thinking on your own" in messages[-1]["content"]:
            return json.dumps({"idea": "Move DSA practice to 9am on weekdays", "why": "you finish 80% of morning blocks"})
        return "{}" if kw.get("json_mode") else "Done — DSA is at 9 now."
    monkeypatch.setattr(llm, "complete", model)
    from datetime import datetime as _dt
    from app.core import timeutil
    evening = _dt.now(timeutil.user_tz()).replace(hour=21, minute=0)
    monkeypatch.setattr(timeutil, "now_local", lambda: evening)
    with client.session_factory() as db:
        db.add(Memory(kind="insight", content="He finishes morning blocks, skips night ones", importance=4))
        db.commit()
        core = client.app.state.orchestrator
        asyncio.run(core.dispatch(IncomingEvent("plan.nightly", {}, "scheduler"), db))
        asyncio.run(core.dispatch(IncomingEvent("plan.nightly", {}, "scheduler"), db))  # once a day
        msgs = [m for m in db.query(Message).all() if (m.meta or {}).get("kind") == "initiative"]
        assert len(msgs) == 1 and "Want me to do it?" in msgs[0].content
        assert db.query(Decision).filter(Decision.kind == "initiative", Decision.action == "sent").count() == 1
        mid = msgs[0].id
    r = client.post(f"/proposals/{mid}/respond", json={"action": "approve"})
    assert r.status_code == 200
    assert any("Yes, do it: Move DSA practice to 9am" in s for s in seen)
    assert client.post(f"/proposals/{mid}/respond", json={"action": "approve"}).status_code == 409  # once


def test_stop_nagging_me_is_respected(client, llm_calls):
    from tests.conftest import trinetra_prompt
    body = client.post("/chat", json={"text": "stop nagging me so much"}).json()
    assert body["notes"]["quieter_until"] and "turned your OPTIONAL nudges" in trinetra_prompt(llm_calls)
    with client.session_factory() as db:
        v = autonomy.decide(db, "lag")
        assert not v.send and "back off" in v.reason
        assert autonomy.decide(db, "wellbeing", label="comforting").send  # care still gets through
    client.post("/chat", json={"text": "ok you can nudge me again"})
    with client.session_factory() as db:
        assert autonomy.decide(db, "lag").send


def test_knowing_nothing_is_said_honestly(client, llm_calls):
    from tests.conftest import trinetra_prompt
    client.post("/chat", json={"text": "what do you know about me?"})
    assert "nothing saved yet" in trinetra_prompt(llm_calls)


def test_an_idea_is_settled_by_his_answer(client):
    with client.session_factory() as db:
        t = datetime.now(timezone.utc) - timedelta(hours=1)
        yes = Message(role="trinetra", content="idea", meta={"kind": "initiative", "answered": "approve"})
        no = Message(role="trinetra", content="idea", meta={"kind": "initiative", "answered": "reject"})
        db.add_all([yes, no]); db.flush()
        a = Decision(kind="initiative", action="sent", created_at=t, message_id=yes.id)
        b = Decision(kind="initiative", action="sent", created_at=t, message_id=no.id)
        db.add_all([a, b, Message(role="user", content="✋ Not now.", created_at=t + timedelta(minutes=1))]); db.commit()
        autonomy.settle(db)
        assert (a.outcome, b.outcome) == ("engaged", "ignored")  # a "no" is not engagement


def test_quiet_mode_is_not_triggered_by_ordinary_sentences(client, llm_calls):
    for t in ("can you back off the gym to 7pm", "leave me alone for an hour to study", "don't leave me alone tonight"):
        assert "quieter_until" not in client.post("/chat", json={"text": t}).json()["notes"], t
    client.post("/chat", json={"text": "stop nagging me"})
    client.post("/chat", json={"text": "never nudge me again"})  # not a request to turn them back on
    with client.session_factory() as db:
        assert autonomy.quiet_until(db) is not None
