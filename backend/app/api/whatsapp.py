"""WhatsApp autopilot endpoints.

/whatsapp/event   the bridge on Render (Bearer TRINETRA_BRIDGE_KEY; public path, its own secret)
/whatsapp/*       Tarun's app (behind the passcode)
"""
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import style, whatsapp
from app.core.orchestrator import IncomingEvent, Orchestrator
from app.db.models import Message, WaContact
from app.db.session import get_db

router = APIRouter(prefix="/whatsapp")


def get_orchestrator(request: Request) -> Orchestrator:
    return request.app.state.orchestrator


def _bridge(request: Request) -> None:
    key = get_settings().trinetra_bridge_key
    sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not key or not hmac.compare_digest(sent, key):
        raise HTTPException(401, "not the bridge")


def _when(v: Any) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00"))


class BridgeEvent(BaseModel):
    type: str = Field(pattern="^(message|activity|history|status|sent|cancelled)$")
    data: dict[str, Any] = {}


@router.post("/event")
async def bridge_event(body: BridgeEvent, request: Request, db: Session = Depends(get_db),
                       core: Orchestrator = Depends(get_orchestrator)):
    """Everything the bridge sees. Only ids go through the agents (the event log never keeps other people's words)."""
    _bridge(request)
    d = body.data
    if body.type == "status":  # linked / waiting for the QR / disconnected
        whatsapp._put(db, "wa_link", json.dumps({**d, "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}))
        db.commit()
        return {"ok": True}
    if body.type == "activity":  # he read something on his phone
        await core.dispatch(IncomingEvent("whatsapp.activity", {"at": (_when(d.get("at")) or datetime.now(timezone.utc)).isoformat()}, "whatsapp"), db)
        return {"ok": True}
    if body.type == "cancelled":
        whatsapp.cancelled(db, d.get("jid", ""), d.get("text", ""))
        db.commit()
        return {"ok": True}
    if body.type == "history":  # WhatsApp's history sync when he links: his style comes from his own replies
        added = 0
        for x in d.get("messages", [])[:5000]:
            if x.get("text") and x.get("jid") and not x.get("group"):
                if whatsapp.store(db, jid=x["jid"], text=x["text"], from_me=bool(x.get("from_me")), wa_id=x.get("id"),
                                  ts=_when(x.get("ts")), name=x.get("name"), group=False, handled="history"):
                    added += 1
        db.commit()
        if added:
            await core.dispatch(IncomingEvent("whatsapp.history", {"added": added}, "whatsapp"), db)
        return {"added": added}
    # a message, either way
    if not d.get("text") or not d.get("jid"):
        return {"ok": True}
    mine, by_me = bool(d.get("from_me")), bool(d.get("by_trinetra"))
    m = whatsapp.store(db, jid=d["jid"], text=d["text"], from_me=mine or body.type == "sent", wa_id=d.get("id"),
                       ts=_when(d.get("ts")), name=d.get("name"), group=d.get("group"),
                       by_trinetra=by_me or body.type == "sent", handled="replied" if body.type == "sent" else None)
    db.commit()
    if m is None or body.type == "sent":
        return {"ok": True}
    if mine and not by_me:  # he wrote from his phone: he's on WhatsApp
        await core.dispatch(IncomingEvent("whatsapp.activity", {"at": (_when(d.get("ts")) or datetime.now(timezone.utc)).isoformat()}, "whatsapp"), db)
        return {"ok": True}
    result = await core.dispatch(IncomingEvent("whatsapp.received", {"message_id": m.id}, "whatsapp"), db)
    return {"route": result.notes.get("wa_route"), "did": result.notes.get("wa_did")}


# ---------- the app ----------

@router.get("")
def overview(db: Session = Depends(get_db)):
    return whatsapp.status(db)


class BusyIn(BaseModel):
    action: str = Field(pattern="^(busy30|busy60|busy120|busy_tonight|not_busy)$")


@router.post("/busy")
async def busy(body: BusyIn, db: Session = Depends(get_db)):
    """His answer to "are you busy?" (the chat buttons)."""
    for m in db.scalars(select(Message).where(Message.meta.is_not(None)).order_by(Message.id.desc()).limit(30)):
        if (m.meta or {}).get("kind") == "wa_busy" and not m.meta.get("answered"):
            m.meta = {**m.meta, "answered": body.action}
    until = whatsapp.until_for(body.action)
    if until is None:
        text = "Okay, I'll leave WhatsApp to you."
        for m in db.scalars(select(whatsapp.WaMessage).where(whatsapp.WaMessage.handled == "pending")):
            m.handled = "skipped"
    else:
        whatsapp.start(db, until)
        did = await whatsapp.catch_up(db)
        from app.core.timeutil import local
        text = (f"Got it. I'll look after WhatsApp until {local(until):%-I:%M %p}: simple messages I'll answer like you "
                "would (with a 🤖), anything serious waits for you. Open WhatsApp and I step back.")
        if did:
            text += f" Already handled {len(did)} that came in: {did.count('replied')} answered, {did.count('for_you')} left for you."
    db.add(Message(role="trinetra", content=text, channel="whatsapp"))
    db.commit()
    return {"reply": text}


class OnIn(BaseModel):
    on: bool


@router.post("/autopilot")
def autopilot(body: OnIn, db: Session = Depends(get_db)):
    """The kill switch."""
    whatsapp.set_autopilot(db, body.on)
    if not body.on and (s := whatsapp.current(db)):
        whatsapp.end(db, s, "you turned the autopilot off")
    db.commit()
    return whatsapp.status(db)


class ExtendIn(BaseModel):
    minutes: int = Field(0, ge=0, le=12 * 60)


@router.post("/session")
async def session(body: ExtendIn, db: Session = Depends(get_db)):
    """minutes = 0 ends it now; otherwise start one, or add that much to the running one."""
    s = whatsapp.current(db)
    if body.minutes == 0:
        if s:
            whatsapp.end(db, s, "you ended it")
    elif s:
        s.until = s.until + timedelta(minutes=body.minutes)
    else:
        whatsapp.start(db, datetime.now(timezone.utc) + timedelta(minutes=body.minutes))
        await whatsapp.catch_up(db)
    db.commit()
    return whatsapp.status(db)


class ContactIn(BaseModel):
    jid: str = Field(max_length=80)
    auto_ok: bool


@router.post("/contacts")
def set_contact(body: ContactIn, db: Session = Depends(get_db)):
    c = db.get(WaContact, body.jid)
    if c is None:
        raise HTTPException(404, "no such contact")
    c.auto_ok = body.auto_ok
    db.commit()
    return {"jid": c.jid, "auto_ok": c.auto_ok}


class ImportIn(BaseModel):
    text: str = Field(min_length=10, max_length=3_000_000)
    my_name: str = Field("Tarun", max_length=60)
    chat: str = Field(max_length=80)


@router.post("/import")
def import_chat(body: ImportIn, db: Session = Depends(get_db)):
    """A WhatsApp "Export chat" .txt (without media): more of his real replies to learn from."""
    added = style.import_export(db, body.text, body.my_name, f"export:{body.chat.strip().lower()}")
    if not added:
        raise HTTPException(422, "no messages found — is it WhatsApp's 'Export chat' text file?")
    learned = style.learn(db)
    db.commit()
    return {"added": added, "learned_from": (learned.get("overall") or {}).get("n", 0)}


@router.post("/style/test")
async def style_test(db: Session = Depends(get_db)):
    """The "sounds like you" test: a dozen of his real past messages, rewritten by TRINETRA, compared with his own."""
    from app.core import llm
    llm.load_bench(db)
    score = await style.sounds_like_you(db)
    llm.save_bench(db)
    db.commit()
    if score is None:
        raise HTTPException(422, "I need at least 10 of your replies first — link WhatsApp or import a chat.")
    return {"score": score}


@router.get("/qr")
def qr():
    """The QR to link WhatsApp, fetched from the bridge (its key never reaches the browser)."""
    s = get_settings()
    if not whatsapp.configured():
        raise HTTPException(503, "the WhatsApp bridge isn't set up yet")
    try:
        r = httpx.get(f"{s.trinetra_bridge_url.rstrip('/')}/qr.png", headers={"Authorization": f"Bearer {s.trinetra_bridge_key}"}, timeout=15)
    except httpx.HTTPError as e:
        raise HTTPException(503, "the bridge is waking up — try again in a minute") from e
    if r.status_code == 204:
        raise HTTPException(409, "already linked")
    if r.status_code != 200:
        raise HTTPException(503, "no QR yet — the bridge is starting")
    return Response(r.content, media_type="image/png", headers={"Cache-Control": "no-store"})
