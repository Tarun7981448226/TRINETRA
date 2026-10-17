"""TRINETRA's Neural Core — a neural network trained only on YOUR life.

It learns P(you actually complete this block) from every planned block you finished or skipped.

The network grows as it learns you. More data supports more neurons without memorising noise:
    < 20 outcomes     → no network yet; a smoothed statistical prior ("instinct")
    20 – 99           → 1 hidden layer:  16 neurons
    100 – 499         → 2 hidden layers: 64 → 32
    500 – 1999        → 3 hidden layers: 128 → 64 → 32
    2000+             → 4 hidden layers: 256 → 128 → 64 → 32
"""
from __future__ import annotations

import json
import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import from_db, local
from app.db.models import KeyValue, Task, TaskStatus

log = logging.getLogger("trinetra.neural")

STORE_KEY = "neural_core"  # weights live in the database (serverless has no disk)
MIN_SAMPLES = 20
CATEGORIES = ["study", "work", "health", "fitness", "personal", "social", "chores", "rest", "general"]
GROWTH = [(2000, (256, 128, 64, 32)), (500, (128, 64, 32)), (100, (64, 32)), (MIN_SAMPLES, (16,))]

FEATURE_NAMES = (
    ["hour_sin", "hour_cos", "duration_h", "priority", "is_weekend", "recent_done_rate", "recent_skip_streak",
     "load_that_day"]
    + [f"dow_{d}" for d in range(7)]
    + [f"cat_{c}" for c in CATEGORIES]
)


def architecture_for(n_samples: int) -> tuple[int, ...] | None:
    for threshold, layers in GROWTH:
        if n_samples >= threshold:
            return layers
    return None


def _history_stats(history: list[Task], before: datetime) -> tuple[float, int]:
    """Done-rate over the 14 days before `before`, and the current run of consecutive skips."""
    window = [t for t in history if before - timedelta(days=14) <= from_db(t.planned_start) < before]
    rate = (sum(t.status == TaskStatus.DONE for t in window) + 1) / (len(window) + 2)  # Laplace-smoothed
    streak = 0
    for t in sorted(window, key=lambda t: t.planned_start, reverse=True):
        if t.status != TaskStatus.SKIPPED:
            break
        streak += 1
    return rate, streak


def features(task: Task, history: list[Task], load: int) -> list[float]:
    start = local(task.planned_start)
    hour = start.hour + start.minute / 60
    duration = (from_db(task.planned_end) - from_db(task.planned_start)).total_seconds() / 3600
    rate, streak = _history_stats(history, from_db(task.planned_start))
    category = task.category if task.category in CATEGORIES else "general"
    return (
        [math.sin(2 * math.pi * hour / 24), math.cos(2 * math.pi * hour / 24), min(duration, 6.0),
         task.priority / 5, float(start.weekday() >= 5), rate, min(streak, 5) / 5, min(load, 12) / 12]
        + [float(start.weekday() == d) for d in range(7)]
        + [float(category == c) for c in CATEGORIES]
    )


def _outcomes(db: Session) -> list[Task]:
    return db.scalars(
        select(Task).where(Task.status.in_([TaskStatus.DONE, TaskStatus.SKIPPED]), Task.category != "sleep")
        .order_by(Task.planned_start)
    ).all()


def _dataset(db: Session) -> tuple[np.ndarray, np.ndarray]:
    done = _outcomes(db)
    loads: dict = {}
    for t in done:
        loads[local(t.planned_start).date()] = loads.get(local(t.planned_start).date(), 0) + 1
    X = [features(t, done, loads[local(t.planned_start).date()]) for t in done]
    y = [int(t.status == TaskStatus.DONE) for t in done]
    return np.array(X, dtype=float), np.array(y, dtype=int)


class MLP:
    """A small feed-forward network in pure numpy: ReLU hidden layers → sigmoid output.

    Trained full-batch with Adam + L2 weight decay. Inputs are standardised with the training
    mean/std, which are stored with the weights so predictions use exactly the same scaling.
    """

    def __init__(self, layers: tuple[int, ...], alpha: float = 1e-2, lr: float = 0.01, epochs: int = 800, seed: int = 7):
        self.layers, self.alpha, self.lr, self.epochs, self.seed = layers, alpha, lr, epochs, seed
        self.W: list[np.ndarray] = []
        self.b: list[np.ndarray] = []
        self.mean = self.std = None

    def _forward(self, X: np.ndarray) -> list[np.ndarray]:
        acts = [X]
        for i, (W, b) in enumerate(zip(self.W, self.b)):
            z = acts[-1] @ W + b
            acts.append(1 / (1 + np.exp(-np.clip(z, -30, 30))) if i == len(self.W) - 1 else np.maximum(z, 0))
        return acts

    def fit(self, X: np.ndarray, y: np.ndarray) -> "MLP":
        rng = np.random.default_rng(self.seed)
        self.mean, self.std = X.mean(axis=0), X.std(axis=0) + 1e-8
        Xs, Y = (X - self.mean) / self.std, y.reshape(-1, 1).astype(float)
        sizes = [X.shape[1], *self.layers, 1]
        self.W = [rng.normal(0, np.sqrt(2 / a), (a, b)) for a, b in zip(sizes, sizes[1:])]  # He init
        self.b = [np.zeros(b) for b in sizes[1:]]
        m = [np.zeros_like(p) for p in self.W + self.b]
        v = [np.zeros_like(p) for p in self.W + self.b]
        n = len(Xs)
        for t in range(1, self.epochs + 1):
            acts = self._forward(Xs)
            delta = (acts[-1] - Y) / n  # gradient of log-loss through the sigmoid
            gW, gb = [], []
            for i in range(len(self.W) - 1, -1, -1):
                gW.insert(0, acts[i].T @ delta + self.alpha * self.W[i] / n)
                gb.insert(0, delta.sum(axis=0))
                if i:
                    delta = (delta @ self.W[i].T) * (acts[i] > 0)
            for j, (p, g) in enumerate(zip(self.W + self.b, gW + gb)):
                m[j] = 0.9 * m[j] + 0.1 * g
                v[j] = 0.999 * v[j] + 0.001 * g * g
                p -= self.lr * (m[j] / (1 - 0.9**t)) / (np.sqrt(v[j] / (1 - 0.999**t)) + 1e-8)
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        return self._forward((np.asarray(X, dtype=float) - self.mean) / self.std)[-1].ravel()

    def to_dict(self) -> dict:
        return {"layers": list(self.layers), "W": [w.tolist() for w in self.W], "b": [b.tolist() for b in self.b],
                "mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, d: dict) -> "MLP":
        net = cls(tuple(d["layers"]))
        net.W = [np.array(w) for w in d["W"]]
        net.b = [np.array(b) for b in d["b"]]
        net.mean, net.std = np.array(d["mean"]), np.array(d["std"])
        return net


def _cv_accuracy(X: np.ndarray, y: np.ndarray, layers: tuple[int, ...], folds: int) -> float:
    """Stratified k-fold accuracy: how well the network predicts days it has never seen."""
    rng = np.random.default_rng(0)
    fold_of = np.empty(len(y), dtype=int)
    for cls in (0, 1):
        idx = rng.permutation(np.flatnonzero(y == cls))
        fold_of[idx] = np.arange(len(idx)) % folds
    scores = []
    for k in range(folds):
        test = fold_of == k
        net = MLP(layers).fit(X[~test], y[~test])
        scores.append(float(((net.predict_proba(X[test]) >= 0.5) == y[test]).mean()))
    return float(np.mean(scores))


@dataclass
class BrainReport:
    samples: int
    layers: tuple[int, ...] | None
    neurons: int
    accuracy: float | None
    trained_at: str | None
    mode: str  # "neural" or "instinct"


def _store(db: Session) -> KeyValue | None:
    return db.get(KeyValue, STORE_KEY)


def train(db: Session) -> BrainReport:
    X, y = _dataset(db)
    layers = architecture_for(len(y))
    if layers is None or len(set(y.tolist())) < 2:
        return BrainReport(len(y), None, 0, None, None, "instinct")
    folds = min(5, int(np.bincount(y).min()))
    accuracy = _cv_accuracy(X, y, layers, folds) if folds >= 2 else None
    net = MLP(layers).fit(X, y)
    trained_at = datetime.now(timezone.utc).isoformat()
    bundle = {"net": net.to_dict(), "samples": len(y), "accuracy": accuracy, "trained_at": trained_at,
              "features": FEATURE_NAMES}
    row = _store(db)
    if row is None:
        db.add(KeyValue(key=STORE_KEY, value=json.dumps(bundle)))
    else:
        row.value = json.dumps(bundle)
    db.flush()
    log.info("neural core trained: %d samples, layers %s, cv accuracy %s", len(y), layers, accuracy)
    return BrainReport(len(y), layers, sum(layers), accuracy, trained_at, "neural")


def _load(db: Session) -> dict | None:
    row = _store(db)
    if not row or not row.value:
        return None
    try:
        bundle = json.loads(row.value)
        return bundle if bundle.get("features") == FEATURE_NAMES else None  # features changed → retrain
    except ValueError:
        return None


def predict(db: Session, task: Task) -> float:
    """Probability (0..1) that you'll actually complete this block."""
    history = _outcomes(db)
    day = local(task.planned_start).date()
    load = sum(1 for t in history if local(t.planned_start).date() == day) + 1
    x = features(task, history, load)
    if bundle := _load(db):
        return float(MLP.from_dict(bundle["net"]).predict_proba(np.array([x]))[0])
    # Instinct (before the network exists): smoothed done-rate for this category, nudged by skip streak.
    same = [t for t in history if t.category == task.category]
    rate = (sum(t.status == TaskStatus.DONE for t in same) + 2) / (len(same) + 3)
    _, streak = _history_stats(history, from_db(task.planned_start))
    return max(0.05, min(0.95, rate - 0.08 * streak))


def report(db: Session) -> BrainReport:
    if bundle := _load(db):
        layers = tuple(bundle["net"]["layers"])
        return BrainReport(bundle["samples"], layers, sum(layers), bundle["accuracy"], bundle["trained_at"], "neural")
    return BrainReport(len(_outcomes(db)), None, 0, None, None, "instinct")
