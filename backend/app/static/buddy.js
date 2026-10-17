/* TRINETRA's character — one engine, two looks.
   pixel: a little pixel bot drawn on a 16×13 grid (frame-by-frame, like classic sprite mascots)
   fuzzy: a soft felt blob (SVG noise filter for the furry edge)
   Both wear TRINETRA's mark: a small third-eye gem on the forehead that glows when it listens or speaks.

   const b = TrinetraBuddy.create(el, { style: "pixel", palette: "saffron" });
   b.setEmotion("proud"); b.setActivity("speaking"); b.look(dx, dy); b.celebrate();
   Emotions:   neutral happy proud angry firm caring surprised sleepy
   Activities: idle listening thinking speaking sleeping walking watching
   Works in a normal page or inside a Shadow DOM (it brings its own CSS). Original design — TRINETRA's own. */
(() => {
  if (window.TrinetraBuddy) return;

  const PALETTES = {  // body · shadow · dark (eyes) · [fuzzy shine, default .38]
    saffron: ["#f0a83a", "#c47d1c", "#1d1206"],
    mint: ["#7ee0c3", "#4fb39a", "#0f2a24"],
    berry: ["#c77dff", "#9a4fd6", "#1b0d2b"],
    ocean: ["#4cc3e8", "#2a8db3", "#071a24"],
    coral: ["#ff7a6b", "#d6503f", "#2a0d0a"],
    red: ["#d7263d", "#9e1529", "#2a0a0e", 0.12],  // crimson; 4th = how much white shine the fuzzy blob gets (less keeps red red)
    night: ["#5b6cff", "#3a47c9", "#f1f3ff"],
    mono: ["#d9d9df", "#a9a9b3", "#141418"],
  };
  const EMOTIONS = ["neutral", "happy", "proud", "angry", "firm", "caring", "surprised", "sleepy"];
  const ACTIVITIES = ["idle", "listening", "thinking", "speaking", "sleeping", "walking", "watching"];
  const PINK = "#ff8fa3", GEM = "#ffd27a", GEM_HOT = "#fff1c2", GEM_RED = "#ff5b4f";

  const mix = (a, b, t) => {  // blend two #rrggbb colours
    const p = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
    const [x, y] = [p(a), p(b)];
    return "#" + x.map((v, i) => Math.round(v + (y[i] - v) * t).toString(16).padStart(2, "0")).join("");
  };

  // ---------- the pixel bot ----------
  const BODY = [  // B body · S shadow · A arm · F foot
    "....BBBBBBBB....",
    "..BBBBBBBBBBBB..",
    ".BBBBBBBBBBBBBB.",
    ".BBBBBBBBBBBBBB.",
    ".BBBBBBBBBBBBBB.",
    ".BBBBBBBBBBBBBB.",
    "AABBBBBBBBBBBBAA",
    "AABBBBBBBBBBBBAA",
    ".BBBBBBBBBBBBBB.",
    ".SBBBBBBBBBBBBS.",
    "..SSSSSSSSSSSS..",
    "...FF......FF...",
    "...FF......FF...",
  ];
  const sq = (x, y) => [[x, y], [x + 1, y], [x, y + 1], [x + 1, y + 1]];

  function pixelFace(s) {  // → [[x, y, colourKey]]
    const out = [], D = (pts, c = "D") => pts.forEach(([x, y]) => out.push([x, y, c]));
    const ox = Math.max(-1, Math.min(1, s.lookX)), oy = Math.max(-1, Math.min(1, s.lookY));
    const closed = () => D([[4, 5], [5, 5], [10, 5], [11, 5]]);
    const open = (dx = ox, dy = oy) => { D(sq(4 + dx, 4 + dy)); D(sq(10 + dx, 4 + dy)); };
    const act = s.activity, emo = s.emotion;
    if (act === "sleeping" || emo === "sleepy") closed();
    else if (s.blinking) closed();
    else if (act === "thinking") open(1, -1);
    else if (act === "listening") open(ox, 0);
    else if (emo === "happy" || emo === "proud") D([[3, 5], [4, 4], [5, 5], [10, 5], [11, 4], [12, 5]]);
    else if (emo === "angry") D([[4, 5], [5, 5], [10, 5], [11, 5], [3, 3], [4, 3], [5, 4], [12, 3], [11, 3], [10, 4]]);
    else if (emo === "firm") { open(ox, 0); D([[4, 2], [5, 2], [10, 2], [11, 2]]); }
    else open();
    if (emo === "caring" && act !== "sleeping") D([[2, 6], [3, 6], [12, 6], [13, 6]], "P");
    if (act === "speaking") D(s.talkFrame ? [[7, 7], [8, 7], [7, 8], [8, 8]] : [[7, 8], [8, 8]]);
    else if (emo === "surprised" || act === "listening" && emo === "surprised") D([[7, 7], [8, 7], [7, 8], [8, 8]]);
    else if (["happy", "proud", "caring"].includes(emo) && act !== "sleeping") D([[6, 7], [9, 7], [7, 8], [8, 8]]);
    else if (["firm", "angry"].includes(emo)) D([[6, 8], [9, 8], [7, 7], [8, 7]]);
    return out;
  }

  function pixelSVG(s) {
    let [body, shade, dark] = PALETTES[s.palette] || PALETTES.saffron;
    if (s.emotion === "angry") { body = mix(body, "#ff3b2f", 0.22); shade = mix(shade, "#b3241b", 0.22); }
    const lift = s.activity === "walking" && s.stepFrame;  // walking: one foot up
    const cell = (x, y, c) => `<rect x="${x}" y="${y}" width="1.04" height="1.04" fill="${c}"/>`;
    let rects = "";
    BODY.forEach((row, y) => [...row].forEach((ch, x) => {
      if (ch === ".") return;
      if (ch === "F") {
        const left = x < 8;
        if (lift && (left === (s.stepFrame === 1)) && y === 12) return;  // lifted foot
        return (rects += cell(x, y, shade));
      }
      rects += cell(x, y, ch === "S" ? shade : body);
    }));
    const glow = s.activity === "listening" ? GEM_RED : (s.activity === "speaking" || s.activity === "thinking") ? GEM_HOT : GEM;
    const gemOn = s.activity !== "sleeping" && s.emotion !== "sleepy";
    rects += `<rect class="tb-gem" x="7" y="2" width="2" height="1.04" fill="${gemOn ? glow : shade}" ${gemOn ? `filter="url(#${s.uid}g)"` : ""}/>`;
    for (const [x, y, k] of pixelFace(s)) rects += cell(x, y, k === "P" ? PINK : dark);
    return `<svg class="tb-svg" viewBox="-0.5 -2 17 17" shape-rendering="crispEdges" aria-hidden="true">
      <defs><filter id="${s.uid}g" x="-200%" y="-300%" width="500%" height="700%"><feGaussianBlur stdDeviation=".45" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
      <ellipse cx="8" cy="13.6" rx="5.5" ry=".7" fill="#000" opacity=".25" shape-rendering="auto"/>
      <g class="tb-body">${rects}</g></svg>`;
  }

  // ---------- the fuzzy blob ----------
  function fuzzySVG(s) {
    let [body, shade, dark] = PALETTES[s.palette] || PALETTES.saffron;
    if (s.emotion === "angry") { body = mix(body, "#ff3b2f", 0.22); shade = mix(shade, "#b3241b", 0.22); }
    const shine = (PALETTES[s.palette] || [])[3] ?? 0.38;  // reds wash out to pink with a strong white shine
    const hi = mix(body, "#ffffff", shine), u = s.uid;
    const fur = mix(body, "#ffffff", Math.min(0.5, shine + 0.12));  // fur speckles tinted with the body colour, not white
    const [fr, fg, fb] = [1, 3, 5].map((i) => (parseInt(fur.slice(i, i + 2), 16) / 255).toFixed(3));
    const lx = Math.max(-1, Math.min(1, s.lookX)) * 3.2, ly = Math.max(-1, Math.min(1, s.lookY)) * 2.4;
    const act = s.activity, emo = s.emotion;
    const eye = (cx, cy, rx = 4.6, ry = 6.6) =>
      `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="${dark}"/><ellipse cx="${cx - 1.4}" cy="${cy - 2.4}" rx="1.3" ry="1.7" fill="#fff" opacity=".85"/>`;
    const arc = (cx, cy, up) => `<path d="M${cx - 5} ${cy} Q${cx} ${cy + (up ? -6 : 4)} ${cx + 5} ${cy}" stroke="${dark}" stroke-width="2.6" fill="none" stroke-linecap="round"/>`;
    let face = "";
    const L = 38 + lx, R = 62 + lx, Y = 56 + ly;
    if (act === "sleeping" || emo === "sleepy" || s.blinking) face += arc(L, Y, false) + arc(R, Y, false);
    else if (act === "thinking") face += eye(41, 52) + eye(65, 52);
    else if (emo === "happy" || emo === "proud") face += arc(L, Y + 1, true) + arc(R, Y + 1, true);
    else if (emo === "surprised") face += eye(L, Y, 5.4, 7.8) + eye(R, Y, 5.4, 7.8);
    else if (emo === "firm") face += eye(L, Y + 1, 4.6, 4.6) + eye(R, Y + 1, 4.6, 4.6);
    else face += eye(L, Y) + eye(R, Y);
    if (emo === "angry" && act !== "sleeping") face += `<path d="M30 44 L44 49 M70 44 L56 49" stroke="${dark}" stroke-width="3" stroke-linecap="round"/>`;
    if (emo === "firm") face += `<path d="M31 46 L44 46 M56 46 L69 46" stroke="${dark}" stroke-width="2.6" stroke-linecap="round"/>`;
    if (emo === "caring" && act !== "sleeping") face += `<path d="M31 45 Q37 42 43 44 M57 44 Q63 42 69 45" stroke="${dark}" stroke-width="2" fill="none" stroke-linecap="round"/>
      <ellipse cx="29" cy="66" rx="6" ry="3.2" fill="${PINK}" opacity=".55"/><ellipse cx="71" cy="66" rx="6" ry="3.2" fill="${PINK}" opacity=".55"/>`;
    if (act === "speaking") face += `<ellipse cx="50" cy="70" rx="4.4" ry="${s.talkFrame ? 3.8 : 1.4}" fill="${dark}"/>`;
    else if (emo === "surprised") face += `<ellipse cx="50" cy="71" rx="3.2" ry="3.8" fill="${dark}"/>`;
    else if (["happy", "proud", "caring"].includes(emo)) face += `<path d="M44 68 Q50 74 56 68" stroke="${dark}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`;
    else if (["firm", "angry"].includes(emo)) face += `<path d="M44 72 Q50 67 56 72" stroke="${dark}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`;
    const glow = act === "listening" ? GEM_RED : (act === "speaking" || act === "thinking") ? GEM_HOT : GEM;
    const gemOn = act !== "sleeping" && emo !== "sleepy";
    return `<svg class="tb-svg" viewBox="0 0 100 100" aria-hidden="true">
      <defs>
        <radialGradient id="${u}b" cx="36%" cy="28%" r="75%"><stop offset="0" stop-color="${hi}"/><stop offset=".55" stop-color="${body}"/><stop offset="1" stop-color="${shade}"/></radialGradient>
        <filter id="${u}f" x="-15%" y="-15%" width="130%" height="130%">
          <feTurbulence type="fractalNoise" baseFrequency=".95" numOctaves="2" seed="4" result="n"/>
          <feDisplacementMap in="SourceGraphic" in2="n" scale="3.4" xChannelSelector="R" yChannelSelector="G" result="d"/>
          <feTurbulence type="fractalNoise" baseFrequency="2.4" numOctaves="1" seed="9" result="n2"/>
          <feColorMatrix in="n2" type="matrix" values="0 0 0 0 ${fr}  0 0 0 0 ${fg}  0 0 0 0 ${fb}  .9 0 0 0 -.38" result="lint"/>
          <feComposite in="lint" in2="d" operator="in" result="tex"/>
          <feMerge><feMergeNode in="d"/><feMergeNode in="tex"/></feMerge>
        </filter>
        <filter id="${u}g" x="-150%" y="-150%" width="400%" height="400%"><feGaussianBlur stdDeviation="1.6" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
      </defs>
      <ellipse cx="50" cy="89" rx="30" ry="4" fill="#000" opacity=".28"/>
      <g class="tb-body">
        <path filter="url(#${u}f)" fill="url(#${u}b)" d="M14 70 C9 46 26 21 50 21 C74 21 91 46 86 70 C84 83 70 87 50 87 C30 87 16 83 14 70 Z"/>
        <path d="M50 30 l3.2 4.4 -3.2 4.4 -3.2 -4.4 z" fill="${gemOn ? glow : shade}" ${gemOn ? `filter="url(#${u}g)"` : ""}/>
        <g class="tb-face">${face}</g>
      </g></svg>`;
  }

  // ---------- styles (injected once per document / shadow root) ----------
  const CSS = `
  .tb-root { position: relative; width: 100%; height: 100%; font-size: 14px; user-select: none; -webkit-user-select: none; }
  .tb-svg { width: 100%; height: 100%; display: block; overflow: visible; }
  .tb-body { transform-box: view-box; transform-origin: 50% 88%; }
  .tb-fuzzy .tb-body { animation: tb-breathe 3.4s ease-in-out infinite; }
  .tb-pixel .tb-body { animation: tb-pixbob 2.4s steps(2) infinite; }
  .tb-root.tb-walking .tb-body { animation: tb-step .32s steps(2) infinite; }
  .tb-fuzzy.tb-walking .tb-body { animation: tb-squash .36s ease-in-out infinite alternate; }
  .tb-root.tb-sleeping .tb-body { animation: tb-breathe 4.5s ease-in-out infinite; }
  .tb-e-angry .tb-svg { filter: drop-shadow(0 0 .25em rgba(255, 59, 47, .75)); }
  .tb-e-proud .tb-svg { filter: drop-shadow(0 0 .22em rgba(255, 210, 122, .7)); }
  .tb-proudspark { position: absolute; color: #ffd27a; font-size: .55em; pointer-events: none; display: none; animation: tb-twinkle 1.6s ease-in-out infinite; }
  .tb-e-proud .tb-proudspark { display: block; }
  .tb-proudspark.a { left: 4%; top: 2%; } .tb-proudspark.b { right: 2%; top: 14%; animation-delay: .8s; font-size: .4em; }
  @keyframes tb-twinkle { 50% { opacity: .2; transform: scale(.6) rotate(20deg); } }
  .tb-root.tb-hop .tb-svg { animation: tb-hop .42s ease-in-out 3; }
  .tb-root.tb-shake .tb-svg { animation: tb-shake .08s linear 8; }
  @keyframes tb-breathe { 50% { transform: scale(1.025, .975); } }
  @keyframes tb-pixbob { 50% { transform: translateY(.35px); } }
  @keyframes tb-step { 50% { transform: translateY(-.45px); } }
  @keyframes tb-squash { from { transform: scale(1.04, .95); } to { transform: scale(.97, 1.04) translateY(-3px); } }
  @keyframes tb-hop { 50% { transform: translateY(-16%) scale(1.04); } }
  @keyframes tb-shake { 25% { transform: translateX(-4%) rotate(-3deg); } 75% { transform: translateX(4%) rotate(3deg); } }
  .tb-z, .tb-dots, .tb-spark { position: absolute; pointer-events: none; font-family: -apple-system, system-ui, sans-serif; font-weight: 800; }
  .tb-z { right: -2%; top: -6%; color: #a9a7c7; font-size: 1em; display: none; }
  .tb-sleeping .tb-z { display: block; animation: tb-z 2.6s ease-in-out infinite; }
  @keyframes tb-z { 0% { opacity: 0; transform: translate(0, .4em); } 40% { opacity: 1; } 100% { opacity: 0; transform: translate(.6em, -.9em); } }
  .tb-dots { right: -14%; top: -10%; background: #fff; color: #333; border-radius: 1em; padding: .05em .45em .25em; font-size: .9em; line-height: 1; display: none; }
  .tb-thinking .tb-dots { display: block; animation: tb-dots 1.2s ease-in-out infinite; }
  @keyframes tb-dots { 50% { transform: translateY(-.15em); opacity: .75; } }
  .tb-root::before, .tb-root::after { content: ""; position: absolute; inset: 8%; border-radius: 50%; border: 2px solid #ff5b4f; opacity: 0; pointer-events: none; }
  .tb-listening::before { animation: tb-ripple 1.4s ease-out infinite; }
  .tb-listening::after { animation: tb-ripple 1.4s ease-out .7s infinite; }
  @keyframes tb-ripple { 0% { opacity: .55; transform: scale(.8); } 100% { opacity: 0; transform: scale(1.35); } }
  .tb-spark { color: #ffd27a; font-size: .9em; animation: tb-spark 1.1s ease-out forwards; }
  @keyframes tb-spark { 0% { opacity: 0; transform: translate(0, 0) scale(.4); } 30% { opacity: 1; } 100% { opacity: 0; transform: translate(var(--sx), var(--sy)) scale(1.1); } }
  @media (prefers-reduced-motion: reduce) { .tb-root *, .tb-root::before, .tb-root::after { animation: none !important; } }`;
  function injectCSS(node) {
    const root = node.getRootNode ? node.getRootNode() : document;
    const host = root === document ? document.head : root;
    if (host.querySelector?.("style[data-trinetra-buddy]")) return;
    const st = document.createElement("style"); st.dataset.trinetraBuddy = ""; st.textContent = CSS;
    host.appendChild(st);
  }

  let n = 0;
  function create(container, opts = {}) {
    injectCSS(container);
    const s = {
      uid: `tb${++n}x`, style: opts.style === "fuzzy" ? "fuzzy" : "pixel", palette: PALETTES[opts.palette] ? opts.palette : "saffron",
      emotion: "neutral", activity: "idle", lookX: 0, lookY: 0, blinking: false, talkFrame: 0, stepFrame: 0,
    };
    const still = opts.static || matchMedia("(prefers-reduced-motion: reduce)").matches;
    const root = document.createElement("div");
    root.className = "tb-root";
    root.innerHTML = `<div class="tb-art"></div><span class="tb-z">z z</span><span class="tb-dots">…</span>` +
      `<span class="tb-proudspark a">✦</span><span class="tb-proudspark b">✦</span>`;
    container.replaceChildren(root);
    const art = root.querySelector(".tb-art");
    art.style.cssText = "width:100%;height:100%";
    const draw = () => {
      art.innerHTML = s.style === "fuzzy" ? fuzzySVG(s) : pixelSVG(s);
      root.className = `tb-root tb-${s.style} tb-${s.activity} tb-e-${s.emotion}` + (root._extra || "");
    };
    const fit = () => { root.style.fontSize = Math.max(9, root.clientWidth * 0.2) + "px"; };
    const timers = [];
    if (!still) {
      const blinkLoop = () => {
        timers[0] = setTimeout(() => {
          if (!["sleeping", "listening"].includes(s.activity) && s.emotion !== "sleepy") {
            s.blinking = true; draw(); setTimeout(() => { s.blinking = false; draw(); }, 130);
          }
          blinkLoop();
        }, 2400 + Math.random() * 3600);
      };
      blinkLoop();
      timers[1] = setInterval(() => {  // talking mouth and walking feet
        if (s.activity === "speaking") { s.talkFrame ^= 1; draw(); }
        else if (s.activity === "walking") { s.stepFrame = s.stepFrame === 1 ? 2 : 1; draw(); }
      }, 150);
    }
    const ro = window.ResizeObserver ? new ResizeObserver(fit) : null;
    ro?.observe(root);
    draw(); fit();

    const api = {
      el: root,
      get state() { return { ...s }; },
      setStyle(v) { if (v !== s.style) { s.style = v === "fuzzy" ? "fuzzy" : "pixel"; draw(); } return api; },
      setPalette(v) { if (PALETTES[v] && v !== s.palette) { s.palette = v; draw(); } return api; },
      setEmotion(v) { v = EMOTIONS.includes(v) ? v : "neutral"; if (v !== s.emotion) { s.emotion = v; draw(); } return api; },
      setActivity(v) {
        v = ACTIVITIES.includes(v) ? v : "idle";
        if (v !== s.activity) { s.activity = v; s.talkFrame = 0; s.stepFrame = 0; draw(); }
        return api;
      },
      look(dx = 0, dy = 0) {  // screen-pixel direction → eyes shift a step
        const m = Math.hypot(dx, dy);
        const nx = m < 12 ? 0 : Math.round(dx / Math.max(m, 1) * 1.2), ny = m < 12 ? 0 : Math.round(dy / Math.max(m, 1) * 1.2);
        if (nx !== s.lookX || ny !== s.lookY) { s.lookX = nx; s.lookY = ny; draw(); }
        return api;
      },
      blink() { s.blinking = true; draw(); setTimeout(() => { s.blinking = false; draw(); }, 130); return api; },
      celebrate() {
        root._extra = " tb-hop"; draw();
        for (let i = 0; i < 6; i++) {
          const sp = document.createElement("span"); sp.className = "tb-spark"; sp.textContent = "✦";
          const a = (i / 6) * Math.PI * 2;
          sp.style.cssText = `left:45%;top:35%;--sx:${Math.cos(a) * 1.6}em;--sy:${Math.sin(a) * 1.6 - .4}em;animation-delay:${i * 40}ms`;
          root.appendChild(sp); setTimeout(() => sp.remove(), 1300);
        }
        setTimeout(() => { root._extra = ""; draw(); }, 1300);
        return api;
      },
      shake() { root._extra = " tb-shake"; draw(); setTimeout(() => { root._extra = ""; draw(); }, 700); return api; },
      destroy() { clearTimeout(timers[0]); clearInterval(timers[1]); ro?.disconnect(); root.remove(); },
    };
    return api;
  }

  window.TrinetraBuddy = { create, PALETTES, EMOTIONS, ACTIVITIES };
})();
