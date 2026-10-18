import pytest

from app.core import mood, voice
from tests.conftest import trinetra_prompt


@pytest.mark.parametrize("text, expected", [
    ("be angry with me", "angry"),
    ("I want the angry version", "angry"),
    ("talk to me in an angry voice", "angry"),
    ("angry mode please", "angry"),
    ("scold me, I wasted the whole day", "angry"),
    ("yell at me", "angry"),
    ("be strict with me today", "strict"),
    ("hype me up", "hype"),
    ("be gentle with me", "gentle"),
    ("ok back to normal", None),
    ("calm down trinetra", None),
])
def test_mode_requests_are_detected(text, expected):
    assert mood.detect_request(text) == (True, expected)


@pytest.mark.parametrize("text", [
    "my boss was angry at me today",
    "I studied hard, how are you",
    "I'm mad tired",
])
def test_ordinary_sentences_dont_switch_mode(text):
    assert mood.detect_request(text) == (False, None)


def test_angry_mode_sticks_until_reset(client, llm_calls):
    body = client.post("/chat", json={"text": "be angry with me"}).json()
    assert body["notes"]["mode_changed"] == "angry"
    assert body["mood"].startswith("ANGRY")
    assert "switch to angry mode" in trinetra_prompt(llm_calls)
    assert client.get("/mode").json() == {"mode": "angry", "label": "😠 angry"}

    body = client.post("/chat", json={"text": "what's next on my plan?"}).json()
    assert body["mood"].startswith("ANGRY")  # still angry

    body = client.post("/chat", json={"text": "ok back to normal"}).json()
    assert not body["mood"].startswith("ANGRY")
    assert client.get("/mode").json()["mode"] is None


def test_distress_beats_angry_mode(client, llm_calls):
    client.post("/chat", json={"text": "angry mode"})
    body = client.post("/chat", json={"text": "honestly I feel hopeless"}).json()
    assert "no pressure" in body["mood"]


def test_sadness_beats_angry_mode(client, llm_calls):
    """Not crisis-level, just sad: the Emotion Engine says 'comforting', and a requested angry mode must not override it."""
    client.post("/chat", json={"text": "angry mode"})
    body = client.post("/chat", json={"text": "I feel so sad and lonely today"}).json()
    assert not body["mood"].startswith("ANGRY") and "comfort" in body["mood"]
    assert client.get("/mode").json()["mode"] == "angry"  # the mode is still there for when he's better


def test_chip_reset_and_validation(client):
    assert client.post("/mode", json={"mode": "angry"}).json()["mode"] == "angry"
    assert client.post("/mode", json={"mode": None}).json()["mode"] is None
    assert client.post("/mode", json={"mode": "evil"}).status_code == 422


def test_angry_voice_is_louder_and_faster():
    rate, pitch, volume = voice.prosody(mood.MODES["angry"])
    assert int(rate.rstrip("%")) > 0 and int(volume.rstrip("%")) >= 30


@pytest.mark.parametrize("text, expected", [
    ("scold Rahul", ("angry", "Rahul")),
    ("scold my brother for not studying", ("angry", "brother")),
    ("yell at Priya", ("angry", "Priya")),
    ("show me your angry version", ("angry", None)),
    ("demonstrate how you would scold someone", ("angry", None)),
    ("let me hear the gentle version", ("gentle", None)),
    ("show me how you'd hype someone up", ("hype", None)),
])
def test_demo_requests(text, expected):
    assert mood.detect_demo(text) == expected


def test_scold_me_is_not_a_demo():
    assert mood.detect_demo("scold me") is None
    assert mood.detect_demo("show me my timetable") is None


def test_demo_performs_once_without_changing_mode(client, llm_calls):
    body = client.post("/chat", json={"text": "scold Rahul for skipping the gym"}).json()
    assert body["mood"].startswith("ANGRY")
    assert "ONE-TIME demonstration" in trinetra_prompt(llm_calls)
    assert "Rahul" in trinetra_prompt(llm_calls)
    assert client.get("/mode").json()["mode"] is None

    body = client.post("/chat", json={"text": "thanks, how are you"}).json()
    assert not body["mood"].startswith("ANGRY")


def test_demo_does_not_cancel_a_lasting_mode(client, llm_calls):
    client.post("/chat", json={"text": "hype mode"})
    client.post("/chat", json={"text": "show me your angry version"})
    assert client.get("/mode").json()["mode"] == "hype"


# ---------- Emotion Engine ----------

from datetime import datetime, timedelta, timezone  # noqa: E402

from app.core import emotion  # noqa: E402


def _skip(state, n=1):
    for _ in range(n):
        emotion.react(state, "task.skipped", {}, priority=3, strictness=3)


def test_anger_escalates_with_repeated_skips():
    state = emotion.EmotionState()
    labels = []
    for _ in range(3):
        _skip(state)
        labels.append(emotion.expression(state)[1])
    assert labels == ["soft angry", "firm angry", "angry"]


def test_sadness_outranks_anger():
    state = emotion.EmotionState()
    _skip(state, 3)
    emotion.react(state, "user.message", {"user_mood": "sad", "user_mood_intensity": 0.8})
    assert emotion.expression(state)[1] == "comforting"


def test_finishing_things_brings_pride():
    state = emotion.EmotionState()
    for _ in range(2):
        emotion.react(state, "task.done", {}, priority=3)
    assert emotion.expression(state)[1] == "proud"


def test_feelings_fade_over_time():
    state = emotion.EmotionState()
    _skip(state, 3)
    later = datetime.now(timezone.utc) + timedelta(hours=18)
    emotion.decay(state, later)
    assert emotion.expression(state)[1] == "calm"


def test_strictness_dial_changes_how_fast_anger_builds():
    gentle, relentless = emotion.EmotionState(), emotion.EmotionState()
    emotion.react(gentle, "task.skipped", {}, strictness=1)
    emotion.react(relentless, "task.skipped", {}, strictness=5)
    assert gentle.frustration < relentless.frustration


def test_skip_buttons_make_trinetra_progressively_angrier(client, llm_calls):
    from app.core.timeutil import now_local
    moods = []
    for i in range(3):
        start = now_local() + timedelta(hours=2 + i)
        t = client.post("/tasks", json={"title": f"Study {i}", "planned_start": start.isoformat(),
                                        "planned_end": (start + timedelta(hours=1)).isoformat()}).json()
        moods.append(client.post(f"/tasks/{t['id']}/respond", json={"action": "skip"}).json()["mood"])
    assert moods[0].startswith("softly annoyed")
    assert moods[1].startswith("firm and angry")
    assert moods[2].startswith("ANGRY")
    assert client.get("/emotion").json()["label"] == "angry"


def test_empathy_offline_fallback_comforts(client, llm_calls):
    body = client.post("/chat", json={"text": "I feel so sad and down today"}).json()
    assert body["notes"]["user_mood"] == "sad"
    assert "comfort" in body["mood"]
