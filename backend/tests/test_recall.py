from datetime import datetime, timedelta, timezone

from app.core import embed, recall
from app.core.orchestrator import IncomingEvent
from app.db.models import Memory


def test_local_embeddings_understand_meaning():
    s = embed.similarity("how are his job interviews going", ["Interview with Google on Friday", "Likes biryani",
                                                              "Sleeps at 2am", "Nervous about job interviews"])
    assert s.argmax() == 3 and s[1] < 0.2
    assert embed.embed(["", "😀", "x" * 300]).shape == (3, 256)  # empty, emoji-only, absurd input: no crash


def test_recall_brings_what_matters_now(client):
    with client.session_factory() as db:
        for i in range(30):
            db.add(Memory(kind="event", content=f"Watched episode {i} of a sitcom", importance=2))
        db.add(Memory(kind="profile", content="Tarun studies MSCS at USC", importance=5))
        db.add(Memory(kind="event", content="Has a Google interview on Friday and feels nervous about it", importance=3))
        db.add(Memory(kind="habit", content="Sleeps around 2am on weekdays", importance=3))
        db.commit()
        got = [m.content for m in recall.recall(db, "I'm scared about my interview", k=5)]
        assert "Tarun studies MSCS at USC" in got  # core profile always
        assert any("Google interview" in g for g in got)
        assert sum("sitcom" in g for g in got) <= 3
        m = db.query(Memory).filter(Memory.content.like("%Google interview%")).one()
        assert m.uses == 1 and m.last_used is not None  # recalled → stays fresh


def test_recency_and_strength():
    now = datetime.now(timezone.utc)
    old = Memory(kind="event", content="a", importance=3, created_at=now - timedelta(days=30), uses=0)
    old_but_used = Memory(kind="event", content="a", importance=3, created_at=now - timedelta(days=30), uses=10)
    new = Memory(kind="event", content="a", importance=3, created_at=now, uses=0)
    s = recall.scores([old, old_but_used, new], "", now)
    assert s[2] > s[1] > s[0]  # used often fades slower


def test_forgetter_merges_twins_and_archives_faded_trivia(client, llm_calls):
    from app.agents.memory import forgetter
    from app.core.orchestrator import AgentContext
    from app.config import get_settings
    with client.session_factory() as db:
        long_ago = datetime.now(timezone.utc) - timedelta(days=60)
        db.add_all([Memory(kind="habit", content="Goes to the gym at 6pm", importance=3),
                    Memory(kind="habit", content="Goes to the gym at 6 pm", importance=2),
                    Memory(kind="event", content="Ate pasta for lunch", importance=1, created_at=long_ago, last_used=long_ago),
                    Memory(kind="event", content="Watched a movie", importance=1, created_at=long_ago),  # from before recall
                    Memory(kind="profile", content="Born in Hyderabad", importance=2, created_at=long_ago)])
        db.commit()
        ctx = AgentContext(event=IncomingEvent("cron.nightly"), db=db, settings=get_settings())
        import asyncio
        asyncio.run(forgetter(ctx))
        live = {m.content for m in recall.live(db)}
        # twin merged, faded trivia archived, profile kept; a memory saved before recall existed gets a fresh clock
        assert live == {"Goes to the gym at 6pm", "Born in Hyderabad", "Watched a movie"}
        assert db.query(Memory).count() == 5  # archived, never deleted


def test_reflector_writes_supported_insights(client, monkeypatch):
    import json
    from app.agents.memory import reflector
    from app.config import get_settings
    from app.core import llm
    from app.core.orchestrator import AgentContext
    monkeypatch.setattr(get_settings(), "gemini_api_key", "x")
    with client.session_factory() as db:
        ms = [Memory(kind="habit", content=c, importance=3) for c in
              ("Skips DSA practice after late nights", "Sleeps at 2am before exams", "Does best work at 9am", "Loves cricket")]
        db.add_all(ms); db.commit()
        ids = [m.id for m in ms]

        async def model(messages, **kw):
            return json.dumps({"insights": [
                {"content": "Late nights wreck his next-day DSA practice; protecting sleep protects the streak.", "evidence": ids[:2]},
                {"content": "He just likes cricket.", "evidence": [ids[3]]},  # one fact is not an insight
            ]})
        monkeypatch.setattr(llm, "complete", model)
        import asyncio
        asyncio.run(reflector(AgentContext(event=IncomingEvent("cron.nightly"), db=db, settings=get_settings())))
        insights = [m.content for m in recall.live(db) if m.kind == "insight"]
        assert insights == ["Late nights wreck his next-day DSA practice; protecting sleep protects the streak."]


def test_trained_emotion_reader():
    from app.core import feel
    assert feel.read("I failed the exam again. I am such a disappointment")["low"]
    assert feel.read("im kinda nervous about tmrw interview")["group"] == "fear"
    assert feel.read("thanks a lot man, really appreciate it")["group"] == "joy"
    assert feel.read("what time is my next class")["group"] == "neutral"
    assert feel.read("")["group"] == "neutral"


def test_reader_is_the_fallback_and_second_opinion(client, llm_calls):
    """Offline (the stub LLM returns non-JSON), a sad message without keywords is still heard."""
    body = client.post("/chat", json={"text": "I failed the exam again. I am such a disappointment"}).json()
    assert body["notes"]["felt"]["low"] and body["notes"]["user_mood"] in ("low", "sad")


def test_reader_hears_negation():
    from app.core import feel
    for t in ("not feeling good today", "I am not happy with my progress", "I don't feel ready for this"):
        assert feel.read(t)["low"], t


def test_a_fact_that_stops_being_true_is_retired(client, monkeypatch):
    import json
    from app.config import get_settings
    from app.core import llm
    monkeypatch.setattr(get_settings(), "gemini_api_key", "x")
    with client.session_factory() as db:
        gym = Memory(kind="habit", content="Goes to the gym at 6pm", importance=3)
        db.add(gym); db.commit(); gid = gym.id

    async def model(messages, json_mode=False, **kw):
        if json_mode and "long-term memory" in messages[0]["content"]:
            return json.dumps({"facts": [{"kind": "habit", "content": "Quit the gym; runs in the mornings now", "importance": 3}],
                               "forget": [gid]})
        return "{}" if json_mode else "Got it."
    monkeypatch.setattr(llm, "complete", model)
    body = client.post("/chat", json={"text": "I quit the gym, I run in the mornings now"}).json()
    assert body["notes"]["forgot"] == ["Goes to the gym at 6pm"]
    with client.session_factory() as db:
        assert "Goes to the gym at 6pm" not in {m.content for m in recall.live(db)}
        assert db.get(Memory, gid).archived  # kept, not deleted
