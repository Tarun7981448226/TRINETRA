from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import select

from app.agents import monitoring
from app.config import get_settings
from app.core import emotion, push, timetable, voice
from app.core.timeutil import to_utc, user_tz
from app.core.voice import SILENT_MP3
from app.db.models import AppOpen, Message

KEY = "sc-test-key"
DAY = date(2026, 10, 20)


def at(hh: int, mm: int = 0) -> datetime:
    return to_utc(datetime.combine(DAY, time(hh, mm), user_tz()))


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setattr(get_settings(), "trinetra_shortcut_key", KEY)
    monkeypatch.setattr(get_settings(), "gemini_api_key", "")  # use the fixed fallback lines
    monkeypatch.setattr(get_settings(), "groq_api_key", "")

    async def fake_speak(text, mood=None):
        return b"ID3" + text.encode()[:60]

    monkeypatch.setattr(voice, "speak", fake_speak)
    pushed = []
    monkeypatch.setattr(push, "send", lambda *a, **k: pushed.append(a[2]) or 1)
    return pushed


def opened(client, monkeypatch, when: datetime, app="Instagram") -> bytes:
    monkeypatch.setattr(monitoring, "clock", lambda: when)
    r = client.get("/sc/opened", params={"key": KEY, "app": app})
    assert r.status_code == 200
    return r.content


def blocks(client):
    with client.session_factory() as db:
        timetable.create_block(db, "TUF DSA", DAY, time(10), time(12), category="study")
        timetable.create_block(db, "CSCI 570 class", DAY, time(14), time(17), category="study")
        timetable.create_block(db, "Gym", DAY, time(18), time(19), category="fitness")
        db.commit()


def test_focus_block_calls_it_out_and_gets_firmer(client, monkeypatch):
    blocks(client)
    first = opened(client, monkeypatch, at(10, 15))
    assert first.startswith(b"ID3") and b"TUF DSA" in first
    assert opened(client, monkeypatch, at(10, 16)) == SILENT_MP3  # bouncing in and out: one call-out
    before = emotion.load(client.session_factory()).frustration
    second = opened(client, monkeypatch, at(10, 30), app="YouTube")
    assert b"2 times" in second
    with client.session_factory() as db:
        assert emotion.load(db).frustration > before
        rows = db.scalars(select(AppOpen).order_by(AppOpen.id)).all()
        assert [(r.app, r.kind, r.spoke) for r in rows] == [
            ("Instagram", "focus", True), ("Instagram", "focus", False), ("YouTube", "focus", True)]
        lines = db.scalars(select(Message).where(Message.channel == "shortcut")).all()
        assert len(lines) == 2 and lines[1].meta["count"] == 2  # in the chat, but the app won't replay it


def test_class_is_silent_push_never_a_voice(client, monkeypatch, setup):
    blocks(client)
    assert opened(client, monkeypatch, at(15)) == SILENT_MP3
    assert len(setup) == 1 and "CSCI 570" in setup[0]


def test_free_time_and_gym_only_counted(client, monkeypatch, setup):
    blocks(client)
    assert opened(client, monkeypatch, at(13)) == SILENT_MP3
    assert opened(client, monkeypatch, at(18, 30)) == SILENT_MP3
    with client.session_factory() as db:
        assert [r.kind for r in db.scalars(select(AppOpen)).all()] == ["free", "free"]
        assert not db.scalars(select(Message).where(Message.channel == "shortcut")).all()
    assert setup == []


def test_late_night_says_sleep(client, monkeypatch):
    out = opened(client, monkeypatch, at(23, 50))
    assert b"sleep" in out


def test_needs_the_shortcut_key(client):
    assert client.get("/sc/opened", params={"key": "wrong"}).status_code == 401
