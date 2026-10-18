"""WhatsApp autopilot: TRINETRA answers simple messages like Tarun while he's busy and offline; everything else is his."""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from app.config import get_settings
from app.core import llm, push, style, whatsapp
from app.db.models import Event, KeyValue, Message, WaContact, WaMessage, WaSession

KEY = "bridge-secret"
RAVI = "919800000001@s.whatsapp.net"
MOM = "919800000002@s.whatsapp.net"


@pytest.fixture
def wa(client, monkeypatch):
    """A configured bridge that records what it was asked to send, a model that answers in JSON, and recorded pushes."""
    monkeypatch.setattr(get_settings(), "trinetra_bridge_url", "https://bridge.test")
    monkeypatch.setattr(get_settings(), "trinetra_bridge_key", KEY)
    sent, pushes, model = [], [], {"kind": "simple", "confidence": 0.95, "reply": "haha ya all good ra, tell"}

    async def fake_complete(messages, tier="smart", **kw):
        if "WhatsApp reply as Tarun" in messages[0]["content"]:
            return json.dumps(model)
        return "Got it."

    monkeypatch.setattr(llm, "complete", fake_complete)
    monkeypatch.setattr(whatsapp, "bridge_send", lambda jid, text: sent.append((jid, text)) or True)
    monkeypatch.setattr(push, "send", lambda db, title, body, url="/", tag=None: pushes.append(body) or 1)
    client.sent, client.pushes, client.model = sent, pushes, model
    # he has chatted with Ravi and Mom before (so they're not strangers)
    event(client, "history", {"messages": [
        {"id": "h1", "jid": RAVI, "text": "bro what's up", "from_me": False, "ts": "2026-10-10T10:00:00+00:00", "name": "Ravi"},
        {"id": "h2", "jid": RAVI, "text": "nothing much ra, chill", "from_me": True, "ts": "2026-10-10T10:02:00+00:00"},
        {"id": "h3", "jid": MOM, "text": "did you eat?", "from_me": False, "ts": "2026-10-10T11:00:00+00:00", "name": "Mom"},
        {"id": "h4", "jid": MOM, "text": "ha amma, ate", "from_me": True, "ts": "2026-10-10T11:05:00+00:00"},
    ]})
    return client


def event(client, kind, data, key=KEY):
    return client.post("/whatsapp/event", json={"type": kind, "data": data}, headers={"Authorization": f"Bearer {key}"})


def text_in(client, jid, text, n=[0], **extra):
    n[0] += 1
    return event(client, "message", {"id": f"m{n[0]}-{text[:8]}", "jid": jid, "text": text,
                                     "ts": datetime.now(timezone.utc).isoformat(), **extra}).json()


def away(client, minutes=10):
    """He was last on WhatsApp this long ago."""
    with client.session_factory() as db:
        whatsapp._put(db, "wa_last_active", (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat())
        db.commit()


def busy(client, choice="busy60"):
    return client.post("/whatsapp/busy", json={"action": choice}).json()


def test_only_the_bridge_can_post_events(wa):
    assert event(wa, "activity", {}, key="wrong").status_code == 401
    assert wa.post("/whatsapp/event", json={"type": "activity", "data": {}}).status_code == 401


def test_he_is_online_so_it_does_nothing(wa):
    event(wa, "activity", {})  # he just read something on his phone
    assert text_in(wa, RAVI, "hey")["route"] == "online"
    assert not wa.sent and not wa.pushes


def test_offline_it_asks_are_you_busy_once_then_answers_for_him(wa):
    assert text_in(wa, RAVI, "hey bro")["route"] == "asked"
    assert "Ravi messaged on WhatsApp. Are you busy?" in wa.pushes[-1]
    with wa.session_factory() as db:
        q = db.scalar(select(Message).where(Message.channel == "whatsapp").order_by(Message.id.desc()))
        assert q.meta["kind"] == "wa_busy" and "busy60" in q.meta["buttons"] and q.meta["respond"] == "/whatsapp/busy"
    assert text_in(wa, RAVI, "u there?")["route"] == "waiting"  # no second "are you busy?" within half an hour
    assert len([p for p in wa.pushes if "Are you busy" in p]) == 1
    out = busy(wa, "busy60")  # yes, for an hour → the two waiting messages get answered
    assert "until" in out["reply"] and "2 that came in" in out["reply"]
    assert len(wa.sent) == 2 and all(t.endswith(" 🤖") and t.startswith("haha ya all good ra") for _, t in wa.sent)
    assert text_in(wa, RAVI, "cool cool")["did"] == "replied" and len(wa.sent) == 3


def test_not_busy_means_it_leaves_whatsapp_to_him(wa):
    text_in(wa, RAVI, "hey")
    assert "leave WhatsApp to you" in busy(wa, "not_busy")["reply"]
    assert not wa.sent
    with wa.session_factory() as db:
        assert db.scalar(select(WaSession)) is None


def test_opening_whatsapp_pauses_it_and_leaving_again_resumes(wa):
    busy(wa, "busy120")
    event(wa, "activity", {})  # he opened WhatsApp
    with wa.session_factory() as db:
        assert db.scalar(select(WaSession)).state == "paused"
    assert text_in(wa, RAVI, "yo")["route"] == "online" and not wa.sent
    away(wa, 5)  # he left WhatsApp a few minutes ago
    assert text_in(wa, RAVI, "hello?")["did"] == "replied" and len(wa.sent) == 1
    with wa.session_factory() as db:
        s = db.scalar(select(WaSession))
        assert s.state == "active" and [i["did"] for i in s.log][:2] == ["paused", "resumed"]


def test_the_heartbeat_resumes_a_paused_session_once_he_has_gone(wa):
    busy(wa, "busy60")
    event(wa, "activity", {})
    away(wa, 5)
    import asyncio
    with wa.session_factory() as db:
        assert asyncio.run(whatsapp.tick(db)) == "resumed"
        db.commit()


@pytest.mark.parametrize("jid,text,why", [
    (RAVI, "can we meet tomorrow evening?", "plan"),
    (RAVI, "your OTP is 482913, don't share it", "codes"),
    (RAVI, "bro can you lend me 2000 rs", "money"),
    (MOM, "URGENT call me now, dad is in hospital", "urgent"),
    ("919800000099@s.whatsapp.net", "hi, is this tarun?", "haven't chatted"),
    (RAVI, "bro are you okay? you seem off", "personal"),
    (MOM, "sorry about yesterday", "personal"),
])
def test_serious_things_always_go_to_him(wa, jid, text, why):
    busy(wa, "busy60")
    assert text_in(wa, jid, text, name="Someone")["did"] == "for_you"
    assert not wa.sent
    assert why in wa.pushes[-1] and "left it for you" in wa.pushes[-1]
    if why == "urgent":
        with wa.session_factory() as db:
            assert db.scalar(select(WaMessage).where(WaMessage.text == text)).handled == "for_you"


def test_groups_are_never_answered(wa):
    busy(wa, "busy60")
    assert text_in(wa, "1203630@g.us", "who's coming tonight", group=True)["route"] == "group"
    assert not wa.sent


def test_when_the_model_isnt_sure_it_leaves_it_for_him(wa):
    busy(wa, "busy60")
    wa.model.update(kind="needs_tarun", confidence=0.4, reply="will tell you later ra")
    assert text_in(wa, RAVI, "what did the professor say about the project?")["did"] == "for_you"
    assert not wa.sent and "Suggested: “will tell you later ra”" in wa.pushes[-1]


def test_the_hourly_cap_holds(wa, monkeypatch):
    monkeypatch.setattr(whatsapp, "MAX_PER_HOUR", 3)
    busy(wa, "busy60")
    did = [text_in(wa, RAVI, f"hey {i}")["did"] for i in range(5)]
    assert did == ["replied"] * 3 + ["for_you"] * 2 and len(wa.sent) == 3


def test_coming_online_while_it_types_cancels_the_reply(wa):
    busy(wa, "busy60")
    text_in(wa, RAVI, "sup")
    event(wa, "cancelled", {"jid": RAVI, "text": wa.sent[-1][1]})
    with wa.session_factory() as db:
        m = db.scalar(select(WaMessage).where(WaMessage.text == "sup"))
        assert m.handled == "for_you" and "came online" in m.note


def test_the_kill_switch_stops_everything(wa):
    busy(wa, "busy60")
    wa.post("/whatsapp/autopilot", json={"on": False})
    assert text_in(wa, RAVI, "hey")["route"] == "off" and not wa.sent
    with wa.session_factory() as db:
        assert db.scalar(select(WaSession)).state == "ended"


def test_time_up_ends_with_a_summary(wa):
    busy(wa, "busy30")
    text_in(wa, RAVI, "hey")
    text_in(wa, MOM, "call me when free")
    import asyncio
    with wa.session_factory() as db:
        assert asyncio.run(whatsapp.tick(db, datetime.now(timezone.utc) + timedelta(minutes=31))) == "ended"
        db.commit()
    summary = wa.pushes[-1]
    assert "I replied 1 time (Ravi)" in summary and "Mom: “call me when free”" in summary


def test_telling_trinetra_im_busy_starts_it_and_im_back_ends_it(wa):
    wa.post("/chat", json={"text": "I'm in deep research for 2 hours, handle things"})
    with wa.session_factory() as db:
        s = db.scalar(select(WaSession))
        left = whatsapp.from_db(s.until) - datetime.now(timezone.utc)
        assert s.state == "active" and timedelta(minutes=118) < left <= timedelta(hours=2)
    text_in(wa, RAVI, "hey")
    wa.post("/chat", json={"text": "I'm back"})
    with wa.session_factory() as db:
        assert db.scalar(select(WaSession)).state == "ended"
    assert "I replied 1 time (Ravi)" in wa.pushes[-1]


def test_only_a_real_busy_request_starts_it():
    from app.agents.whatsapp import busy_until
    now = datetime(2026, 10, 18, 14, 0)
    assert busy_until("I'm busy with DSA right now", now) is None  # just chat
    assert busy_until("how busy is my day tomorrow", now) is None
    assert busy_until("I'm in a meeting for 45 minutes", now) is not None
    assert busy_until("take care of my whatsapp till 5pm", now) is not None
    assert busy_until("handle my messages", now) is not None  # an hour when he doesn't say


def test_other_peoples_words_never_reach_the_event_log(wa):
    busy(wa, "busy60")
    text_in(wa, RAVI, "my secret is PINEAPPLE-42")
    with wa.session_factory() as db:
        assert "PINEAPPLE" not in " ".join(json.dumps(e.payload) for e in db.scalars(select(Event)))


def test_his_style_is_learned_from_his_own_replies(wa):
    msgs = []
    for i in range(12):
        msgs += [{"id": f"s{i}a", "jid": RAVI, "text": f"bro are you coming to the gym {i}", "from_me": False, "ts": f"2026-10-11T10:{i:02d}:00+00:00"},
                 {"id": f"s{i}b", "jid": RAVI, "text": "ha ra coming 😂", "from_me": True, "ts": f"2026-10-11T10:{i:02d}:30+00:00"}]
    event(wa, "history", {"messages": msgs})
    with wa.session_factory() as db:
        st = style.learn(db)
        p = st["people"][RAVI]
        assert p["n"] >= 12 and p["emoji_rate"] > 0.9 and p["lowercase_rate"] > 0.9 and p["tenglish"] > 0
        assert "Tenglish" in style.describe(p) and "😂" in style.describe(p)
        assert style.examples(db, RAVI, "are you coming to the gym?", k=3)[0][1] == "ha ra coming 😂"
        # TRINETRA's own sent replies never count as his style
        db.add(WaMessage(jid=RAVI, from_me=True, by_trinetra=True, text="ROBOT REPLY 🤖", ts=datetime.now(timezone.utc)))
        db.commit()
        assert all("ROBOT" not in mine for _, _, mine in style.pairs(db))


def test_chat_exports_from_android_and_iphone_are_read(wa):
    android = "18/10/26, 9:41 PM - Ravi: bro free?\n18/10/26, 9:42 PM - Tarun: ha ra\n18/10/26, 9:43 PM - Ravi: <Media omitted>\n"
    iphone = "[18/10/26, 9:41:03 PM] Mom: eat on time\nand sleep early\n[18/10/26, 9:45:10 PM] Tarun: sare amma\n"
    r1 = wa.post("/whatsapp/import", json={"text": android, "my_name": "Tarun", "chat": "Ravi"}).json()
    r2 = wa.post("/whatsapp/import", json={"text": iphone, "my_name": "Tarun", "chat": "Mom"}).json()
    assert r1["added"] == 2 and r2["added"] == 2
    with wa.session_factory() as db:
        mom = db.scalar(select(WaMessage).where(WaMessage.jid == "export:mom", WaMessage.from_me.is_(False)))
        assert mom.text == "eat on time\nand sleep early"
    assert wa.post("/whatsapp/import", json={"text": "just some random text here", "chat": "x"}).status_code == 422


def test_the_app_screen_shows_what_happened(wa):
    event(wa, "status", {"state": "open", "me": "Tarun"})
    busy(wa, "busy60")
    text_in(wa, RAVI, "hey")
    s = wa.get("/whatsapp").json()
    assert s["configured"] and s["autopilot"] and s["link"]["state"] == "open"
    assert s["session"]["state"] == "active" and s["recent"][0]["did"] == "replied"
    assert {c["name"] for c in s["contacts"]} >= {"Ravi", "Mom"}
    wa.post("/whatsapp/contacts", json={"jid": RAVI, "auto_ok": False})
    assert text_in(wa, RAVI, "hey again")["did"] == "for_you"  # he said never answer Ravi


def test_the_same_person_under_two_ids_is_one_friend(wa):
    """WhatsApp's history arrives under a private "lid"; live messages under the phone number. Same friend."""
    LID = "157758561226931@lid"
    event(wa, "history", {"messages": [
        {"id": "l1", "jid": LID, "text": "bro wassup", "from_me": False, "ts": "2026-10-09T10:00:00+00:00", "name": "K"},
        {"id": "l2", "jid": LID, "text": "chill ra", "from_me": True, "ts": "2026-10-09T10:01:00+00:00"}]})
    K = "919811122233@s.whatsapp.net"
    assert event(wa, "aliases", {"pairs": [{"lid": "157758561226931@lid", "pn": "919811122233@s.whatsapp.net"},
                                           {"lid": "999@lid", "pn": "91999@s.whatsapp.net"}]}).json()["merged"] == 1
    with wa.session_factory() as db:
        assert db.get(WaContact, LID) is None
        c = db.get(WaContact, K)
        assert c.known and c.name == "K"
        assert {m.jid for m in db.scalars(select(WaMessage).where(WaMessage.wa_id.in_(("l1", "l2"))))} == {K}
    busy(wa, "busy60")
    assert text_in(wa, K, "hi")["did"] == "replied"  # an old friend, not a stranger
