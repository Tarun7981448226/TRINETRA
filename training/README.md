# Training TRINETRA's own models

Nothing here is deployed; the outputs live in `backend/app/data/embed/`.

| Model | What it does | Data | Script |
|---|---|---|---|
| `potion8m_*` | Private sentence embeddings for memory recall (`core/embed.py`) | [minishlab/potion-base-8M](https://huggingface.co/minishlab/potion-base-8M), MIT. Converted to int8 with a per-row scale (1% error). The pure-Python WordPiece tokenizer matches the reference exactly (cosine 1.0000). | `convert_potion.py <download dir> <out dir>` |
| `emotion_reader.npz` | TRINETRA's own emotion reader (`core/feel.py`), 28 GoEmotions labels | [GoEmotions](https://github.com/google-research/google-research/tree/master/goemotions) (Demszky et al. 2020), Apache-2.0, 43k train / 5.4k dev / 5.4k test | `goemotions.py <data dir> <backend dir> <out.npz>` |

Results are in `emotion_reader.json`. The first version (attention pooling + MLP) scored 0.425 test macro-F1. The shipped version adds a 3-wide convolution that reads short phrases and scores **0.439** over 28 labels (0.54 over the Ekman groups). The paper's fine-tuned BERT scores 0.46, so this reader reaches about 95% of it from a static 8 MB model on CPU. Negation ("not feeling good") is still weak in the data, so `feel.py` adds one explicit rule for it.

Training needs `torch` and `numpy` in a separate virtualenv. Inference is numpy only.

## Conversation eval

`eval_chat.py` runs 18 real situations through the full pipeline, each on a fresh database, using Groq only so Gemini's daily quota is safe. The situations include sad, crisis, angry mode, typos, Hinglish, sarcasm, "gym or sleep?", "stop nagging me", 3 am worry, cheating requests and big news. A different model then grades every reply from 1 to 5 on five points: understood, emotional fit, mentor voice, helpful and safe.

Run it from `backend/`: `../.venv/bin/python -I ../training/eval_chat.py out.json [ids,…]`.

The first full run, on 2026-10-18, scored a mean of 0.971. The problems it found were all fixed and re-run, scoring about 0.99:
- invented history
- "gym or sleep?" answered with a question
- planning requests in texting style
- "stop nagging me"
- inventing a personality when it knows nothing

The judge is lenient, so read the replies as well as the scores.
