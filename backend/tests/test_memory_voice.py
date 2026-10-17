import json

from app.core import llm, voice
from app.db.models import Memory


def test_memory_agent_saves_and_updates_facts(client, monkeypatch):
    with client.session_factory() as db:
        db.add(Memory(kind="goal", content="Wants to learn DSA", importance=3))
        db.commit()

    async def fake_complete(messages, tier="smart", json_mode=False, **kw):
        if json_mode:
            assert "1: (goal) Wants to learn DSA" in messages[0]["content"]
            return json.dumps({"facts": [
                {"kind": "goal", "content": "Wants to crack DSA interviews by March", "importance": 5, "replaces": 1},
                {"kind": "person", "content": "Has a sister named Priya", "importance": 3, "replaces": None},
            ]})
        return "Got it."

    monkeypatch.setattr(llm, "complete", fake_complete)
    body = client.post("/chat", json={"text": "My goal is cracking DSA interviews by March. My sister Priya helps me."}).json()
    assert len(body["notes"]["remembered"]) == 2

    mems = client.get("/memories").json()
    assert [m["content"] for m in mems] == ["Wants to crack DSA interviews by March", "Has a sister named Priya"]
    assert client.delete(f"/memories/{mems[1]['id']}").status_code == 204
    assert len(client.get("/memories").json()) == 1


def test_memory_agent_survives_bad_llm_output(client, llm_calls):
    body = client.post("/chat", json={"text": "I wake up at 6 every day"}).json()
    assert body["reply"] == "Got it, I'm on it."  # reply still arrives
    assert client.get("/memories").json() == []


def test_history_is_restored(client):
    client.post("/chat", json={"text": "hello there"})
    rows = client.get("/messages").json()
    assert [r["role"] for r in rows] == ["user", "trinetra"]


def test_router_no_longer_angry_at_didnt():
    import re
    from app.agents.command import INTENT_PATTERNS
    assert not re.search(INTENT_PATTERNS["slacking"], "i didnt mention you that yesterday", re.I)
    assert re.search(INTENT_PATTERNS["slacking"], "I didn't study today", re.I)


def test_mood_shapes_voice():
    assert voice.mood_family("firm and disappointed — push them") == "firm"
    assert voice.mood_family("deeply caring — no pressure at all") == "comfort"
    assert voice.mood_family("gentle and comforting") == "gentle"
    assert voice.mood_family("softly annoyed — disappointed but still warm") == "annoyed"
    assert voice.mood_family("firm and angry — raised voice") == "firm_angry"
    assert voice.mood_family("proud and energised") == "proud"
    assert voice.mood_family(None) == "calm"
    assert voice.clean_for_speech("How are *you* doing?") == "How are you doing?"


def test_angry_moods_ask_the_app_for_the_furious_effect(client, monkeypatch):
    async def fake_speak(text, mood=None):
        return b"ID3fake"

    monkeypatch.setattr(voice, "speak", fake_speak)
    r = client.post("/speak", json={"text": "Get up!", "mood": "ANGRY — fired up"})
    assert r.headers["x-trinetra-effect"] == "angry"
    r = client.post("/speak", json={"text": "Hey.", "mood": "calm and caring"})
    assert r.headers["x-trinetra-effect"] == "none"
    assert voice.effect_for("firm and angry — raised voice") == "firm_angry"
