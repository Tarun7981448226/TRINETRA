"""Proof of work for the courses you study in order: TUF DSA and the ML Specialization on Coursera.

Each course is a syllabus (sections → items) and a position. A block whose title matches the course
(e.g. "TUF DSA (1/2)") gets a target: the next `per_block` items. At the block's end you tick what you
actually finished and say where you stopped — that's the proof, and TRINETRA reacts to it.
The outlines below are only starters; Tarun replaces them with his exact syllabus (one item per line,
"# Section" headers) and sets where he is.
"""
import re
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.timeutil import from_db, local, user_tz
from app.db.models import Course, StudyItem, Task, TaskStatus

START_DAY = date(2026, 10, 19)  # Monday: the real timetable (and proof of work) starts

STARTERS = {
    "tuf": dict(title="TUF DSA (Striver's A2Z)", block_match=r"\bTUF\b", goal_id=2, target=date(2027, 1, 1), outline="""
# Step 1 · Basics
Things to know + logic building (patterns)
STL / collections, basic maths
Basic recursion + basic hashing
# Step 2 · Sorting
Sorting I (selection, bubble, insertion)
Sorting II (merge, quick, recursive bubble/insertion)
# Step 3 · Arrays
Arrays: easy
Arrays: medium
Arrays: hard
# Step 4 · Binary search
Binary search on 1D arrays
Binary search on answers
Binary search on 2D arrays
# Step 5 · Strings
Strings: basic and medium
# Step 6 · Linked list
Singly linked list
Doubly linked list
Linked list: medium
Linked list: hard
# Step 7 · Recursion
Recursion: strong hold
Recursion: subsequences pattern
Recursion: all combinations (hard)
# Step 8 · Bit manipulation
Bit manipulation: concepts + interview problems
Bit manipulation: advanced maths
# Step 9 · Stack and queues
Stack/queue: learning
Prefix, infix, postfix conversions
Monotonic stack / queue
Stack/queue: implementation problems
# Step 10 · Sliding window + two pointers
Sliding window: medium
Sliding window: hard
# Step 11 · Heaps
Heaps: learning + medium
Heaps: hard
# Step 12 · Greedy
Greedy: easy
Greedy: medium / hard
# Step 13 · Binary trees
Binary trees: traversals
Binary trees: medium
Binary trees: hard
# Step 14 · Binary search trees
BST: concepts + practice
# Step 15 · Graphs
Graphs: learning + BFS/DFS problems
Topological sort
Shortest paths
MST + disjoint set
Graphs: other algorithms
# Step 16 · Dynamic programming
DP: intro + 1D
DP on grids
DP on subsequences
DP on strings
DP on stocks + LIS
Partition DP (MCM) + DP on squares
# Step 17 · Tries
Tries
# Step 18 · Strings (advanced)
Strings: hard problems
"""),
    "ml": dict(title="Machine Learning Specialization (Coursera)", block_match=r"\bML Specialization\b|\bCoursera\b",
               goal_id=1, target=None, outline="""
# Course 1 · Supervised ML: Regression and Classification
Week 1 · Intro to ML, linear regression, gradient descent
Week 2 · Regression with multiple input variables
Week 3 · Classification, logistic regression, regularization
# Course 2 · Advanced Learning Algorithms
Week 1 · Neural networks
Week 2 · Neural network training
Week 3 · Advice for applying machine learning
Week 4 · Decision trees
# Course 3 · Unsupervised Learning, Recommenders, Reinforcement Learning
Week 1 · Clustering + anomaly detection
Week 2 · Recommender systems
Week 3 · Reinforcement learning
"""),
}


def parse_outline(text: str) -> list[tuple[str, str]]:
    """'# Section' headers and one item per line → [(section, item)]."""
    section, out = "", []
    for raw in text.splitlines():
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", raw).strip()
        if not line:
            continue
        if raw.strip().startswith("#"):
            section = line.lstrip("#").strip()[:200]
        else:
            out.append((section, line[:300]))
    return out


def ensure(db: Session) -> None:
    """Create the two courses with their starter outlines, once."""
    if db.scalar(select(func.count()).select_from(Course)):
        return
    from app.db.models import Goal

    monday = datetime.combine(START_DAY, time(0), user_tz()).astimezone(timezone.utc)
    for key, c in STARTERS.items():
        course = Course(key=key, title=c["title"], block_match=c["block_match"], per_block=1, active_from=monday,
                        goal_id=c["goal_id"] if db.get(Goal, c["goal_id"]) else None, starter=True,
                        target_date=datetime.combine(c["target"], time(0), user_tz()).astimezone(timezone.utc)
                        if c["target"] else None)
        db.add(course)
        db.flush()
        set_outline(db, course, c["outline"], starter=True)
    db.flush()


def items(db: Session, course: Course) -> list[StudyItem]:
    return db.scalars(select(StudyItem).where(StudyItem.course_id == course.id).order_by(StudyItem.position)).all()


def set_outline(db: Session, course: Course, text: str, starter: bool = False) -> int:
    """Replace the syllabus. Items you'd already finished (same title) stay finished."""
    done = {i.title.lower(): (i.done_at, i.task_id) for i in items(db, course) if i.done_at}
    for i in items(db, course):
        db.delete(i)
    db.flush()
    rows = parse_outline(text)
    for n, (section, title) in enumerate(rows):
        at, task_id = done.get(title.lower(), (None, None))
        db.add(StudyItem(course_id=course.id, position=n, section=section, title=title, done_at=at, task_id=task_id))
    course.starter = starter
    db.flush()
    return len(rows)


def set_position(db: Session, course: Course, item_id: int) -> None:
    """'I'm here': everything before this item is done, this one and after are not."""
    now = datetime.now(timezone.utc)
    here = db.get(StudyItem, item_id)
    for i in items(db, course):
        if i.position < here.position:
            i.done_at = i.done_at or now
        else:
            i.done_at, i.task_id = None, None
    db.flush()


def course_for(db: Session, task: Task) -> Course | None:
    ensure(db)
    for c in db.scalars(select(Course)).all():
        if re.search(c.block_match, task.title, re.I) and (c.active_from is None or from_db(task.planned_start) >= from_db(c.active_from)):
            return c
    return None


def target(db: Session, task: Task) -> tuple[Course, list[StudyItem]] | None:
    """What this block should get through: what it already finished, then the next items in order (the backlog
    first, since the plan is in date order). Items with time estimates fill the block's minutes; otherwise per_block."""
    c = course_for(db, task)
    if c is None:
        return None
    all_items = items(db, c)
    mine = [i for i in all_items if i.task_id == task.id]
    pool = [i for i in all_items if i.done_at is None and not i.optional]
    if any(i.est_min for i in all_items):
        budget = (from_db(task.planned_end) - from_db(task.planned_start)).total_seconds() / 60
        budget -= sum(i.est_min or 10 for i in mine)
        nxt = []
        for i in pool:
            if budget <= 0 and (nxt or mine):
                break
            nxt.append(i)
            budget -= i.est_min or 10
    else:
        nxt = pool[: max(0, c.per_block - len(mine))]
    return c, sorted(mine + nxt, key=lambda i: i.position)


def import_items(db: Session, course: Course, rows: list[dict]) -> int:
    """Load a course exactly as its own site has it (TUF Planly, Coursera): order, dates, estimates, what's done."""
    keep = {i.title.lower(): i.task_id for i in items(db, course) if i.done_at and i.task_id}
    for i in items(db, course):
        db.delete(i)
    db.flush()
    now = datetime.now(timezone.utc)
    for n, r in enumerate(rows):
        db.add(StudyItem(course_id=course.id, position=n, section=(r.get("section") or "")[:200], title=r["title"][:300],
                         kind=r.get("kind"), est_min=r.get("est_min"), planned_date=r.get("planned_date"),
                         optional=bool(r.get("optional")), done_at=now if r.get("done") else None,
                         task_id=keep.get(r["title"].lower()) if r.get("done") else None))
    course.starter = False
    db.flush()
    return len(rows)


def sprints(all_items: list[StudyItem]) -> list[dict]:
    """'Sprint 2 · Day 3 · …' sections → per-sprint progress (for plans that have sprints)."""
    out: dict[str, dict] = {}
    for i in all_items:
        m = re.match(r"(Sprint \d+)", i.section or "")
        if not m:
            continue
        s = out.setdefault(m.group(1), {"name": m.group(1), "done": 0, "total": 0, "start": i.planned_date,
                                         "end": i.planned_date, "minutes": 0, "subjects": {}})
        s["total"] += 1
        s["done"] += bool(i.done_at)
        s["minutes"] += i.est_min or 0
        s["end"] = max(filter(None, [s["end"], i.planned_date]), default=None)
        s["start"] = min(filter(None, [s["start"], i.planned_date]), default=None)
        s["subjects"][i.kind or "other"] = s["subjects"].get(i.kind or "other", 0) + 1
    return list(out.values())


SUBJECTS = {"dsa": "DSA", "dbms": "DBMS", "computer-networks": "Networks", "operating-system": "OS", "lld": "LLD",
            "oops": "OOPs"}


def rebuild_roadmap(db: Session, course: Course, title: str | None = None) -> int:
    """The course's goal gets one milestone per sprint, in a chain, sized by the plan's own estimates."""
    from app.db.models import Goal, Milestone

    goal = db.get(Goal, course.goal_id) if course.goal_id else None
    if goal is None:
        return 0
    all_items = items(db, course)
    sp = sprints(all_items)
    if not sp:
        return 0
    if title:
        goal.title = title[:200]
    for m in list(goal.milestones):
        db.delete(m)
    db.flush()
    prev = None
    for n, s in enumerate(sp):
        names = [i for i in all_items if (i.section or "").startswith(s["name"] + " ") and (i.kind or "") == "dsa"]
        span = f"{names[0].title} → {names[-1].title}" if names else ""
        subj = ", ".join(SUBJECTS.get(k, k.replace("-", " ")) for k, _ in sorted(s["subjects"].items(), key=lambda kv: -kv[1])[:3])
        due = datetime.combine(date.fromisoformat(s["end"]), time(23, 59), user_tz()).astimezone(timezone.utc) if s["end"] else None
        m = Milestone(goal_id=goal.id, title=f"{s['name']} · {subj}" + (f" ({span})" if span else ""), position=n,
                      due_date=due, effort_hours=round(s["minutes"] / 60, 1), depends_on=[prev] if prev else None,
                      done_at=datetime.now(timezone.utc) if s["done"] == s["total"] else None)
        db.add(m)
        db.flush()
        prev = m.id
    goal.progress = sum(s["done"] for s in sp) / max(1, sum(s["total"] for s in sp))
    db.flush()
    return len(sp)


def blocks_until(db: Session, c: Course, now: datetime) -> int:
    """Roughly how many blocks of this course are left before its target date."""
    if not c.target_date:
        return 0
    ahead = db.scalars(select(Task).where(Task.planned_start > now, Task.status == TaskStatus.PLANNED,
                                          Task.planned_start < now + timedelta(days=14))).all()
    per_2w = sum(1 for t in ahead if re.search(c.block_match, t.title, re.I))
    days = max(0, (from_db(c.target_date) - now).days)
    return round(per_2w * days / 14)


def summary(db: Session, c: Course, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    all_items = items(db, c)
    done = [i for i in all_items if i.done_at]
    left = len(all_items) - len(done)
    nxt = next((i for i in all_items if not i.done_at), None)
    blocks = blocks_until(db, c, now)
    need = round(left / blocks, 2) if blocks else None
    week_ago = now - timedelta(days=7)
    return {
        "id": c.id, "key": c.key, "title": c.title, "starter": c.starter, "per_block": c.per_block,
        "target_date": local(c.target_date).date().isoformat() if c.target_date else None,
        "active_from": local(c.active_from).date().isoformat() if c.active_from else None,
        "total": len(all_items), "done": len(done), "left": left,
        "now_at": {"id": nxt.id, "section": nxt.section, "title": nxt.title} if nxt else None,
        "this_week": sum(1 for i in done if from_db(i.done_at) >= week_ago and i.task_id),
        "blocks_left": blocks, "need_per_block": need,
        "on_pace": None if need is None else c.per_block >= need,
        "items": [{"id": i.id, "section": i.section, "title": i.title, "done": bool(i.done_at), "kind": i.kind,
                   "est_min": i.est_min, "date": i.planned_date} for i in all_items],
        "sprints": sprints(all_items),
        "today": _today(all_items, local(now).date().isoformat()),
        "behind": sum(1 for i in all_items if not i.done_at and not i.optional and i.planned_date
                      and i.planned_date < local(now).date().isoformat()),
    }


def _today(all_items: list[StudyItem], day: str) -> dict | None:
    mine = [i for i in all_items if i.planned_date == day]
    if not mine:
        return None
    return {"date": day, "section": mine[0].section, "done": sum(1 for i in mine if i.done_at), "total": len(mine),
            "minutes": sum(i.est_min or 0 for i in mine)}


def record(db: Session, task: Task, done_ids: list[int], note: str) -> dict:
    """Your proof for a block: what you ticked, where you stopped. Returns how it went."""
    tg = target(db, task)
    if tg is None:
        return {"course": None}
    c, aimed = tg
    now = datetime.now(timezone.utc)
    ticked = set(done_ids)
    for i in items(db, c):
        if i.id in ticked and not i.done_at:
            i.done_at, i.task_id = now, task.id
        elif i.task_id == task.id and i.id not in ticked:  # unticked something from this block
            i.done_at, i.task_id = None, None
    db.flush()
    finished = [i for i in items(db, c) if i.task_id == task.id]
    hit = all(i.task_id == task.id for i in aimed) if aimed else bool(finished)
    outcome = "all" if hit and finished else "some" if finished or note.strip() else "none"
    return {"course": c.key, "outcome": outcome, "finished": [i.title for i in finished],
            "aimed": [i.title for i in aimed], "note": note.strip()[:300],
            "next": (summary(db, c, now)["now_at"] or {}).get("title")}
