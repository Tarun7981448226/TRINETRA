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
FALLBACK_ANSWER = "I'm not sure about that one. The best way is to ask Tarun directly at tarundeepreddybv@gmail.com."
OFFLINE_SMALL_TALK = [  # when every model is busy: the commonest small talk still gets a real answer
    (r"\b(test|testing)\b", "Test away, I'm here. Ask me anything about Tarun's work: SKYNET, his research, or what I do for him."),
    (r"^\s*(hi|hey|hello|yo|sup)\b", "Hey! Ask me anything about Tarun's work, or say 'tour' and I'll show you around."),
    (r"\b(who|what) are you\b|\bare you (real|a bot|ai)\b", "I'm TRINETRA, the AI mentor Tarun built to run his days. Under each of my replies you can watch how I answered."),
    (r"\b(thanks|thank you|cool|nice|great|awesome)\b", "Glad to help. Anything else about Tarun you'd like to know?"),
]
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
EJECT_LINE = "That's not how anyone talks about Tarun here. You're done — goodbye."


def abusive(text: str) -> bool:
    if not ABUSE.search(text):
        return False
    # a sceptical question ("are his numbers fake?") is fair; a swear word never is
    return not (text.strip().endswith("?") and not re.search(rf"\b({_STRONG})\b", text, re.I))


def eject(db: Session, v: GuestVisit, text: str) -> dict:
    """Thrown out for abuse: the page closes on them, Tarun hears about it, the conversation is forgotten.
    No ban (Tarun's call) — they can open the site again."""
    v.topics = [*(v.topics or []), "removed: insulted you"][-12:]
    push.send(db, "TRINETRA 🚫", f"{_who(v)} insulted you on your portfolio and was thrown out: “{text[:160]}”",
              url="/#visitors", tag="visitor-removed")
    forget(v)
    db.commit()
    return {"reply": EJECT_LINE, "eject": True}


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
NEVER_NAMES = {"i", "me", "my", "you", "u", "your", "ur", "he", "him", "his", "she", "it", "this", "that", "there", "we",
               "they", "what", "who", "why", "how", "is", "are", "am", "test", "testing", "tested", "just", "looking", "ok",
               "okay", "yes", "no", "nope", "sure", "thanks", "thank", "cool", "nice", "lol", "hmm", "bot", "ai", "nothing",
               "nobody", "none", "anonymous", "guess", "skip", "later", "not", "dont", "don't", "why", "liar", "fake"}


LIKELY_NAMES = {"sam", "alex", "john", "max", "mark", "will", "grace", "joy", "hope", "faith", "victor", "rose", "jack", "ben",
                "dan", "tom", "ray", "art", "bill", "pat", "sky", "kim", "lee", "jay", "raj", "ali", "ana", "eva", "mia", "leo"}
TITLES = {"dr", "mr", "mrs", "ms", "miss", "prof", "professor", "sir", "madam"}


def _plausible_name(name: str, typed: str) -> bool:
    """A name has to be in what they typed, and can't be words like "testing you" or "just looking"."""
    words = [w.strip(".,'-") for w in name.split()]
    words = [w for w in words if w and w.lower() not in TITLES] or words
    return (0 < len(words) <= 3 and all(w.lower() not in NEVER_NAMES for w in words)
            and all(re.search(rf"(?<!\w){re.escape(w)}(?!\w)", typed, re.I) for w in words))


def _guess_name(text: str) -> tuple[str | None, str | None]:
    """Offline fallback: "I'm Priya from Google" → ("Priya", "Google"). A bare reply ("Sathwik") counts only when every
    word is unusual or typed with a capital — "testing you" or "just looking" is not a name."""
    from app.core.show import _common
    t = text.strip().strip(".!")
    m = re.search(r"(?:i'?m|i am|my name is|this is|it'?s|name'?s|call me)\s+([A-Za-z][A-Za-z'\-]+(?:\s+[A-Z][a-z'\-]+)?)",
                  t, re.I)
    name = m.group(1) if m else None
    if not m and re.fullmatch(r"[A-Za-z][A-Za-z'\-]{1,20}(\s+[A-Za-z][A-Za-z'\-]{1,20})?", t):
        words = t.split()  # iPhones capitalise the first word: "Great" is a word, not a name
        if all(w.lower() not in _common() or (w[0].isupper() and (len(words) > 1 or w.lower() in LIKELY_NAMES)) for w in words):
            name = t
    if name:  # "Priya from" → "Priya"
        words = [w for w in name.split() if w.lower() not in NOT_NAMES]
        name = " ".join(words) or None
    if name and not _plausible_name(name, t):
        name = None
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


UNDERSTAND = """

Right now, before you answer, read the WHOLE conversation and work out what the visitor's last message means. Reply ONLY with JSON:
{{"intent": "introduce" | "role" | "question" | "smalltalk" | "testing" | "feedback" | "other",
  "name": string or null,     // their OWN name, only if they clearly told you it (e.g. "I'm Priya", or just "Priya" right after you asked). Never a phrase like "testing you", "just looking", "a recruiter". No guessing.
  "company": string or null,  // only if they said where they work or study
  "role": "recruiter" | "manager" | "founder" | "researcher" | "ml_engineer" | "swe" | "mentor" | "student" | "other" | null,
  "reply": string}}           // what you say back, following every rule above (1–3 short spoken sentences, plain text)
If they're testing you or being sceptical ("testing you", "is this real?", "tarun is a liar"), answer that with calm, \
good-humoured confidence; don't treat it as a name. Known so far: {known}"""


SKILL_ASK = re.compile(
    r"\b(?:does|do|can|has|is)\s+(?:he|tarun)\b.{0,25}?\b(?:know|use|used|code in|program in|work(?:ed)? with|"
    r"experience (?:with|in)|familiar with|skilled in|proficient in)\s+([A-Za-z][\w.+#/\- ]{0,30}?)\s*(?:\?|$|,|\band\b)",
    re.I)
PERSONAL = re.compile(r"\b(girl ?friend|boy ?friend|wife|husband|partner|family|parents?|salary|money|religion|politics|"
                      r"address|phone|night|weekend|secret)s?\b", re.I)
GENERIC = {"ml", "ai", "machine learning", "deep learning", "python", "coding", "programming", "llms", "llm", "research",
           "papers", "paper", "projects", "experience", "software", "it", "this", "that", "them", "agents"}


def unlisted_skill(text: str) -> str | None:
    """'does he know kubernetes?' and Kubernetes isn't in the public brief → 'kubernetes'. Never let the model say yes."""
    m = SKILL_ASK.search(text)
    if not m:
        return None
    raw = m.group(1).strip(" ?.,")
    skill = re.sub(r"^(the|a|an|any|some)\s+", "", raw.lower())
    words = [w for w in re.split(r"[\s/]+", skill) if w]
    if (not skill or skill in GENERIC or len(skill) < 2 or PERSONAL.search(skill) or len(words) > 3
            or re.match(r"(what|how|why|when|where|who|which|about|us|our|we|you|your|a team|team|with|people|others|"
                        r"english|hindi|telugu|startups?|companies|clients|customers)\b", skill)):
        return None  # not a tool / language question — the model answers (and declines personal ones politely)
    b = brief().lower()
    # short tech tokens may sit inside a listed one: "sql" in "postgresql", "git" in "github actions"
    listed = all((w in b) if len(w) <= 4 else re.search(rf"(?<![\w]){re.escape(w)}(?![\w])", b) for w in words)
    return None if listed else re.sub(r"^(the|a|an|any|some)\s+", "", raw, flags=re.I)


def _model_name() -> str:
    m = llm.last_model.get() or "a model"
    return m.split("/")[-1]


async def _understand(v: GuestVisit) -> dict | None:
    """One call to the smart model with the whole conversation: what they meant (who they are, if they said) and the reply.
    None when the models are down or don't answer in JSON — the plain pattern matching takes over."""
    known = ", ".join(f"{k}: {x}" for k, x in (("name", v.name), ("company", v.company), ("role", v.role)) if x) or "nothing yet"
    if _said(v, ROLE_Q) and not v.role:
        known += f' (you just asked "{ROLE_Q}")'
    history = [{"role": "assistant" if m["role"] == "trinetra" else "user", "content": m["text"]} for m in (v.messages or [])[-12:]]
    try:
        raw = await llm.complete([{"role": "system", "content": guest_prompt(brief(), v.name, v.company, v.role)
                                   + UNDERSTAND.format(known=known)}, *history],
                                 tier="guest", temperature=0.6, max_tokens=500, json_mode=True, reasoning="low")
        d = json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except llm.LLMUnavailable:  # every model is down or out of time: don't spend another full budget on _say
        return {"offline": True}
    except Exception:  # not JSON
        return None
    if not isinstance(d, dict) or not isinstance(d.get("reply"), str) or not d["reply"].strip():
        return None
    typed = (v.messages or [{}])[-1].get("text", "")
    name = d.get("name") if isinstance(d.get("name"), str) else None
    d["name"] = name.strip()[:80] if name and _plausible_name(name.strip(), typed) else None
    d["company"] = str(d["company"]).strip()[:120] if d.get("company") else None
    d["role"] = d.get("role") if d.get("role") in ROLES else None
    return d


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
                                           tier="guest", temperature=0.7, max_tokens=300, reasoning="low"), strip_name=False) or fallback
    except llm.LLMUnavailable:
        text = fallback
    return _sparing(v, _short(text))


def _short(text: str, keep: int = 3) -> str:
    """Spoken and on a small panel: three sentences at most, however chatty the model was."""
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"])", text.strip())
    return " ".join(parts[:keep])


ASK_PASSWORD = "If you're really Tarun, tell me our password. You have 3 tries."
NO_PASSWORD_YET = ("Tarun hasn't set my password yet, so I can't tell if it's really him. "
                   "Happy to tell you about his work though.")
NOT_TARUN = ("Three wrong passwords, so you're not Tarun. No hard feelings! "
             "I'm still happy to tell you about him and his work.")
LOCK = re.compile(r"^\s*(lock( it| me out)?|sign ?out|log ?out|logout|i'?m done)[\s.!]*$", re.I)
LOCKED = "Locked. Anyone typing here now is a guest again."
CANCEL = re.compile(r"^\s*(no|nope|cancel|never ?mind|not (him|that tarun|me)|wrong tarun|skip|forget it|stop)\b[\s.!]*$", re.I)


def owner_ready(v: GuestVisit) -> bool:
    """He proved it with the password: this visit talks to his own TRINETRA (memories, timetable, everything)."""
    return v.owner == "yes"


def _challenge(db: Session, v: GuestVisit, step) -> dict | None:
    """They say they're Tarun. None when this visit can't try any more (wrong 3 times already)."""
    from app.core import owner
    if v.owner == "no":
        step("wellbeing", "Guard: this visit already got the password wrong 3 times")
        return {"reply": "You've used your three tries on this visit, so I'll keep treating you as a guest."}
    if not owner.has_password(db):
        step("wellbeing", "Guard: no owner password set yet — can't verify")
        return {"reply": NO_PASSWORD_YET}
    if owner.paused(db):
        step("wellbeing", "Guard: too many wrong passwords this hour — checks paused")
        return {"reply": "Too many wrong passwords lately, so I've paused the check for an hour. Try again later."}
    v.owner, v.owner_tries = "asking", v.owner_tries or 0
    step("wellbeing", "Guard: says they're Tarun — password first (3 tries)")
    return {"reply": ASK_PASSWORD, "secret": True}


def _password_turn(db: Session, v: GuestVisit, text: str) -> dict:
    """The answer to "what's our password?". It is never stored, never sent to a model."""
    from app.core import owner
    v.turns += 1
    _remember(v, "visitor", "••••••")
    trace = [{"team": "wellbeing", "did": "Guard: checked the password (never stored, never sent to a model)"}]

    def done(reply: str, **extra) -> dict:
        _remember(v, "trinetra", reply)
        db.commit()
        return {"reply": reply, **extra, "trace": trace}

    if CANCEL.search(text):
        v.owner = None
        return done("No problem. What would you like to know about Tarun?")
    if owner.paused(db):
        v.owner = None
        return done("Too many wrong passwords lately, so I've paused the check for an hour. Try again later.")
    if owner.check(db, text):
        v.owner, v.name = "yes", "Tarun"
        v.messages = []  # the guest chat isn't needed any more; the welcome below is all this visit keeps
        push.send(db, "TRINETRA 🔐", "You unlocked me on your portfolio with the password. Not you? Change it in the app (Visitors).",
                  url="/#visitors", tag="owner-unlock")
        trace.append({"team": "command", "did": "Verified: it's Tarun — switching to his own TRINETRA"})
        return done("It's really you. Welcome back, Tarun. You're talking to your own TRINETRA now: "
                    "your plan, your goals, anything you'd ask me in the app.", owner=True)
    v.owner_tries = (v.owner_tries or 0) + 1
    left = owner.TRIES - v.owner_tries
    if left > 0:
        return done(f"That's not it. {left} {'try' if left == 1 else 'tries'} left.", secret=True)
    v.owner = "no"
    v.topics = [*(v.topics or []), "pretended to be you (3 wrong passwords)"][-12:]
    push.send(db, "TRINETRA ⚠️", f"{_who(v) if v.name != 'Tarun' else 'A visitor'} said they're you on your portfolio "
              "and got the password wrong 3 times.", url="/#visitors", tag="owner-fail")
    trace.append({"team": "reminders", "did": "Told Tarun someone tried to pass as him"})
    return done(NOT_TARUN)


async def chat(db: Session, v: GuestVisit, text: str) -> dict:
    text = text.strip()[:MAX_TEXT]
    if v.owner == "asking":  # before anything else: a password can look like anything, and it's never stored
        return _password_turn(db, v, text)
    v.turns += 1
    _remember(v, "visitor", text)
    trace: list[dict] = []  # what really happened, step by step — the portfolio shows it live in the Brain

    def step(team: str, did: str) -> None:
        trace.append({"team": team, "did": did})

    def done(reply: str, **extra) -> dict:
        _remember(v, "trinetra", reply)
        db.commit()
        if not trace or trace[-1]["team"] != "command":
            step("command", "TRINETRA approved the reply")
        return {"reply": reply, **extra, "trace": trace}

    # 0. Insulting Tarun gets you thrown out.
    if abusive(text):
        return {**eject(db, v, text), "trace": [{"team": "wellbeing", "did": "Guard: an insult about Tarun — the visitor is removed"},
                                                 {"team": "reminders", "did": "Told Tarun on his phone"}]}
    # 0b. "Show me your emotions" → just the names; the face acts them out (whatever step of the chat we're at).
    from app.agents.command import EMOTION_LABEL, perform_request
    from app.core import show
    if wanted := show.request(text, lab=True):  # "dance", "play the guitar", "stop" → just the name; the character performs it
        step("command", f"Language reader: understood “{show.label(wanted)}” (typos and slang fixed)")
        step("mentor_emotion", "Performer: acts it out")
        return done(show.label(wanted), show=wanted)
    if perform := perform_request(text):
        step("command", "Language reader: a request to show emotions")
        step("mentor_emotion", "Emotion engine: " + ", ".join(perform))
        return done(" · ".join(EMOTION_LABEL[e] for e in perform), perform=perform)
    # 1. They gave us their email / number — always welcome, never refused.
    from app.agents.command import CRISIS_LINE, DISTRESS
    if not DISTRESS.search(text) and (thanks := _take_contact(db, v, text)) is not None:
        step("communications", "Contact keeper: saved the email / number")
        step("reminders", "Sent it to Tarun's phone")
        return done(thanks, celebrate=True)
    # 1b. Someone in crisis: care and a real way to get help, before anything about Tarun (their contact is still kept).
    if DISTRESS.search(text):
        _take_contact(db, v, text)
        step("wellbeing", "Guard: crisis words — care and the 988 line, nothing else")
        return done("I'm really glad you said something. What you're feeling matters. " + CRISIS_LINE)
    # 1c. "I'm Tarun" / "I'm your creator": prove it with the password first.
    from app.core import owner
    if owner.claims_to_be_tarun(text) and (c := _challenge(db, v, step)) is not None:
        return done(c.pop("reply"), **c)
    # 2. Leaving.
    if BYE.search(text) and len(text) < 60:
        step("communications", "Host: a goodbye")
        ask = _important(v) and not (v.email or v.phone) and not _said(v, CONTACT_FORM_Q)
        return done(f"Thanks for stopping by{', ' + v.name if v.name else ''}! "
                    + (CONTACT_ASK.replace("just drop", "drop") if ask else "Tarun will be glad you came. Take care."))
    # 3. They want to leave their details: the card, whoever they are (they asked).
    if CONTACT_INTENT.search(text) and not (v.email or v.phone):
        step("communications", "Host: they want to leave details — show the card")
        return done(CONTACT_HOW, contact_form=True)
    # 4. "What is Tarun doing right now?" → his phone.
    if NOW_PATTERN.search(text):
        ask = GuestAsk(visit_id=v.id, question=text)
        db.add(ask)
        db.flush()
        push.send(db, "TRINETRA 👀", f"{_who(v)} is on your portfolio and asks what you're doing right now. Tap to answer.",
                  url=f"/#ask/{ask.id}", tag=f"ask-{ask.id}")
        v.topics = [*(v.topics or []), "asked what you're doing"][-12:]
        step("reminders", "Asked Tarun on his phone what he's doing")
        return done(CHECKING, ask_id=ask.id)

    # 4b. "Does he know Kubernetes?" — not in the brief: an honest answer, never a model's guess.
    if (skill := unlisted_skill(text)) is not None:
        step("memory", f"Fact check: “{skill}” isn't in Tarun's public brief — no guessing")
        return done(f"{skill[:1].upper() + skill[1:]} isn't on his public list, so I won't guess. He's worked with Python, "
                    "FastAPI, Docker, LangGraph and LLM agents — and you can ask him directly at tarundeepreddybv@gmail.com.")
    # 5. Everything else: the model reads the whole conversation once — who they are (if they said) and what to say back.
    u = await _understand(v)
    offline = bool(u and u.get("offline"))
    if offline:
        u = None
    if u is not None:
        step("command", f"Understanding ({_model_name()}): read the whole chat → {u.get('intent') or 'question'}")
    else:
        step("command", "Understanding: models busy — plain pattern matching")
    introducing = v.name is None and v.turns <= 2  # don't keep pestering someone who'd rather not say
    if introducing:
        if u is not None:
            name, company, role = u["name"], u["company"], (u["role"] or _role_from_words(text)) if u["name"] else None
        else:
            name, company = _guess_name(text)
            role = _role_from_words(text)
        name = " ".join(w[:1].upper() + w[1:] for w in name.split()) if name else None  # "charan" → "Charan"
        if name and name.split()[0].lower() == "tarun" and v.owner is None and (c := _challenge(db, v, step)) is not None:
            return done(c.pop("reply"), **c)
        if name:  # only an introduction tells us who THEY are ("his research?" doesn't make them a researcher)
            v.name, v.company, v.role = name, v.company or company, v.role or role
            step("memory", f"Profile keeper: remembered the visitor's name ({name})")
            push.send(db, "TRINETRA 👋", f"{_who(v)} is talking to me on your portfolio.", url="/#visitors", tag="visitor")
        if v.name and not v.role:
            return done(f"Nice to meet you, {v.name}! {ROLE_Q}", role_options=ROLE_OPTIONS)
    answering_role = not introducing and v.role is None and _said(v, ROLE_Q) and v.turns <= 4
    if answering_role:  # they typed it instead of tapping a button
        role = (u or {}).get("role") or _role_from_words(text)
        if role or u is None or u.get("intent") == "role":
            v.role = role or "other"
            v.company = v.company or (u or {}).get("company") or _guess_name(text)[1]
        else:  # a question instead of an answer — answer it; the buttons are still there
            answering_role = False
    if (introducing and v.name) or answering_role:
        step("communications", "Host: a short pitch made for who they are")
        return await pitch(db, v, done)

    # 6. A normal question about Tarun / TRINETRA.
    v.topics = [*(v.topics or []), _topic(text)][-12:]
    step("memory", "Privacy guard: only Tarun's public brief is used — nothing private")
    step("communications", "Host: wrote the reply")
    if u is not None:
        reply = _sparing(v, _short(humanize(u["reply"], strip_name=False))) or FALLBACK_ANSWER
    elif offline:
        reply = next((line for pat, line in OFFLINE_SMALL_TALK if re.search(pat, text, re.I)), FALLBACK_ANSWER)
    else:
        history = [{"role": "assistant" if m["role"] == "trinetra" else "user", "content": m["text"]} for m in v.messages[-10:]]
        reply = await _say(v, history, FALLBACK_ANSWER)
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
