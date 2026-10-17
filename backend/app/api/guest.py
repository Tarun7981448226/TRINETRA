"""Endpoints for the Eye on the portfolio.

/guest/*    public (the portfolio widget; each visit has its own token)
/visitors/* private (Tarun's app, behind the passcode)
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import guest, tour, voice
from app.db.models import GuestAsk, GuestNote, GuestReply, GuestVisit
from app.core.timeutil import from_db
from app.db.session import get_db

STATIC = Path(__file__).resolve().parents[1] / "static"
ORIGINS = ["https://www.tarundeepreddy.com", "https://tarundeepreddy.com", "http://localhost:4321"]

public = APIRouter(prefix="/guest")
private = APIRouter(prefix="/visitors")
look_router = APIRouter()  # TRINETRA's look, shared by the app (every device) and the portfolio

STYLES = ("pixel", "fuzzy")
PALETTES = ("saffron", "mint", "berry", "ocean", "coral", "red", "night", "mono")
LOOK_KEY = "buddy_look"


def _look(db: Session) -> dict:
    from app.db.models import KeyValue

    row = db.get(KeyValue, LOOK_KEY)
    try:
        d = json.loads(row.value) if row and row.value else {}
    except ValueError:
        d = {}
    return {"style": d.get("style") if d.get("style") in STYLES else "pixel",
            "palette": d.get("palette") if d.get("palette") in PALETTES else "saffron", "saved": bool(d)}


class LookIn(BaseModel):
    style: str = Field(pattern="^(pixel|fuzzy)$")
    palette: str = Field(pattern="^(saffron|mint|berry|ocean|coral|red|night|mono)$")


@look_router.get("/look")
def get_look(db: Session = Depends(get_db)):
    return _look(db)


@look_router.post("/look")
def set_look(body: LookIn, db: Session = Depends(get_db)):
    from app.db.models import KeyValue

    value = json.dumps({"style": body.style, "palette": body.palette})
    row = db.get(KeyValue, LOOK_KEY)
    if row is None:
        db.add(KeyValue(key=LOOK_KEY, value=value))
    else:
        row.value = value
    db.commit()
    return _look(db)


def _ip(request: Request) -> str | None:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() or None) if fwd else (request.client.host if request.client else None)


def _visit(db: Session, token: str) -> GuestVisit:
    v = guest.visit_for(db, token)
    if v is None:
        raise HTTPException(404, "visit ended — say hello again")
    return v


@public.get("/eye.js", include_in_schema=False)
def eye_js():
    return FileResponse(STATIC / "guest-eye.js", media_type="text/javascript", headers={"Cache-Control": "public, max-age=300"})


@public.get("/buddy.js", include_in_schema=False)
def buddy_js():
    return FileResponse(STATIC / "buddy.js", media_type="text/javascript", headers={"Cache-Control": "public, max-age=300"})


@public.get("/look")
def public_look(db: Session = Depends(get_db)):
    """What the portfolio character should look like (read-only for visitors), and its resting mood — the same as in
    Tarun's app, but only the visitor-safe ones (proud / caring / neutral; never his frustration)."""
    from app.core import emotion

    f = emotion.decay(emotion.load(db))
    mood = "proud" if f.pride >= 0.5 else "caring" if f.concern >= 0.5 else "neutral"
    return {**_look(db), "mood": mood}


@public.post("/hello")
def hello(request: Request, db: Session = Depends(get_db)):
    v = guest.new_visit(db, _ip(request))
    if v is None:
        raise HTTPException(429, "Lots of hellos from here. Try again in a little while.")
    db.commit()
    return {"token": v.token, "reply": guest.GREETING}


class GuestText(BaseModel):
    token: str = Field(max_length=64)
    text: str = Field(min_length=1, max_length=guest.MAX_TEXT)


@public.post("/chat")
async def chat(body: GuestText, db: Session = Depends(get_db)):
    v = _visit(db, body.token)
    if v.turns >= guest.MAX_TURNS:
        raise HTTPException(429, "That's a lot of questions! Email Tarun at tarundeepreddybv@gmail.com to keep talking.")
    return await guest.chat(db, v, body.text)


class RoleIn(BaseModel):
    token: str = Field(max_length=64)
    role: str = Field(max_length=20)


@public.post("/role")
async def role(body: RoleIn, db: Session = Depends(get_db)):
    """They tapped a "who are you?" button."""
    return await guest.choose_role(db, _visit(db, body.token), body.role)


class ContactIn(BaseModel):
    token: str = Field(max_length=64)
    phone: str | None = Field(default=None, max_length=30, pattern=r"^\+\d{1,4} [\d\s\-().]{5,20}$")  # "+1 213 555 0101"
    email: str | None = Field(default=None, max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@public.post("/contact")
def contact(body: ContactIn, db: Session = Depends(get_db)):
    """The contact card: number and / or email — both empty means they skipped, which is fine."""
    return guest.contact_card(db, _visit(db, body.token), body.phone, body.email)


@public.get("/ask/{ask_id}")
def ask(ask_id: int, token: str, db: Session = Depends(get_db)):
    return guest.ask_status(db, _visit(db, token), ask_id)


@public.get("/inbox")
def inbox(token: str, db: Session = Depends(get_db)):
    """Tarun's replies that haven't reached this visitor yet (the widget checks every few seconds)."""
    v = guest.visit_for(db, token)
    if v is None:
        return {"lines": []}
    return {"lines": guest.inbox(db, v)}


class NoteIn(BaseModel):
    token: str = Field(max_length=64)
    email: str = Field(max_length=160, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    message: str = Field(default="", max_length=1000)


@public.post("/note")
def note(body: NoteIn, db: Session = Depends(get_db)):
    v = _visit(db, body.token)
    guest.leave_note(db, v, body.email, body.message)
    return {"reply": v.last_said}


class TokenIn(BaseModel):
    token: str = Field(max_length=64)


@public.post("/resume")
def resume(body: TokenIn, db: Session = Depends(get_db)):
    """A new page of the site opened: pick the visit back up (and cancel the pending forget)."""
    v = _visit(db, body.token)
    v.last_seen = datetime.now(timezone.utc)
    db.commit()
    return {"name": v.name, "messages": v.messages or []}


@public.post("/tour/{i}")
def tour_stop(i: int, body: TokenIn, db: Session = Depends(get_db)):
    """One stop of the guided tour: where to go on the page, what to say (it becomes what /speak voices), a diagram."""
    v = _visit(db, body.token)
    s = tour.stop(i, v.name)
    if s is None:
        return {"done": True, "total": len(tour.STOPS)}
    if i == 0:
        v.topics = [*(v.topics or []), "took the tour"][-12:]
    v.last_said, v.last_seen = s["text"], datetime.now(timezone.utc)
    db.commit()
    return s


@public.get("/tour/{i}")
def tour_peek(i: int, token: str, db: Session = Depends(get_db)):
    """A stop, read ahead of time (doesn't change what /speak would say)."""
    v = _visit(db, token)
    s = tour.stop(i, v.name)
    if i == 0 and s is not None and "took the tour" not in (v.topics or []):
        v.topics = [*(v.topics or []), "took the tour"][-12:]
        db.commit()
    return s or {"done": True, "total": len(tour.STOPS)}


_tour_voice: dict[str, bytes] = {}  # most stops say the same words to everyone: keep them ready


@public.get("/tour/{i}/voice", response_class=Response)
async def tour_voice(i: int, token: str, db: Session = Depends(get_db)):
    """A stop's narration as audio, fetched ahead of time so the tour never waits on the voice."""
    v = _visit(db, token)
    s = tour.stop(i, v.name)
    if s is None:
        raise HTTPException(404, "no such stop")
    audio = _tour_voice.get(s["text"])
    if audio is None:
        try:
            audio = await voice.speak(s["text"], "proud and upbeat")  # a touch brisker for the tour
        except Exception as e:
            raise HTTPException(503, "voice unavailable") from e
        if len(_tour_voice) < 60:
            _tour_voice[s["text"]] = audio
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=600"})


@public.post("/speak", response_class=Response)
async def speak(body: TokenIn, db: Session = Depends(get_db)):
    """Voices only what TRINETRA just said to this visitor — never arbitrary text."""
    v = _visit(db, body.token)
    if not v.last_said:
        raise HTTPException(404, "nothing to say")
    try:
        audio = await voice.speak(v.last_said, "warm and upbeat")
    except Exception as e:
        raise HTTPException(503, "voice unavailable") from e
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "no-store"})


@public.post("/bye")
async def bye(request: Request, db: Session = Depends(get_db)):
    """Sent by navigator.sendBeacon when a page closes (a text/plain body, so no CORS preflight)."""
    try:
        token = json.loads((await request.body()) or b"{}").get("token", "")
    except ValueError:
        token = ""
    v = guest.visit_for(db, str(token)[:64])
    if v:
        guest.leaving(v)  # forgotten in 2 minutes unless they open another page of the site
        db.commit()
    return {"ok": True}


# ---------- Tarun's side ----------

@private.get("")
def visitors(limit: int = 50, db: Session = Depends(get_db)):
    visits = db.scalars(select(GuestVisit).where(GuestVisit.name.is_not(None) | (GuestVisit.turns > 0))
                        .order_by(GuestVisit.id.desc()).limit(min(limit, 200))).all()
    ids = [v.id for v in visits]
    asks = db.scalars(select(GuestAsk).where(GuestAsk.visit_id.in_(ids))).all() if ids else []
    notes = db.scalars(select(GuestNote).where(GuestNote.visit_id.in_(ids))).all() if ids else []
    replies = db.scalars(select(GuestReply).where(GuestReply.visit_id.in_(ids))).all() if ids else []
    return [{
        "id": v.id, "name": v.name, "company": v.company, "role": v.role, "email": v.email, "phone": v.phone,
        "topics": v.topics or [],
        "started_at": v.started_at, "turns": v.turns, "here_now": v.ended_at is None,
        "asks": [{"id": a.id, "question": a.question, "answer": a.answer, "status": a.status} for a in asks if a.visit_id == v.id],
        "notes": [{"email": n.email, "phone": n.phone, "message": n.message, "created_at": n.created_at}
                  for n in notes if n.visit_id == v.id],
        "replies": [{"text": r.text, "delivered": r.delivered_at is not None} for r in replies if r.visit_id == v.id],
    } for v in visits]


def _here_now(v: GuestVisit) -> bool:
    return v.ended_at is None and datetime.now(timezone.utc) - from_db(v.last_seen) < guest.FORGET_AFTER


@private.get("/{visit_id}")
def visitor(visit_id: int, db: Session = Depends(get_db)):
    v = db.get(GuestVisit, visit_id)
    if v is None:
        raise HTTPException(404, "no such visitor")
    replies = db.scalars(select(GuestReply).where(GuestReply.visit_id == v.id).order_by(GuestReply.id)).all()
    return {"id": v.id, "name": v.name, "company": v.company, "role": v.role, "email": v.email, "phone": v.phone,
            "here_now": _here_now(v),
            "replies": [{"text": r.text, "delivered": r.delivered_at is not None} for r in replies]}


class ReplyIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


@private.post("/{visit_id}/reply")
def reply(visit_id: int, body: ReplyIn, db: Session = Depends(get_db)):
    r = guest.reply_to(db, visit_id, body.text)
    if r is None:
        raise HTTPException(404, "no such visitor")
    return {"ok": True, "here_now": _here_now(db.get(GuestVisit, visit_id))}


@private.get("/ask/{ask_id}")
def ask_detail(ask_id: int, db: Session = Depends(get_db)):
    a = db.get(GuestAsk, ask_id)
    if a is None:
        raise HTTPException(404, "no such question")
    v = db.get(GuestVisit, a.visit_id)
    return {"id": a.id, "question": a.question, "answer": a.answer, "status": a.status,
            "name": v.name if v else None, "company": v.company if v else None, "here_now": bool(v and v.ended_at is None)}


class AnswerIn(BaseModel):
    text: str = Field(min_length=1, max_length=400)


@private.post("/ask/{ask_id}/answer")
def answer(ask_id: int, body: AnswerIn, db: Session = Depends(get_db)):
    a = guest.answer_ask(db, ask_id, body.text)
    if a is None:
        raise HTTPException(404, "no such question")
    return {"ok": True, "status": a.status}
