"""TRINETRA's voice (edge-tts, free) and ears (Groq Whisper, free).

Mood changes how it sounds: firm is slower, lower and louder; gentle is slow and soft;
proud is quicker and brighter.
"""
import re

import httpx

from app.config import get_settings

# The mentor's baseline: a touch slower and deeper than stock, so he sounds older and settled.
BASE = (-6, -5, 0)  # rate %, pitch Hz, volume %

# Mood shifts layered on the baseline: (rate %, pitch Hz, volume %)
PROSODY = {
    "angry": (+10, +3, +35),  # full coach: faster, sharper, much louder
    "firm_angry": (+4, 0, +25),
    "annoyed": (-2, -3, +10),  # soft angry: a raised eyebrow
    "firm": (-4, -4, +15),
    "comfort": (-12, -2, -15),  # deepest care: slow and quiet
    "gentle": (-8, -1, -10),
    "concerned": (-5, -1, -5),
    "proud": (+8, +4, +5),
    "upbeat": (+4, +2, +3),
    "focused": (+4, 0, 0),
    "calm": (0, 0, 0),
}


def prosody(mood: str | None) -> tuple[str, str, str]:
    r, p, v = (b + m for b, m in zip(BASE, PROSODY[mood_family(mood)]))
    return f"{r:+d}%", f"{p:+d}Hz", f"{v:+d}%"


def mood_family(mood: str | None) -> str:
    m = (mood or "").lower()
    for family, keys in (
        ("comfort", ("deeply caring", "no pressure at all")),
        ("gentle", ("gentle", "comfort", "no pressure")),
        ("annoyed", ("softly annoyed", "soft angry")),
        ("firm_angry", ("firm and angry",)),
        ("angry", ("angry",)),
        ("firm", ("firm", "disappointed")),
        ("concerned", ("attentive", "concerned")),
        ("proud", ("proud",)),
        ("upbeat", ("upbeat",)),
        ("focused", ("focused", "sharp")),
    ):
        if any(k in m for k in keys):
            return family
    return "calm"


def clean_for_speech(text: str) -> str:
    text = re.sub(r"[*_`#>]+", "", text)
    text = re.sub(r"https?://\S+", "a link", text)
    return re.sub(r"\s+", " ", text).strip()


# Prosody alone can't make a calm voice sound furious. For angry moods the APP applies an audio
# chain (presence boost → drive into soft clipping → hard compression) with the Web Audio API,
# because serverless hosting has no ffmpeg. The server just says which effect to use.
EFFECTS = {"angry", "firm_angry"}


# Half a second of silence (MPEG-1 Layer III, 128 kbps, 44.1 kHz, mono): what a Shortcut plays when there's
# nothing to say, so it never has to check (Shortcuts can't reliably branch — see api/routes.py).
SILENT_MP3 = (bytes([0xFF, 0xFB, 0x90, 0xC4]) + bytes(413)) * 20


def effect_for(mood: str | None) -> str | None:
    family = mood_family(mood)
    return family if family in EFFECTS else None


async def speak(text: str, mood: str | None = None) -> bytes:
    import edge_tts

    rate, pitch, volume = prosody(mood)
    communicate = edge_tts.Communicate(
        clean_for_speech(text), get_settings().trinetra_voice, rate=rate, pitch=pitch, volume=volume
    )
    audio = bytearray()
    async for chunk in communicate.stream():
        if chunk["type"] == "audio":
            audio.extend(chunk["data"])
    return bytes(audio)


class STTUnavailable(RuntimeError):
    pass


# Words Whisper would otherwise mishear (names, courses, tools Tarun talks about).
STT_VOCAB = ("Tarun talking to TRINETRA, his AI mentor, about TUF, Striver, NeetCode, DSA, LeetCode, CSCI 570, "
             "CSCI 585, DBMS, ML Specialization, NumPy, Pandas, dynamic programming, network flows, internship, gym.")
# What Whisper "hears" in silence or background noise.
STT_FIXES = [(r"\bne+a?t ?code\b", "NeetCode"), (r"\bt\.?u\.?f\.?(?=\s|$)", "TUF"), (r"\btri ?netra\b", "TRINETRA")]
SILENCE_HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "thank you for watching", "bye"}


async def transcribe(audio: bytes, filename: str, content_type: str) -> str:
    s = get_settings()
    if not s.groq_api_key:
        raise STTUnavailable("Add GROQ_API_KEY to .env so I can hear you.")
    async with httpx.AsyncClient(timeout=60) as client:
        r = await client.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {s.groq_api_key}"},
            files={"file": (filename, audio, content_type)},
            data={"model": s.groq_stt_model, "response_format": "json", "language": "en", "temperature": "0",
                  "prompt": STT_VOCAB},
        )
    if r.status_code != 200:
        raise STTUnavailable(f"Speech recognition failed ({r.status_code}).")
    text = r.json().get("text", "").strip()
    if text.lower().strip(" .!?") in SILENCE_HALLUCINATIONS:
        return ""
    for wrong, right in STT_FIXES:
        text = re.sub(wrong, right, text, flags=re.I)
    return text
