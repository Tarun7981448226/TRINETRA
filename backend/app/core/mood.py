"""Mood modes you can ask for ("be angry with me", "hype me up", "back to normal").

A requested mode sticks until you change it, and colours every reply and reminder.
Distress always overrides it: an angry coach never shouts at someone who is hurting.
(The full Emotion Engine in phase 3b will pick moods on its own; this is the manual dial.)
"""
import re

from sqlalchemy.orm import Session

from app.db.models import KeyValue

MODE_KEY = "mood_mode"

MODES = {
    "angry": (
        "ANGRY — genuinely fired up and loud, like a coach yelling from the sideline because they refuse "
        "to watch someone waste their potential. Short, punchy, intense sentences. Zero excuses accepted. "
        "Blunt, raw, demanding. Attack the excuse and the action, never their worth — no insults, "
        "no name-calling, no humiliation. Write it the way a furious person actually shouts out loud: very short bursts, exclamation marks, repeated words for punch (Three times! THREE!), rhetorical questions (What are you doing?!)"
    ),
    "strict": "firm and disappointed — push them, kindly but without excuses",
    "gentle": "gentle and comforting",
    "hype": "proud and energised — hype them up, big energy, make them feel unstoppable",
}

LABELS = {"angry": "😠 angry", "strict": "😤 strict", "gentle": "🤍 gentle", "hype": "🔥 hype"}

_W = r"(be|get|go|talk|speak|turn|switch|put|use|show|want|need)"
REQUESTS: list[tuple[str | None, re.Pattern]] = [
    (None, re.compile(
        r"\b(normal mode|back to normal|be normal|calm down|stop being (angry|mad|harsh|strict|so \w+)|"
        r"reset (your )?mood|chill out|default mode)\b", re.I)),
    ("angry", re.compile(
        rf"\b(angry|mad|furious|rage|aggressive)\s+(mode|version|voice|trinetra)\b|\b{_W}\b[^.?!]{{0,30}}\b(angry|mad|furious|aggressive)\b|"
        r"\b(scold|yell at|shout at|roast) me\b", re.I)),
    ("strict", re.compile(rf"\b(strict|tough|harsh)\s+(mode|version)\b|\b{_W}\b[^.?!]{{0,20}}\b(strict|tough|harsh)\b", re.I)),
    ("gentle", re.compile(rf"\b(gentle|soft|kind)\s+(mode|version)\b|\b{_W}\b[^.?!]{{0,20}}\b(gentle|soft|kind)\b|\bcomfort me\b", re.I)),
    ("hype", re.compile(r"\b(hype|pump) me( up)?\b|\bhype (mode|version)\b|\bmotivate me\b", re.I)),
]


_MODE_WORDS = {
    "angry": r"angry|mad|furious|rage|aggressive|scold\w*|yell\w*|shout\w*|roast\w*",
    "strict": r"strict|tough|harsh",
    "gentle": r"gentle|soft|kind|comfort\w*",
    "hype": r"hype\w*|motivat\w*|pump\w*",
}
_DEMO = re.compile(
    r"\b(show|demonstrate|demo|example|sample|let me hear|how (would|do) you|what does|what's your|try)\b", re.I
)
# "scold Rahul" / "yell at my brother" — aimed at someone other than me
_AT_SOMEONE = re.compile(
    r"\b(scold|yell at|shout at|roast)\s+(?!me\b|myself\b|us\b)(?:(?:my|our)\s+)?(?P<who>[a-z][\w'-]*)", re.I
)
_NOBODY = {"someone", "somebody", "anyone", "anybody", "people", "them", "him", "her"}


def detect_demo(text: str) -> tuple[str, str | None] | None:
    """One-off performances: ('angry', 'Rahul') for "scold Rahul", ('angry', None) for "show me your angry side".
    Returns None if this isn't a demo request. A demo never changes the lasting mode."""
    if m := _AT_SOMEONE.search(text):
        who = m.group("who")
        return "angry", None if who.lower() in _NOBODY else who
    if _DEMO.search(text):
        for mode, words in _MODE_WORDS.items():
            if re.search(rf"\b({words})\b", text, re.I):
                return mode, None
    return None


def detect_request(text: str) -> tuple[bool, str | None]:
    """(asked_for_a_mode_change, mode or None for 'back to normal')."""
    for mode, pattern in REQUESTS:
        if pattern.search(text):
            return True, mode
    return False, None


def get_mode(db: Session) -> str | None:
    row = db.get(KeyValue, MODE_KEY)
    return row.value if row and row.value in MODES else None


def set_mode(db: Session, mode: str | None) -> None:
    row = db.get(KeyValue, MODE_KEY)
    if row is None:
        db.add(KeyValue(key=MODE_KEY, value=mode))
    else:
        row.value = mode
    db.flush()


def apply(db: Session, default_mood: str) -> str:
    """The mood to speak in: a requested mode wins over the situational default."""
    mode = get_mode(db)
    return MODES[mode] if mode else default_mood
