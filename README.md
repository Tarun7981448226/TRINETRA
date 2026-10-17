# TRINETRA — The Eye That Watches Over You

Your personal AI mentor and caretaker: timetable, reminders, monitoring, an ML brain that learns you,
an emotional voice, Gmail and WhatsApp — run by 65 agents in 10 councils.

## Run it (on your Mac, for now)
```bash
cp .env.example .env        # then paste your free GEMINI_API_KEY and/or GROQ_API_KEY
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/uvicorn app.main:app --reload
```
Open http://localhost:8000/docs to talk to TRINETRA (`POST /chat`) and see every endpoint.

## Layout
- `agents/*.yaml`: the 65 agents, one file per council. An agent is **active** once it has a Python handler in `backend/app/agents/`, and **planned** until then.
- `backend/app/core/`: the orchestrator (routes events to agents), the registry, the LLM layer (free Gemini/Groq via LiteLLM), the persona, and time rules.
- `backend/app/api/routes.py`: `/chat`, `/events` (the single entry point for n8n, iOS Shortcuts, WhatsApp and the PWA), `/tasks`, `/goals`, `/agents`.

## Tests
```bash
cd backend && ../.venv/bin/python -m pytest -q
```

## Status
See ROADMAP.md. Phases 1–2 work: chat, voice, memory, timetable by talking, reminders and check-ins.
