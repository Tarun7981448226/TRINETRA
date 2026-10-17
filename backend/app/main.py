"""TRINETRA — The Eye That Watches Over You."""
import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api import guest as guest_api
from app.api.routes import router
from app.config import get_settings
from app.core import scheduler
from app.core.auth import PasscodeMiddleware
from app.core.orchestrator import Orchestrator
from app.core.registry import Registry
from app.db.session import SessionLocal, init_db

STATIC = Path(__file__).parent / "static"

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")


class CachedStatic(StaticFiles):
    """Instrument samples and the music model never change in place: let browsers and the CDN keep them."""

    def file_response(self, *args, **kwargs):
        resp = super().file_response(*args, **kwargs)
        if "/music/" in str(args[0] if args else kwargs.get("full_path", "")):
            resp.headers["Cache-Control"] = "public, max-age=604800, s-maxage=2592000"
        return resp


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            init_db()  # creates/upgrades tables; harmless if they exist
        except Exception:
            logging.getLogger("trinetra").exception("database init failed")
        heartbeat = None
        if settings.trinetra_scheduler:
            heartbeat = asyncio.create_task(scheduler.run_forever(SessionLocal, app.state.orchestrator))
        yield
        if heartbeat:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

    app = FastAPI(title="TRINETRA", description="The Eye That Watches Over You", lifespan=lifespan)
    app.state.orchestrator = Orchestrator(Registry.load(settings.agents_dir), settings)
    app.add_middleware(PasscodeMiddleware)
    # The portfolio (another site) talks to /guest/* from the visitor's browser. No cookies cross over.
    app.add_middleware(CORSMiddleware, allow_origins=guest_api.ORIGINS, allow_methods=["GET", "POST"],
                       allow_headers=["content-type"], allow_credentials=False)
    app.include_router(router)
    app.include_router(guest_api.public)
    app.include_router(guest_api.private)
    app.include_router(guest_api.look_router)
    app.mount("/static", CachedStatic(directory=STATIC), name="static")

    # The service worker must be served from the root so it controls the whole app.
    @app.get("/sw.js", include_in_schema=False)
    def service_worker():
        return FileResponse(STATIC / "sw.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest", include_in_schema=False)
    def manifest():
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(STATIC / "index.html")

    @app.get("/health")
    def health():
        reg = app.state.orchestrator.registry
        return {
            "status": "awake",
            "llm_connected": settings.llm_available,
            "agents": len(reg.specs),
        }

    return app


app = create_app()
