"""Vercel entry point: every request is routed here (see vercel.json) and handled by TRINETRA's FastAPI app."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.main import app  # noqa: E402,F401
