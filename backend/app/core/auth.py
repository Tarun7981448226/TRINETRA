"""Passcode lock. One person, one passcode — every device logs in once and stays logged in.

Machines (n8n, iOS Shortcuts, the WhatsApp bridge) send `Authorization: Bearer <passcode>` instead.
Changing TRINETRA_PASSCODE logs every device out.
"""
import hashlib
import hmac
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_settings

COOKIE = "trinetra_session"
# Reachable without logging in: the login page, health check, what iOS needs to install the app,
# and the portfolio widget's endpoints.
PUBLIC = ("/login", "/health", "/manifest.webmanifest", "/sw.js", "/static/", "/cron/", "/sc/",  # own secrets
          "/guest/")  # portfolio visitors: per-visit tokens, public facts only


def session_token(passcode: str, secret: str) -> str:
    return hmac.new(secret.encode(), f"trinetra:{passcode}".encode(), hashlib.sha256).hexdigest()


def is_authenticated(request: Request) -> bool:
    s = get_settings()
    if not s.trinetra_passcode:
        return True
    expected = session_token(s.trinetra_passcode, s.trinetra_secret)
    if hmac.compare_digest(request.cookies.get(COOKIE, ""), expected):
        return True
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    return bool(bearer) and hmac.compare_digest(bearer, s.trinetra_passcode)


class PasscodeMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith(PUBLIC) or is_authenticated(request):
            return await call_next(request)
        if request.method == "GET" and "text/html" in request.headers.get("accept", ""):
            return RedirectResponse(f"/login?next={quote(path)}", status_code=303)
        return JSONResponse({"detail": "locked — log in with your passcode"}, status_code=401)
