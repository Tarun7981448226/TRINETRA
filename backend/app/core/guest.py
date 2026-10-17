"""TRINETRA on the portfolio: greets visitors, explains itself, relays "what is Tarun doing now?" to his phone.

Privacy by construction: the guest persona only ever sees the public brief and the visitor's own conversation —
no private table is read while answering a visitor. Each conversation is wiped when they leave the site (LEAVE_GRACE after the
last page closes) or after FORGET_AFTER idle; Tarun keeps a small log (name, company, topics) and any notes they leave.
"""
import json
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import llm, push
from app.core.persona import guest_prompt, humanize, without_name
from app.core.timeutil import from_db, now_local
from app.db.models import GuestAsk, GuestNote, GuestReply, GuestVisit, KeyValue, Message

BRIEF = Path(__file__).resolve().parents[1] / "guest_brief.md"
ASK_TIMEOUT = timedelta(seconds=60)
FORGET_AFTER = timedelta(minutes=30)
MAX_TURNS = 25  # per visit
MAX_VISITS_PER_HOUR = 8  # per IP
MAX_TEXT = 500
DIGEST_AT = (21, 30)  # local time, every night

GREETING = ("Hey there! I'm TRINETRA, Tarun's AI mentor. He built me to run his days and keep him sharp. "
            "Before I tell you more, what's your name?")
CHECKING = "Good question. Let me check with him right now, one moment."
TOUR_OFFER = "Would you like a quick tour of Tarun's portfolio? I can show you around."
FALLBACK = ("I think he's at work right now. Please leave him a message and he'll get back to you. "
            "May I have your email?")

NOW_PATTERN = re.compile(
    r"\b(what|where|how)\b.{0,40}\b(tarun|he|him)\b.{0,40}\b(doing|up to|busy|right now|now)\b"
    r"|\b(check on|ask) (him|tarun)\b|\bis (he|tarun) (free|available|busy|around|online)\b", re.I)


@lru_cache
def brief() -> str:
    return BRIEF.read_text()


# Insulting Tarun (or TRINETRA) on his own site gets you removed: one line, the page goes, 24 h before you can return.
_STRONG = r"f+u+c+k+\w*|fck\w*|fuk\w*|motherf\w*|bitch\w*|bastard\w*|assholes?|a\$\$hole|dickhead\w*|cunts?|sluts?|whores?|retard\w*|piece of shit|bullshit"
_INSULT = r"idiot\w*|stupid|dumb(ass)?|moron\w*|loser\w*|useless|worthless|pathetic|trash|garbage|clown|fraud|ugly|sucks?|incompetent|scammer|failure|nobody|joke"
_TARGET = r"you|u|ur|you'?re|tarun'?s?|he|he'?s|him|his|this guy|trinetra|bot|this ai|your (owner|creator|boss)"
ABUSE = re.compile(
    rf"\b({_STRONG})\b"                                                    # swearing at all
    rf"|\b({_TARGET})\b(?:\W+\w+){{0,3}}?\W+(is|are|r|a|an|such|so|total|complete|real|just|the|biggest)?\W*\b({_INSULT})\b"
    rf"|\b({_INSULT})\b\W+({_TARGET})\b"                                    # "idiot tarun"
    rf"|\b(shut up|go to hell|hate (you|him|tarun)|kill (yourself|urself)|get lost|screw (you|him|tarun))\b", re.I)
BAN_FOR = timedelta(hours=24)
EJECT_LINE = "That's not how anyone talks about Tarun here. You're done — goodbye."


def abusive(text: str) -> bool:
    if not ABUSE.search(text):
        return False
    # a sceptical question ("are his numbers fake?") is fair; a swear word never is
    return not (text.strip().endswith("?") and not re.search(rf"\b({_STRONG})\b", text, re.I))


def banned(db: Session, ip: str | None) -> bool:
    row = db.get(KeyValue, f"guest_ban:{ip}") if ip else None
    return bool(row and row.value and datetime.fromisoformat(row.value) > datetime.now(timezone.utc))


def eject(db: Session, v: GuestVisit, text: str) -> dict:
    """Removed for abuse: Tarun hears about it, the IP is shut out for BAN_FOR, the conversation is forgotten."""
    now = datetime.now(timezone.utc)
    if v.ip:
        row = db.get(KeyValue, f"guest_ban:{v.ip}")
        until = (now + BAN_FOR).isoformat()
        if row is None:
            db.add(KeyValue(key=f"guest_ban:{v.ip}", value=until))
        else:
            row.value = until
    v.topics = [*(v.topics or []), "removed: insulted you"][-12:]
    push.send(db, "TRINETRA 🚫", f"{_who(v)} insulted you on your portfolio and was removed for 24 h: “{text[:160]}”",
              url="/#visitors", tag="visitor-removed")
    forget(v)
    db.commit()
    return {"reply": EJECT_LINE, "eject": True, "ban_hours": int(BAN_FOR.total_seconds() // 3600)}


def new_visit(db: Session, ip: str | None) -> GuestVisit | None:
    """None when this IP opened too many visits in the last hour."""
    hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = db.scalar(select(func.count(GuestVisit.id)).where(GuestVisit.ip == ip, GuestVisit.started_at > hour_ago))
    if ip and recent >= MAX_VISITS_PER_HOUR:
        return None
    v = GuestVisit(token=secrets.token_urlsafe(24), ip=ip, messages=[{"role": "trinetra", "text": GREETING}],
                   topics=[], last_said=GREETING)
    db.add(v)
    db.flush()
    return v


def visit_for(db: Session, token: str) -> GuestVisit | None:
    v = db.scalar(select(GuestVisit).where(GuestVisit.token == token)) if token else None
    if v is None or v.ended_at is not None:
        return None
    return v


def _remember(v: GuestVisit, role: str, text: str) -> None:
    v.messages = [*(v.messages or []), {"role": role, "text": text}][-24:]
    v.last_seen = datetime.now(timezone.utc)
    if role == "trinetra":
        v.last_said = text


NOT_NAMES = {"from", "at", "with", "and", "here", "the", "a", "an", "hi", "hello", "hey", "working", "recruiter"}


def _guess_name(text: str) -> tuple[str | None, str | None]:
    """Offline fallback: "I'm Priya from Google" → ("Priya", "Google")."""
    t = text.strip().strip(".!")
    m = re.search(r"(?:i'?m|i am|my name is|this is|it'?s|name'?s|call me)\s+([A-Za-z][A-Za-z'\-]+(?:\s+[A-Z][a-z'\-]+)?)",
                  t, re.I)
    name = m.group(1) if m else (t if re.fullmatch(r"[A-Za-z][A-Za-z'\-]{1,20}(\s+[A-Za-z][A-Za-z'\-]{1,20})?", t) else None)
    if name:  # "Priya from" → "Priya"
        words = [w for w in name.split() if w.lower() not in NOT_NAMES]
        name = " ".join(words) or None
    c = re.search(r"\b(?:from|at|with|work at|working at)\s+([A-Z][\w&.\- ]{1,40})", t)
    return (name.title() if name else None), (c.group(1).strip() if c else None)


ROLES = {  # key: (how to talk about them, button label, ask for their number / email) — in priority order
    "recruiter": ("a recruiter", "Recruiter", True),
    "manager": ("a hiring manager", "Hiring manager", True),
    "researcher": ("an AI/ML researcher", "AI/ML researcher", True),
    "ml_engineer": ("an AI/ML engineer", "AI/ML engineer", True),
    "swe": ("a software engineer", "Software engineer", True),
    "founder": ("a founder", "Founder", False),  # only recruiters and engineers are asked for contact details
    "mentor": ("a mentor or professor", "Mentor / professor", False),
    "student": ("a student", "Student", False),
    "other": ("a visitor", "Just browsing", False),
}
ROLE_OPTIONS = [{"key": k, "label": v[1]} for k, v in ROLES.items()]
ROLE_WORDS = [  # typed instead of tapped; first match wins
    ("recruiter", r"recruit|talent|sourc|\bhr\b|people team|headhunt"),
    ("founder", r"founder|\bceo\b|\bcto\b|start-?up"),
    ("manager", r"hiring manager|manager|\blead\b|director|head of|\bvp\b"),
    ("mentor", r"mentor|professor|advisor|teacher|lecturer|faculty"),
    ("researcher", r"research|scientist|\bphd\b|postdoc"),
    ("ml_engineer", r"\b(ml|ai|machine learning|data|llm|mlops)\b.{0,15}engineer|\bml\b|\bai\b|machine learning"),
    ("swe", r"software|engineer|developer|\bswe\b|\bsde\b|programmer|\bdev\b|full.?stack|backend|frontend"),
    ("student", r"student|studying|undergrad|freshman|sophomore|junior|senior year|master'?s|grad school|college|university"),
]
ROLE_Q = "Who are you? Pick the one that fits best."
CONTACT_FORM_Q = ("Quick heads-up: Tarun is looking for a Summer 2027 internship in AI/ML or software engineering, and "
                  "he brings a strong set of skills. If you'd like to talk with him, leave your number and email below; "
                  "if it's a good fit, you can take it further from there. Skipping is totally fine.")
CONTACT_ASK = ("If you'd like Tarun to reach out, just drop your email or phone number here and I'll pass it to him "
               "right away.")
EMAIL = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
PHONE = re.compile(r"(?<![\w@])\+?\d[\d\s().\-]{7,}\d(?!\w)")
CONTACT_INTENT = re.compile(  # "how can I leave my details?", "can I give you my number", "how do I get in touch"
    r"\b(leave|share|give|drop|send|put|add|submit)\b[^.!?]{0,25}\b(details?|number|contact|e-?mail|mail|phone|info)\b"
    r"|\bhow (can|do|could) i (contact|reach|connect with|get in touch with) (him|tarun)\b|\bget in touch\b"
    r"|\b(contact|reach out to) (him|tarun)\b", re.I)
CONTACT_HOW = "Easy, just fill this in: your number and email go straight to Tarun. Leave either one, or both."
BYE = re.compile(r"\b(good\s?bye|bye+|see (you|ya)|cya|gotta go|take care|signing off)\b", re.I)  # in a short message


def _role_from_words(text: str) -> str | None:
    t = text.lower()
    for role, pattern in ROLE_WORDS:
        if re.search(pattern, t):
            return role
    return None


async def _extract_identity(text: str) -> tuple[str | None, str | None, str | None]:
    """(name, company, role) from what they typed. The model first, then plain pattern matching."""
    try:
        raw = await llm.complete(
            [{"role": "system", "content": "From a visitor's message to a portfolio website's assistant, extract their own "
                                           "first name (or full name), company, and role. role is one of: recruiter, manager, "
                                           "founder, researcher, engineer, student, other — or null if not stated. Reply as "
                                           'JSON: {"name": string|null, "company": string|null, "role": string|null}. No guessing.'},
             {"role": "user", "content": text[:300]}],
            tier="fast", temperature=0, max_tokens=80, json_mode=True)
        d = json.loads(raw)
        name, company, role = d.get("name") or None, d.get("company") or None, d.get("role") or None
        if name or company or role:
            role = role if role in ROLES else _role_from_words(text)
            return (str(name)[:80] if name else None), (str(company)[:120] if company else None), role
    except Exception:  # offline, rate-limited or not JSON: the pattern guess below is fine
        pass
    name, company = _guess_name(text)
    return name, company, _role_from_words(text)


def _topic(text: str) -> str:
    t = text.lower()
    for label, keys in (("projects", ("project", "skynet", "orion", "apex", "built")), ("trinetra", ("trinetra", "you do", "what are you")),
                        ("experience", ("experience", "research", "paper", "srm", "intern")), ("hiring", ("hire", "role", "position", "interview", "available")),
                        ("skills", ("skill", "stack", "python", "ml", "ai")), ("contact", ("email", "contact", "reach"))):
        if any(k in t for k in keys):
            return label
    return "chat"


def _said(v: GuestVisit, line: str) -> bool:
    return any(line in m["text"] for m in (v.messages or []) if m["role"] == "trinetra")


def _important(v: GuestVisit) -> bool:
    return ROLES.get(v.role, ("", "", False))[2]


def _who(v: GuestVisit) -> str:
    bits = [b for b in (ROLES[v.role][1].lower() if v.role in ROLES and v.role != "other" else None, v.company) if b]
    return (v.name or "A visitor") + (f" ({', '.join(bits)})" if bits else "")


def save_contact(db: Session, v: GuestVisit, email: str | None, phone: str | None, message: str) -> str:
    """Keep their email / number, tell Tarun right away. Returns the thank-you line."""
    v.email, v.phone = email or v.email, phone or v.phone
    db.add(GuestNote(visit_id=v.id, name=v.name, email=email or "", phone=phone, message=message[:1000]))
    contact = " and ".join(x for x in (phone, email) if x)
    push.send(db, "TRINETRA 📇", f"{_who(v)} left their contact on your portfolio: {contact}" +
              (f" — “{message[:160]}”" if message and message != contact else "") + " Tap to reply.",
              url=f"/#reply/{v.id}", tag="visitor-contact")
    v.topics = [*(v.topics or []), "left contact"][-12:]
    return f"Got it. I've sent {contact} to Tarun just now, so expect to hear from him soon."


def _take_contact(db: Session, v: GuestVisit, text: str) -> str | None:
    """They typed an email or number into the chat. None if there's none."""
    email = (EMAIL.findall(text) or [None])[0]
    phones = [p for p in PHONE.findall(text) if len(re.sub(r"\D", "", p)) >= 7]
    phone = phones[0].strip() if phones else None
    if not email and not phone:
        return None
    thanks = save_contact(db, v, email, phone, text)
    return thanks + (" Thanks for stopping by!" if BYE.search(text) else " Anything else you'd like to know in the meantime?")


def _sparing(v: GuestVisit, text: str) -> str:
    """Their name now and then, not in every line: drop it if one of my last few lines already used it."""
    if not v.name:
        return text
    names = {v.name, v.name.split()[0]}
    recent = [m["text"] for m in (v.messages or []) if m["role"] == "trinetra"][-4:]
    if not any(re.search(rf"\b{re.escape(n)}\b", r, re.I) for r in recent for n in names):
        return text
    for n in sorted(names, key=len, reverse=True):
        text = without_name(text, n)
    return text


async def _say(v: GuestVisit, history: list[dict], fallback: str) -> str:
    try:
        text = humanize(await llm.complete([{"role": "system", "content": guest_prompt(brief(), v.name, v.company, v.role)}, *history],
                                           tier="fast", temperature=0.7, max_tokens=220), strip_name=False) or fallback
    except llm.LLMUnavailable:
        text = fallback
    return _sparing(v, _short(text))


def _short(text: str, keep: int = 3) -> str:
    """Spoken and on a small panel: three sentences at most, however chatty the model was."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"])", text.strip())
    return " ".join(parts[:keep])


async def chat(db: Session, v: GuestVisit, text: str) -> dict:
    text = text.strip()[:MAX_TEXT]
    v.turns += 1
    _remember(v, "visitor", text)

    def done(reply: str, **extra) -> dict:
        _remember(v, "trinetra", reply)
        db.commit()
        return {"reply": reply, **extra}

    # 0. Insulting Tarun gets you thrown out.
    if abusive(text):
        return eject(db, v, text)
    # 0b. "Show me your emotions" → just the names; the face acts them out (whatever step of the chat we're at).
    from app.agents.command import EMOTION_LABEL, perform_request
    from app.core import show
    if wanted := show.request(text, lab=True):  # "dance", "play the guitar", "stop" → just the name; the character performs it
        return done(show.label(wanted), show=wanted)
    if perform := perform_request(text):
        return done(" · ".join(EMOTION_LABEL[e] for e in perform), perform=perform)
    # 1. They gave us their email / number — always welcome, never refused.
    if (thanks := _take_contact(db, v, text)) is not None:
        return done(thanks, celebrate=True)
    # 2. Leaving.
    if BYE.search(text) and len(text) < 60:
        ask = _important(v) and not (v.email or v.phone) and not _said(v, CONTACT_FORM_Q)
        return done(f"Thanks for stopping by{', ' + v.name if v.name else ''}! "
                    + (CONTACT_ASK.replace("just drop", "drop") if ask else "Tarun will be glad you came. Take care."))
    # 3. They want to leave their details: the card, whoever they are (they asked).
    if CONTACT_INTENT.search(text) and not (v.email or v.phone):
        return done(CONTACT_HOW, contact_form=True)
    # 4. "What is Tarun doing right now?" → his phone.
    if NOW_PATTERN.search(text):
        ask = GuestAsk(visit_id=v.id, question=text)
        db.add(ask)
        db.flush()
        push.send(db, "TRINETRA 👀", f"{_who(v)} is on your portfolio and asks what you're doing right now. Tap to answer.",
                  url=f"/#ask/{ask.id}", tag=f"ask-{ask.id}")
        v.topics = [*(v.topics or []), "asked what you're doing"][-12:]
        return done(CHECKING, ask_id=ask.id)

    # 5. Getting to know them: name (first couple of messages), then who they are (buttons).
    introducing = v.name is None and v.turns <= 2  # don't keep pestering someone who'd rather not say
    if introducing:
        name, company, role = await _extract_identity(text)
        name = " ".join(w[:1].upper() + w[1:] for w in name.split()) if name else None  # "charan" → "Charan"
        if name:  # only an introduction tells us who THEY are ("his research?" doesn't make them a researcher)
            v.name, v.company, v.role = name, v.company or company, v.role or role
            push.send(db, "TRINETRA 👋", f"{_who(v)} is talking to me on your portfolio.", url="/#visitors", tag="visitor")
        if v.name and not v.role:
            return done(f"Nice to meet you, {v.name}! {ROLE_Q}", role_options=ROLE_OPTIONS)
    answering_role = not introducing and v.role is None and _said(v, ROLE_Q) and v.turns <= 4
    if answering_role:  # they typed it instead of tapping a button
        _, company, role = await _extract_identity(text)
        v.role, v.company = role or "other", v.company or company
    if (introducing and v.name) or answering_role:
        return await pitch(db, v, done)

    # 6. A normal question about Tarun / TRINETRA.
    v.topics = [*(v.topics or []), _topic(text)][-12:]
    history = [{"role": "assistant" if m["role"] == "trinetra" else "user", "content": m["text"]} for m in v.messages[-10:]]
    reply = await _say(v, history, "I'm not sure about that one. The best way is to ask Tarun directly at tarundeepreddybv@gmail.com.")
    if _important(v) and not (v.email or v.phone) and v.turns >= 4 and not (_said(v, CONTACT_ASK) or _said(v, CONTACT_FORM_Q)):
        return done(f"{reply} {CONTACT_ASK}")  # once, for people worth connecting with
    offer = v.turns >= 2 and not _said(v, TOUR_OFFER)  # didn't introduce themselves: still offer the tour, once
    return done(f"{reply} {TOUR_OFFER}" if offer else reply, offer_tour=offer)


async def pitch(db: Session, v: GuestVisit, done) -> dict:
    """We know who they are: a pitch made for them. Important people then get the contact card; everyone the tour."""
    who = ROLES.get(v.role, ROLES["other"])[0]
    history = [{"role": "user", "content": (
        f"The visitor{' ' + v.name if v.name else ''} is {who}{' at ' + v.company if v.company else ''}. In 2 short spoken "
        "sentences (you already greeted them by name, so don't use it again): one concrete reason Tarun is worth their attention, picked "
        "for someone like them (recruiter / hiring manager → impact and shipped results; engineer → how he builds; "
        "researcher → the research and the paper; founder → products he's shipped; mentor → how fast he learns and what "
        "he's aiming for; student → what he's learned). Don't introduce yourself again. Under 45 words. No question at the end.")}]
    reply = await _say(v, history, "Here's the short version: Tarun ships real AI systems, from a face-recognition pipeline "
                                   "he made twelve times faster to SKYNET, live in production.")
    if _important(v) and not (v.email or v.phone) and not _said(v, CONTACT_FORM_Q):
        return done(f"{reply} {CONTACT_FORM_Q}", contact_form=True)
    offer = not _said(v, TOUR_OFFER)
    return done(f"{reply} {TOUR_OFFER}" if offer else reply, offer_tour=offer)


async def choose_role(db: Session, v: GuestVisit, role: str) -> dict:
    """They tapped one of the "who are you?" buttons."""
    v.role = role if role in ROLES else "other"
    _remember(v, "visitor", ROLES[v.role][1])

    def done(reply: str, **extra) -> dict:
        _remember(v, "trinetra", reply)
        db.commit()
        return {"reply": reply, **extra}

    return await pitch(db, v, done)


def contact_card(db: Session, v: GuestVisit, phone: str | None, email: str | None) -> dict:
    """The contact card: a number (with country code) and / or an email — or nothing, which is fine."""
    if phone or email:
        reply, celebrate = save_contact(db, v, email, phone, " · ".join(x for x in (phone, email) if x)), True
    else:
        reply, celebrate = "No problem at all.", False
    offer = not _said(v, TOUR_OFFER)
    reply = f"{reply} {TOUR_OFFER}" if offer else reply
    _remember(v, "trinetra", reply)
    db.commit()
    return {"reply": reply, "offer_tour": offer, "celebrate": celebrate}


def ask_status(db: Session, v: GuestVisit, ask_id: int) -> dict:
    ask = db.get(GuestAsk, ask_id)
    if ask is None or ask.visit_id != v.id:
        return {"status": "missing"}
    if ask.status == "waiting" and datetime.now(timezone.utc) - from_db(ask.created_at) > ASK_TIMEOUT:
        ask.status = "timeout"
        _remember(v, "trinetra", FALLBACK)
        db.commit()
    if ask.status == "answered":
        reply = f"He says: {ask.answer}"
        if v.last_said != reply:
            _remember(v, "trinetra", reply)
            db.commit()
        return {"status": "answered", "reply": reply}
    if ask.status == "timeout":
        return {"status": "timeout", "reply": FALLBACK, "wants_email": True}
    return {"status": "waiting"}


def reply_to(db: Session, visit_id: int, text: str) -> GuestReply | None:
    """Tarun writes back to a visitor from the app. It pops up in their chat while they're still on the site."""
    v = db.get(GuestVisit, visit_id)
    if v is None:
        return None
    r = GuestReply(visit_id=v.id, text=text.strip()[:400])
    db.add(r)
    v.topics = [*(v.topics or []), "you replied"][-12:]
    db.commit()
    return r


def inbox(db: Session, v: GuestVisit) -> list[str]:
    """Tarun's replies this visitor hasn't seen yet (marked seen now). Each becomes a line in their chat."""
    rows = db.scalars(select(GuestReply).where(GuestReply.visit_id == v.id, GuestReply.delivered_at.is_(None))
                      .order_by(GuestReply.id)).all()
    lines = []
    for r in rows:
        r.delivered_at = datetime.now(timezone.utc)
        lines.append(f"Message from Tarun: “{r.text}”")
        _remember(v, "trinetra", lines[-1])
    if rows:
        db.commit()
    return lines


def answer_ask(db: Session, ask_id: int, text: str) -> GuestAsk | None:
    ask = db.get(GuestAsk, ask_id)
    if ask is None:
        return None
    ask.answer, ask.status, ask.answered_at = text.strip()[:400], "answered", datetime.now(timezone.utc)
    db.commit()
    return ask


def leave_note(db: Session, v: GuestVisit, email: str, message: str) -> GuestNote:
    v.email = email[:160]
    note = GuestNote(visit_id=v.id, name=v.name, email=email[:160], message=(message.strip() or "(no message)")[:1000])
    db.add(note)
    push.send(db, "TRINETRA 📇", f"{_who(v)} left you a message: {email} — “{note.message[:160]}”",
              url="/#visitors", tag="visitor-contact")
    reply = f"Thanks{', ' + v.name if v.name else ''}! I've passed that to Tarun, and he'll get back to you at {email}."
    _remember(v, "trinetra", reply)
    db.commit()
    return note


LEAVE_GRACE = timedelta(minutes=2)  # the portfolio reloads on every page change: only forget if they don't come back


def leaving(v: GuestVisit) -> None:
    """The page closed. Forget them in LEAVE_GRACE unless another page of the site picks the visit up again."""
    v.last_seen = min(from_db(v.last_seen), datetime.now(timezone.utc) - FORGET_AFTER + LEAVE_GRACE)


def forget(v: GuestVisit) -> None:
    """They left: the conversation goes, the log (name, company, topics) stays."""
    v.messages = None
    v.last_said = None
    v.ended_at = v.ended_at or datetime.now(timezone.utc)


def sweep(db: Session, now: datetime) -> int:
    """Forget visits that went quiet; time out unanswered asks (so they reach the digest)."""
    idle = db.scalars(select(GuestVisit).where(GuestVisit.ended_at.is_(None), GuestVisit.last_seen < now - FORGET_AFTER)).all()
    for v in idle:
        forget(v)
    for ask in db.scalars(select(GuestAsk).where(GuestAsk.status == "waiting", GuestAsk.created_at < now - ASK_TIMEOUT)).all():
        ask.status = "timeout"
    return len(idle)


def digest(db: Session, now: datetime) -> str | None:
    """Every night at DIGEST_AT: what visitors left for Tarun, and the asks he missed. Once a day."""
    local_now = now_local()
    if (local_now.hour, local_now.minute) < DIGEST_AT:
        return None
    key = f"guest_digest:{local_now.date().isoformat()}"
    if db.get(KeyValue, key) is not None:
        return None
    db.add(KeyValue(key=key, value="1"))
    notes = db.scalars(select(GuestNote).where(GuestNote.digested_at.is_(None)).order_by(GuestNote.id)).all()
    missed = db.scalars(select(GuestAsk).where(GuestAsk.status == "timeout", GuestAsk.digested_at.is_(None))).all()
    if not notes and not missed:
        db.commit()
        return None
    lines = [f"• {n.name or 'A visitor'} ({' · '.join(x for x in (n.email, n.phone) if x)}): {n.message}" for n in notes]
    noted = {n.visit_id for n in notes}
    for a in missed:
        if a.visit_id not in noted:
            v = db.get(GuestVisit, a.visit_id)
            lines.append(f"• {(v.name if v else None) or 'A visitor'} asked what you were doing, and left no email.")
    people = len(noted | {a.visit_id for a in missed})
    text = f"📬 You missed {people} portfolio visitor{'s' if people != 1 else ''} today:\n" + "\n".join(lines)
    db.add(Message(role="trinetra", content=text, channel="reminder", mood="calm and caring", meta={"kind": "visitor_digest"}))
    push.send(db, "TRINETRA 📬", text, url="/#visitors", tag="visitor-digest")
    for item in [*notes, *missed]:
        item.digested_at = now
    db.commit()
    return text
