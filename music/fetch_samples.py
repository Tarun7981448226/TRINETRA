"""Download the instrument samples TRINETRA plays with (run once; the files are kept in the repo).

Source: FluidR3_GM soundfont rendered to MP3 by gleitz/midi-js-soundfonts (CC BY 3.0, see music/README.md).
Only every 4th semitone is kept; the player shifts pitch by up to ±2 semitones in between.

    python music/fetch_samples.py            # skips files that are already there
"""
from __future__ import annotations

import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

BASE = "https://gleitz.github.io/midi-js-soundfonts/FluidR3_GM"
OUT = Path(__file__).resolve().parents[1] / "backend/app/static/music/samples"

# our name → (soundfont instrument, lowest MIDI note, highest MIDI note)
INSTRUMENTS = {
    "guitar": ("acoustic_guitar_steel", 40, 84),
    "electric": ("overdriven_guitar", 40, 84),
    "nylon": ("acoustic_guitar_nylon", 44, 84),   # ukulele plays this, an octave up
    "bass": ("electric_bass_finger", 28, 64),
    "banjo": ("banjo", 48, 84),
    "sitar": ("sitar", 48, 84),
    "violin": ("violin", 56, 96),
    "cello": ("cello", 36, 76),
    "piano": ("acoustic_grand_piano", 36, 96),
    "epiano": ("electric_piano_1", 40, 88),       # chords under the dance song
    "harp": ("orchestral_harp", 36, 96),
    "flute": ("flute", 60, 96),
    "sax": ("alto_sax", 48, 84),
    "trumpet": ("trumpet", 52, 88),
    "xylophone": ("xylophone", 64, 104),
    "lead": ("lead_1_square", 48, 88),           # the dance song's tune
}
NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]


def note_name(m: int) -> str:
    return f"{NAMES[m % 12]}{m // 12 - 1}"


def jobs():
    for ours, (sf, lo, hi) in INSTRUMENTS.items():
        start = lo - lo % 4  # C, E, Ab in every octave
        for m in range(start, hi + 1, 4):
            if m >= lo - 2:
                yield ours, sf, m


def fetch(job) -> str:
    ours, sf, m = job
    dest = OUT / ours / f"{m}.mp3"
    if dest.exists():
        return "skip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(f"{BASE}/{sf}-mp3/{note_name(m)}.mp3", timeout=30) as r:
        dest.write_bytes(r.read())
    return "ok"


if __name__ == "__main__":
    todo = list(jobs())
    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(fetch, todo))
    print(f"{results.count('ok')} downloaded, {results.count('skip')} already there, {len(todo)} samples in {OUT}")
    sys.exit(0)
