"""Teach TRINETRA to make up music: learn melodies and chord progressions from real songs.

Dataset: POP909 (909 pop songs: melody + chords + keys + beats, MIT licence, github.com/music-x-lab/POP909-Dataset).

    # 1. extract the dataset once into a small corpus that lives in the repo (music/corpus.json.gz)
    python music/train.py extract /path/to/POP909-Dataset/POP909      (needs: pip install mido)
    # 2. train the model the app plays from (backend/app/static/music/model.json); no extra packages
    python music/train.py train

What it learns, separately for songs in a major key and in a minor key:
  melody  — which note comes next (pitch relative to the key's home note + length in 16ths),
            from the two notes before it (2nd-order Markov chain, with a 1st-order fallback)
  chords  — which chord comes next (degree in the key + major/minor), from the two before it,
            and how long chords last
The player (static/music.js) walks these chains with the mood's tempo, register and instrument,
so it never plays the same tune twice.
"""
from __future__ import annotations

import bisect
import gzip
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "corpus.json.gz"
MODEL = HERE.parent / "backend/app/static/music/model.json"
PCS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
DURS = [1, 2, 3, 4, 6, 8, 12, 16]  # allowed note lengths in 16ths


def pc(name: str) -> int:
    p = PCS[name[0]]
    for ch in name[1:]:
        p += {"#": 1, "b": -1}.get(ch, 0)
    return p % 12


def snap(d: int) -> int:
    return min(DURS, key=lambda x: (abs(x - d), x))


# ---------- 1. extract ----------
def extract(root: Path) -> None:
    import mido

    songs = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        sid = folder.name
        try:
            beats = [line.split() for line in (folder / "beat_midi.txt").read_text().splitlines() if line.strip()]
            keys = [line.split("\t") for line in (folder / "key_audio.txt").read_text().splitlines() if line.strip()]
            chords = [line.split("\t") for line in (folder / "chord_midi.txt").read_text().splitlines() if line.strip()]
            mid = mido.MidiFile(folder / f"{sid}.mid")
        except (OSError, ValueError, IndexError):
            continue
        bt = [float(b[0]) for b in beats]
        downs = [i for i, b in enumerate(beats) if float(b[2]) == 1.0]
        if len(bt) < 16 or not downs:
            continue
        first = downs[0]

        def at16(t: float) -> int:  # seconds → 16ths since the first downbeat
            i = max(0, min(len(bt) - 2, bisect.bisect_right(bt, t) - 1))
            return round((i + (t - bt[i]) / max(1e-6, bt[i + 1] - bt[i]) - first) * 4)

        def key_at(t: float):
            for s, e, k in keys:
                if float(s) - 2 <= t <= float(e) + 2 and ":" in k:
                    tonic, mode = k.strip().split(":")
                    return pc(tonic), mode[:3]
            return None

        # melody notes (seconds) from the MELODY track
        mel = next((t for t in mid.tracks if t.name.strip().upper() == "MELODY"), None)
        if mel is None:
            continue
        tempo, tick, on, notes = 500000, 0, {}, []
        merged = mido.merge_tracks([mid.tracks[0], mel])
        secs = 0.0
        for msg in merged:
            secs += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)
            if msg.type == "set_tempo":
                tempo = msg.tempo
            elif msg.type == "note_on" and msg.velocity > 0:
                on[msg.note] = secs
            elif msg.type in ("note_off", "note_on") and msg.note in on:
                notes.append((on.pop(msg.note), secs, msg.note))
        notes.sort()
        k0 = key_at(notes[0][0]) if notes else None
        if not notes or not k0:
            continue
        out, last = [], None
        for s, e, p in notes:
            k = key_at(s) or k0
            a, b = at16(s), at16(e)
            if a < 0 or (last is not None and a <= last[0]):
                continue  # one note at a time: the first one wins
            out.append([a, max(1, b - a), p - (60 + k[0]), k[1]])
            last = out[-1]
        chs = []
        for s, e, lab in chords:
            if lab == "N" or ":" not in lab:
                continue
            k = key_at(float(s)) or k0
            root_name, qual = lab.split(":")
            q = "m" if qual.startswith("min") else "d" if qual.startswith("dim") else "M"
            a, b = at16(float(s)), at16(float(e))
            if a >= 0 and b > a:
                chs.append([a, b - a, (pc(root_name.split("/")[0]) - k[0]) % 12, q, k[1]])
        songs.append({"id": sid, "mode": k0[1], "notes": out, "chords": chs})
    with gzip.open(CORPUS, "wt") as f:
        json.dump({"source": "POP909 (MIT) — github.com/music-x-lab/POP909-Dataset", "songs": songs}, f, separators=(",", ":"))
    print(f"extracted {len(songs)} songs, {sum(len(s['notes']) for s in songs)} notes → {CORPUS}")


# ---------- 2. train ----------
def train() -> None:
    with gzip.open(CORPUS, "rt") as f:
        songs = json.load(f)["songs"]
    mel2 = {m: defaultdict(Counter) for m in ("maj", "min")}
    mel1 = {m: defaultdict(Counter) for m in ("maj", "min")}
    starts = {m: Counter() for m in ("maj", "min")}
    ch2 = {m: defaultdict(Counter) for m in ("maj", "min")}
    ch1 = {m: defaultdict(Counter) for m in ("maj", "min")}
    chlen = {m: Counter() for m in ("maj", "min")}
    count = Counter()
    for song in songs:
        # melody → tokens "pitch,len" (pitch = semitones from the key's home note; "r" = a rest), cut into phrases at long rests
        phrases, cur, prev_end, mode = [], [], None, song["mode"]
        for a, d, p, m in song["notes"]:
            mode = m
            if not -14 <= p <= 26:
                continue
            gap = a - prev_end if prev_end is not None else 0
            if gap >= 16 and cur:
                phrases.append((mode, cur)); cur = []
            elif gap >= 2 and cur:
                cur.append(f"r,{snap(min(gap, 8))}")
            cur.append(f"{p},{snap(min(d, 16))}")
            prev_end = a + d
        if cur:
            phrases.append((mode, cur))
        for mode, ph in phrases:
            if len(ph) < 4 or mode not in mel2:
                continue
            count[mode] += 1
            seq = ["^", "^"] + ph + ["$"]
            starts[mode][ph[0]] += 1
            for i in range(2, len(seq)):
                mel2[mode][f"{seq[i - 2]} {seq[i - 1]}"][seq[i]] += 1
                mel1[mode][seq[i - 1]][seq[i]] += 1
        # chords → tokens "degree+quality" (0M = I, 9m = vi …), repeats merged
        seq, last = [], None
        for a, d, deg, q, m in song["chords"]:
            tok = f"{deg}{q}"
            if m not in ch2:
                continue
            if tok == last:
                continue
            seq.append((m, tok)); last = tok
            chlen[m][min(32, max(4, round(d / 4) * 4))] += 1
        toks = [t for _, t in seq]
        mode = song["mode"] if song["mode"] in ch2 else "maj"
        for i in range(2, len(toks)):
            ch2[mode][f"{toks[i - 2]} {toks[i - 1]}"][toks[i]] += 1
        for i in range(1, len(toks)):
            ch1[mode][toks[i - 1]][toks[i]] += 1

    def pack(table: dict, keep: int, floor: int) -> dict:  # state → [[next, count], …], small and pruned
        out = {}
        for state, nxt in table.items():
            items = [[k, v] for k, v in nxt.most_common(keep) if v >= floor]
            if items and sum(v for _, v in items) >= floor * 2:
                out[state] = items
        return out

    model = {
        "about": "Trained by music/train.py on POP909 (909 pop songs, MIT). Tokens: 'pitch,len' — pitch in semitones "
                 "from the key's home note ('r' = rest), len in 16th notes; chords are 'degree+M/m/d'.",
        "phrases": dict(count),
        "melody": {m: {"o2": pack(mel2[m], 10, 2), "o1": pack(mel1[m], 16, 1), "start": starts[m].most_common(24)} for m in mel2},
        "chords": {m: {"o2": pack(ch2[m], 8, 2), "o1": pack(ch1[m], 10, 1), "len": chlen[m].most_common()} for m in ch2},
    }
    MODEL.parent.mkdir(parents=True, exist_ok=True)
    MODEL.write_text(json.dumps(model, separators=(",", ":")))
    print(f"trained on {dict(count)} phrases → {MODEL} ({MODEL.stat().st_size // 1024} KB); "
          f"melody states maj {len(model['melody']['maj']['o2'])}, min {len(model['melody']['min']['o2'])}")


if __name__ == "__main__":
    if sys.argv[1:2] == ["extract"]:
        extract(Path(sys.argv[2]))
    elif sys.argv[1:2] == ["train"]:
        train()
    else:
        print(__doc__)
