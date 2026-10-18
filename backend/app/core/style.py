"""How Tarun writes on WhatsApp, learned from his own messages, so TRINETRA's replies sound like him.

No fine-tuning (free models can't be): a numeric profile of his habits (length, emoji, lowercase, his words, how he
mixes in Telugu / Hindi), plus his most similar past replies to that same person, found with TRINETRA's own
embeddings (core/embed.py) — nothing leaves the server for that search. The profile is rebuilt every night.
"""
import json
import re
from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import from_db
from app.db.models import KeyValue, WaMessage

KEY = "wa_style"
PAIR_GAP = timedelta(hours=6)  # his message counts as a reply if it came within this long after theirs
EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿⭐❤]")
TELUGU_SCRIPT = re.compile(r"[ఀ-౿]")
DEVANAGARI = re.compile(r"[ऀ-ॿ]")
# Common romanised Telugu / Hindi words (Tenglish / Hinglish) — enough to tell the model he mixes languages.
TENGLISH = {"ra", "ga", "anna", "enti", "emi", "ela", "unnav", "unnava", "cheppu", "chesava", "chestha", "ledu", "kadu",
            "avunu", "sare", "bagunna", "bagunnava", "inka", "ippudu", "repu", "mama", "bava", "nenu", "nuvvu", "em"}
HINGLISH = {"hai", "haan", "nahi", "kya", "bhai", "yaar", "kal", "acha", "accha", "theek", "kaise", "kar", "raha",
            "rahi", "mein", "hoon", "bas", "chal", "bol", "matlab", "kuch", "abhi", "tum", "hum"}
STOP = {"the", "a", "an", "to", "and", "is", "it", "i", "you", "of", "in", "for", "on", "at", "me", "my", "be", "that",
        "this", "so", "are", "was", "with", "do", "if", "we", "will", "can", "but", "not", "have", "just", "what"}


def _words(text: str) -> list[str]:
    return re.findall(r"[a-z']+", text.lower())


def pairs(db: Session, jid: str | None = None, limit: int = 4000) -> list[tuple[str, str, str]]:
    """(jid, what they said, what Tarun answered) — his own replies only, never TRINETRA's."""
    q = select(WaMessage).order_by(WaMessage.jid, WaMessage.ts)
    if jid:
        q = q.where(WaMessage.jid == jid)
    out, last = [], None
    for m in db.scalars(q.limit(limit * 3)):
        if last is not None and last.jid != m.jid:
            last = None
        if not m.from_me:
            last = m
        elif not m.by_trinetra and last is not None and from_db(m.ts) - from_db(last.ts) <= PAIR_GAP:
            out.append((m.jid, last.text, m.text))
            last = None
    return out[-limit:]


def _profile(replies: list[str]) -> dict:
    if not replies:
        return {}
    n = len(replies)
    words = [w for r in replies for w in _words(r)]
    letters = [c for r in replies for c in r if c.isalpha()]
    common = [w for w, _ in Counter(w for w in words if w not in STOP and len(w) > 1).most_common(15)]
    openers = [w for w, k in Counter(_words(r)[0] for r in replies if _words(r)).most_common(5) if k > 1]
    return {
        "n": n,
        "avg_words": round(sum(len(_words(r)) for r in replies) / n, 1),
        "emoji_rate": round(sum(bool(EMOJI.search(r)) for r in replies) / n, 2),
        "top_emoji": [e for e, _ in Counter(e for r in replies for e in EMOJI.findall(r)).most_common(4)],
        "lowercase_rate": round(sum(c.islower() for c in letters) / max(1, len(letters)), 2),
        "ends_with_period": round(sum(r.rstrip().endswith(".") for r in replies) / n, 2),
        "tenglish": round(sum(w in TENGLISH for w in words) / max(1, len(words)), 3),
        "hinglish": round(sum(w in HINGLISH for w in words) / max(1, len(words)), 3),
        "telugu_script": any(TELUGU_SCRIPT.search(r) for r in replies),
        "hindi_script": any(DEVANAGARI.search(r) for r in replies),
        "common_words": common,
        "openers": openers,
    }


def learn(db: Session) -> dict:
    """Rebuild his style: overall, and per person he talks to often (the nightly Reply Style Learner)."""
    by_jid: dict[str, list[str]] = {}
    for jid, _theirs, mine in pairs(db):
        by_jid.setdefault(jid, []).append(mine)
    style = {"overall": _profile([r for rs in by_jid.values() for r in rs]),
             "people": {j: _profile(rs) for j, rs in by_jid.items() if len(rs) >= 8},
             "learned_at": datetime.now().isoformat(timespec="minutes")}
    row = db.get(KeyValue, KEY)
    old = json.loads(row.value) if row and row.value else {}
    style["score"] = old.get("score")  # the last "sounds like you" test stays until the next one
    if row:
        row.value = json.dumps(style)
    else:
        db.add(KeyValue(key=KEY, value=json.dumps(style)))
    return style


def load(db: Session) -> dict:
    row = db.get(KeyValue, KEY)
    try:
        return json.loads(row.value) if row and row.value else {}
    except ValueError:
        return {}


def describe(p: dict) -> str:
    """The profile in words, for the model."""
    if not p:
        return "Not enough of his messages yet: keep it short, casual and friendly."
    bits = [f"about {p['avg_words']:g} words per message"]
    bits.append("mostly lowercase" if p["lowercase_rate"] > 0.93 else "normal capitalisation")
    bits.append("rarely ends with a full stop" if p["ends_with_period"] < 0.25 else "often ends with a full stop")
    if p["emoji_rate"] >= 0.15:
        bits.append(f"uses emoji in {round(p['emoji_rate'] * 100)}% of messages ({' '.join(p['top_emoji'])})")
    else:
        bits.append("hardly uses emoji")
    if p["tenglish"] >= 0.02 or p["telugu_script"]:
        bits.append("mixes in Telugu words (Tenglish)" + (" and Telugu script" if p["telugu_script"] else ""))
    if p["hinglish"] >= 0.02 or p["hindi_script"]:
        bits.append("mixes in Hindi words (Hinglish)")
    if p["common_words"]:
        bits.append("words he often uses: " + ", ".join(p["common_words"][:10]))
    if p["openers"]:
        bits.append("often starts with: " + ", ".join(p["openers"]))
    return "; ".join(bits) + "."


def examples(db: Session, jid: str, text: str, k: int = 8) -> list[tuple[str, str]]:
    """His real replies to the most similar things this person (or anyone, if they're new) said before."""
    from app.core import embed
    mine = pairs(db, jid) or pairs(db)
    if not mine:
        return []
    mine = mine[-400:]
    try:
        scores = embed.similarity(text, [theirs for _, theirs, _ in mine])
        order = sorted(range(len(mine)), key=lambda i: -float(scores[i]))[:k]
    except Exception:  # the embedding files are missing: the latest ones still teach the tone
        order = list(range(len(mine)))[-k:]
    return [(mine[i][1], mine[i][2]) for i in sorted(order)]


# ---- WhatsApp's "Export chat" (.txt), to learn faster than the linked-device history allows ----

_LINE = re.compile(
    r"^\[?(\d{1,2})[/.](\d{1,2})[/.](\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?\]?\s*(?:-\s*)?([^:]{1,60}):\s(.*)$")


def import_export(db: Session, text: str, my_name: str, jid: str) -> int:
    """Lines like "18/10/26, 9:41 PM - Tarun: on my way" (Android) or "[18/10/26, 9:41:03 PM] Tarun: …" (iPhone).
    Returns how many messages were added. Media, deleted and system lines are skipped."""
    added, cur = 0, None
    rows: list[tuple[datetime, bool, str]] = []
    for raw in text.replace("‎", "").splitlines():
        m = _LINE.match(raw.strip())
        if not m:
            if cur is not None and raw.strip():
                cur[2] += "\n" + raw.strip()  # a message that runs over several lines
            continue
        d, mo, y, h, mi, ap, who, body = m.groups()
        y = int(y) + (2000 if len(y) == 2 else 0)
        h = int(h) % 12 + (12 if ap and ap.lower() == "pm" else 0) if ap else int(h)
        try:
            when = datetime(y, int(mo), int(d), h, int(mi))
        except ValueError:
            when = datetime(y, int(d), int(mo), h, int(mi))  # month/day order (US phones)
        cur = [when, who.strip().lower() == my_name.strip().lower(), body.strip()]
        rows.append(cur)
    from app.core.timeutil import to_utc, user_tz
    for when, mine, body in rows:
        if not body or body.startswith("<") or "omitted" in body or body in ("This message was deleted", "You deleted this message"):
            continue
        db.add(WaMessage(jid=jid, from_me=mine, text=body[:2000], ts=to_utc(when.replace(tzinfo=user_tz())), handled="history"))
        added += 1
    return added


async def sounds_like_you(db: Session, n: int = 12) -> float | None:
    """The test: write replies to his real past messages and see how close they are to what he actually said
    (0–100). Paced and small on purpose — it shares the free model quota with everything else."""
    import random

    from app.core import embed, whatsapp
    test = pairs(db)
    if len(test) < 10:
        return None
    rng = random.Random(7)
    picked = rng.sample(test, min(n, len(test)))
    got, real = [], []
    for jid, theirs, mine in picked:
        draft = await whatsapp.write_reply(db, jid, theirs, holdout=mine)
        if draft:
            got.append(draft)
            real.append(mine)
    if not got:
        return None
    sims = [float(embed.similarity(g, [r])[0]) for g, r in zip(got, real)]
    score = round(100 * sum(sims) / len(sims))
    style = load(db)
    style["score"] = {"value": score, "tested": len(got), "at": datetime.now().isoformat(timespec="minutes")}
    row = db.get(KeyValue, KEY)
    if row:
        row.value = json.dumps(style)
    else:
        db.add(KeyValue(key=KEY, value=json.dumps(style)))
    return score
