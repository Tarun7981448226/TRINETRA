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
    assert show.request("jump") == {"show": "act", "action": "jump", "actions": ["jump"]}
    assert show.request("can you roll")["action"] == "spin"
    assert show.request("can you cry")["action"] == "cry"
    for t in ["stop", "stop the music", "Stop it please", "please stop"]:
        assert show.request(t) == {"show": "stop"}, t
    assert show.label({"show": "stop"}) == "⏹ Stopped"


def test_ordinary_messages_are_not_shows():
    for t in ["where are my keys", "roll a dice", "i love to play football", "i need to stop procrastinating",
              "dance class at 5", "what are you doing", "show me exitement", "play football", "let us play a game", "play chess with me"]:
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


def test_world_and_shadow_assets(client):
    """The portfolio world script is public, and the shadow lives outside the moving body (so it never rotates)."""
    r = client.get("/static/brain.js")
    assert r.status_code == 200 and "TrinetraBrain" in r.text and "thalamus" in r.text.lower()
    for team in ("command", "time_planning", "reminders", "monitoring", "learning", "coaching", "wellbeing", "memory", "communications", "mentor_emotion"):
        assert f"{team}: [" in r.text, team  # every council has a brain region
    buddy = client.get("/static/buddy.js").text
    assert '<div class="tb-shadow"></div><div class="tb-mover">' in buddy  # sibling of the mover, not inside it
    assert 'ellipse cx="8" cy="13.6"' not in buddy and 'ellipse cx="50" cy="89"' not in buddy
    assert "setSuit(" in buddy and "hold(act)" in buddy and "bodyURL(" in buddy  # fuzzy dolls rasterised for speed
    assert "loadWorld" in client.get("/guest/eye.js").text


def test_public_agents_org_chart(client):
    """The portfolio lab shows the real team: every agent, 10 councils, one manager each, written about Tarun."""
    d = client.get("/guest/agents").json()
    teams = d["teams"]
    assert d["total"] == sum(len(t["members"]) for t in teams) and len(teams) == 10
    for t in teams:
        assert t["manager"] in {m["id"] for m in t["members"]}, t["id"]
        for m in t["members"]:
            assert " you " not in f" {m['role'].lower()} " and "your " not in m["role"].lower(), m["role"]
    assert d["active"] < d["total"]  # some agents are still being built


def test_lab_orders():
    assert show.request("assemble", lab=True) == {"show": "lab", "cmd": "assemble"}
    assert show.request("what do your agents do", lab=True)["cmd"] == "roles"
    assert show.request("show me your lab", lab=True) == {"show": "lab", "cmd": None}
    assert show.request("assemble") is None  # Tarun's own app: no lab, normal chat
    assert show.request("line up my blocks for tomorrow", lab=True) is None
    assert show.label({"show": "lab", "cmd": "assemble"}) == "🧍 Assemble"
    for t in ["i need to assemble furniture", "what do you do", "where are my keys", "Line up a call with Tarun", "see the world"]:
        assert show.request(t, lab=True) is None, t
