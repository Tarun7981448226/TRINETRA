from datetime import date, time, timedelta

from app.core import roadmap, timetable
from app.core.timeutil import now_local
from app.db.models import Goal, Milestone, Task, TaskStatus


def _goal(db, efforts, target_days=60):
    g = Goal(title="DSA", target_date=None)
    for i, (t, h) in enumerate(efforts):
        g.milestones.append(Milestone(title=t, position=i, effort_hours=h))
    db.add(g)
    db.flush()
    return g


def test_forecast_walks_topics_through_the_study_blocks(client):
    tomorrow = now_local().date() + timedelta(days=1)
    with client.session_factory() as db:
        g = _goal(db, [("Arrays", 4), ("Two Pointers", 3), ("Stack", 2)])
        timetable.create_block(db, "TUF", tomorrow, time(8), time(10), recurrence="daily", goal_id=g.id)
        f = roadmap.forecast(db, g)
        ms = {m.title: f["milestones"][m.id] for m in g.milestones}
        assert ms["Arrays"]["start"] == tomorrow.isoformat()
        assert ms["Arrays"]["finish"] == (tomorrow + timedelta(days=1)).isoformat()  # 4h at 2h/day
        assert ms["Two Pointers"]["finish"] == (tomorrow + timedelta(days=3)).isoformat()  # shares day 3
        assert f["finish"] == (tomorrow + timedelta(days=4)).isoformat()
        assert f["hours_per_week"] >= 12 and f["sprints"]


def test_routines_are_projected_past_the_rows_that_exist(client):
    tomorrow = now_local().date() + timedelta(days=1)
    with client.session_factory() as db:
        g = _goal(db, [("Big topic", 2 * 40)])  # needs 40 days of 2h blocks; only 14 days of rows exist
        timetable.create_block(db, "TUF", tomorrow, time(8), time(10), recurrence="daily", goal_id=g.id)
        f = roadmap.forecast(db, g)
        assert f["finish"] == (tomorrow + timedelta(days=39)).isoformat()


def test_done_topics_and_logged_hours_count(client):
    tomorrow = now_local().date() + timedelta(days=1)
    with client.session_factory() as db:
        g = _goal(db, [("A", 2), ("B", 4)])
        timetable.create_block(db, "TUF", tomorrow, time(8), time(10), recurrence="daily", goal_id=g.id)
        past = timetable.create_block(db, "TUF", now_local().date() - timedelta(days=1), time(8), time(10), goal_id=g.id)
        past[0].status = TaskStatus.DONE  # 2h already studied → A is effectively covered
        f = roadmap.forecast(db, g)
        b = next(m for m in g.milestones if m.title == "B")
        assert f["milestones"][b.id]["finish"] == (tomorrow + timedelta(days=1)).isoformat()


def test_milestone_undo_and_forecast_in_api(client):
    tomorrow = now_local().date() + timedelta(days=1)
    with client.session_factory() as db:
        g = _goal(db, [("A", 2), ("B", 2)])
        timetable.create_block(db, "TUF", tomorrow, time(8), time(10), recurrence="daily", goal_id=g.id)
        db.commit()
        mid = g.milestones[0].id
    assert client.patch(f"/milestones/{mid}", json={"done": True}).json()["forecast"]["milestones"][str(mid)]["status"] == "done"
    goal = client.patch(f"/milestones/{mid}", json={"done": False}).json()
    assert goal["progress"] == 0 and not goal["milestones"][0]["done"]
    assert goal["forecast"]["milestones"][str(mid)]["finish"] == tomorrow.isoformat()


def test_rebaseline_sets_due_dates(client):
    tomorrow = now_local().date() + timedelta(days=1)
    with client.session_factory() as db:
        g = _goal(db, [("A", 2), ("B", 2)])
        timetable.create_block(db, "TUF", tomorrow, time(8), time(10), recurrence="daily", goal_id=g.id)
        assert roadmap.rebaseline(db, g) == 2
        from app.core.timeutil import local
        assert [local(m.due_date).date() for m in g.milestones] == [tomorrow, tomorrow + timedelta(days=1)]
