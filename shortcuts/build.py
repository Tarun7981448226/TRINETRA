"""Build TRINETRA's iOS Shortcuts (.shortcut plists), then sign them with macOS `shortcuts sign`.

    ../.venv/bin/python shortcuts/build.py        → shortcuts/out/*.shortcut (signed, contain your shortcut key)
"""
import plistlib
import re
import subprocess
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://trinetra-tarun.vercel.app"
KEY = re.search(r"^TRINETRA_SHORTCUT_KEY=(.+)$", (ROOT / ".env").read_text(), re.M).group(1).strip()
OUT = Path(__file__).parent / "out"


def uid() -> str:
    return str(uuid.uuid4()).upper()


def action(ident: str, **params) -> dict:
    return {"WFWorkflowActionIdentifier": f"is.workflow.actions.{ident}", "WFWorkflowActionParameters": params}


def out_ref(u: str, name: str) -> dict:
    return {"OutputUUID": u, "Type": "ActionOutput", "OutputName": name}


def attach(ref: dict) -> dict:  # a whole parameter that IS a variable
    return {"Value": ref, "WFSerializationType": "WFTextTokenAttachment"}


def text(*parts) -> dict:  # text with variables mixed in: parts are str or ref dicts
    s, attachments = "", {}
    for p in parts:
        if isinstance(p, str):
            s += p
        else:
            attachments[f"{{{len(s)}, 1}}"] = p
            s += "￼"
    return {"Value": {"string": s, "attachmentsByRange": attachments}, "WFSerializationType": "WFTextTokenString"}


def get(path: str, u: str, *extra) -> dict:
    return action("downloadurl", UUID=u, WFHTTPMethod="GET", WFURL=text(f"{BASE}{path}?key={KEY}", *extra))


def play(ref: dict) -> dict:
    return action("playsound", WFInput=attach(ref))


# Every shortcut is a straight line of fetch / vibrate / play: NO "If" and NO loops. iOS 26 drops the settings of
# control-flow actions in generated shortcuts ("Please choose a value for each parameter"), while these simple
# actions always import intact. All the deciding happens on the server, which sends silence when there's
# nothing to say. The wake-up questions are answered in the app (the 6am notifications open that screen).

def wake_up() -> list:
    speech = uid()
    return [
        action("setvolume", WFVolume=1.0),
        get("/sc/wake/start", uid()),          # counts the ring (06:00, 06:10, 06:20 …)
        action("vibrate"),
        get("/sc/wake/speech", speech),        # shouting until you've answered in the app; then silence
        play(out_ref(speech, "Contents of URL")),
        action("vibrate"),
    ]


def now() -> list:
    n = uid()
    return [
        get("/sc/now", n),                     # "Tarun, it's time…" for the block starting now (or silence)
        action("vibrate"),
        action("setvolume", WFVolume=0.8),
        play(out_ref(n, "Contents of URL")),
    ]


def weekly_report() -> list:
    acts = [action("setvolume", WFVolume=0.7)]
    for part in range(1, 7):                   # six ~5-minute chapters (silence if a chapter isn't there)
        u = uid()
        acts += [get("/sc/report/audio", u, f"&part={part}"), play(out_ref(u, "Contents of URL"))]
    return acts


def shortcut(actions: list, color: int, glyph: int) -> dict:
    return {
        "WFWorkflowActions": actions,
        "WFWorkflowClientVersion": "2605.0.5",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowIcon": {"WFWorkflowIconStartColor": color, "WFWorkflowIconGlyphNumber": glyph},
        "WFWorkflowImportQuestions": [],
        "WFWorkflowInputContentItemClasses": [],
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowTypes": [],
        "WFQuickActionSurfaces": [],
        "WFWorkflowHasShortcutInputVariables": False,
    }


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for name, acts, color in (("Trinetra Wake-Up Call", wake_up(), 4282601983), ("Trinetra Time Check", now(), 4292093695),
                              ("Trinetra Weekly Report", weekly_report(), 463140863)):
        raw = OUT / f"{name}.unsigned.shortcut"
        raw.write_bytes(plistlib.dumps(shortcut(acts, color, 59446), fmt=plistlib.FMT_BINARY))
        signed = OUT / f"{name}.shortcut"
        r = subprocess.run(["shortcuts", "sign", "--mode", "anyone", "--input", str(raw), "--output", str(signed)],
                           capture_output=True, text=True)
        print(name, "→", "signed ✅" if r.returncode == 0 and signed.exists() else f"sign failed: {r.stderr.strip()[:200]}")
        raw.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
