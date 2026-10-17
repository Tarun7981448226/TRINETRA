import os

# Tests never use your real keys, timezone or database.
os.environ.update(GEMINI_API_KEY="", GROQ_API_KEY="test-key", TRINETRA_TIMEZONE="Asia/Kolkata",
                  DATABASE_URL="sqlite://", TRINETRA_SCHEDULER="false", TRINETRA_PASSCODE="")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.core import llm
from app.db.session import get_db, init_db, make_engine
from app.main import create_app


@pytest.fixture
def llm_calls(monkeypatch):
    """Stub the LLM so tests are free, offline and deterministic. Records every prompt."""
    calls: list[dict] = []

    async def fake_complete(messages, tier="smart", **kwargs):
        calls.append({"messages": messages, "tier": tier})
        return "Got it, I'm on it."

    monkeypatch.setattr(llm, "complete", fake_complete)
    return calls


@pytest.fixture
def client(llm_calls):
    # Default: in-memory SQLite. Set TRINETRA_TEST_DB=postgresql://... to run the suite on Postgres (Neon's engine).
    engine = make_engine(os.environ.get("TRINETRA_TEST_DB", "sqlite://"))
    from app.db.models import Base
    Base.metadata.drop_all(engine)
    init_db(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app = create_app()
    app.dependency_overrides[get_db] = override_db
    with TestClient(app) as c:
        c.session_factory = Session
        yield c


def trinetra_prompt(calls: list[dict]) -> str:
    """The system prompt of the last call made by TRINETRA's main voice (other agents call the LLM too)."""
    return [c for c in calls if "You are TRINETRA" in c["messages"][0]["content"]][-1]["messages"][0]["content"]
