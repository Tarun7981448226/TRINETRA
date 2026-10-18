"""Sentence embeddings that never leave TRINETRA — no API, no GPU, ~8 MB.

The model is minishlab/potion-base-8M (Model2Vec, MIT licence): a static embedding distilled from BAAI/bge-base-en-v1.5.
Each word piece has a fixed 256-d vector; a sentence is the mean of its pieces, normalised. On MTEB it keeps ~92% of
all-MiniLM-L6-v2's quality at a fraction of the cost, which is plenty for "which memories matter right now?".
Stored as int8 with a per-row scale (1% error). The tokenizer is BERT's WordPiece, re-implemented here (lowercase,
strip accents, split punctuation, greedy longest-match with ## continuations) so no `tokenizers` package is needed.
"""
from __future__ import annotations

import re
import unicodedata
from functools import lru_cache
from pathlib import Path

import numpy as np

DIR = Path(__file__).resolve().parents[1] / "data" / "embed"
DIM = 256


@lru_cache(maxsize=1)
def _model() -> tuple[dict[str, int], np.ndarray]:
    vocab = {w: i for i, w in enumerate((DIR / "potion8m_vocab.txt").read_text().split("\n"))}
    q = np.load(DIR / "potion8m_int8.npy")
    scale = np.load(DIR / "potion8m_scale.npy")
    return vocab, q.astype(np.float32) * scale


def _normalise(text: str) -> str:  # BertNormalizer: clean, lowercase, strip accents, space out CJK
    text = "".join(" " if unicodedata.category(c) in ("Cc", "Cf") and c not in "\t\n\r" else c for c in text)
    text = unicodedata.normalize("NFD", text.lower())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"([一-鿿])", r" \1 ", text)


def _is_punct(c: str) -> bool:
    o = ord(c)
    return (33 <= o <= 47) or (58 <= o <= 64) or (91 <= o <= 96) or (123 <= o <= 126) or unicodedata.category(c).startswith("P")


def _words(text: str) -> list[str]:  # BertPreTokenizer: whitespace, and every punctuation mark on its own
    out = []
    for chunk in text.split():
        cur = ""
        for c in chunk:
            if _is_punct(c):
                if cur:
                    out.append(cur)
                out.append(c)
                cur = ""
            else:
                cur += c
        if cur:
            out.append(cur)
    return out


def tokens(text: str) -> list[int]:
    vocab, _ = _model()
    ids = []
    for w in _words(_normalise(text)):
        if len(w) > 100:
            continue
        start, pieces = 0, []
        while start < len(w):
            end, hit = len(w), None
            while start < end:
                piece = ("##" if start else "") + w[start:end]
                if piece in vocab:
                    hit = vocab[piece]
                    break
                end -= 1
            if hit is None:
                pieces = []  # an unknown word is skipped whole, like [UNK] in Model2Vec
                break
            pieces.append(hit)
            start = end
        ids += pieces
    return ids


def embed(texts: list[str]) -> np.ndarray:
    """(n, 256) unit vectors; an all-zero row for text with no known words."""
    _, E = _model()
    out = np.zeros((len(texts), DIM), dtype=np.float32)
    for i, t in enumerate(texts):
        ids = tokens(t)
        if ids:
            v = E[ids].mean(axis=0)
            n = np.linalg.norm(v)
            out[i] = v / n if n else v
    return out


def similarity(query: str, texts: list[str]) -> np.ndarray:
    """Cosine similarity of the query to each text."""
    if not texts:
        return np.zeros(0, dtype=np.float32)
    m = embed([query, *texts])
    return m[1:] @ m[0]
