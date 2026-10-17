"""The guided tour of tarundeepreddy.com that TRINETRA gives visitors.

Each stop says where to go on the page (the widget scrolls / opens it), ~10 seconds of narration, two pictures from
the site, and for systems a flow diagram: each step as [icon, what happens]. Never code, keys or internals.
`page` / `target` / `click` must match the site's paths and selectors; picture paths are the site's own
("/images/…"), or "trinetra:/…" for files served by TRINETRA. Edit freely when the portfolio changes.
"""

OPEN_PROJECT = '[data-open-project="{i}"]'
CLOSE_PROJECT = '[data-expanded]:not([hidden]) [data-back]'  # back to the card fan before opening the next one

STOPS = [
    {"page": "/home", "target": "#top", "title": "Welcome",
     "images": ["/images/tarun-portrait.webp", "/images/tarun-graduation.webp"],
     "text": "Welcome. This is Tarun Deep Reddy, a Computer Science master's student at USC who builds AI that takes "
             "repetitive work off people's plates. Let me show you around."},
    {"page": "/home", "target": "#about", "title": "About",
     "images": ["/images/tarun-graduation.webp", "/images/usc-campus-v2.webp"],
     "text": "He loves AI and ML: the math underneath and what you can build on top. His focus is generative, multimodal "
             "and agentic AI."},
    {"page": "/home", "target": "#toolkit", "title": "Toolkit",
     "images": ["/images/work-plant.webp", "/images/multimodal-showcase.webp"],
     "text": "His toolkit covers the whole path: LLMs, multi-agent systems, RAG and MCP, vision and speech, plus the "
             "engineering to ship it."},
    {"page": "/home", "target": "#experience", "title": "Experience",
     "images": ["/images/workplace-monitoring-showcase.webp", "/images/work-plant.webp"],
     "text": "At SRM he made a face-recognition system twelve times faster, cut its CPU use to 23 percent, reduced bias "
             "by 18 percent, and co-authored an ICCP 2026 paper."},
    {"page": "/home", "target": "#work", "title": "Current work",
     "images": ["/images/orion-showcase.webp", "/images/apex-showcase.webp"],
     "text": "Right now at USC he's building a multimodal, autonomous agentic AI system, plus two flagship projects: "
             "ORION and APEX. Let's go see them."},
    {"page": "/projects", "target": "#projects", "video": ".projects-bg", "title": "Why Iron Man",
     "images": ["/video/projects-bg-poster.webp", "/images/projects-bg.webp"],
     "text": "Tarun loves Iron Man. This scene is his reminder that he's on the right path, and to keep building "
             "projects that challenge the world."},
    {"page": "/projects", "target": "#projects-list", "click": OPEN_PROJECT.format(i=0), "before": CLOSE_PROJECT,
     "title": "AI-Powered Workplace Monitoring",
     "images": ["/images/workplace-monitoring-showcase.webp", "/images/work-plant.webp"],
     "text": "Workplace monitoring: cameras feed a real-time face pipeline that confirms who's present. "
             "Twelve times faster, a quarter of the CPU, and fairer across groups.",
     "diagram": {"steps": [["📷", "Camera feed"], ["🙂", "Face detection (Haar Cascade)"], ["🪪", "Recognition (LBPH)"],
                           ["⏱️", "80% temporal validation"], ["📋", "Presence & attendance log"]],
                 "notes": ["Fairness: synthetic data + selective fine-tuning + loss reweighting",
                           "Tested against noise, blur and face masks"]}},
    {"page": "/projects", "target": "#projects-list", "click": OPEN_PROJECT.format(i=1), "before": CLOSE_PROJECT,
     "title": "Multimodal Agentic AI System",
     "images": ["/images/multimodal-showcase.webp", "/images/usc-campus-v2.webp"],
     "text": "A multimodal agent: text, images, video, audio and PDFs become one shared memory, so one agent "
             "can plan, use tools and check its own answers.",
     "diagram": {"steps": [["📥", "Inputs: text · image · video · audio · PDF"], ["🧩", "Encoders (vision transformers, Whisper)"],
                           ["🧭", "Unified embeddings + vector search"], ["🤖", "Agent: plan · tools · memory · self-reflection"],
                           ["✅", "Grounded answer"]],
                 "notes": ["Every answer evaluated (RAGAS)", "Served as an API in containers"]}},
    {"page": "/projects", "target": "#projects-list", "click": OPEN_PROJECT.format(i=2), "before": CLOSE_PROJECT,
     "title": "SKYNET",
     "images": ["/images/skynet-showcase.webp", "/images/og-card.jpg"],
     "text": "SKYNET is live. It ranks job postings by real skill fit and drafts a tailored résumé for each, but a "
             "person always makes the final call.",
     "diagram": {"steps": [["📰", "Job postings"], ["✨", "Skill-relevance ranking (Gemini)"], ["⚖️", "Domain-weighted matching"],
                           ["📄", "Tailored ATS-safe résumé"], ["🧑‍⚖️", "Human review: the final call"]],
                 "notes": ["Tracks every document", "Voice interaction", "Runs on schedule in CI"]}},
    {"page": "/projects", "target": "#projects-list", "click": OPEN_PROJECT.format(i=3), "before": CLOSE_PROJECT,
     "title": "ORION",
     "images": ["/images/orion-showcase.webp", "/images/projects-bg.webp"],
     "text": "ORION automates research: it reads papers, forms hypotheses, runs experiments, learns from failures, and "
             "writes up a technical report.",
     "diagram": {"steps": [["❓", "Research question"], ["📚", "Retrieve papers & data"], ["💡", "Hypotheses"],
                           ["🧪", "Design & run experiments"], ["🔍", "Evaluate · find failures"], ["📑", "Technical report"]],
                 "loop": "Improve and re-run until the results hold up",
                 "notes": ["Multi-agent", "RAG + MCP tools", "GPU / cloud execution"]}},
    {"page": "/projects", "target": "#projects-list", "click": OPEN_PROJECT.format(i=4), "before": CLOSE_PROJECT,
     "title": "APEX",
     "images": ["/images/apex-showcase.webp", "/images/orion-showcase.webp"],
     "text": "APEX is about efficiency: it sizes up each task and picks the cheapest setup that can solve it, then "
             "checks the answer.",
     "diagram": {"steps": [["📝", "Task"], ["📏", "Estimate complexity"], ["🔀", "Route the work"], ["🎯", "Evaluate & optimise"],
                           ["🏁", "Final answer"]],
                 "notes": ["Routes to: direct LLM · one agent · multi-agent · RAG · tools/MCP", "Local or cloud models"]}},
    {"page": "/projects", "target": "#projects-list", "before": CLOSE_PROJECT, "title": "And me: TRINETRA",
     "images": ["trinetra:/static/icons/icon-512.png", "/images/tarun-portrait.webp"],
     "text": "And me. Tarun built me as his mentor: I plan his week, wake him at six, check in when he drifts, "
             "and write his weekly report.",
     "diagram": {"steps": [["📱", "iPhone app + Shortcuts"], ["☁️", "Brain: API in the cloud"],
                           ["🧠", "Agent councils: plan · remind · monitor · mentor"], ["🗄️", "Memory (Postgres)"],
                           ["🔔", "Voice + push notifications back to him"]],
                 "notes": ["Free LLMs (Gemini / Groq)", "Speech: edge-tts + Whisper", "This little character is me"]}},
    {"page": "/home", "target": "#contact", "title": "Let's connect",
     "images": ["/images/contact-bg.webp", "/images/tarun-portrait.webp"],
     "text": "That's the tour{name}. Tarun is looking for a Summer 2027 internship, so reach him here, or leave your "
             "details with me."},
]


def stop(i: int, name: str | None) -> dict | None:
    if not 0 <= i < len(STOPS):
        return None
    s = dict(STOPS[i])
    s["text"] = s["text"].format(name=f", {name}" if name else "")
    return {**s, "i": i, "total": len(STOPS)}
