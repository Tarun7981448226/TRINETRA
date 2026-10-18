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
        assert v.send and "0.75" in v.reason


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
        asyncio.run(core.dispatch(IncomingEvent("initiative.evening", {}, "scheduler"), db))
        asyncio.run(core.dispatch(IncomingEvent("initiative.evening", {}, "scheduler"), db))  # once a day
        msgs = [m for m in db.query(Message).all() if (m.meta or {}).get("kind") == "initiative"]
        assert len(msgs) == 1 and "Want me to set that up?" in msgs[0].content
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
    assert body["notes"]["quieter_until"] in body["reply"]  # the reply names the real end of the pause
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


def test_it_learns_when_he_answers_not_just_whether():
    """Answers lag talks in the afternoon, ignores them at night: the same nudge, two different decisions."""
    from app.core.timeutil import user_tz
    import app.core.autonomy as A
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as S
    from app.db.models import Base
    eng = create_engine("sqlite://"); Base.metadata.create_all(eng)
    with S(eng) as db:
        today = datetime.now(user_tz()).replace(minute=0, second=0, microsecond=0)
        for d in range(1, 9):
            day = today - timedelta(days=d)
            db.add(Decision(kind="lag", action="sent", outcome="engaged", created_at=day.replace(hour=14).astimezone(timezone.utc)))
            db.add(Decision(kind="lag", action="sent", outcome="ignored", created_at=day.replace(hour=23).astimezone(timezone.utc)))
        db.commit()
        p_day = A.p_engage(db, "lag", today.replace(hour=15))
        p_night = A.p_engage(db, "lag", today.replace(hour=23))
        assert p_day > 0.75 and p_night < 0.3


def test_a_harsh_nudge_is_rewritten_by_the_critic(monkeypatch):
    import asyncio, json
    from app.agents import planning
    from app.core import llm

    async def model(messages, **kw):
        return json.dumps({"ok": False, "fixed": "You're two blocks behind on DSA this week. Want to grab one tonight?"})
    monkeypatch.setattr(llm, "complete", model)
    out = asyncio.run(planning._critique("You're pathetic, you never finish anything.", "lag"))
    assert out.startswith("You're two blocks behind")

    async def fine(messages, **kw):
        return json.dumps({"ok": True})
    monkeypatch.setattr(llm, "complete", fine)
    assert asyncio.run(planning._critique("Two blocks behind — one tonight?", "lag")) == "Two blocks behind — one tonight?"


def test_initiative_has_its_own_evening_beat_once(client, llm_calls, monkeypatch):
    import asyncio
    from datetime import datetime as _dt
    from app.core import scheduler, timeutil
    evening = _dt.now(timeutil.user_tz()).replace(hour=20, minute=5)
    monkeypatch.setattr(scheduler, "now_local", lambda: evening)
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        assert asyncio.run(scheduler.initiative_watch(db, core)) is True
        assert asyncio.run(scheduler.initiative_watch(db, core)) is False  # once per evening
    monkeypatch.setattr(scheduler, "now_local", lambda: evening.replace(hour=15))
    with client.session_factory() as db:
        assert asyncio.run(scheduler.initiative_watch(db, client.app.state.orchestrator)) is False


def test_policy_shows_his_best_time(client):
    from app.core.timeutil import user_tz
    with client.session_factory() as db:
        today = datetime.now(user_tz()).replace(minute=0, second=0, microsecond=0)
        for d in range(1, 6):
            day = today - timedelta(days=d)
            db.add(Decision(kind="lag", action="sent", outcome="engaged", created_at=day.replace(hour=14).astimezone(timezone.utc)))
            db.add(Decision(kind="lag", action="sent", outcome="ignored", created_at=day.replace(hour=23).astimezone(timezone.utc)))
        db.commit()
        lag = next(k for k in autonomy.policy(db)["kinds"] if k["kind"] == "lag")
        assert lag["best_time"] == "afternoon" and lag["by_part_of_day"]["afternoon"] > lag["by_part_of_day"]["night"]


def test_reflection_has_its_own_night_beat_once(client, llm_calls, monkeypatch):
    import asyncio
    from datetime import datetime as _dt
    from app.core import scheduler, timeutil
    four = _dt.now(timeutil.user_tz()).replace(hour=4, minute=10)
    monkeypatch.setattr(scheduler, "now_local", lambda: four)
    with client.session_factory() as db:
        core = client.app.state.orchestrator
        assert asyncio.run(scheduler.reflect_watch(db, core)) is True
        assert asyncio.run(scheduler.reflect_watch(db, core)) is False
    assert client.app.state.orchestrator.registry.specs["reflector"].triggers == ["reflect.nightly"]


def test_quiet_mode_also_holds_nudges_from_his_own_taps(client, llm_calls):
    """'Streak cheers are off' must be true even when the cheer comes from a button tap (source api, not scheduler)."""
    import asyncio
    from app.agents.planning import _speak_up
    from app.config import get_settings
    from app.core.orchestrator import AgentContext, IncomingEvent
    with client.session_factory() as db:
        autonomy.quieter(db)
        db.commit()
        ctx = AgentContext(event=IncomingEvent("task.done", {"task_id": 1}, "api"), db=db, settings=get_settings())
        r = asyncio.run(_speak_up(ctx, instruction="cheer", fallback="🔥 7 days in a row", mood="proud",
                                  meta={"kind": "streak"}, keep_mood=True, channel="web"))
        assert r.reply is None and ctx.notes["held_back"]["kind"] == "streak"
        autonomy.louder(db)
        r = asyncio.run(_speak_up(ctx, instruction="cheer", fallback="🔥 7 days in a row", mood="proud",
                                  meta={"kind": "streak"}, keep_mood=True, channel="web"))
        assert r.reply  # back on: his taps get their cheer again
