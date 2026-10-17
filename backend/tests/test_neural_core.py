import asyncio
import random
from datetime import date, time, timedelta

import pytest

from app.core import scheduler, timetable
from app.core.timeutil import local
from app.db.models import Task, TaskStatus
from app.ml import neural_core


def _life(db, days=60, seed=1):
    """Synthetic Tarun: does morning study ~90% of the time, skips late-night study ~80% of the time."""
    rng = random.Random(seed)
    start = date(2026, 6, 1)
    for i in range(days):
        d = start + timedelta(days=i)
        [m] = timetable.create_block(db, "Morning DSA", d, time(7), time(8), category="study")
        [n] = timetable.create_block(db, "Night DSA", d, time(23), time(23, 59), category="study")
        m.status = TaskStatus.DONE if rng.random() < 0.9 else TaskStatus.SKIPPED
        n.status = TaskStatus.DONE if rng.random() < 0.2 else TaskStatus.SKIPPED
    db.commit()


def test_architecture_grows_with_data():
    assert neural_core.architecture_for(5) is None
    assert neural_core.architecture_for(20) == (16,)
    assert neural_core.architecture_for(150) == (64, 32)
    assert neural_core.architecture_for(800) == (128, 64, 32)
    assert neural_core.architecture_for(5000) == (256, 128, 64, 32)


def test_instinct_before_enough_data(client):
    with client.session_factory() as db:
        _life(db, days=5)
        r = neural_core.train(db)
        assert r.mode == "instinct" and r.layers is None
        [t] = timetable.create_block(db, "Night DSA", date(2026, 7, 1), time(23), time(23, 59), category="study")
        assert 0.05 <= neural_core.predict(db, t) <= 0.95


def test_network_learns_when_you_follow_through(client):
    with client.session_factory() as db:
        _life(db, days=60)
        r = neural_core.train(db)
        assert r.mode == "neural" and r.layers == (64, 32) and r.samples == 120
        assert r.accuracy is not None and r.accuracy > 0.7
        [morning] = timetable.create_block(db, "Morning DSA", date(2026, 8, 3), time(7), time(8), category="study")
        [night] = timetable.create_block(db, "Night DSA", date(2026, 8, 3), time(23), time(23, 59), category="study")
        assert neural_core.predict(db, morning) > 0.7
        assert neural_core.predict(db, night) < 0.4


def test_brain_endpoint_reports_layers(client):
    with client.session_factory() as db:
        _life(db, days=30)
    body = client.post("/brain/train").json()
    assert body["layers"] == [16] or body["layers"] == (16,)
    brain = client.get("/brain").json()
    assert [l["name"] for l in brain["layers"]][:2] == ["Perception", "Emotion"]
    assert brain["neural_core"]["neurons"] == 16
    assert brain["neural_core"]["next_growth"] == {"at_samples": 100, "layers": [64, 32]}


def test_risky_block_makes_reminder_more_persuasive(client, llm_calls):
    from datetime import datetime, timezone

    with client.session_factory() as db:
        _life(db, days=60)
        neural_core.train(db)
        [t] = timetable.create_block(db, "Night DSA", date(2026, 8, 3), time(23), time(23, 59), category="study")
        db.commit()
        when = local(t.planned_start).astimezone(timezone.utc) - timedelta(minutes=3)
        asyncio.run(scheduler.tick(db, client.app.state.orchestrator, when))
    prompt = llm_calls[-1]["messages"][-1]["content"]
    assert "neural core says there's only a" in prompt


def test_nightly_retrains_once_a_day(client, llm_calls, monkeypatch):
    from datetime import datetime

    from app.core import scheduler as sch
    from app.core.timeutil import user_tz

    monkeypatch.setattr(sch, "now_local", lambda: datetime(2026, 8, 3, 4, 0, tzinfo=user_tz()))
    with client.session_factory() as db:
        _life(db, days=30)
        core = client.app.state.orchestrator
        assert asyncio.run(sch.nightly(db, core)) is True
        assert asyncio.run(sch.nightly(db, core)) is False
        db.commit()
        assert neural_core.report(db).mode == "neural"


def test_mlp_round_trips_through_json():
    import numpy as np
    rng = np.random.default_rng(3)
    X = rng.normal(size=(80, 5))
    y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(int)
    net = neural_core.MLP((16,)).fit(X, y)
    clone = neural_core.MLP.from_dict(net.to_dict())
    assert np.allclose(net.predict_proba(X), clone.predict_proba(X))
    assert ((net.predict_proba(X) >= 0.5) == y).mean() > 0.9
