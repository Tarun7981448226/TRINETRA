import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from app.config import get_settings
from app.core import push, scheduler


@pytest.fixture
def locked(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "trinetra_passcode", "tiger-river-42")
    monkeypatch.setattr(s, "trinetra_secret", "test-secret")


@pytest.fixture(autouse=True)
def data_in_tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "data_dir", tmp_path)


def test_locked_app_redirects_browsers_and_refuses_api(client, locked):
    r = client.get("/", headers={"accept": "text/html"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/login")
    assert client.get("/memories").status_code == 401
    assert client.post("/chat", json={"text": "hi"}).status_code == 401


def test_install_files_are_public_even_when_locked(client, locked):
    for path in ("/health", "/login", "/manifest.webmanifest", "/sw.js", "/static/icons/icon-192.png"):
        assert client.get(path).status_code == 200, path
    manifest = client.get("/manifest.webmanifest").json()
    assert manifest["display"] == "standalone" and manifest["name"] == "TRINETRA"


def test_login_with_passcode_unlocks(client, locked):
    assert client.post("/login", json={"passcode": "wrong"}).status_code == 401
    assert client.post("/login", json={"passcode": "tiger-river-42"}).status_code == 200
    assert client.get("/memories").status_code == 200  # cookie now set


def test_machines_use_bearer_passcode(client, locked):
    headers = {"authorization": "Bearer tiger-river-42"}
    assert client.post("/events", json={"type": "shortcut.app_opened"}, headers=headers).status_code == 200
    assert client.post("/events", json={"type": "shortcut.app_opened"},
                       headers={"authorization": "Bearer nope"}).status_code == 401


def test_vapid_keys_are_made_once(client):
    a, b = push.vapid_keys(), push.vapid_keys()
    assert a == b and len(a["public_key"]) > 80


SUB = {"endpoint": "https://web.push.apple.com/abc", "keys": {"p256dh": "BEl6-key", "auth": "authsecret"}}


def test_subscribe_is_idempotent(client):
    assert client.post("/push/subscribe", json=SUB).status_code == 201
    assert client.post("/push/subscribe", json=SUB).status_code == 201
    from app.db.models import PushSubscription
    with client.session_factory() as db:
        assert db.query(PushSubscription).count() == 1
    assert client.post("/push/subscribe", json={**SUB, "endpoint": "http://insecure"}).status_code == 422


def test_reminder_goes_to_lock_screen(client, llm_calls, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "send", lambda db, title, body, url="/", tag=None: sent.append(body) or 1)
    client.post("/push/subscribe", json=SUB)
    start = datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc)
    client.post("/tasks", json={"title": "Gym", "planned_start": start.isoformat(),
                                "planned_end": (start + timedelta(hours=1)).isoformat()})
    with client.session_factory() as db:
        asyncio.run(scheduler.tick(db, client.app.state.orchestrator, start - timedelta(minutes=2)))
    assert sent == ["Got it, I'm on it."]


def test_dead_subscriptions_are_pruned(client, monkeypatch):
    import pywebpush

    class Gone:
        status_code = 410

    def boom(**kw):
        raise pywebpush.WebPushException("gone", response=Gone())

    monkeypatch.setattr(pywebpush, "webpush", boom)
    client.post("/push/subscribe", json=SUB)
    from app.db.models import PushSubscription
    with client.session_factory() as db:
        assert push.send(db, "T", "hello") == 0
        db.commit()
        assert db.query(PushSubscription).count() == 0


def test_cron_tick_needs_its_secret_and_fires_reminders(client, llm_calls, monkeypatch):
    monkeypatch.setattr(get_settings(), "trinetra_cron_secret", "cron-s3cret")
    monkeypatch.setattr(push, "send", lambda *a, **k: 0)
    assert client.post("/cron/tick").status_code == 401
    assert client.post("/cron/tick", headers={"authorization": "Bearer wrong"}).status_code == 401

    from app.core.timeutil import now_local
    start = now_local() + timedelta(minutes=3)
    t = client.post("/tasks", json={"title": "Gym", "planned_start": start.isoformat(),
                                    "planned_end": (start + timedelta(hours=1)).isoformat()}).json()
    r = client.post("/cron/tick", headers={"authorization": "Bearer cron-s3cret"})
    assert r.status_code == 200
    assert r.json()["fired"] == [f"task.due:{t['id']}"]
    assert client.post("/cron/tick", headers={"authorization": "Bearer cron-s3cret"}).json()["fired"] == []


def test_cron_disabled_without_secret(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "trinetra_cron_secret", "")
    assert client.post("/cron/tick", headers={"authorization": "Bearer "}).status_code == 401


def test_vapid_keys_from_env(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "vapid_private_pem", "-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----")
    monkeypatch.setattr(get_settings(), "vapid_public_key", "BPUB")
    keys = push.vapid_keys()
    assert keys["public_key"] == "BPUB" and "\nabc\n" in keys["private_pem"]


def test_login_is_rate_limited(client, locked):
    for _ in range(8):
        assert client.post("/login", json={"passcode": "guess"}).status_code == 401
    assert client.post("/login", json={"passcode": "guess"}).status_code == 429
    # even the right passcode waits out the lockout
    assert client.post("/login", json={"passcode": "tiger-river-42"}).status_code == 429


def test_successful_login_clears_failures(client, locked):
    for _ in range(3):
        client.post("/login", json={"passcode": "nope"})
    assert client.post("/login", json={"passcode": "tiger-river-42"}).status_code == 200
    from app.db.models import KeyValue
    with client.session_factory() as db:
        assert db.get(KeyValue, "login_failures") is None


def test_page_has_the_living_character(client):
    html = client.get("/", headers={"accept": "text/html"}).text
    assert 'class="orb" id="eye"' in html  # tap to talk; jumps out to listen / speak
    assert 'class="buddy"' in html and 'class="tbar"' in html and "/static/buddy.js" in html  # the character + time bar
    assert html.count('id="eye"') == 1
    assert client.get("/static/buddy.js").status_code == 200


def test_messages_carry_time_and_app_waits_for_a_tap_to_speak(client):
    client.post("/chat", json={"text": "hello", "channel": "web"})
    rows = client.get("/messages?limit=5").json()
    assert rows and all(datetime.fromisoformat(m["at"]).tzinfo for m in rows)
    page = client.get("/").text
    assert 'id="hear"' in page and "heardId" in page  # iPhone: blocked lines wait for the first tap
