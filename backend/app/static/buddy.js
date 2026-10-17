/* TRINETRA's character — one engine, two looks.
   pixel: a little pixel bot drawn on a 16×13 grid (frame-by-frame, like classic sprite mascots)
   fuzzy: a soft felt blob (SVG noise filter for the furry edge)
   Both wear TRINETRA's mark: a small third-eye gem on the forehead that glows when it listens or speaks.

   const b = TrinetraBuddy.create(el, { style: "pixel", palette: "saffron" });
   b.setEmotion("proud"); b.setActivity("speaking"); b.look(dx, dy); b.celebrate();
   Emotions:   neutral happy proud excited angry firm caring shy surprised sad sleepy
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
    pink: ["#ff8cc6", "#e2589f", "#2a0a1c", 0.25],  // her colours (the dance partner)
  };
  const EMOTIONS = ["neutral", "happy", "proud", "excited", "angry", "firm", "caring", "shy", "surprised", "sad", "sleepy"];
  const ACTIVITIES = ["idle", "listening", "thinking", "speaking", "sleeping", "walking", "watching"];
  const BOW = "#ff3d8b", BOW_KNOT = "#ffc2dc";
  const PINK = "#ff8fa3", TEAR = "#7cc7ff", GEM = "#ffd27a", GEM_HOT = "#fff1c2", GEM_RED = "#ff5b4f";

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
    const dozing = act === "sleeping" || (emo === "sleepy" && ["idle", "sleeping"].includes(act));  // talking / watching: eyes open
    const shine = () => D([[4 + ox, 4 + oy], [10 + ox, 4 + oy]], "W");  // a glint in each eye
    if (dozing) closed();
    else if (s.blinking) closed();
    else if (act === "thinking") open(1, -1);
    else if (act === "listening") open(ox, 0);
    else if (emo === "happy") D([[3, 5], [4, 4], [5, 5], [10, 5], [11, 4], [12, 5]]);
    else if (emo === "proud") { open(); shine(); }
    else if (emo === "excited") { D([[3, 3], [4, 3], [5, 3], [3, 4], [4, 4], [5, 4], [3, 5], [4, 5], [5, 5], [10, 3], [11, 3], [12, 3], [10, 4], [11, 4], [12, 4], [10, 5], [11, 5], [12, 5]]); D([[3, 3], [10, 3]], "W"); }
    else if (emo === "sad") { open(ox, 1); D([[3, 3], [4, 2], [12, 3], [11, 2]]); D([[4, 7], [4, 8]], "T"); }
    else if (emo === "shy") { open(-1, 1); D([[2, 7], [3, 7], [12, 7], [13, 7]], "P"); }
    else if (emo === "angry") D([[4, 5], [5, 5], [10, 5], [11, 5], [3, 3], [4, 3], [5, 4], [12, 3], [11, 3], [10, 4]]);
    else if (emo === "firm") { open(ox, 0); D([[4, 2], [5, 2], [10, 2], [11, 2]]); }
    else open();
    if (s.girl && !dozing && !s.blinking && !["happy", "angry", "excited"].includes(emo)) D([[3, 3], [12, 3]]);  // her lashes
    if (emo === "caring" && act !== "sleeping") D([[2, 6], [3, 6], [12, 6], [13, 6]], "P");
    if (act === "speaking") D(s.talkFrame ? [[7, 7], [8, 7], [7, 8], [8, 8]] : [[7, 8], [8, 8]]);
    else if (emo === "surprised" || act === "listening" && emo === "surprised") D([[7, 7], [8, 7], [7, 8], [8, 8]]);
    else if (emo === "excited" && !dozing) D([[6, 7], [7, 7], [8, 7], [9, 7], [6, 8], [9, 8], [7, 9], [8, 9]]);
    else if (["happy", "proud", "caring"].includes(emo) && !dozing) D([[6, 7], [9, 7], [7, 8], [8, 8]]);
    else if (emo === "sad" && !dozing) D([[7, 8], [8, 8], [6, 9], [9, 9]]);
    else if (emo === "shy" && !dozing) D([[7, 9], [8, 9]]);
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
      if (ch === "A" && ((x < 8 && /^(up|lup)$/.test(s.arms)) || (x >= 8 && /^(up|rup)$/.test(s.arms)))) return;  // that arm is up
      if (ch === "F") {
        const left = x < 8;
        if (lift && (left === (s.stepFrame === 1)) && y === 12) return;  // lifted foot
        return (rects += cell(x, y, shade));
      }
      rects += cell(x, y, ch === "S" ? shade : body);
    }));
    const suit = s.suit, J = suit?.jacket, sleeve = (x) => (suit ? J : x === 0 ? shade : body);
    if (suit) {  // a suit: jacket over the lower body and sleeves, white collar, a tie (gold for the boss) and a badge
      const on = (x, y, c) => (rects += cell(x, y, c));
      for (const [x0, x1, y] of [[1, 4, 9], [11, 14, 9], [2, 13, 10]]) for (let x = x0; x <= x1; x++) on(x, y, J);
      for (const [x, y] of [[0, 6], [1, 6], [0, 7], [1, 7], [14, 6], [15, 6], [14, 7], [15, 7]])
        if (!((x < 8 && /^(up|lup)$/.test(s.arms)) || (x >= 8 && /^(up|rup)$/.test(s.arms)))) on(x, y, J);
      on(6, 10, "#f4f4f4"); on(9, 10, "#f4f4f4"); on(7, 10, suit.tie); on(8, 10, suit.tie); on(7, 11, mix(suit.tie, "#000000", 0.25));
      if (suit.badge) on(12, 9, suit.badge);
    }
    const UP = [[0, 5], [0, 4], [0, 3], [0, 2], [1, 1], [1, 0], [1, -1], [2, -1]];  // an arm raised beside the head, hand up top
    if (/^(up|lup)$/.test(s.arms)) for (const [x, y] of UP) rects += cell(x, y, sleeve(x));
    if (/^(up|rup)$/.test(s.arms)) for (const [x, y] of UP) rects += cell(15 - x, y, sleeve(x));
    if (s.girl) {  // a bow on her head
      for (const [x, y] of [[8, -1], [9, -1], [11, -1], [12, -1], [8, 0], [9, 0], [11, 0], [12, 0]]) rects += cell(x, y, BOW);
      rects += cell(10, 0, BOW_KNOT) + cell(10, -1, BOW);
    }
    const glow = s.activity === "listening" ? GEM_RED : (s.activity === "speaking" || s.activity === "thinking") ? GEM_HOT : GEM;
    const gemOn = s.activity !== "sleeping" && !(s.emotion === "sleepy" && s.activity === "idle");
    rects += `<rect class="tb-gem" x="7" y="2" width="2" height="1.04" fill="${gemOn ? glow : shade}" ${gemOn ? `filter="url(#${s.uid}g)"` : ""}/>`;
    for (const [x, y, k] of pixelFace(s)) rects += cell(x, y, k === "P" ? PINK : k === "W" ? "#ffffff" : k === "T" ? TEAR : dark);
    return `<svg class="tb-svg" viewBox="-0.5 -2 17 17" shape-rendering="crispEdges" aria-hidden="true">
      <defs><filter id="${s.uid}g" x="-200%" y="-300%" width="500%" height="700%"><feGaussianBlur stdDeviation=".45" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
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
    const dozing = act === "sleeping" || (emo === "sleepy" && ["idle", "sleeping"].includes(act));  // talking / watching: eyes open
    const glint = (cx, cy) => `<circle cx="${cx + 1.6}" cy="${cy + 1.8}" r=".9" fill="#fff" opacity=".9"/>`;
    if (dozing || s.blinking) face += arc(L, Y, false) + arc(R, Y, false);
    else if (act === "thinking") face += eye(41, 52) + eye(65, 52);
    else if (emo === "happy") face += arc(L, Y + 1, true) + arc(R, Y + 1, true);
    else if (emo === "proud") face += eye(L, Y) + eye(R, Y) + glint(L, Y) + glint(R, Y);
    else if (emo === "excited") face += eye(L, Y - 1, 5.6, 8) + eye(R, Y - 1, 5.6, 8) + glint(L, Y - 1) + glint(R, Y - 1);
    else if (emo === "shy") face += eye(L - 3, Y + 3, 4.2, 5.6) + eye(R - 3, Y + 3, 4.2, 5.6)
      + `<ellipse cx="28" cy="67" rx="7" ry="3.6" fill="${PINK}" opacity=".75"/><ellipse cx="72" cy="67" rx="7" ry="3.6" fill="${PINK}" opacity=".75"/>`;
    else if (emo === "sad") face += eye(L, Y + 2, 4.4, 6) + eye(R, Y + 2, 4.4, 6)
      + `<path d="M30 47 L43 43 M70 47 L57 43" stroke="${dark}" stroke-width="2.4" stroke-linecap="round"/>`
      + `<path d="M${L - 3} ${Y + 8} q-1.6 3.4 0 5.4 q1.6 -2 0 -5.4z" fill="${TEAR}" opacity=".9"/>`;
    else if (emo === "surprised") face += eye(L, Y, 5.4, 7.8) + eye(R, Y, 5.4, 7.8);
    else if (emo === "firm") face += eye(L, Y + 1, 4.6, 4.6) + eye(R, Y + 1, 4.6, 4.6);
    else face += eye(L, Y) + eye(R, Y);
    if (s.girl && !dozing && !s.blinking && !["happy", "angry"].includes(emo))
      face += `<path d="M${L - 4} ${Y - 5} l-3.4 -2.6 M${L - 2} ${Y - 6.4} l-1.6 -3 M${R + 4} ${Y - 5} l3.4 -2.6 M${R + 2} ${Y - 6.4} l1.6 -3" stroke="${dark}" stroke-width="1.6" stroke-linecap="round"/>`;
    if (emo === "angry" && act !== "sleeping") face += `<path d="M30 44 L44 49 M70 44 L56 49" stroke="${dark}" stroke-width="3" stroke-linecap="round"/>`;
    if (emo === "firm") face += `<path d="M31 46 L44 46 M56 46 L69 46" stroke="${dark}" stroke-width="2.6" stroke-linecap="round"/>`;
    if (emo === "caring" && act !== "sleeping") face += `<path d="M31 45 Q37 42 43 44 M57 44 Q63 42 69 45" stroke="${dark}" stroke-width="2" fill="none" stroke-linecap="round"/>
      <ellipse cx="29" cy="66" rx="6" ry="3.2" fill="${PINK}" opacity=".55"/><ellipse cx="71" cy="66" rx="6" ry="3.2" fill="${PINK}" opacity=".55"/>`;
    if (act === "speaking") face += `<ellipse cx="50" cy="70" rx="4.4" ry="${s.talkFrame ? 3.8 : 1.4}" fill="${dark}"/>`;
    else if (emo === "surprised") face += `<ellipse cx="50" cy="71" rx="3.2" ry="3.8" fill="${dark}"/>`;
    else if (emo === "excited" && !dozing) face += `<path d="M42 67 Q50 79 58 67 Z" fill="${dark}"/><path d="M45 72 Q50 76 55 72" stroke="${PINK}" stroke-width="2" fill="none"/>`;
    else if (emo === "shy" && !dozing) face += `<path d="M45 71 Q48 73.5 50 71.5 Q52 73.5 55 71" stroke="${dark}" stroke-width="2" fill="none" stroke-linecap="round"/>`;
    else if (emo === "sad" && !dozing) face += `<path d="M44 73 Q50 67 56 73" stroke="${dark}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`;
    else if (["happy", "proud", "caring"].includes(emo)) face += `<path d="M44 68 Q50 74 56 68" stroke="${dark}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`;
    else if (["firm", "angry"].includes(emo)) face += `<path d="M44 72 Q50 67 56 72" stroke="${dark}" stroke-width="2.4" fill="none" stroke-linecap="round"/>`;
    const glow = act === "listening" ? GEM_RED : (act === "speaking" || act === "thinking") ? GEM_HOT : GEM;
    const gemOn = !dozing;
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
      <g class="tb-body">
        <path filter="url(#${u}f)" fill="url(#${u}b)" d="M14 70 C9 46 26 21 50 21 C74 21 91 46 86 70 C84 83 70 87 50 87 C30 87 16 83 14 70 Z"/>
        <path d="M50 30 l3.2 4.4 -3.2 4.4 -3.2 -4.4 z" fill="${gemOn ? glow : shade}" ${gemOn ? `filter="url(#${u}g)"` : ""}/>
        ${s.suit ? `<path d="M15 76 C19 85 33 87 50 87 C67 87 81 85 85 76 C76 80 68 81 62 80 L50 87 L38 80 C32 81 24 80 15 76 Z" fill="${s.suit.jacket}"/>
          <path d="M38 80 L50 87 L62 80 Z" fill="#f4f4f4"/><path d="M48.4 80.6 L51.6 80.6 L52.6 85 L50 87.4 L47.4 85 Z" fill="${s.suit.tie}"/>
          ${s.suit.badge ? `<circle cx="70" cy="81" r="1.8" fill="${s.suit.badge}"/>` : ""}` : ""}
        <g class="tb-face">${face}</g>
        ${s.girl ? `<path d="M66 25 L55 17 L56 32 Z M66 25 L77 17 L76 32 Z" fill="${BOW}" stroke="${mix(BOW, "#000000", 0.25)}" stroke-width="1"/><circle cx="66" cy="25" r="3.2" fill="${BOW_KNOT}"/>` : ""}
      </g></svg>`;
  }

  // ---------- instruments it can hold (pixel art on a half-cell grid, drawn over the body) ----------
  function canvas() {
    const out = [], r2 = (v) => Math.round(v * 2) / 2;
    const px = (x, y, c, w = 0.5, h = 0.5, attr = "") => out.push(`<rect x="${x}" y="${y}" width="${w + 0.02}" height="${h + 0.02}" fill="${c}"${attr}/>`);
    const P = {
      px, raw: (s) => out.push(s),
      ell(cx, cy, rx, ry, c) {
        for (let y = r2(cy - ry); y <= cy + ry; y += 0.5) for (let x = r2(cx - rx); x <= cx + rx; x += 0.5)
          if (((x + 0.25 - cx) / rx) ** 2 + ((y + 0.25 - cy) / ry) ** 2 <= 1) px(x, y, c);
      },
      body(cx, cy, rx, ry, c, edge) { P.ell(cx, cy, rx + 0.5, ry + 0.5, edge); P.ell(cx, cy, rx, ry, c); },
      line(x0, y0, x1, y1, c, t = 0.5) {
        const n = Math.max(1, Math.ceil(Math.hypot(x1 - x0, y1 - y0) / 0.35));
        for (let i = 0; i <= n; i++) px(r2(x0 + (x1 - x0) * i / n - t / 2), r2(y0 + (y1 - y0) * i / n - t / 2), c, t, t);
      },
      thin(x0, y0, x1, y1, c, w = 0.22, attr = "") { out.push(`<line x1="${x0}" y1="${y0}" x2="${x1}" y2="${y1}" stroke="${c}" stroke-width="${w}"${attr}/>`); },
      group(attr, fn) { out.push(`<g ${attr}>`); fn(); out.push("</g>"); },
      svg: () => out.join(""),
    };
    return P;
  }
  const WOOD = "#d98a3a", WOOD_EDGE = "#7a4310", NECK = "#6b3a14", HEAD = "#3b1f0a", GOLD = "#e6ad35", GOLD_EDGE = "#9a6a12", STRING = "#f5e6c8";
  function guitarLike(P, o) {  // a body over the belly, the neck up to the right
    const { body, edge, neck = NECK, s = 1, hole = true, to = [15.6, 5.2] } = o;  // the neck passes under its right eye
    P.body(5, 9.6, 3.2 * s, 2.6 * s, body, edge);
    P.body(5 + 2.6 * s, 9.6 - 1.4 * s, 2.2 * s, 1.9 * s, body, edge);
    P.ell(5 + 2.6 * s, 9.6 - 1.4 * s, 2.2 * s, 1.9 * s, body);
    if (hole) P.ell(5 + 1.2 * s, 9.6 - 0.7 * s, 0.8 * s, 0.8 * s, "#2b1405");
    if (o.extra) o.extra(P);
    P.line(5 + 3.8 * s, 9.6 - 2.1 * s, to[0], to[1], neck, 1);
    P.px(to[0] - 0.2, to[1] - 1, HEAD, 1.5, 1.2);
    P.px(to[0] - 0.2, to[1] - 1.5, "#e8e8e8"); P.px(to[0] + 0.8, to[1] - 1.5, "#e8e8e8");
    P.px(3.6, 10.2, "#4a2408", 1.4, 0.5);
    P.group('class="tb-strings"', () => P.thin(4.3, 10.4, to[0], to[1] - 0.1, STRING, 0.2, ' opacity=".85"'));
  }
  const PROPS = {
    guitar: (P) => guitarLike(P, { body: WOOD, edge: WOOD_EDGE }),
    electric: (P) => guitarLike(P, { body: "#e63946", edge: "#7d1020", neck: "#2c2018", hole: false,
      extra: (Q) => { Q.px(5.5, 8.6, "#f2f2f2", 1.5, 1.5); Q.px(4.5, 9.6, "#111", 1.5, 0.5); Q.px(6, 8.1, "#111", 1.5, 0.5); } }),
    bass: (P) => guitarLike(P, { body: "#6a3fd0", edge: "#2e1670", neck: "#2c2018", hole: false, to: [16.6, 4.4],
      extra: (Q) => { Q.px(4.6, 9.4, "#111", 1.5, 0.5); Q.px(6, 8.4, "#111", 1.5, 0.5); } }),
    ukulele: (P) => guitarLike(P, { body: "#e9b56e", edge: "#8a5a1e", s: 0.68, to: [13.4, 6.4] }),
    banjo: (P) => {
      P.body(5.4, 9.4, 2.8, 2.8, "#f6f1e7", "#9aa0aa"); P.px(5, 9.2, "#6b4a2a", 1, 0.5);
      P.line(7.8, 8.4, 15.8, 5, "#7a4a1f", 1); P.px(15.6, 4, HEAD, 1.5, 1.2);
      P.group('class="tb-strings"', () => P.thin(4.4, 10, 15.6, 5, STRING, 0.2));
    },
    sitar: (P) => {
      P.body(4.2, 10.2, 3, 2.6, "#b8662a", "#5e2c0c"); P.ell(4.2, 10.2, 1.6, 1.3, "#f2c46d"); P.ell(4.2, 10.2, 1.1, 0.8, "#b8662a");
      P.line(5.6, 8.4, 14.4, -0.4, "#8a4f1f", 1);
      for (let i = 1; i < 8; i++) P.px(5.6 + i * 1.1, 8.4 - i * 1.1, GOLD);
      P.body(15, -1, 0.9, 0.9, "#b8662a", "#5e2c0c");
      P.group('class="tb-strings"', () => P.thin(3.6, 11, 14.4, -0.2, STRING, 0.18));
    },
    violin: (P) => {
      P.body(11.6, 7.8, 1.9, 1.2, "#b0561f", "#4d1f06"); P.px(11.4, 7.6, "#2a1004");
      P.line(13.2, 7, 16.2, 5.6, "#2a1508", 0.5); P.px(16.2, 5, "#2a1508", 0.5, 0.8);
      P.group('class="tb-bowstroke"', () => { P.thin(8.6, 4.6, 16.6, 9.4, "#f3e9d2", 0.25); P.px(16.2, 9, "#3b1f0a", 0.8, 0.6); });
    },
    cello: (P) => {
      P.body(2.4, 10.4, 2.4, 1.9, "#9a4a1a", "#3d1606"); P.body(2.4, 7.9, 1.9, 1.4, "#9a4a1a", "#3d1606");  // beside it, clear of its eyes
      P.px(1.4, 9.6, "#2a1004"); P.px(3, 9.6, "#2a1004");
      P.line(2.4, 6.6, 2.4, 0.6, "#2a1508", 0.6); P.px(2, 0, "#2a1508", 0.8, 0.8);
      P.thin(2.4, 12.4, 2.4, 13.6, "#9aa0aa", 0.25);
      P.group('class="tb-bowstroke"', () => { P.thin(0.4, 9.4, 10.6, 9.4, "#f3e9d2", 0.25); P.px(10.2, 9.1, "#3b1f0a", 0.8, 0.6); });
    },
    piano: (P) => {
      P.px(-0.6, 9.3, "#3a3a46", 17.2, 0.4); P.px(-0.6, 9.7, "#1b1b22", 17.2, 3.5);
      for (let i = 0; i < 17; i++) P.raw(`<rect class="key" data-k="${i}" x="${i - 0.45}" y="10.05" width=".9" height="2.75" fill="#f7f7f2"/>`);
      for (let i = 0; i < 16; i++) if ([0, 1, 3, 4, 5].includes(i % 7)) P.px(i + 0.22, 10.05, "#111", 0.56, 1.6);
    },
    harp: (P) => {
      P.line(15.6, -0.6, 15.6, 12.8, "#d9a63c", 0.7); P.line(9.4, 0.8, 12.6, -0.8, "#d9a63c", 0.6); P.line(12.6, -0.8, 15.6, -0.6, "#d9a63c", 0.6);
      P.line(9.4, 0.8, 13.4, 12.6, "#a0582a", 0.8);
      for (let k = 0; k < 7; k++) {
        const x = 10.3 + k * 0.72, top = k < 4 ? 0.6 - k * 0.4 : -0.6, bot = Math.min(12.4, 0.8 + (x - 9.4) * 2.9);
        P.raw(`<line class="str" data-k="${k}" x1="${x}" y1="${top}" x2="${x}" y2="${bot}" stroke="#f3ead2" stroke-width=".2"/>`);
      }
    },
    flute: (P) => { P.line(8.2, 7.6, 17.4, 6.2, "#d4dbe5", 0.6); for (let i = 1; i < 6; i++) P.px(10 + i * 1.2, 7.3 - i * 0.18, "#5d6673"); P.px(8.6, 7.2, "#2a2f38"); },
    sax: (P) => {
      P.px(8.3, 7.4, "#111", 0.7, 0.6); P.line(8.9, 7.8, 10.4, 8.6, GOLD, 0.6); P.line(10.4, 8.6, 12.6, 12.2, GOLD, 1); P.line(12.6, 12.2, 13.8, 12.4, GOLD, 0.8);
      P.body(14.6, 11.2, 1.1, 1.4, GOLD, GOLD_EDGE); P.ell(14.8, 10.8, 0.5, 0.6, "#5a3a08");
      for (let i = 0; i < 4; i++) P.px(10.6 + i * 0.5, 9.4 + i * 0.8, "#7a5208");
    },
    trumpet: (P) => {
      P.px(8.2, 7.4, "#9aa0aa", 0.6, 0.5); P.line(8.8, 7.6, 14.2, 7.6, GOLD, 0.5); P.line(10, 8.6, 13.6, 8.6, GOLD, 0.5);
      P.px(10.6, 6.4, GOLD_EDGE, 2, 1.4); for (const x of [10.7, 11.4, 12.1]) P.px(x, 5.8, "#d8dde4", 0.5, 0.6);
      P.ell(15.2, 7.6, 1, 1.5, GOLD); P.ell(16, 7.6, 0.4, 1.7, "#f6cf6a");
    },
    xylophone: (P) => {
      P.px(-0.4, 11.4, "#5a3010", 17, 0.4); P.px(-0.4, 12.6, "#5a3010", 17, 0.4);
      const cols = ["#ff5b5b", "#ff9a3c", "#ffd23c", "#7ed957", "#3cc8ff", "#5b7cff", "#a65bff", "#ff5bc8"];
      cols.forEach((c, i) => P.raw(`<rect class="bar" data-k="${i}" x="${0.2 + i * 2.05}" y="${9.4 + i * 0.14}" width="1.6" height="${3.6 - i * 0.24}" fill="${c}"/>`));
      P.group('class="tb-sticks"', () => { P.thin(1, 7, 3.2, 9.6, "#c8a070", 0.3); P.ell(3.4, 9.7, 0.4, 0.4, "#f2f2f2"); P.thin(15, 7, 12.8, 9.6, "#c8a070", 0.3); P.ell(12.6, 9.7, 0.4, 0.4, "#f2f2f2"); });
    },
    drums: (P) => {
      P.group('data-k="C"', () => { P.thin(15.4, 7, 15.4, 12.8, "#9aa0aa", 0.25); P.ell(15.4, 6.8, 1.9, 0.4, "#e6b13a"); });
      P.group('data-k="K"', () => { P.body(8, 11.4, 2.6, 2.2, "#f4f4f4", "#c0392b"); P.ell(8, 11.4, 0.9, 0.9, "#c0392b"); });
      P.group('data-k="S"', () => { P.px(1.2, 10.2, "#c0392b", 3.6, 1.2); P.ell(3, 10.1, 1.8, 0.5, "#ececec"); });
      P.group('data-k="T"', () => { P.px(11.2, 9.4, "#c0392b", 3, 1); P.ell(12.7, 9.3, 1.5, 0.45, "#ececec"); });
      P.group('class="tb-sticks"', () => { P.thin(1.2, 6.4, 3.2, 9.6, "#c8a070", 0.3); P.thin(14.8, 6.4, 12.4, 9, "#c8a070", 0.3); });
    },
  };
  function propSVG(name) {
    const draw = PROPS[name]; if (!draw) return "";
    const P = canvas(); draw(P);
    return `<svg viewBox="-0.5 -2 17 17" shape-rendering="crispEdges" aria-hidden="true">${P.svg()}</svg>`;
  }
  const WHITE = [0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6];  // pitch class → white key in the octave
  const whiteOf = (m) => Math.floor(m / 12) * 7 + WHITE[m % 12];

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
  .tb-e-excited .tb-svg { animation: tb-bounce .42s ease-in-out infinite; filter: drop-shadow(0 0 .2em rgba(255, 241, 194, .7)); }
  .tb-e-excited .tb-proudspark { display: block; }
  .tb-e-sad .tb-svg { transform: translateY(.06em) scaleY(.96); filter: saturate(.7) brightness(.92); transition: transform .4s, filter .4s; }
  .tb-e-shy .tb-svg { transform: rotate(-7deg) scale(.96); transition: transform .4s; }
  @keyframes tb-bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(-.12em) scale(1.03, .97); } }
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
  /* the shadow: on the ground, never rotates — it shrinks while the body is in the air, slides with a sway */
  .tb-shadow { position: absolute; left: 18%; width: 64%; top: 88.5%; height: 6%; border-radius: 50%; pointer-events: none;
    background: radial-gradient(closest-side, rgba(0, 0, 0, .34), rgba(0, 0, 0, .12) 70%, rgba(0, 0, 0, 0));
    transition: translate .22s cubic-bezier(.3, 1.4, .5, 1), scale .22s, opacity .22s; }
  .tb-fuzzy > .tb-shadow { left: 20%; width: 60%; top: 86%; }
  .tb-e-excited > .tb-shadow { animation: tb-shadow-bob .42s ease-in-out infinite; }
  .tb-root.tb-hop > .tb-shadow { animation: tb-shadow-up .42s ease-in-out 3; }
  .tb-root.tb-m-hop > .tb-shadow { animation: tb-shadow-up .5s ease-out; }
  .tb-root.tb-m-jump > .tb-shadow { animation: tb-shadow-up .55s ease-out 3; }
  .tb-m-sway-l > .tb-shadow { translate: -14% 0; }
  .tb-m-sway-r > .tb-shadow { translate: 14% 0; }
  .tb-m-step-in > .tb-shadow { translate: -25% 0; }
  .tb-partner .tb-m-step-in > .tb-shadow { translate: 25% 0; }
  .tb-m-dip > .tb-shadow { scale: 1.12 1; }
  .tb-m-leave > .tb-shadow { translate: -110% 0; opacity: 0; transition: translate .6s, opacity .6s; }
  @keyframes tb-shadow-up { 40% { scale: .55; opacity: .45; } 80% { scale: 1.08 1; } }
  @keyframes tb-shadow-bob { 50% { scale: .9; opacity: .8; } }
  /* shows: holding an instrument, dancing, little moves */
  .tb-mover { position: absolute; inset: 0; transform-origin: 50% 88%; transition: transform .22s cubic-bezier(.3, 1.4, .5, 1), opacity .5s; }
  .tb-propbox { position: absolute; inset: 0; pointer-events: none; transform-origin: 40% 70%; transition: transform .09s; }
  .tb-propbox svg { width: 100%; height: 100%; display: block; overflow: visible; }
  .tb-fuzzy > .tb-mover > .tb-propbox { transform: scale(.9) translateY(4%); }
  .tb-root.tb-beat > .tb-mover { transform: translateY(-3%) scale(1.03, .97); transition-duration: .06s; }
  .tb-root.tb-strum > .tb-mover > .tb-propbox { transform: rotate(-3deg); }
  .tb-propbox .key.on, .tb-propbox .bar.on { fill: #ffd27a; }
  .tb-propbox .str.on { stroke: #ffd27a; stroke-width: .4; }
  .tb-propbox g.on { filter: brightness(1.5); }
  .tb-propbox .tb-bowstroke, .tb-propbox .tb-sticks { transition: transform .14s; }
  .tb-flip .tb-bowstroke { transform: translate(-1.8px, -1px); }
  .tb-p-cello.tb-flip .tb-bowstroke { transform: translate(2.4px, 0); }
  .tb-flip .tb-sticks { transform: translateY(.7px); }
  .tb-m-sway-l > .tb-mover { transform: translateX(-9%) rotate(-9deg); }
  .tb-m-sway-r > .tb-mover { transform: translateX(9%) rotate(9deg); }
  .tb-m-step-in > .tb-mover { transform: translateX(-16%) rotate(-4deg); }
  .tb-partner .tb-m-step-in > .tb-mover { transform: translateX(16%) rotate(4deg); }
  .tb-m-dip > .tb-mover { transform: translateY(8%) scale(1.1, .86); }
  .tb-m-hop > .tb-mover { animation: tb-jump .5s ease-out; }
  .tb-m-arms > .tb-mover { transform: translateY(-4%); }
  .tb-m-wave > .tb-mover { transform: rotate(-6deg); }
  .tb-m-spin > .tb-mover { animation: tb-spin .6s ease-in-out 2; }
  .tb-m-laugh > .tb-mover { animation: tb-giggle .2s ease-in-out 12; }
  .tb-m-jump > .tb-mover { animation: tb-jump .55s ease-out 3; }
  .tb-m-cry > .tb-mover { animation: tb-sob .5s ease-in-out 5; }
  .tb-m-leave > .tb-mover { transform: translateX(-70%); opacity: 0; transition: transform .6s, opacity .6s; }
  @keyframes tb-jump { 40% { transform: translateY(-28%) scale(.95, 1.07); } 80% { transform: translateY(0) scale(1.07, .93); } }
  @keyframes tb-spin { to { transform: rotate(360deg); } }
  @keyframes tb-giggle { 50% { transform: translateY(-5%) rotate(4deg); } }
  @keyframes tb-sob { 50% { transform: translateY(3%) scale(1.02, .96); } }
  .tb-partner { position: absolute; right: 104%; bottom: 0; width: 100%; height: 100%; pointer-events: none; animation: tb-enter .6s ease-out; }
  @keyframes tb-enter { from { opacity: 0; transform: translateX(-60%); } }
  .tb-note { position: absolute; pointer-events: none; color: #ffd27a; font-weight: 800; font-size: .75em; line-height: 1;
    font-family: -apple-system, system-ui, sans-serif; text-shadow: 0 0 .25em rgba(0, 0, 0, .45); animation: tb-float 1.7s ease-out forwards; }
  .tb-note.heart { color: #ff5c9a; }
  .tb-note.tear { color: #7cc7ff; font-size: .5em; animation: tb-fall .9s ease-in forwards; }
  .tb-note.ha { color: #fff; font-size: .45em; }
  @keyframes tb-float { 0% { opacity: 0; transform: translate(0, 0) scale(.6); } 20% { opacity: 1; } 100% { opacity: 0; transform: translate(var(--dx, 0), -1.7em) scale(1.15); } }
  @keyframes tb-fall { 0% { opacity: 1; transform: translateY(0); } 100% { opacity: 0; transform: translateY(1.3em); } }
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
      girl: !!opts.bow, arms: null, prop: null, moveCls: null, forceAct: null, held: null,
      suit: opts.suit ? { jacket: "#2b3142", tie: "#3a7bd5", ...(opts.suit === true ? {} : opts.suit) } : null,
    };
    const still = opts.static || matchMedia("(prefers-reduced-motion: reduce)").matches;
    const root = document.createElement("div");
    root.className = "tb-root";
    root.innerHTML = `<div class="tb-shadow"></div><div class="tb-mover"><div class="tb-art"></div><div class="tb-propbox"></div></div><span class="tb-z">z z</span><span class="tb-dots">…</span>` +
      `<span class="tb-proudspark a">✦</span><span class="tb-proudspark b">✦</span>`;
    container.replaceChildren(root);
    const art = root.querySelector(".tb-art"), propbox = root.querySelector(".tb-propbox");
    art.style.cssText = "width:100%;height:100%";
    const flags = new Set();  // short-lived classes: beat, strum, flip
    const cls = () => {
      const act = s.forceAct || s.activity;
      root.className = `tb-root tb-${s.style} tb-${act} tb-e-${s.emotion}` + (root._extra || "") + (s.moveCls ? ` tb-m-${s.moveCls}` : "")
        + (s.prop ? ` tb-p-${s.prop}` : "") + [...flags].map((f) => ` tb-${f}`).join("");
    };
    const draw = () => {
      const view = s.forceAct ? { ...s, activity: s.forceAct } : s;
      art.innerHTML = s.style === "fuzzy" ? fuzzySVG(view) : pixelSVG(view);
      cls();
    };
    const flash = (f, ms) => { flags.add(f); cls(); setTimeout(() => { flags.delete(f); cls(); }, ms); };
    const sparkle = (ch, kind = "") => {
      const sp = document.createElement("span"); sp.className = `tb-note ${kind}`; sp.textContent = ch;
      sp.style.cssText = `left:${15 + Math.random() * 60}%;top:${-5 + Math.random() * 25}%;--dx:${(Math.random() - 0.5) * 1.6}em`;
      root.appendChild(sp); setTimeout(() => sp.remove(), 1800);
    };
    let partner = null, actTimers = [];
    const fit = () => { root.style.fontSize = Math.max(9, root.clientWidth * 0.2) + "px"; };
    const timers = [];
    if (!still) {
      const blinkLoop = () => {
        timers[0] = setTimeout(() => {
          if (!["sleeping", "listening"].includes(s.forceAct || s.activity) && s.emotion !== "sleepy") {
            s.blinking = true; draw(); setTimeout(() => { s.blinking = false; draw(); }, 130);
          }
          blinkLoop();
        }, 2400 + Math.random() * 3600);
      };
      blinkLoop();
      timers[1] = setInterval(() => {  // talking mouth and walking feet
        const act = s.forceAct || s.activity;  // a held activity animates too
        if (act === "speaking") { s.talkFrame ^= 1; draw(); }
        else if (act === "walking") { s.stepFrame = s.stepFrame === 1 ? 2 : 1; draw(); }
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
      setSuit(v) {  // dress up (the lab's CEO) — null takes it off
        s.suit = v ? { jacket: "#2b3142", tie: "#3a7bd5", ...(v === true ? {} : v) } : null; draw(); return api;
      },
      hold(act) {  // keep showing this activity (e.g. "sleeping" in its bed) whatever the host says; null lets go
        s.held = ACTIVITIES.includes(act) ? act : null; s.forceAct = s.held; draw(); return api;
      },
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
      // ---- shows ----
      setProp(name) {  // hold an instrument (null: put it down)
        name = PROPS[name] ? name : null;
        if (!name) flags.clear();
        if (name !== s.prop) { s.prop = name; propbox.innerHTML = name ? propSVG(name) : ""; s.lookY = name ? 1 : 0; draw(); }
        return api;
      },
      beat() { if (!still) flash("beat", 110); return api; },
      strum() { if (!still) flash("strum", 90); return api; },
      hit(n = {}) {  // a note or a drum hit lights up what played it
        let el = null;
        if (n.drum) el = propbox.querySelector(`[data-k="${n.drum === "t" ? "T" : n.drum}"]`);
        else if (n.midi != null && s.prop === "piano") el = propbox.querySelector(`.key[data-k="${((whiteOf(n.midi) - whiteOf(53)) % 17 + 17) % 17}"]`);
        else if (n.midi != null && s.prop === "xylophone") el = propbox.querySelector(`.bar[data-k="${whiteOf(n.midi) % 8}"]`);
        else if (n.midi != null && s.prop === "harp") el = propbox.querySelector(`.str[data-k="${whiteOf(n.midi) % 7}"]`);
        if (el) { el.classList.add("on"); setTimeout(() => el.classList.remove("on"), Math.min(400, (n.len || 0.2) * 1000)); }
        if (n.midi != null || n.drum) { flags.has("flip") ? flags.delete("flip") : flags.add("flip"); cls(); }  // bow / sticks / mallets change direction
        return api;
      },
      sparkle(ch = "♪") { if (!still) sparkle(ch, ch === "♥" ? "heart" : ""); return api; },
      move(name, n = 0) {  // a dance step (null: stand normally)
        const arms = { "sway-l": "lup", "sway-r": "rup", hop: "up", arms: n % 2 ? "up" : null, wave: n % 2 ? "rup" : "up", dip: null, "step-in": "up", spin: "up" }[name] ?? null;
        if (name !== s.moveCls || arms !== s.arms) { s.moveCls = name; s.arms = arms; draw(); }
        return api;
      },
      act(a) {  // a little move on request: jump spin wave cry laugh sleep
        actTimers.forEach(clearTimeout); actTimers = [];
        const at = (ms, fn) => actTimers.push(setTimeout(fn, ms));
        const done = (ms) => at(ms, () => { s.moveCls = null; s.arms = null; s.forceAct = s.held; draw(); });
        if (a === "jump") { s.moveCls = "jump"; s.arms = "up"; draw(); for (let i = 0; i < 3; i++) at(i * 550 + 200, () => sparkle("✦")); done(1700); }
        else if (a === "spin") { s.moveCls = "spin"; s.arms = "up"; draw(); done(1250); }
        else if (a === "wave") { for (let i = 0; i < 8; i++) at(i * 300, () => { s.arms = i % 2 ? "rup" : null; s.moveCls = "wave"; draw(); }); done(2500); }
        else if (a === "cry") { s.moveCls = "cry"; draw(); for (let i = 0; i < 10; i++) at(i * 260, () => sparkle("💧", "tear")); done(2700); }
        else if (a === "laugh") { s.moveCls = "laugh"; s.arms = "up"; draw(); for (let i = 0; i < 5; i++) at(i * 450, () => sparkle(i % 2 ? "ha" : "HA", "ha")); done(2500); }
        else if (a === "sleep") { s.forceAct = "sleeping"; draw(); done(5800); }
        return api;
      },
      partner(on) {  // she joins (a pink buddy with a bow) — or leaves
        if (!on) { partner?.destroy(); partner?._box.remove(); partner = null; return null; }
        if (partner) return partner;
        const box = document.createElement("div"); box.className = "tb-partner";
        if (getComputedStyle(container).position === "static") container.style.position = "relative";
        container.appendChild(box);
        partner = create(box, { style: s.style, palette: "pink", bow: true });
        partner._box = box; partner.setEmotion("happy").setActivity("watching");
        return partner;
      },
      destroy() { clearTimeout(timers[0]); clearInterval(timers[1]); actTimers.forEach(clearTimeout); ro?.disconnect(); partner?.partner?.(false); root.remove(); },
    };
    return api;
  }

  // ---------- reading feelings from words: what the face should show while a line is spoken ----------
  // Each sentence gets the emotion its words carry; the line's overall mood (from the server) is the default.
  const CUES = [  // first match wins, strongest feelings first
    ["angry", /\b(enough|what are you doing|seriously\?|again\?!|ignored (me|it)|three times|four times)\b|[A-Z]{4,}!/],
    ["firm", /\b(no excuses|no more|you need to|you have to|must|right now|start (it|now)|focus|get back|stop|don'?t (skip|waste)|skipp?ed)\b/i],
    ["sad", /\b(sorry|unfortunately|sad(ly)?|too bad|shame|disappoint\w*|i miss|tough (day|one)|hurts?)\b/i],
    ["caring", /\b(rest( up)?|take care|it'?s (okay|ok|fine)|that'?s (okay|ok)|i'?m here|breathe|be kind to yourself|no pressure|get some sleep|go easy|you'?ve got this|proud of you for trying|past midnight|sleep block|bedtime|go to (bed|sleep)|still (doing )?up)\b/i],
    ["proud", /\b(proud|nailed|crushed|killed it|well done|great job|good work|you did it|earned|impressive|shipped|faster|paper|award)\b/i],
    ["excited", /\b(let'?s go|awesome|amazing|huge|incredible|can'?t wait|boom|woo+|hyped|internship)\b|!!/i],
    ["surprised", /\b(wow|whoa|no way|really\?|oh!|interesting|didn'?t expect|guess what)\b/i],
    ["shy", /\b(aww+|blush\w*|i'?m shy|embarrass\w*|you'?re too kind|stop it,? you)\b/i],
    ["happy", /\b(glad|happy|nice|love (that|it)|haha|fun|great|good to (see|hear|meet)|welcome|hey there|hello|hi there|nice to meet)\b/i],
  ];
  function moodBase(mood = "") {
    const m = String(mood);
    if (/^ANGRY/.test(m)) return "angry";
    if (/angry|firm|disappointed|sharp/i.test(m)) return "firm";
    if (/gentle|comfort|caring|warm|soft/i.test(m)) return "caring";
    if (/proud/i.test(m)) return "proud";
    if (/upbeat|hype|energ|excit|playful/i.test(m)) return "excited";
    return "neutral";
  }
  // → [{ emotion, weight }] in speaking order (weight = share of the line's length, so it follows the voice)
  function read(text, mood) {
    const base = moodBase(mood), stern = base === "angry" || base === "firm";
    const parts = String(text || "").split(/(?<=[.!?…])\s+|\n+/).map((p) => p.trim()).filter(Boolean);
    const total = parts.reduce((n, p) => n + p.length, 0) || 1;
    const out = [];
    for (const p of parts) {
      let e = (CUES.find(([, re]) => re.test(p)) || [base])[0];
      if (stern && !["angry", "firm", "sad", "caring"].includes(e)) e = base;  // a telling-off doesn't turn cheerful
      const w = p.length / total;
      if (out.length && out[out.length - 1].emotion === e) out[out.length - 1].weight += w;
      else out.push({ emotion: e, weight: w });
    }
    return out.length ? out : [{ emotion: base, weight: 1 }];
  }
  // what someone just said to it → the face while it thinks about the answer
  function empathize(text) {
    const t = String(text || "");
    if (/\b(sad|down|tired|exhausted|stressed|anxious|lonely|hurt|failed|rejected|bad day|worried|scared)\b/i.test(t)) return "caring";
    if (/\b(got (the|an|my)|passed|won|finished|did it|selected|offer|accepted)\b|!{2,}/i.test(t)) return "excited";
    if (/\b(thanks?|thank you|love (it|you|this)|awesome|amazing|great)\b/i.test(t)) return "happy";
    if (/\b(angry|annoyed|hate|frustrat\w*|pissed)\b/i.test(t)) return "caring";
    if (/\b(wow|guess what|you won'?t believe)\b/i.test(t)) return "surprised";
    return null;
  }

  window.TrinetraBuddy = { create, PALETTES, EMOTIONS, ACTIVITIES, read, empathize, moodBase };
})();
