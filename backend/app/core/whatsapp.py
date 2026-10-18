"""WhatsApp autopilot: while Tarun is busy and offline, TRINETRA answers simple messages the way he would.

The flow he asked for:
  a message comes in while he's offline → "Ravi messaged on WhatsApp. Are you busy?" (once per half hour)
  yes, for 2 hours → a session: simple messages get a reply in his style (+ 🤖), anything serious goes to him
  he opens WhatsApp → the session pauses (and the bridge cancels anything still "typing")
  he leaves again before the end → it takes over again
  time's up → a summary of what it did and what's waiting for him

Never on autopilot (always his): groups, strangers, OTP / bank / money, plans and commitments, emergencies.
Other people's messages are sent to the model with `sensitive=True` (not to a free tier that trains on prompts).
"""
import json
import logging
import random
import re
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import llm, push, style
from app.core.timeutil import from_db, local, now_local, to_utc
from app.db.models import KeyValue, Message, WaContact, WaMessage, WaSession

log = logging.getLogger("trinetra.whatsapp")

ONLINE_WINDOW = timedelta(minutes=3)  # he did something on WhatsApp this recently → he's there
ASK_EVERY = timedelta(minutes=30)  # "are you busy?" at most this often
MAX_PER_HOUR = 20  # replies TRINETRA sends for him (the bridge has its own cap too)
CONFIDENT = 0.85
TAG = " 🤖"
BUSY_CHOICES = {"busy30": 30, "busy60": 60, "busy120": 120, "busy_tonight": None, "not_busy": 0}

OTP_BANK = re.compile(
    r"\b(otp|one[- ]time (password|code)|verification code|security code|passcode|pin|cvv|bank|upi|gpay|google pay|phonepe|"
    r"paytm|transaction|debited|credited|a/c|account (number|no)|ifsc|card (number|ending)|kyc|login code)\b", re.I)
MONEY = re.compile(r"(₹|rs\.? ?\d|\$\s?\d|\b(money|lend|borrow|loan|pay (me|back)|send (me )?(money|cash)|transfer|rupees|dollars|owe)\b)", re.I)
PLANS = re.compile(
    r"\b(meet|meeting|hang ?out|come (over|to|with)|coming|party|dinner|lunch|breakfast|coffee|movie|trip|plan|plans|"
    r"tomorrow|tmrw|tonight|this (weekend|evening|afternoon)|next week|on (mon|tue|wed|thu|fri|sat|sun)\w*|what time|"
    r"when (are|r) (you|u) free|(are|r) (you|u) free|pick (me|you) up|interview|deadline|submit)\b", re.I)
FEELINGS = re.compile(  # someone checking on him, or a feeling in the air: that deserves him, not a quick line
    r"\b((are|r) (you|u) (ok|okay|alright|fine|good|well|mad|angry|upset|sure)|(you|u) (seem|sound|look)|what happened|"
    r"is (everything|all) (ok|okay|fine|good)|worried|upset|sad|hurt|angry (with|at)|mad at|sorry|apolog\w*|miss (you|u)|"
    r"love (you|u)|feel(ing|s)?|break ?up|fight|argument|disappointed|ignoring|ignored)\b", re.I)
EMERGENCY = re.compile(
    r"\b(urgent|urgently|emergency|asap|hospital|accident|ambulance|police|died|passed away|death|help me|call me|"
    r"pick up|phone off|serious|bleeding|injured|fire|lost my|missing|stuck|scared)\b|!{3,}", re.I)


# ---------- small state ----------

def _get(db: Session, key: str) -> str | None:
    row = db.get(KeyValue, key)
    return row.value if row else None


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(KeyValue, key)
    if row:
        row.value = value
    else:
        db.add(KeyValue(key=key, value=value))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def configured() -> bool:
    s = get_settings()
    return bool(s.trinetra_bridge_url and s.trinetra_bridge_key)


def autopilot_on(db: Session) -> bool:
    return _get(db, "wa_autopilot") != "off"


def set_autopilot(db: Session, on: bool) -> None:
    _put(db, "wa_autopilot", "on" if on else "off")


def last_active(db: Session) -> datetime | None:
    v = _get(db, "wa_last_active")
    return datetime.fromisoformat(v) if v else None


def online(db: Session, now: datetime | None = None) -> bool:
    seen = last_active(db)
    return seen is not None and (now or _now()) - seen < ONLINE_WINDOW


def current(db: Session, now: datetime | None = None) -> WaSession | None:
    now = now or _now()
    s = db.scalar(select(WaSession).where(WaSession.state.in_(("active", "paused"))).order_by(WaSession.id.desc()))
    return s if s and from_db(s.until) > now else None


def _log(s: WaSession, **item) -> None:
    s.log = [*(s.log or []), {**item, "at": _now().isoformat(timespec="seconds")}][-200:]


# ---------- what the bridge tells us ----------

def contact(db: Session, jid: str, name: str | None = None, is_group: bool | None = None) -> WaContact:
    c = db.get(WaContact, jid)
    if c is None:
        group = bool(is_group) if is_group is not None else jid.endswith("@g.us")
        c = WaContact(jid=jid, name=name, is_group=group, auto_ok=not group, known=False)
        db.add(c)
        db.flush()
    elif name and not c.name:
        c.name = name
    return c


def who(c: WaContact | None) -> str:
    if c is None:
        return "Someone"
    return c.name or ("+" + c.jid.split("@")[0] if c.jid[:1].isdigit() else c.jid)


def store(db: Session, *, jid: str, text: str, from_me: bool, wa_id: str | None = None, ts: datetime | None = None,
          name: str | None = None, group: bool | None = None, by_trinetra: bool = False, handled: str | None = None) -> WaMessage | None:
    """Keep one text. None if WhatsApp sent the same message twice."""
    if wa_id and db.scalar(select(WaMessage.id).where(WaMessage.wa_id == wa_id)):
        return None
    c = contact(db, jid, None if from_me else name, group)
    if from_me and not by_trinetra:
        c.known = True  # he writes to them himself: not a stranger
    m = WaMessage(wa_id=wa_id, jid=jid, from_me=from_me, by_trinetra=by_trinetra, text=text[:4000],
                  ts=to_utc(ts) if ts else _now(), handled=handled)
    db.add(m)
    db.flush()
    return m


def mark_active(db: Session, at: datetime | None = None) -> WaSession | None:
    """He sent or read something on his phone. A running session pauses: he's there now."""
    at = at or _now()
    seen = last_active(db)
    if seen is None or at > seen:
        _put(db, "wa_last_active", at.isoformat())
    s = current(db)
    if s and s.state == "active":
        s.state, s.paused_at = "paused", at
        _log(s, did="paused", text="You opened WhatsApp, so I stepped back.")
    return s


# ---------- "are you busy?" ----------

def ask_busy(db: Session, c: WaContact) -> bool:
    """Once per half hour, at most. Returns whether it asked."""
    asked = _get(db, "wa_asked_at")
    if asked and _now() - datetime.fromisoformat(asked) < ASK_EVERY:
        return False
    _put(db, "wa_asked_at", _now().isoformat())
    text = (f"{who(c)} messaged you on WhatsApp. Are you busy? If you are, tell me for how long and I'll answer the "
            "simple ones like you would. Anything serious waits for you.")
    db.add(Message(role="trinetra", content=text, channel="whatsapp",
                   meta={"kind": "wa_busy", "buttons": list(BUSY_CHOICES), "respond": "/whatsapp/busy"}))
    push.send(db, "TRINETRA 💬", f"{who(c)} messaged on WhatsApp. Are you busy? Tap to tell me for how long.",
              url="/", tag="wa-busy")
    return True


def until_for(choice: str, now: datetime | None = None) -> datetime | None:
    minutes = BUSY_CHOICES[choice]
    now = now or _now()
    if minutes is None:  # "till tonight": 23:00 his time, or two hours if it's already late
        tonight = now_local().replace(hour=23, minute=0, second=0, microsecond=0)
        return to_utc(tonight) if to_utc(tonight) > now + timedelta(minutes=30) else now + timedelta(hours=2)
    return now + timedelta(minutes=minutes) if minutes else None


def start(db: Session, until: datetime) -> WaSession:
    for old in db.scalars(select(WaSession).where(WaSession.state.in_(("active", "paused")))):
        old.state = "ended"
    s = WaSession(until=until, state="active", log=[])
    db.add(s)
    db.flush()
    _put(db, "wa_asked_at", _now().isoformat())  # no more "are you busy?" while it's looking after things
    return s


def end(db: Session, s: WaSession, why: str = "time's up") -> str:
    """Stop, and tell him what happened while he was away."""
    s.state = "ended"
    replied = [i for i in (s.log or []) if i.get("did") == "replied"]
    waiting = [i for i in (s.log or []) if i.get("did") == "for_you"]
    if not replied and not waiting:
        return ""
    bits = []
    if replied:
        names = sorted({i["name"] for i in replied})
        bits.append(f"I replied {len(replied)} time{'s' if len(replied) > 1 else ''} ({', '.join(names[:5])})")
    if waiting:
        bits.append("waiting for you: " + "; ".join(f"{i['name']}: “{i['text'][:60]}”" for i in waiting[:4]))
    summary = f"WhatsApp while you were busy ({why}): " + ". ".join(bits) + "."
    push.send(db, "TRINETRA 💬", summary, url="/#whatsapp", tag="wa-summary")
    db.add(Message(role="trinetra", content=summary, channel="whatsapp", meta={"kind": "wa_summary"}))
    return summary


# ---------- deciding, and writing like him ----------

def rule_says_tarun(c: WaContact, text: str) -> str | None:
    """Why this one must wait for him, or None if TRINETRA may answer it."""
    from app.agents.command import DISTRESS
    if c.is_group:
        return "a group"
    if EMERGENCY.search(text) or DISTRESS.search(text):
        return "it sounds urgent"
    if OTP_BANK.search(text):
        return "codes and banking are yours"
    if MONEY.search(text):
        return "it's about money"
    if PLANS.search(text):
        return "it's a plan or a commitment"
    if FEELINGS.search(text):
        return "it's personal — they want you"
    if not c.known:
        return "you haven't chatted with them before"
    if not c.auto_ok:
        return "you asked me not to reply to them"
    return None


def _history(db: Session, jid: str, before_id: int | None = None, n: int = 10) -> list[WaMessage]:
    q = select(WaMessage).where(WaMessage.jid == jid)
    if before_id:
        q = q.where(WaMessage.id <= before_id)
    return list(db.scalars(q.order_by(WaMessage.id.desc()).limit(n)))[::-1]


def _prompt(db: Session, jid: str, text: str, chat: list[WaMessage], holdout: str | None = None) -> list[dict]:
    st = style.load(db)
    p = st.get("people", {}).get(jid) or st.get("overall") or {}
    shots = [(t, r) for t, r in style.examples(db, jid, text) if r != holdout]
    c = db.get(WaContact, jid)
    s = current(db)
    status = f"busy until {local(s.until):%-I:%M %p}" if s else "busy right now"
    lines = "\n".join(f"{'Tarun' if m.from_me else (who(c) if c else 'Them')}: {m.text}" for m in chat)
    examples = "\n".join(f"They: {t}\nTarun: {r}" for t, r in shots) or "(none yet)"
    system = (
        "You are writing ONE WhatsApp reply as Tarun himself, to a friend or family member, while he's "
        f"{status}. Write exactly like him — his length, his language mix, his slang, his emoji habits. "
        f"How he writes: {style.describe(p)}\n"
        "Rules: never invent facts about his life, plans, location or feelings; never agree to plans, money, favours or "
        "times; never share anything private; don't say you're an AI (a 🤖 tag is added for you). If they need a real "
        "answer from him, say he'll get back to them soon, in his words.\n"
        f"His real past replies to similar messages (copy this voice):\n{examples}\n\n"
        'Answer in JSON: {"kind": "simple" | "needs_tarun" | "emergency", "confidence": 0-1, "reply": "..."}. '
        '"simple" = small talk, greetings, thanks, "what\'s up", acknowledgements, things a quick holding reply covers. '
        '"needs_tarun" = anything that needs his decision, knowledge, opinion or feelings — including anyone asking how '
        'he is, checking on him, or anything emotional. "emergency" = anything urgent.')
    return [{"role": "system", "content": system},
            {"role": "user", "content": f"The chat so far:\n{lines}\n\nTheir new message: {text}"}]


async def triage(db: Session, m: WaMessage) -> dict:
    """{"kind", "confidence", "reply"} from one model call; rules decide first and can't be overruled."""
    c = db.get(WaContact, m.jid)
    if (why := rule_says_tarun(c, m.text)) is not None:
        return {"kind": "needs_tarun", "confidence": 1.0, "reply": "", "why": why}
    try:
        raw = await llm.complete(_prompt(db, m.jid, m.text, _history(db, m.jid, m.id)), tier="fast", temperature=0.6,
                                 max_tokens=300, json_mode=True, reasoning="low", sensitive=True)
        d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except (llm.LLMUnavailable, ValueError):
        return {"kind": "needs_tarun", "confidence": 0.0, "reply": "", "why": "my models are busy"}
    if not isinstance(d, dict):
        return {"kind": "needs_tarun", "confidence": 0.0, "reply": "", "why": "I wasn't sure"}
    kind = d.get("kind") if d.get("kind") in ("simple", "needs_tarun", "emergency") else "needs_tarun"
    try:
        conf = max(0.0, min(1.0, float(d.get("confidence", 0))))
    except (TypeError, ValueError):
        conf = 0.0
    reply = str(d.get("reply") or "").strip()[:600]
    why = None if kind == "simple" and conf >= CONFIDENT and reply else (
        "it sounds urgent" if kind == "emergency" else "it needs you" if kind == "needs_tarun" else "I wasn't sure")
    return {"kind": kind, "confidence": conf, "reply": reply, "why": why}


async def write_reply(db: Session, jid: str, text: str, holdout: str | None = None) -> str:
    """Just the words, as he'd write them (the "sounds like you" test uses this on his real past messages)."""
    try:
        raw = await llm.complete(_prompt(db, jid, text, [], holdout=holdout), tier="fast", temperature=0.6,
                                 max_tokens=300, json_mode=True, reasoning="low", sensitive=True)
        return str(json.loads(raw[raw.find("{"):raw.rfind("}") + 1]).get("reply") or "").strip()
    except Exception:
        return ""


def _sent_last_hour(db: Session) -> int:
    """Replies it decided to send in the last hour (counted at once, before the bridge's typing delay is over)."""
    hour_ago = _now() - timedelta(hours=1)
    return db.scalar(select(func.count(WaMessage.id)).where(WaMessage.handled == "replied", WaMessage.from_me.is_(False),
                                                            WaMessage.ts > hour_ago)) or 0


def bridge_send(jid: str, text: str) -> bool:
    """Ask the bridge to type for a human-looking while, then send. It cancels on its own if he opens WhatsApp."""
    s = get_settings()
    delay = int(min(90_000, 20_000 + len(text) * 350 + random.randint(0, 8_000)))
    try:
        r = httpx.post(f"{s.trinetra_bridge_url.rstrip('/')}/send", json={"jid": jid, "text": text, "delay_ms": delay},
                       headers={"Authorization": f"Bearer {s.trinetra_bridge_key}"}, timeout=10)
        return r.status_code < 300
    except httpx.HTTPError:
        log.warning("bridge unreachable")
        return False


def act(db: Session, m: WaMessage, s: WaSession, t: dict) -> str:
    """The Confidence Judge's call on a draft: send it as him, or leave it for him (and tell him)."""
    c = db.get(WaContact, m.jid)
    if t["why"] is None and _sent_last_hour(db) < MAX_PER_HOUR and bridge_send(m.jid, t["reply"] + TAG):
        m.handled, m.note = "replied", t["reply"]  # the bridge reports back when it's really sent (or cancelled)
        _log(s, did="replied", name=who(c), text=m.text[:200], reply=t["reply"])
        return "replied"
    why = t["why"] or ("I've sent a lot this hour" if _sent_last_hour(db) >= MAX_PER_HOUR else "I couldn't send it")
    m.handled, m.note = "for_you", why + (f" · draft: {t['reply']}" if t["reply"] else "")
    _log(s, did="for_you", name=who(c), text=m.text[:200], why=why, draft=t["reply"])
    urgent = t["kind"] == "emergency" or why == "it sounds urgent"
    push.send(db, "TRINETRA 🚨" if urgent else "TRINETRA 💬",
              f"{who(c)} on WhatsApp: “{m.text[:140]}” — {why}, so I left it for you."
              + (f" Suggested: “{t['reply'][:100]}”" if t["reply"] else ""), url="/#whatsapp", tag=f"wa-{m.id}")
    return "for_you"


async def handle(db: Session, m: WaMessage, s: WaSession) -> str:
    """During a session, with him offline: draft, then judge. Returns replied / for_you."""
    return act(db, m, s, await triage(db, m))


def route(db: Session, m: WaMessage) -> str:
    """The Listener: where does this message go? off / group / online / asked / waiting / session (no model call)."""
    c = db.get(WaContact, m.jid)
    if not configured() or not autopilot_on(db):
        m.handled = "skipped"
        return "off"
    if c.is_group:
        m.handled = "skipped"
        return "group"
    if online(db):
        m.handled = "skipped"  # he's right there
        return "online"
    s = current(db)
    if s is None:
        m.handled = "pending"  # answered once he says he's busy
        return "asked" if ask_busy(db, c) else "waiting"
    if s.state == "paused":  # he was on WhatsApp, and has gone quiet again: take over again
        s.state, s.paused_at = "active", None
        _log(s, did="resumed", text="You went offline again, so I'm back on it.")
    return "session"


async def on_message(db: Session, m: WaMessage) -> str:
    """The whole decision in one go (used where the agents aren't convened, e.g. catching up)."""
    r = route(db, m)
    return await handle(db, m, current(db)) if r == "session" else r


async def catch_up(db: Session) -> list[str]:
    """Messages that came in while it waited for "are you busy?" (or while he was away during a pause)."""
    s = current(db)
    if s is None or s.state != "active" or online(db):
        return []
    since = last_active(db) or (_now() - timedelta(hours=2))
    out = []
    for m in db.scalars(select(WaMessage).where(WaMessage.handled == "pending", WaMessage.from_me.is_(False),
                                               WaMessage.ts > since).order_by(WaMessage.id)):
        out.append(await handle(db, m, s))
    return out


async def tick(db: Session, now: datetime | None = None) -> str | None:
    """Every heartbeat: end sessions whose time is up; take over again once he's been offline for a bit."""
    now = now or _now()
    s = db.scalar(select(WaSession).where(WaSession.state.in_(("active", "paused"))).order_by(WaSession.id.desc()))
    if s is None:
        return None
    if from_db(s.until) <= now:
        end(db, s)
        return "ended"
    if s.state == "paused" and not online(db, now):
        s.state, s.paused_at = "active", None
        _log(s, did="resumed", text="You went offline again, so I'm back on it.")
        await catch_up(db)
        return "resumed"
    return None


def status(db: Session) -> dict:
    """Everything the app's 💬 screen shows."""
    s = current(db)
    st = style.load(db)
    link = json.loads(_get(db, "wa_link") or "{}")
    recent = db.scalars(select(WaMessage).where(WaMessage.from_me.is_(False), WaMessage.handled.in_(("replied", "for_you")))
                        .order_by(WaMessage.id.desc()).limit(30)).all()
    people = db.scalars(select(WaContact).where(WaContact.is_group.is_(False), WaContact.known)
                        .order_by(WaContact.updated_at.desc()).limit(200)).all()
    return {
        "configured": configured(),
        "link": link,
        "autopilot": autopilot_on(db),
        "online": online(db),
        "session": s and {"until": local(s.until).isoformat(), "state": s.state, "log": (s.log or [])[-20:]},
        "recent": [{"id": m.id, "name": who(db.get(WaContact, m.jid)), "text": m.text, "did": m.handled, "note": m.note,
                    "at": local(from_db(m.ts)).isoformat()} for m in recent],
        "contacts": [{"jid": c.jid, "name": who(c), "auto_ok": c.auto_ok} for c in people],
        "style": {"learned_from": (st.get("overall") or {}).get("n", 0), "people": len(st.get("people", {})),
                  "score": st.get("score"), "learned_at": st.get("learned_at")},
    }


def cancelled(db: Session, jid: str, text: str) -> None:
    """The bridge dropped a reply because he opened WhatsApp while it was "typing": it's his again."""
    reply = text.removesuffix(TAG)
    m = db.scalar(select(WaMessage).where(WaMessage.jid == jid, WaMessage.handled == "replied", WaMessage.note == reply)
                  .order_by(WaMessage.id.desc()))
    if m is not None:
        m.handled, m.note = "for_you", f"you came online before I sent it · draft: {reply}"
    s = db.scalar(select(WaSession).order_by(WaSession.id.desc()))
    if s is not None:
        for item in reversed(s.log or []):
            if item.get("did") == "replied" and item.get("reply") == reply:
                item["did"], item["why"] = "for_you", "you came online before I sent it"
                s.log = list(s.log)  # reassign so the JSON change is saved
                break


def merge_aliases(db: Session, pairs: list[dict]) -> int:
    """WhatsApp gives each person a phone-number id and a private "lid". The bridge files everything under the number;
    anything that arrived under a lid (most of the linked history) is moved over, so old friends aren't "strangers".
    Returns how many people were merged."""
    def norm(v: str, server: str) -> str:
        user = (v or "").split("@")[0].split(":")[0]
        return f"{user}@{server}" if user else ""

    mapping = {norm(p.get("lid", ""), "lid"): norm(p.get("pn", ""), "s.whatsapp.net") for p in pairs}
    mapping.pop("", None)
    if not mapping:
        return 0
    seen = set(db.scalars(select(WaMessage.jid).where(WaMessage.jid.like("%@lid")).distinct()))
    seen |= set(db.scalars(select(WaContact.jid).where(WaContact.jid.like("%@lid"))))
    merged = 0
    for lid in seen & mapping.keys():
        pn = mapping[lid]
        if not pn.split("@")[0]:
            continue
        db.query(WaMessage).filter(WaMessage.jid == lid).update({WaMessage.jid: pn}, synchronize_session=False)
        old = db.get(WaContact, lid)
        if old is not None:
            new = db.get(WaContact, pn)
            if new is None:
                db.add(WaContact(jid=pn, name=old.name, is_group=False, known=old.known, auto_ok=old.auto_ok,
                                 updated_at=old.updated_at))
            else:
                new.known = new.known or old.known
                new.name = new.name or old.name
                new.auto_ok = new.auto_ok and old.auto_ok  # "never reply to them" on either id still holds
            db.delete(old)
        merged += 1
    db.flush()
    return merged
