# Training TRINETRA's own models

Nothing here is deployed; the outputs live in `backend/app/data/embed/`.

| Model | What it does | Data | Script |
|---|---|---|---|
| `potion8m_*` | Private sentence embeddings for memory recall (`core/embed.py`) | [minishlab/potion-base-8M](https://huggingface.co/minishlab/potion-base-8M), MIT. Converted to int8 with a per-row scale (1% error). The pure-Python WordPiece tokenizer matches the reference exactly (cosine 1.0000). | `convert_potion.py <download dir> <out dir>` |
| `emotion_reader.npz` | TRINETRA's own emotion reader (`core/feel.py`), 28 GoEmotions labels | [GoEmotions](https://github.com/google-research/google-research/tree/master/goemotions) (Demszky et al. 2020), Apache-2.0, 43k train / 5.4k dev / 5.4k test | `goemotions.py <data dir> <backend dir> <out.npz>` |

Results are in `emotion_reader.json`: test macro-F1 0.425 over 28 labels and 0.53 over the Ekman groups. The paper's fine-tuned BERT scores 0.46, so this reader reaches about 92% of it from a static 8 MB model on CPU.

Training needs `torch` and `numpy` in a separate virtualenv. Inference is numpy only.
