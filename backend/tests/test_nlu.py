"""Understanding what people type to the character: every phrasing we know of, every single-letter typo of every keyword,
and everyday sentences that must NOT trigger a show (core/show.py)."""
import collections

import pytest

from app.core.show import label, understand

def typos(w):
    out = set()
    for i in range(1, len(w)):            # drop a letter (keep the first)
        out.add(w[:i] + w[i+1:])
    for i in range(len(w) - 1):           # swap neighbours
        out.add(w[:i] + w[i+1] + w[i] + w[i+2:])
    for i in range(len(w)):               # double a letter
        out.add(w[:i] + w[i] + w[i:])
    vowels = "aeiou"
    for i, c in enumerate(w[1:], 1):      # wrong vowel
        if c in vowels:
            for v in vowels:
                if v != c: out.add(w[:i] + v + w[i+1:])
    out.discard(w)
    return sorted(out)

INST = {"guitar": "guitar", "piano": "piano", "violin": "violin", "drums": "drums", "flute": "flute", "trumpet": "trumpet",
        "saxophone": "sax", "ukulele": "ukulele", "cello": "cello", "harp": "harp", "xylophone": "xylophone", "banjo": "banjo", "sitar": "sitar", "bass": "bass"}
EMO = {"happy": "happy", "angry": "angry", "sad": "sad", "excited": "excited", "proud": "proud", "shy": "shy", "surprised": "surprised",
       "sleepy": "sleepy", "caring": "caring", "serious": "firm", "furious": "angry", "embarrassed": "shy"}
ACT = {"jump": "jump", "spin": "spin", "wave": "wave", "laugh": "laugh", "sleep": "sleep", "backflip": "spin", "giggle": "laugh"}
cases = []
for w, want in INST.items():
    for t in [w] + typos(w):
        for tpl in ["play {}", "can you play the {}", "pls play ur {}", "play {} for me"]:
            cases.append(("inst", tpl.format(t), lambda r, want=want: r and r["show"] == "play" and r["instrument"] == want))
for w, want in EMO.items():
    for t in [w] + typos(w):
        for tpl in ["show me {}", "make a {} face", "be {}", "show ur {} face pls"]:
            cases.append(("emo", tpl.format(t), lambda r, want=want: r and r["show"] == "emotion" and r["emotions"] == [want]))
for w, want in ACT.items():
    for t in [w] + typos(w):
        for tpl in ["{}", "can you {}", "{} pls", "do a {}" if w == "backflip" else "{} now"]:
            cases.append(("act", tpl.format(t), lambda r, want=want: r and r["show"] == "act" and r["action"] == want))
for t in ["dance"] + typos("dance"):
    for tpl in ["{}", "lets {}", "can u {}", "{} alone"]:
        cases.append(("dance", tpl.format(t), lambda r: r and r["show"] == "dance"))
NEG = ["where are my keys", "i play guitar", "i'm sad today", "i am so angry at my boss", "does tarun play the piano?", "do you like music",
       "i need to stop procrastinating", "tell me a joke", "what is your name", "who is tarun", "how are you", "you look sad",
       "are you happy", "i love dancing", "my sister plays violin", "roll the dice", "i went to a dance class", "he is a good drummer",
       "can you help me with my resume", "what projects has tarun built", "i'm tired", "i jumped today", "don't dance", "please don't play music",
       "never stop learning", "make me happy", "is tarun shy?", "what's the weather", "i feel excited about the job", "my keys are lost",
       "the drums in this song are great", "how do you feel", "say hi to my mom", "what does tarun do", "i am bored", "sleep is important",
       "we danced at the party", "she plays the flute", "they were furious", "tarun is happy", "good night", "nice to meet you",
       # found by review: names, feelings and distress must reach TRINETRA's real reply
       "Sam", "Joy", "Max", "sad", "so sad", "tired", "sad. i give up on life", "i feel hopeless", "I love you", "wow", "cute",
       "surprise me", "be serious for a moment", "show me happy hour spots", "give me some love advice", "sleep at 11", "nap time",
       "salsa recipe", "disco ball", "groove is in the heart", "show me the keys", "all your instruments are amazing",
       "play everything on my list", "what can you do for my career", "line up my blocks for tomorrow", "gym at 6am every weekday",
       "be angry with me", "angry mode", "show me your angry version", "lol", "time to sleep", "dance like nobody is watching is my motto"]
for t in NEG:
    cases.append(("none", t, lambda r: r is None))



def test_typos_and_phrasings_land_right():
    by = collections.defaultdict(lambda: [0, 0]); misses = []
    for kind, text, ok in cases:
        good = bool(ok(understand(text, lab=True)))
        by[kind][0] += good; by[kind][1] += 1
        if not good: misses.append((kind, text))
    assert by["none"][0] == by["none"][1], [t for k, t in misses if k == "none"]  # normal chat is never hijacked
    for kind in ("inst", "emo", "act", "dance"):
        g, n = by[kind]
        assert g / n >= 0.97, (kind, g, n, [t for k, t in misses if k == kind][:20])


@pytest.mark.parametrize("text,want", [
    ("play all the instruments", {"show": "play", "instrument": "all"}),
    ("pls play all ur instrumnts", {"show": "play", "instrument": "all"}),
    ("play every instrument", {"show": "play", "instrument": "all"}),
    ("play gituar and pianoo", {"show": "play", "instrument": ["guitar", "piano"]}),
    ("play guitar then drums then piano", {"show": "play", "instrument": ["guitar", "drums", "piano"]}),
    ("play the base guitar", {"show": "play", "instrument": "bass"}),
    ("play a sad song on piano", {"show": "play", "instrument": "piano", "mood": "sad"}),
    ("play something chill", {"show": "play", "instrument": None, "mood": "caring"}),
    ("sing a song", {"show": "play", "instrument": None}),
    ("dance alone", {"show": "dance", "partner": False, "seconds": 10}),
    ("dance solo for 30 sec", {"show": "dance", "partner": False, "seconds": 30}),
    ("dance with your girlfriend", {"show": "dance", "partner": True}),
    ("dance forever", {"show": "dance", "seconds": 0}),
    ("i want to see you dance", {"show": "dance"}),
    ("bust a move", {"show": "dance"}),
    ("jump and spin", {"show": "act", "actions": ["jump", "spin"]}),
    ("can u do a backflip", {"show": "act", "action": "spin"}),
    ("take a nap", {"show": "act", "action": "sleep"}),
    ("say hi", {"show": "act", "action": "wave"}),
    ("show me angery then hapy", {"show": "emotion", "emotions": ["angry", "happy"]}),
    ("how do you look when you are angry", {"show": "emotion", "emotions": ["angry"]}),
    ("what emotions can you show", {"show": "emotion"}),
    ("stopppp", {"show": "stop"}),
    ("ok enough", {"show": "stop"}),
    ("what can you do", {"show": "abilities"}),
    ("asemble", {"show": "lab", "cmd": "assemble"}),
    ("what does each agent do", {"show": "lab", "cmd": "roles"}),
    ("how does ur brain work", {"show": "lab", "cmd": "how"}),
    ("avengers assemble", {"show": "lab", "cmd": "assemble"}),
    ("back to work", {"show": "lab", "cmd": "work"}),
    ("jmp and spin", {"show": "act", "actions": ["jump", "spin"]}),
    ("jump twice", {"show": "act", "actions": ["jump", "jump"]}),
    ("spin 3 times", {"show": "act", "actions": ["spin", "spin", "spin"]}),
    ("dance for half a minute", {"show": "dance", "seconds": 30}),
    ("play heavy metal", {"show": "play", "instrument": "electric"}),
    ("play a lullaby", {"show": "play", "instrument": "harp"}),
    ("play them all", {"show": "play", "instrument": "all"}),
    ("play giyuar", {"show": "play", "instrument": "guitar"}),
    ("wat can u do", {"show": "abilities"}),
    ("🎸🎸", {"show": "play", "instrument": "guitar"}),
    ("angry face", {"show": "emotion", "emotions": ["angry"]}),
])
def test_phrasings(text, want):
    got = understand(text, lab=True)
    assert got is not None, text
    for k, v in want.items():
        assert got.get(k) == v, (text, got)


def test_labels():
    assert label({"show": "play", "instrument": "all"}) == "🎶 All 15 instruments"
    assert label({"show": "play", "instrument": ["guitar", "piano"]}) == "🎸 Guitar → 🎹 Piano"
    assert label({"show": "dance", "partner": False, "seconds": 30}) == "💃 Dance solo · 30 s"
    assert label({"show": "dance", "partner": True, "seconds": 0}) == "💃 Dance · until you say stop"
    assert label({"show": "act", "action": "jump", "actions": ["jump", "spin"]}) == "🦘 Jump → 🌀 Spin"
    assert label({"show": "emotion", "emotions": ["angry", "happy"]}) == "😠 Angry · 😊 Happy"
    assert "15 instruments" in label({"show": "abilities"})


def test_guest_chat_gets_the_show(client):
    """The portfolio chat returns the plan the character performs."""
    tok = client.post("/guest/hello", json={}).json()["token"]
    client.post("/guest/chat", json={"token": tok, "text": "Max"})
    d = client.post("/guest/chat", json={"token": tok, "text": "play all the instruments"}).json()
    assert d["show"]["instrument"] == "all" and d["reply"] == "🎶 All 15 instruments"
    d = client.post("/guest/chat", json={"token": tok, "text": "dance alone"}).json()
    assert d["show"]["partner"] is False and d["reply"] == "💃 Dance solo"
    d = client.post("/guest/chat", json={"token": tok, "text": "show me angery"}).json()
    assert d["perform"] == ["angry"] and d["reply"] == "😠 Angry"


def test_planning_intent_survives_texting_style(client, llm_calls):
    for t in ("cn u mve my gym to 7pm tmrw", "pls shift my dsa to 9", "cancel gym tmrw", "resched my run 2nite"):
        assert client.post("/chat", json={"text": t}).json()["notes"]["intent"] == "planning", t
