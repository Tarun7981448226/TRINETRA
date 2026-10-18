"""Web Push: TRINETRA's reminders reach your iPhone's lock screen (installed PWA, iOS 16.4+).

VAPID keys are generated once on first use and kept in data/vapid.json — no setup needed.
"""
import base64
import json
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import PushSubscription

log = logging.getLogger("trinetra.push")


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def vapid_keys() -> dict:
    """{'private_pem': ..., 'public_key': <base64url uncompressed point for the browser>}"""
    s = get_settings()
    if s.vapid_private_pem and s.vapid_public_key:  # cloud: keys from env vars
        return {"private_pem": s.vapid_private_pem.replace("\\n", "\n"), "public_key": s.vapid_public_key}
    path = s.data_dir / "vapid.json"
    if path.exists():
        return json.loads(path.read_text())
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    keys = {
        "private_pem": key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        ).decode(),
        "public_key": _b64url(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
        )),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(keys))
    path.chmod(0o600)
    return keys


def send(db: Session, title: str, body: str, url: str = "/", tag: str | None = None) -> int:
    """Push to every subscribed device. Dead subscriptions are removed. Returns how many got it."""
    from py_vapid import Vapid
    from pywebpush import WebPushException, webpush

    subs = db.scalars(select(PushSubscription)).all()
    if not subs:
        return 0
    keys = vapid_keys()
    vapid = Vapid.from_pem(keys["private_pem"].encode())
    payload = json.dumps({"title": title, "body": body[:400], "url": url, "tag": tag})
    delivered = 0
    for sub in subs:
        try:
            webpush(
                subscription_info={"endpoint": sub.endpoint, "keys": {"p256dh": sub.p256dh, "auth": sub.auth}},
                data=payload,
                vapid_private_key=vapid,
                vapid_claims={"sub": get_settings().trinetra_contact_email},
                ttl=3600,
            )
            delivered += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (404, 410):  # device unsubscribed or app deleted
                db.delete(sub)
            log.warning("push failed (%s): %s", status, e)
        except Exception as e:  # network error / timeout: never let one phone stop the heartbeat
            log.warning("push failed: %s", e)
    db.flush()
    return delivered
