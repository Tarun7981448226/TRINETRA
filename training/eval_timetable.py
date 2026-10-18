import asyncio, os, sys, time as _t
sys.path.insert(0, os.getcwd())
db_path = sys.argv[1]
os.environ["TRINETRA_MODELS_SMART"] = "groq/openai/gpt-oss-120b,groq/openai/gpt-oss-20b"
os.environ["TRINETRA_MODELS_FAST"] = "groq/openai/gpt-oss-20b,groq/openai/gpt-oss-120b"
from dotenv import load_dotenv; load_dotenv("../.env", override=False)
from datetime import time, timedelta
from sqlalchemy import select
from app.db.session import make_engine, init_db
from sqlalchemy.orm import sessionmaker
from app.main import create_app
from app.core import timetable, deliberation
from app.core.orchestrator import IncomingEvent
from app.core.timeutil import now_local, local
from app.db.models import Task, TaskStatus
app = create_app(); core = app.state.orchestrator
today = now_local().date(); tom = today + timedelta(days=1)
def on(db, title, day):
    return [t for t in db.scalars(select(Task)) if title.lower() in t.title.lower() and local(t.planned_start).date() == day and t.status != TaskStatus.SKIPPED]
CASES = [
    ("move gym to 7pm tomorrow", lambda db: [local(t.planned_start).time() for t in on(db, "gym", tom)] == [time(19)]),
    ("cn u push my dsa to 10pm tmrw", lambda db: [local(t.planned_start).time() for t in on(db, "dsa", tom)] == [time(22)]),
    ("cancel gym tomorrow", lambda db: on(db, "gym", tom) == [] and len(on(db, "gym", tom + timedelta(days=1)) or [1]) >= 0),
    ("add a 30 min walk at 8am tomorrow", lambda db: [(local(t.planned_start).time(), (t.planned_end - t.planned_start).seconds // 60) for t in on(db, "walk", tom)] == [(time(8), 30)]),
    ("I sleep at 1am and wake at 8", lambda db: deliberation.sleep_window(db) == (time(1), time(8))),
    ("go to bed by 12:30 am on weekdays", lambda db: deliberation.sleep_window(db)[0] == time(0, 30)),
]
ok = 0
for text, check in CASES:
    if os.path.exists(db_path): os.remove(db_path)
    eng = make_engine(f"sqlite:///{db_path}"); init_db(eng); S = sessionmaker(bind=eng, expire_on_commit=False)
    with S() as db:
        timetable.create_block(db, "Gym", today - timedelta(days=1), time(18), time(19), category="fitness", recurrence="weekdays")
        timetable.create_block(db, "TUF DSA", today - timedelta(days=1), time(21), time(22), category="study", recurrence="daily")
        db.commit()
        r = asyncio.run(core.dispatch(IncomingEvent("user.message", {"text": text}, "web"), db))
        db.commit(); db.expire_all()
        good = bool(check(db)); ok += good
        print("OK " if good else "BAD", text.ljust(38), "|", (r.notes.get("deliberation") or {}).get("action"), "|", r.notes.get("timetable_changes"), "|", (r.reply or "")[:110], flush=True)
    _t.sleep(8)
print(f"{ok}/{len(CASES)}")
