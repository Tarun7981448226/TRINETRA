"""TRINETRA's own emotion reader — trained, not prompted. Runs locally in numpy: no API call, nothing leaves the server.

Trained on GoEmotions (Demszky et al., 2020; 58k Reddit comments, 27 emotions + neutral; Apache-2.0) over the frozen
potion-base-8M word-piece vectors (core/embed.py). The network: each word piece gets a learned importance and a learned
attention score (so "exhausted" outweighs "the"), an optional 3-wide convolution reads short phrases ("not that good"),
attention-pooled + mean-pooled → 384-unit GELU layer → 28 sigmoid outputs, each with its own threshold tuned on the
dev split. Test macro-F1 is reported in the training notes (music/README-style: see /static/… or app/data/embed/*.json).
Training script: training/goemotions.py.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from app.core import embed

MODEL = Path(__file__).resolve().parents[1] / "data" / "embed" / "emotion_reader.npz"

# The 28 labels → the feelings TRINETRA's Emotion Engine cares about (Ekman's grouping from the GoEmotions paper).
GROUPS = {
    "anger": ["anger", "annoyance", "disapproval", "disgust"],
    "fear": ["fear", "nervousness"],
    "sadness": ["sadness", "disappointment", "embarrassment", "grief", "remorse"],
    "joy": ["joy", "amusement", "excitement", "gratitude", "love", "optimism", "relief", "pride", "admiration", "approval",
            "caring", "desire"],
    "surprise": ["surprise", "realization", "confusion", "curiosity"],
    "neutral": ["neutral"],
}
# What a mentor should soften for: real sadness, grief, fear. Disappointment alone ("I skipped the gym") is not it —
# that moment wants a firm, kind push, not comfort.
LOW_LABELS = {"sadness", "grief", "fear", "nervousness", "remorse"}


@lru_cache(maxsize=1)
def _model() -> dict:
    z = np.load(MODEL)
    return {k: z[k] for k in z.files}


def _gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1 + np.tanh(0.7978845608 * (x + 0.044715 * x ** 3)))


def scores(text: str) -> dict[str, float]:
    """Each of the 28 emotions → its probability divided by its own threshold (≥ 1 means "present")."""
    m = _model()
    labels = [str(x) for x in m["labels"]]
    ids = embed.tokens(text)[:64]
    if not ids:
        return {"neutral": 1.0}
    _, E = embed._model()
    e = E[ids]
    if "conv_w" in m:  # (out, in, 3) over the sequence, zero-padded both ends
        W, b = m["conv_w"], m["conv_b"]
        p = np.vstack([np.zeros((1, e.shape[1]), e.dtype), e, np.zeros((1, e.shape[1]), e.dtype)])
        c = sum(p[k:k + len(ids)] @ W[:, :, k].T for k in range(3)) + b
        e = e + _gelu(c)
    a = e @ m["q"] + m["tw"].astype(np.float32)[ids]
    a = np.exp(a - a.max())
    att = a / a.sum()
    x = np.concatenate([(e * att[:, None]).sum(0), e.mean(0)]) * 10
    h = _gelu(x @ m["W1"] + m["b1"])
    prob = 1 / (1 + np.exp(-(h @ m["W2"] + m["b2"])))
    return {l: float(p / t) for l, p, t in zip(labels, prob, m["th"])}


def read(text: str) -> dict:
    """{"emotions": [present labels, strongest first], "group": main feeling, "low": bool, "strength": 0..1+}."""
    s = scores(text)
    present = sorted((l for l, v in s.items() if v >= 1 and l != "neutral"), key=lambda l: -s[l])
    groups = {g: max(s.get(l, 0) for l in ls) for g, ls in GROUPS.items()}
    main = max((g for g in groups if g != "neutral"), key=lambda g: groups[g])
    if groups[main] < 1:
        main = "neutral"
    low = any(l in LOW_LABELS for l in present)
    return {"emotions": present[:3], "group": main, "low": low, "strength": round(groups[main], 2)}
