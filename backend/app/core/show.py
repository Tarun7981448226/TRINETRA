"""Understanding requests to the character: dance, play an instrument, a little move, an emotion, stop — and on the
portfolio, orders for the agents ("assemble"). Typos, slang and casual phrasing all land in the right place.

    understand("pls play all ur instrumnts")  → {"show": "play", "instrument": "all", "mood": None}
    understand("dance alone for 30 sec")      → {"show": "dance", "partner": False, "seconds": 30, ...}
    understand("show me angery then hapy")    → {"show": "emotion", "emotions": ["angry", "happy"]}
    understand("i play guitar")               → None (a statement about the user — normal chat answers it)

The pipeline (no LLM, instant, deterministic):
  1. normalise — lower-case, slang and contractions ("u", "ur", "pls", "lets", "wanna", "dont"), stretched letters ("stopppp")
  2. correct typos — a word that isn't common English (data/common_words.txt) and is close to a word we know
     (Damerau–Levenshtein distance ≤ 1 for short words, ≤ 2 for longer) becomes that word: gituar → guitar, angery → angry
  3. map words to concepts (instrument, emotion, move, dance, play, stop, …), multi-word phrases first ("bass guitar")
  4. intent — negation ("don't dance"), the user talking about themselves ("i'm sad", "i play guitar"), about Tarun
     ("does tarun play guitar?") or about preferences ("do you like music?") are NOT requests; then
     stop > agents' orders > "what can you do" > dance > play > move > emotion
  5. slots — every instrument named (in order) or "all", the mood, dance solo / with her, how long, several emotions in order
The reply is just the name ("🎸 Guitar → 🎹 Piano", "💃 Dance solo · 30 s", "😠 Angry · 😊 Happy"); the character performs it.
common_words.txt: the 10,000 most common English words (first20hours/google-10000-english, personal/educational use).
"""
from __future__ import annotations

import difflib
import re
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------- the words we know
INSTRUMENT_WORDS = {
    "guitar": ["guitar", "guitars", "acoustic"], "electric": ["electric"], "bass": ["bass"], "ukulele": ["ukulele", "ukuleles", "uke"],
    "banjo": ["banjo", "banjos"], "sitar": ["sitar", "sitars", "veena", "tanpura"], "violin": ["violin", "violins", "fiddle"],
    "cello": ["cello", "cellos"], "piano": ["piano", "pianos", "keyboard", "keys"], "harp": ["harp", "harps"],
    "flute": ["flute", "flutes", "bansuri", "recorder"], "sax": ["sax", "saxophone", "saxophones"], "trumpet": ["trumpet", "trumpets", "horn"],
    "xylophone": ["xylophone", "marimba", "glockenspiel"], "drums": ["drums", "drum", "drumkit", "drumset", "tabla", "percussion"],
}
INSTRUMENT_PHRASES = {"electric guitar": "electric", "rock guitar": "electric", "bass guitar": "bass", "base guitar": "bass",
                      "double bass": "cello", "grand piano": "piano", "drum kit": "drums", "drum set": "drums"}
INSTRUMENT_LABEL = {"guitar": "🎸 Guitar", "electric": "🎸 Electric guitar", "bass": "🎸 Bass", "ukulele": "🎸 Ukulele",
                    "banjo": "🪕 Banjo", "sitar": "🪕 Sitar", "violin": "🎻 Violin", "cello": "🎻 Cello", "piano": "🎹 Piano",
                    "harp": "🎶 Harp", "flute": "🪈 Flute", "sax": "🎷 Saxophone", "trumpet": "🎺 Trumpet",
                    "xylophone": "🎶 Xylophone", "drums": "🥁 Drums"}
ACTION_WORDS = {
    "jump": ["jump", "jumps", "jumping", "hop", "hopping", "bounce", "celebrate"],
    "spin": ["spin", "spinning", "roll", "rolling", "twirl", "flip", "backflip", "rotate", "cartwheel", "somersault"],
    "wave": ["wave", "waving"], "cry": ["cry", "crying", "weep", "sob", "sobbing"], "laugh": ["laugh", "laughing", "giggle"],
    "sleep": ["sleep", "sleeping", "nap", "snooze", "doze"],
}
ACTION_LABEL = {"jump": "🦘 Jump", "spin": "🌀 Spin", "wave": "👋 Wave", "cry": "😢 Cry", "laugh": "😂 Laugh", "sleep": "😴 Sleep"}
EMOTION_WORDS = {  # emotion → its words
    "happy": ["happy", "happiness", "joy", "joyful", "glad", "smile", "smiling", "cheerful"],
    "excited": ["excited", "excitement", "exciting", "hyped", "hype", "pumped", "thrilled"],
    "proud": ["proud", "pride", "confident"],
    "caring": ["caring", "care", "kind", "kindness", "love", "loving", "gentle", "warm", "sweet", "affectionate"],
    "shy": ["shy", "shyness", "blush", "blushing", "embarrassed", "cute", "coy"],
    "surprised": ["surprised", "surprise", "shocked", "shock", "amazed", "wow", "scared", "afraid", "fear", "confused", "curious"],
    "firm": ["firm", "serious", "strict", "stern"],
    "angry": ["angry", "anger", "mad", "furious", "annoyed", "rage", "grumpy"],
    "sad": ["sad", "sadness", "unhappy", "upset", "depressed", "gloomy"],
    "sleepy": ["sleepy", "tired", "bored", "boring", "drowsy", "yawn"],
}
MOOD_WORDS = {  # music words → the mood it plays in
    "caring": ["romantic", "calm", "chill", "relaxing", "relax", "peaceful", "soft", "soothing", "slow"],
    "excited": ["energetic", "party", "fast", "upbeat", "lit", "groovy"], "sleepy": ["lullaby", "bedtime"],
    "sad": ["melancholy", "emotional", "heartbreak", "heartbroken"], "angry": ["aggressive", "intense", "metal", "heavy"],
    "proud": ["epic", "heroic", "victory", "triumphant"],
}
DANCE = {"dance", "dances", "dancing", "danced", "boogie", "groove", "moonwalk", "salsa", "disco", "twerk", "breakdance"}
DANCE_PHRASES = re.compile(r"\b(bust a move|shake it|show (me )?your moves|hit the dance floor)\b")
PLAY = {"play", "plays", "playing", "jam", "strum", "perform", "sing", "singing", "rock"}
MUSIC = {"music", "song", "songs", "tune", "tunes", "melody", "something", "anything", "beat", "beats", "track", "medley"}
STOP = {"stop", "enough", "quiet", "silence", "shh", "pause", "halt", "cancel", "mute", "end", "esc", "escape"}
STOP_FILLER = {"please", "it", "that", "this", "the", "music", "playing", "song", "dancing", "dance", "now", "already", "trinetra", "be",
               "ok", "okay", "turn", "off", "all", "everything", "just", "can", "you", "no", "more", "thanks", "thank", "is", "that"}
ALL = {"all", "every", "each", "everything", "medley"}
EMOTION_TRIGGER = {"show", "act", "make", "do", "give", "be", "look", "pretend", "express", "display", "face", "faces", "expression",
                   "expressions", "mood", "moods", "emotion", "emotions", "feeling", "feelings", "react", "perform", "try"}
FILLER = {"can", "could", "will", "would", "you", "please", "now", "go", "let", "us", "me", "a", "an", "the", "some", "your",
          "just", "again", "quick", "quickly", "for", "trinetra", "hey", "hi", "ok", "okay", "yo", "do", "try", "to", "little",
          "bit", "time", "show", "see", "want", "i", "like", "love", "id", "around", "too", "also", "and", "are", "able", "how", "know"}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10, "fifteen": 15,
           "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "a": 1, "half": 0.5}
SLANG = {"tmrw": "tomorrow", "tmr": "tomorrow", "tmrrw": "tomorrow", "tomoro": "tomorrow", "2moro": "tomorrow", "tmo": "tomorrow",
         "tdy": "today", "2day": "today", "tonite": "tonight", "2nite": "tonight", "mve": "move", "mov": "move",
         "resched": "reschedule", "sched": "schedule", "skd": "schedule", "rmd": "remind", "rmnd": "remind",
         "wat": "what", "wut": "what", "wht": "what", "whats": "what is", "hw": "how", "y": "why", "cn": "can", "cud": "could",
         "sho": "show", "shw": "show", "pl": "please", "u": "you", "ya": "you", "yu": "you", "ur": "your", "yr": "your", "pls": "please", "plz": "please", "plez": "please", "pleas": "please",
         "wanna": "want to", "gonna": "going to", "lemme": "let me", "gimme": "give me", "r": "are", "im": "i am", "ill": "i will",
         "dont": "do not", "cant": "can not", "cannot": "can not", "wont": "will not", "doesnt": "does not", "didnt": "did not",
         "isnt": "is not", "youre": "you are", "lets": "let us", "luv": "love", "sec": "second", "secs": "seconds", "min": "minute",
         "mins": "minutes", "thru": "through", "da": "the", "teh": "the", "nd": "and", "n": "and", "w": "with",
         "wit": "with", "gf": "girlfriend", "ty": "thanks", "thx": "thanks", "fav": "favorite"}
TYPO_OVERRIDES = {"exited": "excited", "wav": "wave", "wavee": "wave", "angery": "angry", "suprised": "surprised", "suprise": "surprise",
                  "embarassed": "embarrassed", "saxaphone": "saxophone", "ukelele": "ukulele", "xylofone": "xylophone",
                  "zylophone": "xylophone", "violen": "violin", "gutiar": "guitar", "giutar": "guitar", "piyano": "piano",
                  "danse": "dance", "dansing": "dancing", "trumphet": "trumpet", "cryy": "cry", "sadd": "sad", "happi": "happy",
                  "asemble": "assemble", "assmble": "assemble", "assamble": "assemble", "emoshions": "emotions", "emotons": "emotions"}

CONCEPT: dict[str, tuple[str, str]] = {}  # word → (kind, value)
for _k, _ws in INSTRUMENT_WORDS.items():
    for _w in _ws: CONCEPT[_w] = ("inst", _k)
for _k, _ws in ACTION_WORDS.items():
    for _w in _ws: CONCEPT[_w] = ("act", _k)
for _k, _ws in EMOTION_WORDS.items():
    for _w in _ws: CONCEPT.setdefault(_w, ("emo", _k))
for _k, _ws in MOOD_WORDS.items():
    for _w in _ws: CONCEPT.setdefault(_w, ("mood", _k))
for _w in DANCE: CONCEPT[_w] = ("dance", "")
for _w in PLAY: CONCEPT.setdefault(_w, ("play", ""))
CONCEPT["rock"] = ("play", "")
# the words the typo-fixer may turn things into
KNOWN = set(CONCEPT) | MUSIC | STOP | ALL | EMOTION_TRIGGER | {
    "assemble", "agents", "agent", "brain", "team", "instruments", "instrument", "emotions", "abilities", "skills", "tricks",
    "alone", "solo", "yourself", "partner", "girlfriend", "forever", "nonstop", "seconds", "second", "minutes", "minute",
    "together", "without", "with", "then", "please", "everything", "every", "explain", "commands", "help"}


@lru_cache(maxsize=1)
def _common() -> frozenset[str]:  # common English words are never "corrected" ("say" stays "say", not "sad")
    path = Path(__file__).resolve().parents[1] / "data" / "common_words.txt"
    try:
        words = set(path.read_text().split())
    except OSError:
        words = set()
    return frozenset(words | {"say", "was", "his", "her", "him", "hey", "yeah", "yes", "nope", "okay", "ok", "tarun", "trinetra"} | set(SLANG))


def _dist(a: str, b: str, cap: int) -> int:
    """Damerau–Levenshtein (optimal string alignment) distance, stopping early once it exceeds `cap`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev2, prev = None, list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        if min(cur) > cap:
            return cap + 1
        prev2, prev = prev, cur
    return prev[-1]


@lru_cache(maxsize=4096)
def correct(word: str) -> str:
    """One word → the word it was meant to be (or itself)."""
    if word in TYPO_OVERRIDES:
        return TYPO_OVERRIDES[word]
    if word in KNOWN or len(word) <= 2 or any(c.isdigit() for c in word):  # "6am" stays "6am", never "jam"
        return word
    squeezed = re.sub(r"(.)\1+", r"\1", word)  # happyy → hapy … try both spellings
    for cand in (re.sub(r"(.)\1{2,}", r"\1", word), squeezed):
        if cand in KNOWN:
            return cand
    if word in _common():
        return word
    return _nearest(word, KNOWN) or word


def _subseq(a: str, b: str) -> bool:  # every letter of a, in order, inside b ("jmp" in "jump")
    it = iter(b)
    return all(c in it for c in a)


def _rank(word: str, k: str, d: int) -> tuple:  # lower is better: distance, a dropped letter, a shared beginning, similar length
    prefix = 0
    while prefix < min(len(word), len(k)) and word[prefix] == k[prefix]:
        prefix += 1
    return (d, not (_subseq(word, k) or _subseq(k, word)), -prefix, abs(len(word) - len(k)))  # a dropped or an extra letter


def _plausible(word: str, k: str, d: float, loose: bool = False) -> bool:
    """Is k a believable typo-fix for word? Short words: only a missing or swapped letter ("Sam" stays a name, not "sad").
    Two edits: the first letter must match (Spanish "baila" isn't "tabla")."""
    if len(word) <= 4:
        if _subseq(word, k) or (len(word) == len(k) and sorted(word) == sorted(k)):
            return True
        # where an order is expected ("jemp pls", "show me sed"), a vowel-for-vowel slip is fine too
        diff = [(a, b) for a, b in zip(word, k) if a != b]
        return loose and len(word) == len(k) and all(a in "aeiouy" and b in "aeiouy" for a, b in diff)
    return d < 2 or word[0] == k[0]


def _nearest(word: str, vocab, cap: int | None = None, loose: bool = False) -> str | None:
    """The closest word in `vocab` within the typo budget (≤1 edit up to 4 letters, ≤2 up to 9, else 3)."""
    cap = cap if cap is not None else 1 if len(word) <= 4 else 2 if len(word) <= 9 else 3
    squeezed = re.sub(r"(.)\1+", r"\1", word)
    best, best_r = None, None
    for k in vocab:
        if len(k) < 3:
            continue
        d = _dist(word, k, cap)
        if d > cap and squeezed != word and len(squeezed) >= max(3, len(word) * 0.6):  # "xxxxxxxx" is not "sax"
            d = _dist(squeezed, k, cap) + 0.5  # the doubled-letters reading counts a little less
        if d <= cap and _plausible(word, k, d, loose):
            r = _rank(word, k, d)
            if best_r is None or r < best_r:
                best, best_r = k, r
    return best


INST_VOCAB = {w for ws in INSTRUMENT_WORDS.values() for w in ws if len(w) >= 3}
EMO_VOCAB = {w for ws in EMOTION_WORDS.values() for w in ws}
ACT_VOCAB = {w for ws in ACTION_WORDS.values() for w in ws}


def _in_context(words: list[str], raw: list[str] | None = None) -> list[str]:
    """A typo that happens to be a real word ("play cell", "show me sod") reads as what the sentence is about."""
    out = list(words)
    playing = any(w in PLAY for w in words)
    emoting = any(w in {"show", "make", "be", "look", "face", "pretend", "act", "your"} for w in words)
    raw = raw or words
    for i, w in enumerate(words):
        prev = words[i - 1] if i else ""
        nxt = words[i + 1] if i + 1 < len(words) else ""
        # "show me sod" / "make a cring face": the typo drifted to a move word, but the sentence is about a face
        if emoting and CONCEPT.get(w, (None,))[0] == "act" and raw[i] != w and (prev in {"me", "be", "a", "your", "so", "very", "an"} or nxt in {"face", "mode", "expression"}):
            if k := _nearest(raw[i], EMO_VOCAB, 1 if len(raw[i]) <= 5 else 2, loose=True):
                out[i] = k; continue
        if w in CONCEPT or len(w) < 3 or w in FILLER or w in KNOWN:
            continue
        if playing and prev in {"play", "the", "your", "a", "some", "on", "my"} | PLAY and nxt in {"", "for", "please", "now", "and", "then", "solo", "music"}:
            # edit distance first; then, for scrambles like "giyuar", how much of the word lines up (ratio ≥ 0.66)
            if k := _nearest(w, INST_VOCAB, 1 if len(w) <= 5 else 2, loose=True) or next(iter(difflib.get_close_matches(w, INST_VOCAB, 1, 0.66)), None):
                out[i] = k; continue
        if emoting and (prev in {"me", "be", "a", "your", "so", "very", "an", "look"} or nxt in {"face", "mode", "expression"}):
            if k := _nearest(w, EMO_VOCAB, 1 if len(w) <= 5 else 2, loose=True) or next(iter(difflib.get_close_matches(w, EMO_VOCAB, 1, 0.7)), None):
                out[i] = k; continue
        lead = words[:i]  # a lone order: "span", "sin pls", "can you jemp"
        if len(words) <= 5 and all(x in {"can", "could", "you", "please", "will", "would", "now", "pls", "go", "just"} for x in lead) and nxt in {"", "please", "now", "again"}:
            if k := _nearest(w, ACT_VOCAB, 1, loose=True):
                out[i] = k
    return out


EMOJI = {"🎸": " guitar ", "🎹": " piano ", "🥁": " drums ", "🎻": " violin ", "🎺": " trumpet ", "🎷": " sax ", "🪕": " banjo ",
         "🪈": " flute ", "🎶": " music ", "🎵": " music ", "💃": " dance ", "🕺": " dance ", "😠": " angry ", "😡": " angry ",
         "😢": " sad ", "😭": " sad ", "😊": " happy ", "😄": " happy ", "😁": " happy ", "🤩": " excited ", "😮": " surprised ",
         "😲": " surprised ", "😴": " sleepy ", "☺️": " shy ", "😳": " shy ", "🤗": " caring ", "😌": " proud ", "🛑": " stop ", "⏹": " stop "}


def normalise(text: str) -> list[str]:
    text = text or ""
    for e, word in EMOJI.items():  # 🎸 → guitar, 💃 → dance
        text = text.replace(e, word)
    t = text.lower().replace("’", "'").replace("‘", "'")
    t = re.sub(r"\b(\w+)'(s|re|ve|ll|d|m|t)\b", lambda m: m.group(1) + ("" if m.group(2) in ("s", "ve", "ll", "d") else m.group(2)), t)
    t = re.sub(r"[^a-z0-9\s]", " ", t)
    out: list[str] = []
    for w in t.split():
        out.extend(SLANG.get(w, w).split())
    return _in_context([correct(w) for w in out], out)


def fix_typos(text: str, loose: bool = False) -> str:  # the corrected text, for callers that match on words
    return " ".join(normalise(text))


# ---------------------------------------------------------------- intent
SELF = {"i", "we", "my", "our", "me", "mine"}
OTHERS = {"tarun", "he", "his", "him", "she", "they", "them"}
REQUEST_AFTER_I = re.compile(r"^(i|we) (want|would like|wish|need|d love|would love|d like) (you to|to see you|to watch you|to hear you)\b"
                             r"|^(i|we) (want|would like) (to )?(see|watch|hear)\b|^i want to (see|watch|hear)\b|^i (am|m) (asking|telling) you\b")
LIKE_Q = re.compile(r"^(do|does|did) (you|tarun|he) (like|love|enjoy|prefer|hate|listen)\b")
LAB_ORDERS = [
    ("work", re.compile(r"^((team|everyone|everybody|agents|guys|all) )?(back to work|get back to work|dismissed|go back to (your )?(desks|work))( now| please)*$")),
    ("report", re.compile(r"^((team|everyone|agents) )?(report|status report|give me a report|report in|show me a report)( now| please)*$")),
    ("assemble", re.compile(r"^(\w+ )?((team|everyone|everybody|agents|guys|all) )?(assemble|line up|fall in|gather)( up| round| around)?( (the |your |all )?(team|agents|squad|everyone|bots))?( now| please)*$"
                            r"|^(please |can you |could you )*(assemble|line up|gather) (the |your |all |all your )?(team|agents|squad|bots)( now| please)*$")),
    ("roles", re.compile(r"\bwhat (do|does) (your |all your |all of your |each of your |each |every |the )?(agents?|bots?|team members|workers)( all| each)? do\b"
                         r"|\bwho does what\b|\b(your |the )?agents?s? (tasks|jobs|roles|duties)\b|\bwhat are your agents?\b")),
    ("how", re.compile(r"\bhow (does|do|is) (your |the )?(brain|agents|team|system) (work|works|working|built|organized)\b|\bexplain (your |the )?(brain|agents|team|system)\b")),
    (None, re.compile(r"\b(open|show|visit|take me to|go to|see|enter)( me)? (the |your |inside your |inside the )?(lab|hq|headquarters|agents|brain)\b")),
]
ABILITIES = re.compile(r"\bwhat (else )?(all )?(can|could) (you) (do|play|show|perform)( for me| now| please| here| trinetra)*$|\bwhat (are |is )?(your |all your )?(abilities|skills|tricks|commands|talents|instruments|powers)\b"
                       r"|\b(show|tell) me what you can do\b|\bwhat instruments\b|^(help|commands|options|menu)$|\bwhat do you know how to do\b")
NOT_A_MOVE = re.compile(r"\b(dice|die|ball|call|number|joke|credits|eyes|over|back to|the window|with it|on the floor|in bed|tonight|tomorrow|well|early|late|at|time|schedule|hours?|pm|am|o clock|by)\b|\d(?! times)")


def _seconds(words: list[str]) -> float | None:
    s = " ".join(words)
    if re.search(r"\b(forever|nonstop|non stop|continuously|until i say stop|till i say stop|until i stop|all day|keep going|endless)\b", s):
        return 0
    if re.search(r"\bhalf (a|an) minute\b", s):
        return 30
    m = re.search(r"\b(\d+|" + "|".join(NUMBERS) + r") (second|seconds|minute|minutes)\b", s)
    if not m:
        return None
    n = float(m.group(1)) if m.group(1).isdigit() else NUMBERS[m.group(1)]
    return max(5, min(120, n * (60 if m.group(2).startswith("minute") else 1)))


DISTRESS = re.compile(r"\b(give up|kill (myself|me)|suicid\w*|end (it|my life)|want to die|hopeless|worthless|hurt myself|self harm|"
                      r"can'?t (go on|do this|take it)|no point|hate myself|depress\w*|panic|anxious|crying|lonely|alone in)\b", re.I)


def understand(text: str, lab: bool = False) -> dict | None:
    raw = (text or "").strip()
    if not raw or len(raw) > 140 or DISTRESS.search(raw):  # someone hurting gets TRINETRA's real reply, never a show
        return None
    w = normalise(raw)
    if not w:
        return None
    s = " ".join(w)
    kinds = [CONCEPT.get(x, (None, None)) for x in w]
    has = lambda kind: [v for k, v in kinds if k == kind]

    # stop: the whole message is a stop ("stop", "stop the music pls", "ok enough")
    if any(x in STOP for x in w) and all(x in STOP or x in STOP_FILLER for x in w) and not re.search(r"\b(do not|never) stop\b", s):
        return {"show": "stop"}
    # not requests: the user talking about themselves / Tarun, likes, negation
    if (w[0] in SELF and not REQUEST_AFTER_I.search(s)) or LIKE_Q.search(s) or any(x in OTHERS for x in re.sub(r"\bthem all\b", "", s).split()[:5]):
        return None
    if re.search(r"\b(do not|never|no|not|stop|quit) (\w+ ){0,2}(dance|dancing|play|playing|sing|singing|jump|jumping|spin|cry|crying|laugh|sleep|show|make|act|wave|be)\b", s):
        return None
    # the agents (portfolio only)
    if lab:
        for cmd, pat in LAB_ORDERS:
            if pat.search(s):
                return {"show": "lab", "cmd": cmd}
    if ABILITIES.search(s) and (lab or s not in ("help", "commands", "options", "menu")):
        return {"show": "abilities"}

    # instruments named, in the order they were said; multi-word names win ("bass guitar" is the bass)
    found: list[tuple[int, str]] = []
    taken: set[int] = set()
    for phrase, inst in INSTRUMENT_PHRASES.items():
        for m in re.finditer(rf"\b{phrase}\b", s):
            pos = len(s[:m.start()].split()); found.append((pos, inst)); taken |= set(range(pos, pos + len(phrase.split())))
    found += [(i, v) for i, (k, v) in enumerate(kinds) if k == "inst" and i not in taken]
    insts = list(dict.fromkeys(v for _, v in sorted(found)))
    playing = any(x in PLAY for x in w)
    if "base" in w and playing and "bass" not in insts:
        insts.append("bass")
    if not playing and insts and all(x not in w or x in {"keys", "horn", "recorder", "acoustic", "electric", "percussion"} for x in
                                     [x for x in w if CONCEPT.get(x, (None,))[0] == "inst"]):
        insts = []  # "show me the keys" is not the piano
    if playing and not insts and re.search(r"\b(rock|metal|heavy metal)\b", s.replace("play", "", 1)) or (playing and s.strip() in ("play rock", "play some rock")):
        insts = ["electric"]
    if playing and not insts and "lullaby" in w:
        insts = ["harp"]
    moods = has("mood") or [e for e in has("emo") if e != "firm"]
    mood = moods[0] if moods else None
    wants_all = (any(x in ALL for x in w) and ("instruments" in w or "instrument" in w)) or bool(
        re.fullmatch(r"(please |can you |could you |now )*(play|jam) (them all|all|all of them|everything|all of it|em all)( please| now| for me)*", s))

    # a key word deep in a long sentence is a statement unless it's asked for ("dance like nobody's watching is my motto")
    key_at = next((i for i, (k, _) in enumerate(kinds) if k in ("dance", "play", "inst", "act")), 0)
    asked = re.search(r"\b(you|please|can|could|would|will|let us|want|show|try)\b", s)
    if (key_at > 3 and len(w) > 6 or re.search(r"\b(is|was|are|were|am) (my|our|his|her|their|so|amazing|great|cool|nice|good|bad|awesome|beautiful|fun)\b|\bmotto\b|\bquote\b", s)) and not asked:
        return None
    if re.match(r"^(time to|time for|going to|gotta|have to|need to|bed ?time)\b", s):  # announcing their own plans
        return None
    # dance
    DANCE_OK = FILLER | {"alone", "solo", "yourself", "single", "without", "with", "her", "partner", "girlfriend", "friend", "together",
                         "for", "seconds", "second", "minutes", "minute", "half", "forever", "nonstop", "non", "stop", "until", "till", "say",
                         "again", "like", "crazy", "move", "moves", "bust", "shake", "it", "hit", "floor", "of", "dance", "dancing", "little",
                         "anyone", "anybody", "everyone", "fast", "slow", "baby", "more", "some", "once", "twice", "keep", "going", "continuously"}
    dance_rest = [x for x in w if x not in DANCE_OK and CONCEPT.get(x, (None,))[0] not in ("dance", "mood", "emo") and not x.isdigit() and x not in NUMBERS]
    if (has("dance") or DANCE_PHRASES.search(s)) and not dance_rest:
        partner = not re.search(r"\b(alone|solo|yourself|single|without (her|your partner|partner|girlfriend|friend|anyone|anybody))\b", s)
        sec = _seconds(w)
        return {"show": "dance", "mood": mood or "excited", "seconds": 10 if sec is None else sec, "partner": partner}
    # instruments
    if wants_all and not insts:
        return {"show": "play", "instrument": "all", "mood": mood}
    others = [x for x in w if x not in FILLER and CONCEPT.get(x, (None,))[0] not in ("inst", "mood", "emo", "play") and x not in ALL
              and x not in {"instrument", "instruments", "music", "song", "solo", "then", "and", "with", "on", "of", "them", "one", "by",
                            "after", "followed", "please", "guitar", "set", "kit", "grand", "double", "base"}]
    if insts and (playing or not others):
        return {"show": "play", "instrument": insts[0] if len(insts) == 1 else insts, "mood": mood}
    if playing and (any(x in MUSIC for x in w) or (has("mood") and len(w) <= 6) or s in ("play", "sing", "sing a song", "sing me a song", "sing for me", "sing something", "sing please")):
        return {"show": "play", "instrument": None, "mood": mood}
    # little moves: the move is the request ("jump", "can you do a backflip", "spin around 3 times")
    if re.fullmatch(r"(please |can you |now )*(say|wave) (hi|hello|bye|goodbye)( to me| please)*", s):
        return {"show": "act", "action": "wave", "actions": ["wave"]}
    acts = list(dict.fromkeys(has("act")))
    if acts and len(w) <= 12 and not NOT_A_MOVE.search(s):
        core = [x for x in w if x not in FILLER and not x.isdigit() and x not in NUMBERS
                and x not in {"times", "around", "in", "air", "at", "the", "high", "big", "for", "loud", "out", "really", "very", "so", "once", "twice", "more", "please", "take", "have", "go", "get", "some"}]
        if core and CONCEPT.get(core[0], (None,))[0] == "act" and all(CONCEPT.get(x, (None,))[0] in ("act", "emo", None) and (CONCEPT.get(x, (None,))[0] or x in {"then", "and", "like", "baby", "crazy"}) for x in core):
            times = 2 if "twice" in w else next((int(x) if x.isdigit() else int(NUMBERS[x]) for i, x in enumerate(w)
                                                 if (x.isdigit() or x in NUMBERS) and i + 1 < len(w) and w[i + 1] == "times"), 1)
            seq = [a for a in acts for _ in range(max(1, min(5, times)))] if len(acts) == 1 else acts
            return {"show": "act", "action": acts[0], "actions": seq}  # "jump and spin" → one after the other; "jump twice"
    # emotions: "show me angry", "make a sad face", "be happy then shy", "how do you look when angry", "angry!"
    emos = list(dict.fromkeys(has("emo")))
    if re.search(r"\b(all|every|each|your) (your |of your |the )?(emotions|emotion|feelings|faces|expressions|moods)\b|\bwhat (emotions|faces|feelings|moods|expressions) (can|do) you\b", s):
        return {"show": "emotion", "emotions": emos or ["happy", "excited", "proud", "caring", "shy", "surprised", "firm", "angry", "sad", "sleepy"]}
    if emos:
        trigger = any(x in EMOTION_TRIGGER for x in w) or re.search(r"\bhow (do|would|will) you look\b|\bwhat does (an? )?\w+ (you|face) look like\b", s)
        EMO_OK = FILLER | EMOTION_TRIGGER | {"then", "and", "now", "very", "super", "so", "really", "more", "too", "please", "when", "are", "is",
                                             "how", "would", "look", "looks", "like", "what", "does", "of", "after", "that", "followed", "by", "an", "be", "yours", "best", "most", "real"}
        extra = [x for x in w if x not in EMO_OK and CONCEPT.get(x, (None,))[0] != "emo"]
        faced = re.search(r"\b(face|faces|expression|look)\b", s) is not None
        bare = not extra and (faced or (trigger and len(w) <= 7))  # "angry face", "show me sad", "be shy" — not just "sad"
        asked_state = re.match(r"^(are|were) you\b|^you (are|look|seem|feel|sound)\b|^(how|why) (are|do) you (feel|feeling)\b|^how are you\b", s)
        mode_talk = re.search(r"\bmode\b|\bwith me\b|\bat me\b|\bon me\b|\bversion\b|\bside\b|\bfrom now\b|\buntil\b|\bstay\b|\bkeep being\b|\btalk\b|\bspeak\b|\bscold\b|\byell\b", s)
        if bare and not asked_state and not mode_talk and not re.search(r"\b(make|making) me\b|\bdo you feel\b", s):
            return {"show": "emotion", "emotions": emos}
    return None


def request(text: str, lab: bool = False) -> dict | None:
    """A show for the character (emotions go through emotions() / perform_request)."""
    r = understand(text, lab)
    return r if r and r["show"] != "emotion" else None


def emotions(text: str) -> list[str] | None:
    r = understand(text)
    return r["emotions"] if r and r["show"] == "emotion" else None


ABILITIES_TEXT = ("Here's what I can do:\n💃 dance (with my partner, or “dance alone”, “dance for 30 seconds”)\n"
                  "🎶 play 15 instruments: guitar, electric guitar, bass, ukulele, banjo, sitar, violin, cello, piano, harp, flute, sax, trumpet, "
                  "xylophone, drums, or “play all instruments”\n"
                  "😊 show 10 emotions: happy, excited, proud, caring, shy, surprised, firm, angry, sad, sleepy (or “show all your emotions”)\n"
                  "🦘 jump · 🌀 spin · 👋 wave · 😢 cry · 😂 laugh · 😴 sleep\n⏹ “stop” or Esc ends it.")


def label(show: dict) -> str:
    from app.agents.command import EMOTION_LABEL
    kind = show["show"]
    if kind == "stop":
        return "⏹ Stopped"
    if kind == "abilities":
        return ABILITIES_TEXT
    if kind == "emotion":
        return " · ".join(EMOTION_LABEL[e] for e in show["emotions"])
    if kind == "dance":
        sec = show.get("seconds")
        return "💃 Dance" + ("" if show.get("partner", True) else " solo") + (" · until you say stop" if sec == 0 else f" · {sec:g} s" if sec and sec != 10 else "")
    if kind == "lab":
        return {"assemble": "🧍 Assemble", "roles": "❓ Who does what", "how": "📘 How the brain works"}.get(show.get("cmd"), "🧠 Brain")
    if kind == "act":
        return " → ".join(ACTION_LABEL[a] for a in show.get("actions") or [show["action"]])
    inst = show.get("instrument")
    if inst == "all":
        name = f"🎶 All {len(INSTRUMENT_LABEL)} instruments"
    elif isinstance(inst, list):
        name = " → ".join(INSTRUMENT_LABEL[i] for i in inst)
    else:
        name = INSTRUMENT_LABEL.get(inst or "", "🎶 Music")
    return f"{name} · {EMOTION_LABEL[show['mood']]}" if show.get("mood") in EMOTION_LABEL else name
