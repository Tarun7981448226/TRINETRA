"""Your 1 / 3 / 5-year vision — what the daily work is for."""
import json

from sqlalchemy.orm import Session

from app.db.models import KeyValue

KEY = "vision"
HORIZONS = ("y1", "y3", "y5")
LABEL = {"y1": "in 1 year", "y3": "in 3 years", "y5": "in 5 years"}


def get(db: Session) -> dict:
    row = db.get(KeyValue, KEY)
    data = json.loads(row.value) if row and row.value else {}
    return {h: data.get(h, "") for h in HORIZONS}


def put(db: Session, **parts: str) -> dict:
    data = {**get(db), **{h: (v or "").strip()[:600] for h, v in parts.items() if h in HORIZONS and v is not None}}
    row = db.get(KeyValue, KEY)
    if row is None:
        db.add(KeyValue(key=KEY, value=json.dumps(data)))
    else:
        row.value = json.dumps(data)
    db.flush()
    return data


def line(db: Session) -> str:
    v = get(db)
    return " ".join(f"{LABEL[h].capitalize()}: {v[h]}." for h in HORIZONS if v[h])
