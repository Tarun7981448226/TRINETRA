"""Little shows on request — "dance", "play the guitar", "jump", "stop".

The words become a plan for the character ({"show": "dance" | "play" | "act" | "stop", ...}); the app and the
portfolio act it out (static/music.js makes the music, buddy.js the moves). The reply is just the name:
"💃 Dance", "🎸 Guitar · 😢 Sad". No LLM, no voice — instant.
"""
from __future__ import annotations

import difflib
import re

INSTRUMENTS = {  # what it plays → the words for it
    "guitar": "guitars?|acoustic guitar|guitarr?",
    "electric": "electric guitar|electric|rock guitar|e-?guitar",
    "bass": "bass( guitar)?|bassguitar",
    "ukulele": "ukuleles?|uke",
    "banjo": "banjos?",
    "sitar": "sitars?|veena|tanpura",
    "violin": "violins?|fiddle",
    "cello": "cellos?|double bass",
    "piano": "pianos?|keyboard|keys|grand piano",
    "harp": "harps?",
    "flute": "flutes?|bansuri|recorder",
    "sax": "sax(ophone)?s?",
    "trumpet": "trumpets?|horn",
    "xylophone": "xylophones?|marimba|glockenspiel",
    "drums": "drums?|drum ?kit|drumset|tabla|beats?",
}
INSTRUMENT_LABEL = {"guitar": "🎸 Guitar", "electric": "🎸 Electric guitar", "bass": "🎸 Bass", "ukulele": "🎸 Ukulele",
                    "banjo": "🪕 Banjo", "sitar": "🪕 Sitar", "violin": "🎻 Violin", "cello": "🎻 Cello", "piano": "🎹 Piano",
                    "harp": "🎶 Harp", "flute": "🪈 Flute", "sax": "🎷 Saxophone", "trumpet": "🎺 Trumpet",
                    "xylophone": "🎶 Xylophone", "drums": "🥁 Drums"}
ACTIONS = {  # little moves
    "jump": "jump|hop|bounce",
    "spin": "spin|roll|twirl|flip|turn around|do a barrel roll|rotate",
    "wave": "wave|say hi|say hello|wave hi",
    "cry": "cry|weep|sob|tears",
    "laugh": "laugh|giggle|lol",
    "sleep": "sleep|nap|go to sleep",
}
ACTION_LABEL = {"jump": "🦘 Jump", "spin": "🌀 Spin", "wave": "👋 Wave", "cry": "😢 Cry", "laugh": "😂 Laugh", "sleep": "😴 Sleep"}
MOOD_EXTRA = {  # music words → the mood it plays in (on top of the emotion words)
    "caring": "romantic|love|calm|chill|relax\\w*|peaceful|soft|soothing|slow",
    "excited": "energetic|party|fast|upbeat|hype|lit|groovy",
    "sleepy": "lullaby|sleepy|bedtime",
    "sad": "sad|melancholy|emotional|heartbreak\\w*|blue",
    "angry": "angry|aggressive|intense|metal|heavy",
    "proud": "epic|heroic|victory|triumphant|proud",
}

LAB = [  # the portfolio's lab (TRINETRA HQ): orders for the team
    ("assemble", re.compile(r"^\s*((team|everyone|agents),?\s*)?(assemble|line up|fall in)[\s.!]*$|^\s*(please\s+)?(assemble|line up) (the |your )?(team|agents|squad)[\s.!]*$", re.I)),
    ("roles", re.compile(r"\bwhat (do|does) (your |all your |the )?(agents?|bots?)( all)? do\b|\bwho does what\b|\b(your )?agents'? (tasks|jobs|roles)\b", re.I)),
    (None, re.compile(r"\b(open|show|visit|take me to|go to)( me)? (the |your )(lab|hq|headquarters|agents)\b", re.I)),
]
LAB_LABEL = {"assemble": "🧍 Assemble", "roles": "❓ Who does what", None: "🧪 Lab"}
PLAY = re.compile(r"\b(play|playing|plays|jam|strum|perform|bang|hit|rock out|pick up)\b", re.I)
MUSIC = re.compile(r"\b(music|songs?|tunes?|melody|something|anything|beats?)\b|\bsing\b", re.I)
DANCE = re.compile(r"\b(dance|dancing|dances|boogie|groove|bust a move|shake it|party time)\b", re.I)
STOP = re.compile(r"^\s*(please\s+|ok(ay)?\s+|now\s+)?(stop|enough|quiet|silence|shh+|pause|halt|turn it off|be quiet|that'?s enough)"
                  r"(\s+(it|that|this|the music|music|playing|the song|song|dancing|now|please|already|trinetra))*[\s.!]*$", re.I)
ASK = re.compile(r"^\s*(can you|could you|will you|would you|please|pls|plz|now|show me( how you| you)?|let me see you|"
                 r"i want to see you|do a|do|go|try to|let'?s|you)?\s*", re.I)

VOCAB_SHOW = sorted({w for pats in (*INSTRUMENTS.values(), *ACTIONS.values()) for w in re.findall(r"[a-z]{4,}", pats)} | {"dance", "dancing"})


def _vocab() -> list[str]:
    from app.agents.command import EMOTION_WORDS
    words = set(VOCAB_SHOW)
    for pats in EMOTION_WORDS.values():
        words |= set(re.findall(r"[a-z]{4,}", pats))
    return sorted(words)


def fix_typos(text: str, loose: bool = False) -> str:
    """'show me exitement' → 'show me excitement', 'play the gituar' → 'play the guitar'."""
    vocab = _vocab()
    def one(m: re.Match) -> str:
        w = m.group(0)
        if len(w) < 5 or w.lower() in vocab:
            return w
        best = difflib.get_close_matches(w.lower(), vocab, 1, 0.65 if loose else 0.8)
        return best[0] if best else w
    return re.sub(r"[A-Za-z]+", one, text)


def _find(table: dict[str, str], text: str) -> str | None:
    hits = [(m.start(), k) for k, pat in table.items() if (m := re.search(rf"\b({pat})\b", text, re.I))]
    return min(hits)[1] if hits else None


def mood_of(text: str) -> str | None:
    from app.agents.command import EMOTION_WORDS
    if m := _find(MOOD_EXTRA, text):
        return m
    m = _find(EMOTION_WORDS, text)
    return m if m and m != "firm" else None


def request(text: str, lab: bool = False) -> dict | None:
    """What show (if any) the words ask for."""
    raw = text.strip()
    if not raw or len(raw) > 90:
        return None
    if STOP.match(raw):
        return {"show": "stop"}
    for cmd, pat in LAB if lab else ():  # the lab lives on the portfolio, so only visitors' chat checks for it
        if pat.search(raw):
            return {"show": "lab", "cmd": cmd}
    t = fix_typos(raw, loose=bool(PLAY.search(raw)))
    if DANCE.search(t) and not re.search(r"\b(class|lesson|teacher|studio|competition)\b", t, re.I):
        return {"show": "dance", "mood": mood_of(t) or "excited", "seconds": 10}
    inst = _find(INSTRUMENTS, t)
    if inst == "bass" and re.search(r"\bdouble bass\b", t, re.I):
        inst = "cello"
    alone = inst and re.fullmatch(rf"((the|a|some|your|sad|happy|calm|epic|soft)\s+)*({INSTRUMENTS[inst]})(\s+(please|now|time|solo|music))*[\s.!]*",
                                  ASK.sub("", t, count=1), re.I)  # just "guitar!" or "can you guitar" — not "where are my keys"
    if inst and (PLAY.search(t) or alone):
        return {"show": "play", "instrument": inst, "mood": mood_of(t)}
    if PLAY.search(t) and MUSIC.search(t) or re.fullmatch(r"\s*(sing|sing (a|me a|us a)? ?song|music|play)\s*[.!]*", t, re.I):
        return {"show": "play", "instrument": None, "mood": mood_of(t)}
    if len(t) <= 50 and not re.search(r"\b(dice|die|ball|call|number|joke)\b", t, re.I):
        rest = ASK.sub("", t, count=1)
        for act, pat in ACTIONS.items():
            if re.match(rf"({pat})\b", rest, re.I):
                return {"show": "act", "action": act}
    return None


def label(show: dict) -> str:
    from app.agents.command import EMOTION_LABEL
    kind = show["show"]
    if kind == "stop":
        return "⏹ Stopped"
    if kind == "dance":
        return "💃 Dance"
    if kind == "lab":
        return LAB_LABEL.get(show.get("cmd"), "🧪 Lab")
    if kind == "act":
        return ACTION_LABEL[show["action"]]
    name = INSTRUMENT_LABEL.get(show.get("instrument") or "", "🎶 Music")
    return f"{name} · {EMOTION_LABEL[show['mood']]}" if show.get("mood") in EMOTION_LABEL else name
