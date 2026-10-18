# TRINETRA — The Eye That Watches Over You

A personal AI mentor and caretaker. It runs Tarun's timetable, reminders and check-ins, learns his patterns, and talks with him like a mentor who knows him. It also greets visitors on his portfolio. About 70 agents in 10 teams do the work, each team has a manager, and TRINETRA decides.

## How it thinks
Each message goes through these steps:
1. **Hear:** the message becomes an event.
2. **Understand:** a router fixes typos and slang. TRINETRA's own emotion reader (`core/feel.py`, trained on GoEmotions) reads the feeling, and a language model reads the whole conversation.
3. **Remember:** `core/recall.py` ranks memories by recency, importance and relevance (the Generative Agents method). The ranking uses local embeddings in `core/embed.py`, so nothing private leaves the server for search.
4. **Teams work:** agents run in priority order. Each team's findings are credited to it, and its manager condenses them into one line (`core/briefing.py`).
5. **Decide:** the core orchestrator replies with the managers' reports in hand. Optional nudges go through the Decider (`core/autonomy.py`), which weighs value × learned chance of a reply at this time of day − interruption.
6. **Act:** the reply goes out by voice, the face or a phone notification. Big timetable changes are reviewed first (`core/deliberation.py`) and asked when needed. Deterministic guards in `agents/planning.py` keep the timetable true to what he said.
7. **Learn:** every decision is settled as engaged or ignored. Each night the Reflector writes insights from the evidence and the Forgetter retires faded trivia. Each evening the Initiative proposes one idea, always asking first.

**Safety and privacy:**
- Crisis language always gets the 988 line (Tele-MANAS 14416 in India).
- Messages about feelings avoid providers that train on free-tier prompts.
- Visitors only ever see the public brief.

**WhatsApp autopilot:** while he's busy and offline, TRINETRA answers simple WhatsApp messages the way he writes, with a 🤖. Anything serious goes to him, and it steps back the moment he opens WhatsApp. `bridge/` holds the always-on WhatsApp link (Render); `core/whatsapp.py` makes the decisions and `core/style.py` learns his style.

## Run it
```bash
cp .env.example .env        # then paste your free GEMINI_API_KEY and/or GROQ_API_KEY
python3 -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cd backend && ../.venv/bin/uvicorn app.main:app --reload
```
Open http://localhost:8000/docs to see every endpoint. `/health` shows that the deployed data files and TRINETRA's own models load.

## Layout
- `agents/*.yaml`: the agents, one file per team, each with its manager. An agent is **active** once it has a handler in `backend/app/agents/` (or a `builtin:` location), and **planned** until then.
- `backend/app/core/`: the orchestrator, registry, LLM pools (`llm.py`: smart / fast / guest tiers, sensitive routing), memory, the Decider, the persona, and the portfolio host (`guest.py`).
- `backend/app/data/`: common words, TRINETRA's own model weights (`embed/`), and the public brief.
- `training/`: how those models were made, plus the conversation and timetable evals (see `training/README.md`).

## Tests
```bash
cd backend && ../.venv/bin/python -m pytest -q                               # SQLite
TEST_TZ=America/Los_Angeles ../.venv/bin/python -m pytest -q                 # any time zone
TRINETRA_TEST_DB=postgresql://… ../.venv/bin/python -m pytest -q             # real Postgres, like production
```

## Status
See ROADMAP.md.
