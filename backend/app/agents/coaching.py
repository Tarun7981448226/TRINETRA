"""Coaching: looking back at the week and ahead at the goals."""
import json
import re
from datetime import date, datetime, timezone

from sqlalchemy import select

from app.agents.planning import _speak_up
from app.core import courses, llm, report, roadmap, vision
from app.core.orchestrator import AgentContext, AgentResult
from app.core.registry import agent
from app.core.timeutil import from_db, local
from app.db.models import Course, Goal, KeyValue, Task


def analyse_week(db, monday: date) -> dict:
    """Where you're lagging: each course's week (TUF sprints, Coursera) and each goal's forecast vs its target."""
    _, start, end = report.week_bounds(monday)
    out = {"courses": [], "goals": []}
    courses.ensure(db)
    for c in db.scalars(select(Course).order_by(Course.id)).all():
        s = courses.summary(db, c, min(end, datetime.now(timezone.utc)))
        its = courses.items(db, c)
        this_week = [i for i in its if i.task_id and i.done_at and start <= from_db(i.done_at) < end]
        due_this_week = [i for i in its if i.planned_date and monday.isoformat() <= i.planned_date
                         < date.fromordinal(monday.toordinal() + 7).isoformat()]
        sprint = next((sp for sp in s["sprints"] if sp["done"] < sp["total"]), None)
        out["courses"].append({
            "course": c.title, "done": s["done"], "total": s["total"], "now_at": (s["now_at"] or {}).get("title"),
            "done_this_week": len(this_week), "planned_this_week": len(due_this_week),
            "planned_this_week_done": sum(1 for i in due_this_week if i.done_at),
            "overdue": s["behind"], "current_sprint": sprint,
            "need_per_block": s["need_per_block"], "per_block": s["per_block"], "on_pace": s["on_pace"],
        })
    for g in db.scalars(select(Goal).where(Goal.status == "active")).all():
        f = roadmap.forecast(db, g) or {}
        target = local(g.target_date).date().isoformat() if g.target_date else None
        finish = f.get("finish")
        out["goals"].append({"goal": g.title, "progress": round(g.progress, 2), "target": target,
                             "forecast_finish": finish,
                             "late_by_days": (date.fromisoformat(finish) - date.fromisoformat(target)).days
                             if finish and target else None})
    from collections import Counter

    from app.db.models import MoodEntry

    moods = db.scalars(select(MoodEntry).where(MoodEntry.at >= start, MoodEntry.at < end)).all()
    from app.ml import insights

    out["insights"] = {k: v for k, v in insights.load(db).items() if k in ("energy", "procrastination", "patterns", "durations")}
    out["moods"] = {"logged": len(moods), "counts": dict(Counter(m.mood for m in moods).most_common(6)),
                    "low": sum(m.mood in ("sad", "low", "tired", "stressed", "anxious", "lonely", "overwhelmed", "hurt",
                                          "frustrated") for m in moods)}
    return out


@agent("weekly_analyst")
async def weekly_analyst(ctx: AgentContext) -> None:
    """Sunday night, before the report is written: the facts on where you're lagging go into it."""
    week = ctx.event.payload.get("week_of")
    if not week:
        return
    found = analyse_week(ctx.db, date.fromisoformat(week))
    key = f"week_analysis:{week}"
    row = ctx.db.get(KeyValue, key)
    if row is None:
        ctx.db.add(KeyValue(key=key, value=json.dumps(found)))
    else:
        row.value = json.dumps(found)
    ctx.db.flush()
    ctx.notes["week_analysis"] = found


# ---------- your why: the vision, and reminding you of it when you waver ----------

VISION_TALK = re.compile(r"\b(in|within|next|after)\s+(1|one|a|3|three|5|five)\s+years?\b|\bmy vision\b|\bmy dream\b", re.I)


@agent("vision_keeper")
async def vision_keeper(ctx: AgentContext) -> AgentResult | None:
    """You talk about where you want to be in 1 / 3 / 5 years → it's kept (and the 🎯 screen shows it)."""
    text = str(ctx.event.payload.get("text", ""))
    if ctx.event.payload.get("button") or not VISION_TALK.search(text):
        return None
    found = {}
    if ctx.settings.llm_available:
        try:
            raw = await llm.complete([
                {"role": "system", "content": "Extract the person's vision from their message. JSON only: "
                 '{"y1": string|null, "y3": string|null, "y5": string|null} — where they want to be in 1, 3 and 5 '
                 "years, in their own words, first person. null when they didn't say. No guessing."},
                {"role": "user", "content": text}], tier="fast", temperature=0, max_tokens=300, json_mode=True)
            found = {k: v for k, v in json.loads(raw).items() if k in vision.HORIZONS and v}
        except (llm.LLMUnavailable, ValueError, TypeError, AttributeError):
            found = {}
    if not found:
        m = re.search(r"\b(1|one|a|3|three|5|five)\s+years?\b", text, re.I)
        h = {"1": "y1", "one": "y1", "a": "y1", "3": "y3", "three": "y3", "5": "y5", "five": "y5"}.get(m.group(1).lower()) if m else None
        if h:
            found = {h: text.strip()}
    if not found:
        return None
    vision.put(ctx.db, **found)
    ctx.notes["vision_saved"] = found
    return None  # the chat reply carries on; the 🎯 screen shows what was kept


@agent("motivation_coach")
async def motivation_coach(ctx: AgentContext) -> AgentResult | None:
    """You skipped something that matters: the reason you're doing it, once a day — fuel, not guilt."""

    task = ctx.db.get(Task, ctx.event.payload.get("task_id"))
    if task is None or task.priority < 4:
        return None
    key = f"why_reminded:{local(datetime.now(timezone.utc)).date().isoformat()}"
    if ctx.db.get(KeyValue, key) is not None:
        return None
    goal = ctx.db.get(Goal, task.goal_id) if task.goal_id else None
    if goal is None and (c := courses.course_for(ctx.db, task)) and c.goal_id:
        goal = ctx.db.get(Goal, c.goal_id)
    why = (goal.why if goal and goal.why else "") or ""
    dream = vision.line(ctx.db)
    if not (why or dream or goal):
        return None
    ctx.db.add(KeyValue(key=key, value="1"))
    return await _speak_up(
        ctx, instruction=(f"I just skipped '{task.title}'. Remind me why it matters, in two short spoken sentences — "
                          f"fuel, not guilt. Goal: {goal.title if goal else 'none'}. My why: {why or 'not written'}. "
                          f"My vision: {dream or 'not written'}."
                          + (f" Note: I skip this one a lot ({ctx.notes['habitual_skip']['rate']}% of the time"
                             + (f" on {ctx.notes['habitual_skip']['day']}s" if ctx.notes['habitual_skip']['day'] else "")
                             + ") — name the pattern gently." if ctx.notes.get("habitual_skip") else "")),
        fallback=f"Remember why you're doing this: {why or (goal.title if goal else dream)}. One skip is fine; two is a pattern.",
        mood="warm and caring, but firm", keep_mood=True, channel="web", meta={"kind": "why"})


# ---------- what TRINETRA knows about you, kept current ----------

AUTO = "[auto-profile] "


@agent("profile_keeper")
async def profile_keeper(ctx: AgentContext) -> None:
    """Every night: your patterns from the data (best hours, what you skip, streaks, moods) → one profile memory."""
    from collections import Counter, defaultdict
    from datetime import timedelta

    from app.core import streaks
    from app.db.models import Memory, MoodEntry, TaskStatus

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=28)
    tasks = ctx.db.scalars(select(Task).where(Task.planned_start >= since, Task.planned_end < now,
                                              Task.notify != "none", Task.category != "sleep")).all()
    if len(tasks) < 5:
        return
    by_hour, by_cat = defaultdict(lambda: [0, 0]), defaultdict(lambda: [0, 0])
    for t in tasks:
        ok = t.status == TaskStatus.DONE
        h = local(t.planned_start).hour
        band = "mornings" if h < 12 else "afternoons" if h < 17 else "evenings"
        by_hour[band][0] += ok
        by_hour[band][1] += 1
        by_cat[t.category][0] += ok
        by_cat[t.category][1] += 1
    rate = lambda p: round(100 * p[0] / p[1]) if p[1] else 0  # noqa: E731
    bands = sorted(by_hour.items(), key=lambda kv: -rate(kv[1]))
    weak = [c for c, p in by_cat.items() if p[1] >= 3 and rate(p) < 50]
    s = [x for x in streaks.all_streaks(ctx.db) if x["best"] >= 2]
    moods = Counter(m.mood for m in ctx.db.scalars(select(MoodEntry).where(MoodEntry.at >= since)).all())
    total = [sum(p[0] for p in by_cat.values()), sum(p[1] for p in by_cat.values())]
    parts = [f"Finishes {rate(total)}% of planned blocks"
             + (f": {rate(bands[0][1])}% in the {bands[0][0]} vs {rate(bands[-1][1])}% in the {bands[-1][0]}."
                if len(bands) > 1 else f", mostly in the {bands[0][0]}.")]
    if weak:
        parts.append("Often skips: " + ", ".join(weak) + ".")
    skipped = Counter(t.title for t in tasks if t.status == TaskStatus.SKIPPED).most_common(2)
    if skipped:
        parts.append("Most skipped: " + ", ".join(f"{n} ({c}×)" for n, c in skipped) + ".")
    if s:
        parts.append("Streaks: " + ", ".join(f"{x['label']} {x['current']} (best {x['best']})" for x in s) + ".")
    if moods:
        parts.append("Most common moods lately: " + ", ".join(m for m, _ in moods.most_common(3)) + ".")
    from app.ml import insights

    ins = insights.load(ctx.db)
    if e := ins.get("energy"):
        parts.append(f"Sharpest {e['peak']} ({e['peak_rate']}% done), weakest {e['slump']} ({e['slump_rate']}%).")
    if pr := ins.get("procrastination"):
        parts.append("Pushes off: " + ", ".join(f"{p['block']}{' on ' + p['day'] + 's' if p['day'] else ''} ({p['rate']}%)" for p in pr[:2]) + ".")
    for pt in (ins.get("patterns") or [])[:2]:
        parts.append(pt["text"])
    content = AUTO + " ".join(p for p in parts if p) + f" (last 28 days, updated {local(now):%d %b})"
    old = ctx.db.scalars(select(Memory).where(Memory.content.like(AUTO + "%"))).all()
    for m in old:
        ctx.db.delete(m)
    ctx.db.add(Memory(kind="habit", content=content[:1000], importance=4))
    ctx.db.flush()


# ---------- the evening: looking back at today, and whether you're falling behind ----------

@agent("daily_reviewer")
async def daily_reviewer(ctx: AgentContext) -> AgentResult | None:
    """After the last block: today's wins, misses and one lesson — short, honest, spoken."""
    from datetime import timedelta

    from app.core import streaks
    from app.core.timeutil import to_utc
    from app.db.models import MoodEntry, StudyItem, TaskStatus

    day = date.fromisoformat(ctx.event.payload["date"])
    lo = to_utc(datetime.combine(day, datetime.min.time()))
    hi = lo + timedelta(days=1)
    tasks = ctx.db.scalars(select(Task).where(Task.planned_start >= lo, Task.planned_start < hi,
                                              Task.notify != "none", Task.category != "sleep")).all()
    if not tasks:
        return None
    done = [t.title for t in tasks if t.status == TaskStatus.DONE]
    skipped = [t.title for t in tasks if t.status == TaskStatus.SKIPPED]
    missed = [t.title for t in tasks if t.status == TaskStatus.PLANNED and from_db(t.planned_end) < datetime.now(timezone.utc)]
    ticked = ctx.db.scalars(select(StudyItem).where(StudyItem.task_id.is_not(None), StudyItem.done_at >= lo,
                                                    StudyItem.done_at < hi)).all()
    alive = [f"{s['label']} {s['current']}" for s in streaks.all_streaks(ctx.db, day) if s["today"] and s["current"] >= 2]
    moods = [m.mood for m in ctx.db.scalars(select(MoodEntry).where(MoodEntry.at >= lo, MoodEntry.at < hi)).all()]
    facts = (f"Done: {', '.join(done) or 'nothing'}. Skipped: {', '.join(skipped) or 'none'}. Never answered: "
             f"{', '.join(missed) or 'none'}. Course topics ticked: {len(ticked)}"
             + (f" ({', '.join(i.title for i in ticked[:6])})" if ticked else "") + "."
             + (f" Streaks alive: {', '.join(alive)}." if alive else "") + (f" Moods today: {', '.join(moods)}." if moods else ""))
    ctx.notes["day_review"] = {"done": len(done), "skipped": len(skipped), "missed": len(missed), "ticked": len(ticked)}
    return await _speak_up(
        ctx, instruction=(f"Review my day like a mentor, in three short spoken sentences: the real win, the honest miss, "
                          f"and one lesson for tomorrow. Facts: {facts}"),
        fallback=f"Today: {len(done)} done, {len(skipped) + len(missed)} not. {len(ticked)} course topics ticked.",
        mood="honest, warm, deeply invested mentor — proud where earned, firm where needed",
        meta={"kind": "review", "date": day.isoformat(), **ctx.notes["day_review"]})


LAG_GAP_DAYS = 3  # behind by more than this → say so
LAG_EVERY_DAYS = 3  # …but not every night


def course_pace(db, c, now: datetime) -> dict | None:
    """Recent pace vs the pace needed to finish on time."""
    from datetime import timedelta

    its = courses.items(db, c)
    left = [i for i in its if not i.done_at and not i.optional]
    dated = [i.planned_date for i in its if i.planned_date]
    deadline = local(c.target_date).date() if c.target_date else (date.fromisoformat(max(dated)) if dated else None)
    if not left or deadline is None:
        return None
    week = [i for i in its if i.done_at and i.task_id and from_db(i.done_at) >= now - timedelta(days=7)]
    per_day = len(week) / 7
    days_left = max(1, (deadline - local(now).date()).days)
    finish = (local(now).date() + timedelta(days=int(len(left) / per_day) + 1)) if per_day else None
    return {"course": c.title, "left": len(left), "per_day": round(per_day, 1), "need_per_day": round(len(left) / days_left, 1),
            "deadline": deadline.isoformat(), "finish": finish.isoformat() if finish else None,
            "late_days": (finish - deadline).days if finish else None}


@agent("lag_detector")
async def lag_detector(ctx: AgentContext) -> AgentResult | None:
    """Evening: is a course (or goal) falling behind its deadline at your real pace? Said plainly, every few days."""
    now = datetime.now(timezone.utc)
    key = "lag_said"
    row = ctx.db.get(KeyValue, key)
    if row and row.value and (now - datetime.fromisoformat(row.value)).days < LAG_EVERY_DAYS:
        return None
    behind = []
    for c in ctx.db.scalars(select(Course).order_by(Course.id)).all():
        if c.starter or (c.active_from and from_db(c.active_from) > now):
            continue
        p = course_pace(ctx.db, c, now)
        if p and (p["late_days"] is None or p["late_days"] > LAG_GAP_DAYS):
            behind.append(p)
    ctx.notes["lag"] = behind
    if not behind:
        return None
    if row is None:
        ctx.db.add(KeyValue(key=key, value=now.isoformat()))
    else:
        row.value = now.isoformat()
    facts = " ".join(
        f"{p['course']}: {p['left']} topics left, doing {p['per_day']}/day, need {p['need_per_day']}/day for {p['deadline']}"
        + (f" — at this pace it finishes {p['finish']}, {p['late_days']} days late." if p["finish"] else " — at this pace it never finishes.")
        for p in behind)
    return await _speak_up(
        ctx, instruction=(f"Tell me plainly I'm falling behind, with the numbers, in two or three short spoken sentences, "
                          f"and what pace fixes it. No drama. {facts}"),
        fallback=facts, mood="firm — a clear nudge", meta={"kind": "lag", "behind": behind})


# ---------- what to do right now ----------

WHAT_NOW = re.compile(r"\bwhat (should|do|can) i (do|work on|study|start)\b|\bwhat now\b|\bwhat next\b|\bwhat'?s next\b", re.I)


def pick_focus(db, minutes: int) -> str | None:
    """The most useful thing that fits: overdue / next TUF topics first, then the ML course."""
    out = []
    budget = minutes
    for key in ("tuf", "ml"):
        c = db.scalar(select(Course).where(Course.key == key))
        if c is None or c.starter:
            continue
        for i in [x for x in courses.items(db, c) if not x.done_at and not x.optional]:
            est = i.est_min or 15
            if est > budget and out:
                break
            out.append(f"{i.title} (~{est} min, {c.title.split(' (')[0]})")
            budget -= est
            if budget <= 0 or len(out) >= 3:
                break
        if out:
            break
    return "; ".join(out) or None


@agent("focus_recommender")
async def focus_recommender(ctx: AgentContext) -> None:
    """Free time, or you ask "what should I do?": the highest-impact thing that fits the time."""
    if ctx.event.type == "user.message" and not WHAT_NOW.search(str(ctx.event.payload.get("text", ""))):
        return
    minutes = int(ctx.event.payload.get("minutes_left") or 60)
    if pick := pick_focus(ctx.db, minutes):
        ctx.notes["focus_pick"] = pick


# ---------- teaching and quizzing what you've studied (spaced repetition) ----------

QUIZ_ME = re.compile(r"\b(quiz|test) me\b|\bask me a question\b|\bquiz time\b", re.I)
EXPLAIN = re.compile(r"^\s*(?:explain|teach me|can you explain)\s+(.{3,100}?)\s*[?.!]*$", re.I)
GIVE_UP = re.compile(r"^\s*(skip|pass|i don'?t know|idk|no idea|give up)\b", re.I)
BOXES = [1, 3, 7, 14, 30]  # days until the next review, by how many times in a row you got it right
QUIZ_TTL_H = 2


def _kv_json(db, key: str, default):
    row = db.get(KeyValue, key)
    return json.loads(row.value) if row and row.value else default


def _kv_put(db, key: str, value) -> None:
    row = db.get(KeyValue, key)
    if value is None:
        if row is not None:
            db.delete(row)
        return
    if row is None:
        db.add(KeyValue(key=key, value=json.dumps(value)))
    else:
        row.value = json.dumps(value)


def next_quiz_item(db, now: datetime):
    """A topic you finished at least a day ago that's due for review (never asked, or its interval is up)."""
    from datetime import timedelta

    from app.db.models import StudyItem

    log = _kv_json(db, "quiz_log", {})
    today = local(now).date().isoformat()
    done = db.scalars(select(StudyItem).where(StudyItem.done_at.is_not(None), StudyItem.done_at <= now - timedelta(hours=20),
                                              StudyItem.optional.is_(False)).order_by(StudyItem.done_at)).all()
    due = [i for i in done if str(i.id) not in log or log[str(i.id)]["next"] <= today]
    due.sort(key=lambda i: (log.get(str(i.id), {}).get("next", "0000"), -(i.done_at.timestamp())))
    return due[0] if due else None


async def _llm_json(system: str, user: str) -> dict | None:
    try:
        return json.loads(await llm.complete([{"role": "system", "content": system}, {"role": "user", "content": user}],
                                             tier="fast", temperature=0.3, max_tokens=400, json_mode=True))
    except (llm.LLMUnavailable, ValueError, TypeError):
        return None


@agent("skill_coach")
async def skill_coach(ctx: AgentContext) -> None:
    """"Quiz me" → one question on a topic due for review; your next message gets graded. "Explain X" → a lesson."""
    from datetime import timedelta

    text = str(ctx.event.payload.get("text", "")).strip()
    if ctx.event.payload.get("button") or not text:
        return
    now = datetime.now(timezone.utc)
    pending = _kv_json(ctx.db, "quiz_pending", None)
    if pending and now - datetime.fromisoformat(pending["at"]) > timedelta(hours=QUIZ_TTL_H):
        pending = None
        _kv_put(ctx.db, "quiz_pending", None)

    if m := EXPLAIN.match(text):
        ctx.notes["coach"] = {"mode": "explain", "topic": m.group(1)}
        return
    if QUIZ_ME.search(text):
        item = next_quiz_item(ctx.db, now)
        if item is None:
            ctx.notes["coach"] = {"mode": "nothing_yet"}
            return
        q = await _llm_json('You write one short interview-style question to check real understanding of a topic a '
                            'student just studied (DSA / CS / ML). JSON only: {"question": string, "key_points": [string]} '
                            "— answerable in 2-3 sentences, no code required.",
                            f"Topic: {item.title} (section: {item.section})") if ctx.settings.llm_available else None
        question = (q or {}).get("question") or f"In two or three sentences: what's the key idea behind “{item.title}”, and its time complexity if it has one?"
        _kv_put(ctx.db, "quiz_pending", {"item_id": item.id, "title": item.title, "question": question,
                                         "key_points": (q or {}).get("key_points") or [], "at": now.isoformat()})
        ctx.notes["coach"] = {"mode": "quiz", "question": question, "topic": item.title}
        return
    if not pending:
        return
    # this message is the answer to the pending question
    gave_up = bool(GIVE_UP.match(text))
    graded = None if gave_up or not ctx.settings.llm_available else await _llm_json(
        'Grade a student\'s spoken answer. JSON only: {"correct": true|false, "feedback": string} — feedback in one or two '
        "sentences: what they got right, and the missing key point. Be fair: the gist counts, wording doesn't.",
        f"Question: {pending['question']}\nKey points: {pending['key_points']}\nAnswer: {text}")
    correct = bool(graded and graded.get("correct")) if graded else (not gave_up and len(text.split()) >= 12)
    log = _kv_json(ctx.db, "quiz_log", {})
    rec = log.get(str(pending["item_id"]), {"box": 0, "hits": 0, "misses": 0})
    rec["box"] = min(rec["box"] + 1, len(BOXES) - 1) if correct else 0
    rec["hits" if correct else "misses"] += 1
    rec["next"] = (local(now).date() + timedelta(days=BOXES[rec["box"]] if correct else 1)).isoformat()
    log[str(pending["item_id"])] = rec
    _kv_put(ctx.db, "quiz_log", log)
    _kv_put(ctx.db, "quiz_pending", None)
    ctx.notes["coach"] = {"mode": "graded", "correct": correct, "gave_up": gave_up, "topic": pending["title"],
                          "question": pending["question"], "key_points": pending["key_points"],
                          "feedback": (graded or {}).get("feedback"), "next": rec["next"]}
