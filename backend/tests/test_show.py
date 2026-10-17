"""Shows on request: dance, instruments, little moves, stop — and typo-proof emotion requests."""
from app.agents.command import perform_request
from app.core import show


def test_dance_and_instruments():
    assert show.request("can you dance")["show"] == "dance"
    assert show.request("dance")["seconds"] == 10
    for text, inst in [("play the gituar", "guitar"), ("play giyuar", "guitar"), ("play drums", "drums"),
                       ("play the tabla", "drums"), ("piano", "piano"), ("play sax", "sax"), ("do you play cello?", "cello")]:
        r = show.request(text)
        assert r["show"] == "play" and r["instrument"] == inst, text
    r = show.request("play a sad song on piano")
    assert r["mood"] == "sad" and show.label(r) == "🎹 Piano · 😢 Sad"
    assert show.request("play some music")["instrument"] is None


def test_moves_and_stop():
    assert show.request("jump") == {"show": "act", "action": "jump"}
    assert show.request("can you roll")["action"] == "spin"
    assert show.request("can you cry")["action"] == "cry"
    for t in ["stop", "stop the music", "Stop it please", "please stop"]:
        assert show.request(t) == {"show": "stop"}, t
    assert show.label({"show": "stop"}) == "⏹ Stopped"


def test_ordinary_messages_are_not_shows():
    for t in ["where are my keys", "roll a dice", "i love to play football", "i need to stop procrastinating",
              "dance class at 5", "what are you doing", "show me exitement"]:
        assert show.request(t) is None, t


def test_emotion_typos():
    assert perform_request("show me exitement") == ["excited"]
    assert perform_request("show me your angry face") == ["angry"]


def test_music_files_present():
    from pathlib import Path
    static = Path(show.__file__).resolve().parents[1] / "static"
    import json
    model = json.loads((static / "music/model.json").read_text())
    assert model["melody"]["maj"]["o2"] and model["chords"]["min"]["o1"]
    assert (static / "music/samples/guitar/60.mp3").exists() and (static / "music.js").exists()
