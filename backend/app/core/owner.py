"""Is this really Tarun? The portfolio asks for his password before TRINETRA talks to him as his own mentor.

Only a salted PBKDF2 hash is stored (kv "owner_pass"); he sets it in the app (Visitors screen). Three wrong tries
and that visit is treated as someone pretending to be him. Across all visits, too many wrong tries in an hour
pause the check for an hour (a stranger can't keep opening new visits to guess), and Tarun hears about it.
"""
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.db.models import KeyValue

KEY = "owner_pass"
FAILS_KEY = "owner_fails"
ITERATIONS = 200_000
TRIES = 3
MAX_FAILS_PER_HOUR = 10
MIN_LENGTH = 6

# "I am Tarun", "it's tarun", "I'm your creator", "I built you"
CLAIM = re.compile(
    r"\b(i\s*am|i'?m|im|this is|it'?s|its|me)\s+(tarun(?!['’]s)|your (creator|owner|maker|boss|master|builder|dad|father))\b"
    r"|\b(i|me)\s+(built|made|created|coded|programmed)\s+(you|u|trinetra)\b"
    r"|\bi'?m\s+the\s+one\s+who\s+(built|made|created)\s+you\b", re.I)


def claims_to_be_tarun(text: str) -> bool:
    return bool(CLAIM.search(text))


def _hash(password: str, salt: bytes, iterations: int = ITERATIONS) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations).hex()


def _get(db: Session, key: str) -> str | None:
    row = db.get(KeyValue, key)
    return row.value if row else None


def _put(db: Session, key: str, value: str) -> None:
    row = db.get(KeyValue, key)
    if row:
        row.value = value
    else:
        db.add(KeyValue(key=key, value=value))


def has_password(db: Session) -> bool:
    return bool(_get(db, KEY))


def set_password(db: Session, password: str) -> None:
    salt = secrets.token_bytes(16)
    _put(db, KEY, json.dumps({"salt": salt.hex(), "hash": _hash(password, salt), "iter": ITERATIONS}))
    _put(db, FAILS_KEY, "[]")


def _fails(db: Session, now: datetime) -> list[str]:
    try:
        stamps = json.loads(_get(db, FAILS_KEY) or "[]")
    except ValueError:
        stamps = []
    hour_ago = now - timedelta(hours=1)
    return [s for s in stamps if datetime.fromisoformat(s) > hour_ago]


def paused(db: Session) -> bool:
    """Too many wrong passwords in the last hour, from anyone: no more checks until it calms down."""
    return len(_fails(db, datetime.now(timezone.utc))) >= MAX_FAILS_PER_HOUR


def check(db: Session, password: str) -> bool:
    raw = _get(db, KEY)
    if not raw:
        return False
    d = json.loads(raw)
    ok = hmac.compare_digest(_hash(password.strip(), bytes.fromhex(d["salt"]), d.get("iter", ITERATIONS)), d["hash"])
    if not ok:
        now = datetime.now(timezone.utc)
        _put(db, FAILS_KEY, json.dumps([*_fails(db, now), now.isoformat()]))
    return ok
