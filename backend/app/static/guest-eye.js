/* TRINETRA on Tarun's portfolio — the living Eye greets visitors.
   <script src="https://trinetra-tarun.vercel.app/guest/eye.js" defer></script>
   Self-contained: everything lives in a Shadow DOM so it never touches the host page's styles. */
(() => {
  if (window.__trinetraEye) return;
  window.__trinetraEye = true;
  const me = document.currentScript;
  const API = new URL(me?.src || "https://trinetra-tarun.vercel.app/guest/eye.js").origin;
  const AVOID = me?.dataset.avoid || "";  // e.g. data-avoid="[data-clock]": float above these when they'd sit under the Eye
  const KEY = "trinetra-guest-token", MUTE = "trinetra-guest-muted", NUDGED = "trinetra-guest-nudged";
  const store = (s, k, v) => { try { return v === undefined ? s.getItem(k) : (v === null ? s.removeItem(k) : s.setItem(k, v)); } catch { return null; } };
  const still = matchMedia("(prefers-reduced-motion: reduce)").matches;

  const host = document.createElement("div");
  host.id = "trinetra-eye";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });
  root.innerHTML = `
<style>
  :host { all: initial; }
  * { box-sizing: border-box; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
  .wrap { --gold: #f0a83a; --iris: #f0a83a; --glow: rgba(240,168,58,.4); --bg: #0f0e16; --panel: #17161f; --line: #2c2a3b;
    --text: #efedf7; --muted: #9a98b0; position: fixed; right: 20px; bottom: 20px; z-index: 2147483000; }
  .orb { width: 72px; height: 72px; padding: 0; border: 0; background: none; cursor: pointer; display: block;
    -webkit-tap-highlight-color: transparent; position: relative; }
  .orb:focus-visible { outline: 2px solid var(--gold); outline-offset: 4px; border-radius: 50%; }
  .float { width: 100%; height: 100%; transition: transform .4s cubic-bezier(.3,1.4,.5,1); transform-origin: 100% 100%; }
  .wrap.showing .float { transform: scale(1.25); }
  .buddy { width: 100%; height: 100%; }
  .orb { transition: transform 2.2s cubic-bezier(.45,.05,.35,1); }
  .nudge { position: absolute; right: 84px; bottom: 18px; white-space: nowrap; background: var(--panel); color: var(--text);
    border: 1px solid var(--line); border-radius: 14px; padding: 8px 12px; font-size: 13px; box-shadow: 0 8px 24px rgba(0,0,0,.35);
    opacity: 0; transform: translateX(8px); transition: opacity .4s, transform .4s; pointer-events: none; }
  .nudge.on { opacity: 1; transform: none; }
  .panel { position: absolute; right: 0; bottom: 86px; width: 360px; max-height: min(560px, calc(100vh - 130px));
    display: flex; flex-direction: column; background: var(--bg); color: var(--text); border: 1px solid var(--line);
    border-radius: 18px; box-shadow: 0 18px 50px rgba(0,0,0,.45); overflow: hidden;
    opacity: 0; transform: translateY(12px) scale(.98); transform-origin: bottom right; transition: opacity .25s, transform .25s; pointer-events: none; }
  .panel.on { opacity: 1; transform: none; pointer-events: auto; }
  .head { display: flex; align-items: center; gap: 10px; padding: 12px 12px 10px 16px; border-bottom: 1px solid var(--line); }
  .head b { font-size: 14px; letter-spacing: .16em; color: var(--gold); }
  .head small { display: block; font-size: 11px; color: var(--muted); letter-spacing: 0; }
  .head .sp { flex: 1; }
  .icon { width: 32px; height: 32px; border-radius: 50%; border: 1px solid var(--line); background: var(--panel); color: var(--text);
    font-size: 14px; cursor: pointer; display: grid; place-items: center; padding: 0; }
  .icon:focus-visible, button:focus-visible, input:focus-visible, textarea:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
  .log { flex: 1; overflow-y: auto; padding: 14px 14px 6px; display: flex; flex-direction: column; gap: 10px; min-height: 160px; }
  .msg { max-width: 86%; padding: 9px 13px; border-radius: 15px; font-size: 14px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }
  .tri { align-self: flex-start; background: var(--panel); border-left: 3px solid var(--gold); border-bottom-left-radius: 4px; }
  .why { align-self: flex-start; margin: -6px 0 0 4px; background: none; border: 0; padding: 2px 4px; color: var(--muted); font-size: 11.5px; cursor: pointer; }
  .why:hover { color: var(--gold); }
  .me { align-self: flex-end; background: #2b2a42; border-bottom-right-radius: 4px; }
  .tri.tarun { border-left-color: #4ade80; background: #13261b; }
  .dots { align-self: flex-start; color: var(--muted); font-size: 13px; padding: 0 4px; }
  form { display: flex; gap: 8px; padding: 10px 12px 12px; border-top: 1px solid var(--line); }
  form.note { flex-direction: column; }
  input, textarea { flex: 1; min-width: 0; background: var(--panel); color: var(--text); border: 1px solid var(--line); border-radius: 20px;
    padding: 10px 14px; font-size: 16px; outline: none; }
  textarea { border-radius: 14px; resize: none; height: 64px; }
  input:focus, textarea:focus { border-color: var(--gold); }
  .send { background: var(--gold); color: #1a1205; border: 0; border-radius: 20px; padding: 0 16px; font-weight: 600; font-size: 14px; cursor: pointer; min-height: 40px; }
  .send:disabled { opacity: .5; }
  .choices { display: flex; gap: 8px; flex-wrap: wrap; align-self: flex-start; }
  .choices button { border: 1px solid var(--gold); background: transparent; color: var(--gold); border-radius: 16px; padding: 7px 14px;
    font-size: 13px; font-weight: 600; cursor: pointer; }
  .choices button.yes { background: var(--gold); color: #1a1205; }
  .tourbar { display: flex; align-items: center; gap: 6px; padding: 8px 12px; border-top: 1px solid var(--line); font-size: 12px; color: var(--muted); }
  .tourbar .sp { flex: 1; }
  .tourbar .bar { height: 3px; background: var(--line); border-radius: 2px; flex: 1; overflow: hidden; margin-right: 6px; }
  .tourbar .bar i { display: block; height: 100%; background: var(--gold); width: 0; transition: width .4s; }
  .tourbar button { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 14px; padding: 5px 10px; font-size: 12px; cursor: pointer; }
  .tourbar button.go { border-color: var(--gold); color: var(--gold); }
  .stop { font-size: 11px; letter-spacing: .14em; text-transform: uppercase; color: var(--gold); align-self: flex-start; margin: 6px 0 -4px 4px; }
  .diagram { align-self: stretch; background: radial-gradient(ellipse at 50% 0%, #241f38, var(--panel) 70%); border: 1px solid var(--line);
    border-radius: 14px; padding: 12px 12px 14px; perspective: 700px; }
  .diagram .lbl { font-size: 11px; letter-spacing: .12em; text-transform: uppercase; color: var(--muted); margin-bottom: 10px; }
  .flow3d { transform: rotateX(16deg); transform-style: preserve-3d; transform-origin: 50% 0; }
  .diagram .node { display: flex; align-items: center; gap: 9px; border: 1px solid rgba(240,168,58,.55); border-radius: 11px; padding: 7px 10px;
    font-size: 13px; background: linear-gradient(180deg, rgba(240,168,58,.16), rgba(240,168,58,.05));
    box-shadow: 0 5px 0 rgba(120,70,10,.55), 0 12px 18px rgba(0,0,0,.4); animation: rise .5s cubic-bezier(.2,.9,.3,1.2) both; animation-delay: var(--d); }
  .diagram .ic { flex: none; width: 28px; height: 28px; border-radius: 8px; display: grid; place-items: center; font-size: 16px;
    background: rgba(240,168,58,.18); box-shadow: inset 0 -2px 0 rgba(0,0,0,.3); }
  .diagram .arrow { position: relative; height: 18px; margin: 3px 0; }
  .diagram .arrow::before { content: ""; position: absolute; left: 50%; top: 0; bottom: 0; width: 2px; margin-left: -1px; background: rgba(240,168,58,.35); }
  .diagram .arrow::after { content: ""; position: absolute; left: 50%; top: 0; width: 6px; height: 6px; margin-left: -3px; border-radius: 50%;
    background: var(--gold); box-shadow: 0 0 8px var(--gold); animation: pulse-down 1.3s linear infinite; animation-delay: var(--d); }
  @keyframes rise { from { opacity: 0; transform: translateY(10px) rotateX(-35deg); } }
  @keyframes pulse-down { from { top: 0; opacity: 1; } to { top: 100%; opacity: .2; } }
  .diagram .loop { margin-top: 10px; font-size: 12px; color: var(--gold); text-align: center; }
  .diagram .notes { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 12px; }
  .diagram .notes span { font-size: 11px; color: var(--muted); border: 1px solid var(--line); border-radius: 10px; padding: 3px 8px; }
  .pics { align-self: stretch; display: grid; grid-template-columns: 1fr 1fr; gap: 6px; }
  .pics img { width: 100%; aspect-ratio: 4 / 3; object-fit: cover; border-radius: 10px; border: 1px solid var(--line); background: var(--panel);
    animation: rise .45s ease-out both; }
  .pics img:only-child { grid-column: 1 / -1; aspect-ratio: 16 / 9; }
  @media (prefers-reduced-motion: reduce) { .diagram .node, .pics img { animation: none; } .diagram .arrow::after { display: none; } .flow3d { transform: none; } }
  .wrap.touring .panel { max-height: min(620px, calc(100vh - 130px)); }
  .roles { display: flex; flex-wrap: wrap; gap: 6px; align-self: stretch; }
  .roles button { border: 1px solid var(--line); background: var(--panel); color: var(--text); border-radius: 14px; padding: 7px 11px; font-size: 13px; cursor: pointer; }
  .roles button:first-child, .roles button:nth-child(2) { border-color: var(--gold); }
  .roles button:hover { border-color: var(--gold); color: var(--gold); }
  .card { align-self: stretch; background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
  .card label { font-size: 12px; color: var(--muted); }
  .card .line { display: flex; gap: 6px; }
  .card select, .card input { background: var(--bg); color: var(--text); border: 1px solid var(--line); border-radius: 10px; padding: 9px 10px; font-size: 16px; outline: none; min-width: 0; }
  .card select { flex: none; max-width: 46%; }
  .card input { flex: 1; }
  .card select:focus, .card input:focus { border-color: var(--gold); }
  .card .btns { display: flex; gap: 8px; justify-content: flex-end; }
  .card .skip { background: transparent; color: var(--muted); border: 1px solid var(--line); border-radius: 16px; padding: 7px 14px; font-size: 13px; cursor: pointer; }
  .card .err { color: #ff8a80; font-size: 12px; min-height: 1em; }
  [hidden] { display: none !important; }
  @media (max-width: 520px) {
    .wrap { right: 16px; bottom: 16px; }
    .orb { width: 62px; height: 62px; }
    .panel { position: fixed; left: 16px; right: 16px; width: auto; bottom: calc(var(--lift, 16px) + 74px); max-height: calc(100vh - var(--lift, 16px) - 104px); }
    .nudge { right: 72px; bottom: 14px; }
    .wrap.touring .panel { max-height: 52vh; }
  }
  @media (prefers-reduced-motion: reduce) { .orb { transition: none; } }
</style>
<div class="wrap">
  <section class="panel" role="dialog" aria-label="Chat with TRINETRA, Tarun's AI mentor">
    <div class="head"><div><b>TRINETRA</b><small>Tarun's AI mentor</small></div><span class="sp"></span>
      <button class="icon brainbtn" type="button" aria-label="See how I think: my brain and agents, live" title="How I think (live)">🧠</button>
      <button class="icon mute" type="button" aria-label="Mute voice">🔊</button>
      <button class="icon close" type="button" aria-label="Close chat">✕</button></div>
    <div class="log" aria-live="polite"></div>
    <div class="tourbar" hidden><div class="bar"><i></i></div><span class="count"></span>
      <button type="button" class="pause">⏸ Pause</button><button type="button" class="next">Next ⏭</button><button type="button" class="end">✕ End tour</button></div>
    <form class="talk"><input name="t" placeholder="Type a message…" autocomplete="off" maxlength="500" aria-label="Message TRINETRA">
      <button class="send" type="submit">Send</button></form>
    <form class="note" hidden><input name="email" type="email" placeholder="Your email" autocomplete="email" required aria-label="Your email">
      <textarea name="message" placeholder="Your message for Tarun (optional)" maxlength="1000" aria-label="Message for Tarun"></textarea>
      <button class="send" type="submit">Leave it for Tarun</button></form>
  </section>
  <div class="nudge">Hi, I'm Tarun's AI. Click to talk to me 👋</div>
  <button class="orb" type="button" aria-label="Talk to TRINETRA, Tarun's AI mentor" aria-expanded="false"><div class="float"><div class="buddy"></div></div></button>
</div>`;

  const $ = (s) => root.querySelector(s);
  const wrap = $(".wrap"), orb = $(".orb"), panel = $(".panel"), log = $(".log"), talkForm = $(".talk"), noteForm = $(".note");
  const input = talkForm.elements.t, sendBtn = talkForm.querySelector(".send"), nudge = $(".nudge");
  const later = (ms, fn) => setTimeout(fn, ms), rand = (a, b) => a + Math.random() * (b - a);
  const has = (c) => wrap.classList.contains(c);

  // ---- TRINETRA's character (drawn by buddy.js from the TRINETRA server) ----
  let buddy = null, glad = false, performing = null, expressing = null;
  // Its look follows what Tarun picked in his app (🎨), unless this page pins one with data-style / data-palette.
  const LOOK = { style: me?.dataset.style, palette: me?.dataset.palette };
  function sync() {  // the widget's state → what the character is doing
    if (!buddy) return;
    buddy.setActivity(has("speaking") ? "speaking" : has("thinking") ? "thinking" : has("walking") ? "walking"
      : has("watch") || has("peek") || has("open") ? "watching" : "idle");
    buddy.setEmotion(performing || expressing || (glad ? "happy" : LOOK.mood || "neutral"));  // resting mood = the app's (visitor-safe)
  }
  new MutationObserver(sync).observe(wrap, { attributes: true, attributeFilter: ["class"] });
  const cheer = () => buddy?.celebrate();
  const beGlad = (ms = 3500) => { glad = true; sync(); later(ms, () => { glad = false; sync(); }); };
  (function loadBuddy() {
    const ready = async () => {
      try {  // the look (unless this page pins one) and the resting mood, shared with Tarun's app
        const l = await (await fetch(`${API}/guest/look`)).json();
        LOOK.style ||= l.style; LOOK.palette ||= l.palette; LOOK.mood = l.mood;
      } catch {}
      buddy = window.TrinetraBuddy.create($(".buddy"), { style: LOOK.style || "pixel", palette: LOOK.palette || "saffron" });
      sync();
      loadMusic();
      if (BRAIN_ON) later(4000, loadWorld);  // ready before they click
    };
    if (window.TrinetraBuddy) return ready();
    const sc = document.createElement("script"); sc.src = `${API}/guest/buddy.js`; sc.onload = ready;
    document.head.appendChild(sc);
  })();

  // ---- shows: "dance" (she joins for 10 s), "play the guitar" (until stop / Esc / a tap), "jump" — music from static/music.js ----
  let musicReady = null;
  function loadMusic() {
    return (musicReady ??= new Promise((ok) => {
      if (window.TrinetraMusic) return ok();
      const sc = document.createElement("script"); sc.src = `${API}/static/music.js`; sc.onload = ok; sc.onerror = ok;
      document.head.appendChild(sc);
    }));
  }
  const stopShow = () => window.TrinetraMusic?.stopAll();
  async function runShow(s) {
    if (s.show === "lab") { stopShow(); return openWorld(s.cmd); }  // "assemble" / "what do your agents do" → the Brain
    if (s.show === "stop") return stopShow();
    if (!["play", "dance", "act"].includes(s.show)) return;  // "what can you do": the reply is the answer
    await loadMusic();
    if (!window.TrinetraMusic || !buddy) return;
    stopShow();  // the last one ends first, so its clean-up can't undo this one
    wrap.classList.add("showing");
    TrinetraMusic.show(buddy, s, { mood: LOOK.mood, feel: (e) => { performing = e; sync(); },
      onEnd: () => wrap.classList.remove("showing") });
    if (s.show === "play") later(300, () => buddy.look(0, 30));
  }

  // ---- its brain (static/brain.js): a click on the doll opens TRINETRA's Brain inside the portfolio — the real 66 agents in 10
  //      teams, placed in the brain regions that match their jobs, managers reporting to TRINETRA at the thalamus. 💬 there = chat ----
  let brainReady = null, bigBrain = null, lastTrace = null;
  const BRAIN_ON = me?.dataset.world !== "off";
  function loadWorld() {
    return (brainReady ??= new Promise((ok) => {
      if (window.TrinetraBrain) return ok();
      const sc = document.createElement("script"); sc.src = `${API}/static/brain.js`; sc.onload = ok; sc.onerror = ok; document.head.appendChild(sc);
    }));
  }
  async function openWorld(cmd, trace) {
    if (!BRAIN_ON) return open();
    nudge.classList.remove("on");
    await loadWorld();
    if (!window.TrinetraBrain) return open();
    if (bigBrain) { if (cmd) bigBrain.ready.then(() => bigBrain?.order(cmd)); else if (trace) bigBrain.ready.then(() => bigBrain?.brain?.replay(trace)); return; }
    bigBrain = TrinetraBrain.open(wrap, {
      agents: fetch(`${API}/guest/agents`).then((r) => (r.ok ? r.json() : null)),
      look: { style: LOOK.style || "pixel", palette: LOOK.palette || "saffron" }, cmd, trace,
      onChat: () => later(50, open), onClose: () => { bigBrain = null; },
    });
  }

  // ---- its little life: peeks, strolls, and watches your cursor when you come near ----
  function look(dx, dy) { buddy?.look(dx, dy); }
  function stroll() {  // now and then a short, calm walk along the bottom edge and back
    later(rand(14000, 24000), stroll);
    if (has("open") || has("watch") || still) return;
    const away = -rand(60, 130);
    wrap.classList.add("walking"); look(-40, 0); orb.style.transform = `translateX(${away}px)`;
    later(2300, () => { look(40, 0); orb.style.transform = ""; });
    later(4600, () => { wrap.classList.remove("walking"); look(0, 0); });
  }
  later(9000, stroll);
  const center = () => { const b = (buddy?.el || orb).getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; };
  function peek() {
    later(rand(9000, 18000), peek);
    if (has("open") || has("watch") || still) return;
    wrap.classList.add("peek"); look(-60, -20);
    later(700, () => look(60, -20)); later(1400, () => look(0, 0)); later(1900, () => wrap.classList.remove("peek"));
  }
  let watchTimer = null;
  document.addEventListener("pointermove", (e) => {
    const [cx, cy] = center();
    if (has("open")) { look(e.clientX - cx, e.clientY - cy); return; }
    if (Math.hypot(e.clientX - cx, e.clientY - cy) > 170 && !has("watch")) return;
    wrap.classList.add("watch"); look(e.clientX - cx, e.clientY - cy);
    clearTimeout(watchTimer);
    watchTimer = later(2000, () => { wrap.classList.remove("watch"); look(0, 0); });
  }, { passive: true });
  later(2500, peek);
  if (!store(sessionStorage, NUDGED)) later(6000, () => {
    if (has("open")) return;
    store(sessionStorage, NUDGED, "1");
    nudge.classList.add("on"); wrap.classList.add("peek"); look(-40, 0);
    later(6000, () => { nudge.classList.remove("on"); wrap.classList.remove("peek"); look(0, 0); });
  });

  // ---- voice: the Eye answers out loud (mute remembered) ----
  let muted = store(localStorage, MUTE) === "1", player = null;
  const muteBtn = $(".mute");
  const paintMute = () => { muteBtn.textContent = muted ? "🔇" : "🔊"; muteBtn.setAttribute("aria-label", muted ? "Unmute voice" : "Mute voice"); };
  paintMute();
  muteBtn.onclick = () => {
    muted = !muted; store(localStorage, MUTE, muted ? "1" : "0"); if (muted) player?.pause(); paintMute();
    if (!muted) ahead.clear();  // stops prepared in silence get their voice now
  };
  const SILENCE = (() => {  // 50 ms of silence as a WAV
    const n = 400, buf = new ArrayBuffer(44 + n), v = new DataView(buf);
    const w = (o, str) => [...str].forEach((c, k) => v.setUint8(o + k, c.charCodeAt(0)));
    w(0, "RIFF"); v.setUint32(4, 36 + n, true); w(8, "WAVEfmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true);
    v.setUint16(22, 1, true); v.setUint32(24, 8000, true); v.setUint32(28, 8000, true); v.setUint16(32, 1, true);
    v.setUint16(34, 8, true); w(36, "data"); v.setUint32(40, n, true);
    for (let k = 0; k < n; k++) v.setUint8(44 + k, 128);
    return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
  })();
  function unlockAudio() {  // browsers only allow sound that a click started — start the player silently on the first click
    if (player) return;
    player = new Audio();
    player.src = SILENCE;
    player.play().catch(() => {});
  }
  let speakSeq = 0;
  // Voices what TRINETRA just said to this visitor (the server knows what that is).
  // Resolves when it has finished speaking (straight away when muted or if the voice fails).
  function speak() {
    return new Promise(async (resolve) => {
      if (muted || !token || !has("open")) return resolve(false);
      const mine = ++speakSeq;
      stopShow();  // it puts the instrument down to talk
      wrap.classList.add("speaking");
      const done = () => { if (mine === speakSeq) wrap.classList.remove("speaking"); resolve(true); };
      try {
        const r = await fetch(`${API}/guest/speak`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token }) });
        if (!r.ok || mine !== speakSeq || muted || !has("open")) return done();  // closed while the voice was on its way
        const p = player || (player = new Audio());
        p.onended = p.onpause = null; p.pause();
        p.src = URL.createObjectURL(await r.blob());
        p.onended = p.onpause = () => { done(); hush(); };
        await p.play();
        const line = lastLine();
        express(line, isFinite(p.duration) && p.duration > 0 ? p.duration * 1000 : line.length * 65);
      } catch { done(); }
    });
  }

  // ---- the conversation ----
  let token = store(sessionStorage, KEY), started = false;
  function add(text, who) {
    const el = document.createElement("div");
    el.className = `msg ${who}` + (who === "tri" && text.startsWith("Message from Tarun:") ? " tarun" : ""); el.textContent = text;
    log.appendChild(el); log.scrollTop = log.scrollHeight;
    return el;
  }
  function thinking(on) {
    wrap.classList.toggle("thinking", on); sendBtn.disabled = on;
    root.querySelector(".dots")?.remove();
    if (on) { const d = document.createElement("div"); d.className = "dots"; d.textContent = "TRINETRA is thinking…"; log.appendChild(d); log.scrollTop = log.scrollHeight; }
  }
  async function api(path, body) {
    const r = await fetch(`${API}/guest/${path}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body || {}) });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw Object.assign(new Error(d.detail || "Something went wrong."), { status: r.status });
    return d;
  }
  async function hello() {
    let d;
    d = await api("hello");
    token = d.token; store(sessionStorage, KEY, token);
    log.innerHTML = ""; add(d.reply, "tri"); speak();
  }
  let beginning = null;
  function begin() {  // pick the visit back up (another page of the site), or say hello — once
    return (beginning ||= (async () => {
      try {
        if (token) {
          try {
            const d = await api("resume", { token });
            log.innerHTML = "";
            for (const m of d.messages) add(m.text, m.role === "trinetra" ? "tri" : "me");
            if (!d.messages.length) await hello();
            return;
          } catch (e) { if (e.status !== 404) throw e; }
        }
        await hello();
      } catch (e) { beginning = null; add(e.message || "I can't reach my brain right now. Try again in a moment.", "tri"); }
    })());
  }

  let askTimer = null;
  function pollAsk(id, since = Date.now()) {
    clearTimeout(askTimer);
    askTimer = later(3000, async () => {
      try {
        const r = await fetch(`${API}/guest/ask/${id}?token=${encodeURIComponent(token)}`);
        const d = await r.json();
        if (d.status === "answered") { add(d.reply, "tri"); speak(); noteForm.hidden = true; talkForm.hidden = false; return; }
        if (d.status === "timeout" && !noteForm.dataset.shown) {
          noteForm.dataset.shown = "1";
          add(d.reply, "tri"); speak();
          noteForm.hidden = false; talkForm.hidden = true; noteForm.elements.email.focus();
        }
        if (d.status === "waiting" || (d.status === "timeout" && Date.now() - since < 5 * 60000)) pollAsk(id, since);  // a late answer still arrives
      } catch { pollAsk(id, since); }
    });
  }

  // ---- the guided tour: ~10 s a stop, scrolls the page, opens each project and draws how it's built ----
  const TOUR = "trinetra-guest-tour";
  const tourbar = $(".tourbar"), pauseBtn = $(".pause");
  const path = (p) => (p.replace(/\/+$/, "") || "/home").replace(/^\/$/, "/home");
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  let tourOn = false, tourPaused = false, tourAt = 0, tourRun = 0;

  function choices(list) {  // little Yes / Not now buttons under a message
    const row = document.createElement("div"); row.className = "choices";
    for (const [label, fn, yes] of list) {
      const b = document.createElement("button"); b.type = "button"; b.textContent = label; if (yes) b.className = "yes";
      b.onclick = () => { row.remove(); fn(); };
      row.append(b);
    }
    log.appendChild(row); log.scrollTop = log.scrollHeight;
  }
  function drawDiagram(title, d) {  // a 3D-ish flow: tilted slabs with icons, a light running down the arrows
    const box = document.createElement("div"); box.className = "diagram";
    const lbl = document.createElement("div"); lbl.className = "lbl"; lbl.textContent = `How ${title} works`;
    const flow = document.createElement("div"); flow.className = "flow3d";
    d.steps.forEach((step, k) => {
      const [icon, text] = Array.isArray(step) ? step : ["•", step];
      if (k) { const a = document.createElement("div"); a.className = "arrow"; a.style.setProperty("--d", `${k * 0.18}s`); flow.append(a); }
      const n = document.createElement("div"); n.className = "node"; n.style.setProperty("--d", `${k * 0.12}s`);
      const ic = document.createElement("span"); ic.className = "ic"; ic.textContent = icon;
      const tx = document.createElement("span"); tx.textContent = text;
      n.append(ic, tx); flow.append(n);
    });
    box.append(lbl, flow);
    if (d.loop) { const l = document.createElement("div"); l.className = "loop"; l.textContent = "↺ " + d.loop; box.append(l); }
    if (d.notes?.length) {
      const ns = document.createElement("div"); ns.className = "notes";
      for (const t of d.notes) { const sp = document.createElement("span"); sp.textContent = t; ns.append(sp); }
      box.append(ns);
    }
    log.appendChild(box); log.scrollTop = log.scrollHeight;
  }
  const imgSrc = (src) => (src.startsWith("trinetra:") ? API + src.slice(9) : src);
  function pictures(list) {
    if (!list?.length) return;
    const row = document.createElement("div"); row.className = "pics";
    for (const src of list.slice(0, 2)) {
      const im = document.createElement("img"); im.src = imgSrc(src); im.alt = ""; im.decoding = "async";
      im.onerror = () => im.remove();
      row.append(im);
    }
    log.appendChild(row); log.scrollTop = log.scrollHeight;
  }
  function showOnPage(st) {
    if (st.before) document.querySelector(st.before)?.click();
    const el = st.target && document.querySelector(st.target);
    if (el) el.scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" });
    if (st.click) later(st.before ? 300 : 30, () => {
      const c = document.querySelector(st.click);
      if (c) { c.click(); later(250, () => (document.querySelector("[data-expanded]:not([hidden])") || c).scrollIntoView({ behavior: still ? "auto" : "smooth", block: "start" })); }
    });
  }
  function paintBar(i, total) {
    tourbar.querySelector(".bar i").style.width = `${Math.round(((i + 1) / total) * 100)}%`;
    tourbar.querySelector(".count").textContent = `${i + 1} / ${total}`;
  }
  function saveTour(i) { store(sessionStorage, TOUR, i === null ? null : JSON.stringify({ i })); }

  // Each stop is made ready (words, voice, pictures) while the one before is still talking, so there's no waiting.
  const ahead = new Map();
  function prepare(i) {
    if (!ahead.has(i)) {
      ahead.set(i, (async () => {
        const r = await fetch(`${API}/guest/tour/${i}?token=${encodeURIComponent(token)}`);
        if (!r.ok) throw new Error("The tour hit a snag. Try again in a moment.");
        const st = await r.json();
        if (st.done) return { st };
        for (const src of st.images || []) { const im = new Image(); im.src = imgSrc(src); }
        let audio = null;
        if (!muted) {
          try { const v = await fetch(`${API}/guest/tour/${i}/voice?token=${encodeURIComponent(token)}`); if (v.ok) audio = URL.createObjectURL(await v.blob()); } catch {}
        }
        return { st, audio };
      })());
      ahead.get(i).catch(() => ahead.delete(i));
    }
    return ahead.get(i);
  }
  function playUrl(url, words = "") {  // resolves when it's finished (or straight away if it can't play)
    return new Promise(async (resolve) => {
      if (muted || !url || !has("open")) return resolve(false);
      const mine = ++speakSeq;
      wrap.classList.add("speaking");
      const done = () => { if (mine === speakSeq) wrap.classList.remove("speaking"); resolve(true); };
      const p = player || (player = new Audio());
      p.onended = p.onpause = null; p.pause();
      p.src = url; p.onended = p.onpause = () => { done(); hush(); };
      try {
        await p.play();
        if (words) express(words, isFinite(p.duration) && p.duration > 0 ? p.duration * 1000 : words.length * 65, "proud and upbeat");
      } catch { done(); }
    });
  }
  function duckVideo(sel) {  // the page's own video plays quietly under the voice, then gets its moment
    const v = document.querySelector(sel);
    if (!v) return null;
    const vol = v.volume;
    v.volume = 0.12;
    v.play?.().catch(() => {});
    return { async release() { v.volume = vol; if (!v.paused && tourOn && !tourPaused) await wait(2500); } };
  }

  async function tourStep(i) {
    const run = ++tourRun;
    tourAt = i;
    let pack;
    try { pack = await prepare(i); } catch (e) { add(e.message, "tri"); return endTour(); }
    if (run !== tourRun) return;
    const st = pack.st;
    if (st.done) return endTour(true);
    saveTour(i);
    if (path(location.pathname) !== path(st.page)) { location.href = st.page; return; }  // next page; the tour carries on there
    prepare(i + 1).catch(() => {});  // the next stop gets ready while this one plays
    paintBar(i, st.total);
    const tag = document.createElement("div"); tag.className = "stop"; tag.textContent = st.title; log.appendChild(tag);
    add(st.text, "tri");
    pictures(st.images);
    if (st.diagram) drawDiagram(st.title, st.diagram);
    makeRoom(!!st.click);  // only an open project needs the room
    showOnPage(st);
    if (!pack.audio && !muted) {  // prepared while muted, sound is on now: fetch this stop's voice
      try { const v = await fetch(`${API}/guest/tour/${i}/voice?token=${encodeURIComponent(token)}`); if (v.ok) pack.audio = URL.createObjectURL(await v.blob()); } catch {}
      if (run !== tourRun) return;
    }
    const duck = st.video ? duckVideo(st.video) : null;
    const spoke = await playUrl(pack.audio, st.text);
    if (!spoke && run === tourRun) express(st.text, Math.min(11000, Math.max(3500, st.text.split(" ").length * 300)), "proud and upbeat");
    if (!spoke && run === tourRun) await wait(Math.min(11000, Math.max(3500, st.text.split(" ").length * 300)));  // muted: reading time
    if (duck) await duck.release();
    await wait(350);
    if (run === tourRun && tourOn && !tourPaused) tourStep(i + 1);
  }
  // Wide screens, project details only: the page shifts left so the open project isn't hidden behind the panel.
  // Never on the full-width sections (it would cut their backgrounds), and always undone when the panel closes.
  const roomy = () => innerWidth >= 1100;
  let roomWanted = false;
  function makeRoom(on) {
    roomWanted = on;
    const html = document.documentElement;
    if (on && roomy() && has("open")) { html.style.transition = "padding-right .35s ease"; html.style.paddingRight = "392px"; }
    else html.style.paddingRight = "";
  }
  addEventListener("resize", () => makeRoom(roomWanted));
  function startTour(from = 0) {
    tourOn = true; tourPaused = false; wrap.classList.add("touring");
    tourbar.hidden = false; pauseBtn.textContent = "⏸ Pause";
    tourStep(from);
  }
  function endTour(finished = false) {
    tourOn = false; tourRun++; saveTour(null); wrap.classList.remove("touring"); tourbar.hidden = true; makeRoom(false);
    if (finished) { cheer(); beGlad(); }
    if (!finished) { player?.pause(); add("No problem. Ask me anything, or type “tour” any time to pick it back up.", "tri"); }
  }
  pauseBtn.onclick = () => {
    if (!tourOn) return;
    tourPaused = !tourPaused;
    pauseBtn.textContent = tourPaused ? "▶ Resume" : "⏸ Pause";
    if (tourPaused) { tourRun++; player?.pause(); } else { saveTour(tourAt); tourStep(tourAt + 1); }
  };
  $(".next").onclick = () => { if (!tourOn) return; player?.pause(); tourPaused = false; pauseBtn.textContent = "⏸ Pause"; tourStep(tourAt + 1); };
  $(".end").onclick = () => endTour();
  function offerTour() {
    later(400, () => prepare(0).catch(() => {}));  // "Yes" starts instantly
    choices([["Yes, show me around", () => startTour(0), true], ["Not now", () => add("Sure. Ask me anything about Tarun, or type “tour” whenever you like.", "tri")]]);
  }
  async function resumeTourHere() {  // the tour moved to this page: one tap lets the voice carry on (browsers need it)
    let saved = null;
    try { saved = JSON.parse(store(sessionStorage, TOUR) || "null"); } catch {}
    if (!saved || !token) return;
    open();
    await begin();
    tourOn = true; wrap.classList.add("touring"); tourbar.hidden = false;
    prepare(saved.i).catch(() => {});
    if (muted || (await soundAllowed())) return startTour(saved.i);  // carry straight on
    choices([["▶ Continue the tour", () => { unlockAudio(); startTour(saved.i); }, true], ["End tour", () => endTour()]]);
  }
  async function soundAllowed() {  // can this page play sound without a tap? (browsers decide)
    try { const a = new Audio(SILENCE); await a.play(); a.pause(); player ||= a; return true; }
    catch { return false; }
  }

  // ---- "who are you?" buttons, and the contact card (number with country code, then email; both skippable) ----
  function roleButtons(options) {
    const row = document.createElement("div"); row.className = "roles";
    for (const o of options) {
      const b = document.createElement("button"); b.type = "button"; b.textContent = o.label;
      b.onclick = async () => {
        row.remove(); add(o.label, "me"); thinking(true);
        try { const d = await api("role", { token, role: o.key }); thinking(false); afterReply(d); }
        catch (err) { thinking(false); add(err.message, "tri"); }
      };
      row.append(b);
    }
    log.appendChild(row); log.scrollTop = log.scrollHeight;
  }
  const COUNTRIES = [  // [code, flag, name, dial]
    ["US", "🇺🇸", "United States", "+1"], ["IN", "🇮🇳", "India", "+91"], ["CA", "🇨🇦", "Canada", "+1"], ["GB", "🇬🇧", "United Kingdom", "+44"],
    ["DE", "🇩🇪", "Germany", "+49"], ["FR", "🇫🇷", "France", "+33"], ["NL", "🇳🇱", "Netherlands", "+31"], ["IE", "🇮🇪", "Ireland", "+353"],
    ["CH", "🇨🇭", "Switzerland", "+41"], ["SE", "🇸🇪", "Sweden", "+46"], ["ES", "🇪🇸", "Spain", "+34"], ["IT", "🇮🇹", "Italy", "+39"],
    ["PL", "🇵🇱", "Poland", "+48"], ["IL", "🇮🇱", "Israel", "+972"], ["AE", "🇦🇪", "UAE", "+971"], ["SA", "🇸🇦", "Saudi Arabia", "+966"],
    ["SG", "🇸🇬", "Singapore", "+65"], ["JP", "🇯🇵", "Japan", "+81"], ["KR", "🇰🇷", "South Korea", "+82"], ["CN", "🇨🇳", "China", "+86"],
    ["HK", "🇭🇰", "Hong Kong", "+852"], ["TW", "🇹🇼", "Taiwan", "+886"], ["AU", "🇦🇺", "Australia", "+61"], ["NZ", "🇳🇿", "New Zealand", "+64"],
    ["BR", "🇧🇷", "Brazil", "+55"], ["MX", "🇲🇽", "Mexico", "+52"], ["PK", "🇵🇰", "Pakistan", "+92"], ["BD", "🇧🇩", "Bangladesh", "+880"],
    ["LK", "🇱🇰", "Sri Lanka", "+94"], ["NP", "🇳🇵", "Nepal", "+977"], ["ZA", "🇿🇦", "South Africa", "+27"], ["NG", "🇳🇬", "Nigeria", "+234"],
  ];
  function detectCountry() {  // the visitor's time zone first (where they are), then their browser language
    const tz = (Intl.DateTimeFormat().resolvedOptions().timeZone || "");
    const byZone = { Kolkata: "IN", Calcutta: "IN", London: "GB", Dublin: "IE", Berlin: "DE", Paris: "FR", Amsterdam: "NL", Zurich: "CH",
      Stockholm: "SE", Madrid: "ES", Rome: "IT", Warsaw: "PL", Jerusalem: "IL", Tel_Aviv: "IL", Dubai: "AE", Riyadh: "SA", Singapore: "SG",
      Tokyo: "JP", Seoul: "KR", Shanghai: "CN", Hong_Kong: "HK", Taipei: "TW", Sydney: "AU", Melbourne: "AU", Brisbane: "AU", Perth: "AU",
      Auckland: "NZ", Sao_Paulo: "BR", Mexico_City: "MX", Karachi: "PK", Dhaka: "BD", Colombo: "LK", Kathmandu: "NP",
      Johannesburg: "ZA", Lagos: "NG", Toronto: "CA", Vancouver: "CA", Montreal: "CA", Edmonton: "CA", Winnipeg: "CA", Halifax: "CA" };
    const city = tz.split("/").pop();
    if (byZone[city]) return byZone[city];
    if (/^America\/|^US\//.test(tz)) return "US";
    for (const l of navigator.languages || [navigator.language || ""]) {
      const region = (l.split("-")[1] || "").toUpperCase();
      if (COUNTRIES.some((c) => c[0] === region)) return region;
    }
    return "US";
  }
  function contactCard() {  // one card: number (with country code) and email together — either, both, or skip
    const card = document.createElement("div"); card.className = "card";
    card.innerHTML = `<label>Phone</label><div class="line"><select aria-label="Country code"></select>
        <input class="num" type="tel" inputmode="tel" autocomplete="tel-national" placeholder="Phone number" aria-label="Phone number"></div>
      <label>Email</label><input class="mail" type="email" autocomplete="email" placeholder="you@company.com" aria-label="Email">
      <div class="err"></div><div class="btns"><button type="button" class="skip">Skip</button><button type="button" class="send">Send to Tarun</button></div>`;
    const sel = card.querySelector("select"), num = card.querySelector(".num"), mail = card.querySelector(".mail"), err = card.querySelector(".err");
    const mine = detectCountry();
    for (const [code, flag, name, dial] of COUNTRIES) {
      const o = document.createElement("option"); o.value = dial; o.textContent = `${flag} ${dial} ${name}`;
      if (code === mine) o.selected = true;
      sel.append(o);
    }
    const finish = async (phone, email) => {
      card.remove(); if (phone || email) add([phone, email].filter(Boolean).join(" · "), "me");
      thinking(true);
      try { const d = await api("contact", { token, phone, email }); thinking(false); afterReply(d); }
      catch (e) { thinking(false); add(e.message, "tri"); }
    };
    const send = () => {
      const digits = num.value.replace(/\D/g, ""), em = mail.value.trim();
      if (!digits && !em) { err.textContent = "Add a number or an email, or tap Skip."; num.focus(); return; }
      if (digits && (digits.length < 6 || digits.length > 14)) { err.textContent = "That number looks too short or too long."; num.focus(); return; }
      if (em && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(em)) { err.textContent = "That email doesn't look right."; mail.focus(); return; }
      finish(digits ? `${sel.value} ${num.value.trim().replace(/[^\d\s\-().]/g, "").trim()}` : null, em || null);
    };
    card.querySelector(".send").onclick = send;
    card.querySelector(".skip").onclick = () => finish(null, null);
    for (const f of [num, mail]) f.onkeydown = (e) => { if (e.key === "Enter") { e.preventDefault(); send(); } };
    log.appendChild(card); log.scrollTop = log.scrollHeight;
    later(50, () => num.focus({ preventScroll: true }));
  }
  // the face follows the feeling of each sentence it says, timed to the voice
  let exprRun = 0;
  function express(text, ms, mood = "") {
    const run = ++exprRun;
    if (!text || !window.TrinetraBuddy?.read) { expressing = null; sync(); return; }
    let t = 0;
    for (const seg of window.TrinetraBuddy.read(text, mood)) {
      later(t, () => {
        if (run !== exprRun || performing) return;
        if (seg.emotion === "angry" && expressing !== "angry") buddy?.shake();
        if ((seg.emotion === "excited" || seg.emotion === "proud") && expressing !== seg.emotion) buddy?.celebrate();
        expressing = seg.emotion === "neutral" ? null : seg.emotion; sync();
      });
      t += Math.max(600, seg.weight * ms);
    }
    later(t + 500, () => { if (run === exprRun) { expressing = null; sync(); } });
  }
  const hush = () => { exprRun++; expressing = null; sync(); };
  const lastLine = () => [...log.querySelectorAll(".msg.tri")].pop()?.textContent || "";
  function perform(list, each = 2200) {  // act out emotions one after another ("show me your emotions")
    list.forEach((emo, i) => later(400 + i * each, () => {
      performing = emo; sync();
      if (emo === "angry" || emo === "firm") buddy?.shake();
      if (emo === "happy" || emo === "excited" || emo === "proud") buddy?.celebrate();
    }));
    later(400 + list.length * each, () => { performing = null; sync(); });
  }
  function afterReply(d) {  // whatever TRINETRA said, plus what comes with it
    if (d.eject) { add(d.reply, "tri"); return throwOut(); }
    add(d.reply, "tri");
    if (d.trace?.length && BRAIN_ON) {  // what really happened to their message — watch it live in the Brain
      lastTrace = d.trace;
      log.querySelectorAll(".why").forEach((w) => w.remove());  // only under the latest reply (🧠 up top replays it too)
      const why = document.createElement("button"); why.type = "button"; why.className = "why"; why.textContent = "🧠 how I answered ▶";
      why.onclick = () => openWorld(null, d.trace);
      log.appendChild(why); log.scrollTop = log.scrollHeight;
    }
    if (d.show) return runShow(d.show);  // just the name; the character performs it (no voice)
    if (d.perform?.length) return perform(d.perform);  // just the names, and the face acts them out (no voice)
    speak();
    if (muted) express(d.reply, d.reply.length * 55);
    if (d.celebrate) { cheer(); beGlad(); }
    if (d.role_options) roleButtons(d.role_options);
    if (d.contact_form) contactCard();
    if (d.offer_tour) offerTour();
    if (d.ask_id) { delete noteForm.dataset.shown; pollAsk(d.ask_id); }
  }

  talkForm.onsubmit = async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || sendBtn.disabled) return;
    input.value = ""; add(text, "me");
    stopShow();  // you said something: the music stops (a new "play …" starts the next one)
    root.querySelector(".roles")?.remove();
    const offered = root.querySelector(".choices");
    // "tour" anywhere, or a plain yes (the whole message) right after the offer — "okay bye" is not a yes
    const wantsTour = /^\s*(the\s+)?tour[\s.!?]*$/i.test(text)
      || (/\b(start|take|give|show|do|begin|restart|want|like)\b[^.!?]{0,20}\btour\b/i.test(text) && !/\b(thanks?|thank you|bye|done|finished|enjoyed|loved|great)\b/i.test(text));
    if (wantsTour || (offered && /^\s*(yes|yeah|yep|sure|ok(ay)?|please|go|let'?s go|why not)[\s.!]*$/i.test(text))) {
      offered?.remove(); startTour(0); return;
    }
    if (tourOn && /\b(good\s?bye|bye+|see (you|ya)|gotta go|take care)\b/i.test(text)) {  // leaving: the tour is over
      tourOn = false; tourRun++; saveTour(null); wrap.classList.remove("touring"); tourbar.hidden = true; makeRoom(false); player?.pause();
    }
    if (tourOn && !tourPaused) pauseBtn.click();  // a question mid-tour pauses it
    const felt = window.TrinetraBuddy?.empathize?.(text);  // "I just got an offer!" → excited before it even answers
    if (felt) { const run = ++exprRun; expressing = felt; sync(); later(9000, () => { if (run === exprRun) { expressing = null; sync(); } }); }
    thinking(true);
    try {
      let d;
      try { d = await api("chat", { token, text }); }
      catch (err) { if (err.status !== 404) throw err; await hello(); d = await api("chat", { token, text }); }
      thinking(false); afterReply(d);
    } catch (err) { thinking(false); add(err.message, "tri"); }
  };
  noteForm.onsubmit = async (e) => {
    e.preventDefault();
    const btn = noteForm.querySelector(".send"); btn.disabled = true;
    try {
      const d = await api("note", { token, email: noteForm.elements.email.value.trim(), message: noteForm.elements.message.value });
      add(d.reply, "tri"); speak(); cheer(); beGlad();
      noteForm.hidden = true; talkForm.hidden = false; noteForm.reset();
    } catch (err) { add(err.status === 422 ? "That email doesn't look right — mind checking it?" : err.message, "tri"); }
    finally { btn.disabled = false; }
  };

  // ---- insulting Tarun: an angry face, one line, and the page is gone. No ban: they can open the site again. ----
  store(localStorage, "trinetra-guest-removed", null);  // clears the old 24 h ban from earlier versions
  function throwOut() {
    input.disabled = sendBtn.disabled = true; stopShow();
    tourOn = false; tourRun++; saveTour(null); player?.pause();
    performing = "angry"; sync(); buddy?.shake();
    later(1800, () => {
      try { window.close(); } catch {}
      location.replace("about:blank");
    });
  }

  // ---- open / close ----
  function open() {
    unlockAudio();
    nudge.classList.remove("on");
    wrap.classList.remove("walking"); orb.style.transform = "";
    wrap.classList.add("open"); panel.classList.add("on"); orb.setAttribute("aria-expanded", "true");
    if (!started) { started = true; beGlad(); }
    begin();
    later(260, () => (noteForm.hidden ? input : noteForm.elements.email).focus({ preventScroll: true }));
  }
  function close() {  // closing means quiet: cancel any voice still on its way, stop what's playing, pause the tour
    speakSeq++; stopShow();
    player?.pause();
    if (tourOn && !tourPaused) { tourPaused = true; tourRun++; pauseBtn.textContent = "▶ Resume"; }
    saveTour(null);  // closing means the tour won't pick itself up on the next page (Resume still works if they reopen here)
    document.documentElement.style.paddingRight = "";
    wrap.classList.remove("open", "speaking"); panel.classList.remove("on"); orb.setAttribute("aria-expanded", "false");
    look(0, 0); orb.focus({ preventScroll: true });
  }
  // tap mid-show = stop the show; otherwise the chat opens (or closes). The 🧠 in the chat's header shows how it thinks, live.
  orb.onclick = () => (window.TrinetraMusic?.playing ? stopShow() : has("open") ? close() : open());
  $(".brainbtn").onclick = () => openWorld(null, lastTrace);
  if (!BRAIN_ON) $(".brainbtn").hidden = true;
  $(".close").onclick = close;
  root.addEventListener("keydown", (e) => { if (e.key === "Escape" && has("open")) close(); });

  // never sit on top of the host page's own corner widgets (data-avoid): lift above them while they're on screen
  if (AVOID) {
    const base = () => (innerWidth <= 520 ? 16 : 20);
    const dodge = () => {
      let lift = base();
      const eyeW = orb.offsetWidth, eyeH = orb.offsetHeight, right = innerWidth - base(), left = right - eyeW;
      for (const el of document.querySelectorAll(AVOID)) {
        const r = el.getBoundingClientRect();
        const underEye = r.width && r.right > left - 8 && r.left < right + 8 && r.bottom > innerHeight - base() - eyeH - 8 && r.top < innerHeight;
        if (underEye) lift = Math.max(lift, innerHeight - r.top + 12);
      }
      wrap.style.bottom = lift + "px"; wrap.style.setProperty("--lift", lift + "px");
    };
    wrap.style.transition = "bottom .35s ease";
    addEventListener("scroll", dodge, { passive: true }); addEventListener("resize", dodge);
    dodge(); later(1500, dodge);
    new MutationObserver(() => later(20, dodge)).observe(wrap, { attributes: true, attributeFilter: ["class"] });
  }

  // Tarun can write back from his phone: his reply pops up in their chat while they're on the site
  async function checkInbox() {
    if (!token || document.hidden) return;
    try {
      const d = await (await fetch(`${API}/guest/inbox?token=${encodeURIComponent(token)}`)).json();
      if (!d.lines?.length) return;
      if (!has("open")) {
        const fresh = !beginning;  // not shown on this page yet: opening it loads the whole chat, these lines included
        open(); await beginning;
        if (fresh) { cheer(); beGlad(); speak(); return; }
      }
      for (const line of d.lines) add(line, "tri");
      cheer(); beGlad(); speak();
    } catch {}
  }
  setInterval(checkInbox, 8000);

  // leaving the site: TRINETRA forgets them (2 minutes later, unless another page of the site picks the visit up)
  addEventListener("pagehide", () => {
    if (token) navigator.sendBeacon?.(`${API}/guest/bye`, new Blob([JSON.stringify({ token })], { type: "text/plain" }));
  });
  if (store(sessionStorage, TOUR) && token) resumeTourHere();  // opens the panel, which picks the visit back up
  else if (token) fetch(`${API}/guest/resume`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ token }) })
    .then((r) => { if (r.status === 404) { token = null; store(sessionStorage, KEY, null); } }).catch(() => {});
})();
