/* TRINETRA's Brain — the real team, drawn as the brain it works like (opens from the portfolio's mini doll).

   66 agents in 10 teams (from GET /guest/agents, i.e. the agents/*.yaml registry). Each team sits in the brain region whose
   job matches its own, around its manager; every manager reports to TRINETRA at the THALAMUS, the brain's relay hub that
   (almost) every signal passes through. TRINETRA means "third eye": the pineal gland just behind it wears the gem.

   How it's laid out (the maths is shown in "How it works"):
   · a hub-and-spoke TREE: n−1 = 66 links, instead of n(n−1)/2 = 2,211 if all 67 talked to each other
   · span of control (Graicunas): a manager with n reports has R = n(2^(n−1) + n − 1) possible relationships, 44 at n = 4,
     1,080 at n = 8 — why every team has a manager and only 10 managers talk to TRINETRA
   · each team is one cluster (Gestalt common region) so the eye takes in 10 chunks, not 66 dots (Cowan's 4 ± 1)
   · members sit on an arc round their manager, the opening facing the hub; radius r ≥ s(n−1)/(1.5π) so neighbours never touch
   · cluster positions minimise Σ‖p − anatomy‖² subject to no overlaps (iterative projection), so every team stays as close
     to its real region as the space allows; the mean displacement is reported
   · 5 orders (Hick: log₂(5+1) ≈ 2.6 bits) on big targets (Fitts)

   TrinetraBrain.open(container, { agents: Promise|data, look: {style, palette}, cmd, onChat, onClose }) */
(() => {
  if (window.TrinetraBrain) return;
  const TZ = "America/Los_Angeles";
  const clockLA = () => new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit" }).format(new Date());

  // team → brain region (lateral view, front = left; x, y in 0..1 of the brain's box) · its job in the brain · team colour
  const REGION = {
    command: ["Prefrontal cortex", "executive control — decides who acts", 0.13, 0.36, "night", "#8b9bff"],
    coaching: ["Anterior cingulate", "spots errors and conflict, drives effort", 0.31, 0.27, "saffron", "#ffd23c"],
    reminders: ["Motor cortex", "sends the output out", 0.47, 0.1, "coral", "#ff9a3c"],
    monitoring: ["Parietal cortex", "attention: tracks what's happening", 0.71, 0.2, "berry", "#c77dff"],
    time_planning: ["Basal ganglia", "picks the next action and its timing", 0.4, 0.43, "ocean", "#3cc8ff"],
    communications: ["Language areas", "Broca–Wernicke: understands and speaks", 0.2, 0.6, "red", "#ff5b5b"],
    mentor_emotion: ["Amygdala · limbic", "gives feelings their weight", 0.37, 0.72, "pink", "#ff5c9a"],
    wellbeing: ["Hypothalamus", "keeps the body steady: sleep, food, stress", 0.5, 0.62, "mint", "#7ed957"],
    memory: ["Hippocampus", "forms and recalls memories", 0.64, 0.6, "mono", "#c9ccd6"],
    learning: ["Cerebellum", "predicts, and learns from its errors", 0.84, 0.8, "ocean", "#7ee0c3"],
  };
  const HUB = [0.5, 0.45];  // the thalamus
  const REPORT = {
    command: "All events routed", time_planning: "Tomorrow's plan drafted", reminders: "Today's reminders queued",
    monitoring: "Focus check-ins on track", learning: "Models retrained overnight", coaching: "Daily review written",
    wellbeing: "Breaks and sleep protected", memory: "Memories updated", communications: "Still being built 🛠",
    mentor_emotion: "Mood read, tone set",
  };
  const DECIDE = ["Approved ✓", "Do it ✓", "Good — send it to Tarun", "Ship it 🚀", "Noted. Next."];

  // stage = 160 × 90 units (16:9). The brain's box inside it:
  const BX = 6, BY = 5, BW = 116, BH = 80;
  const toStage = ([x, y]) => [BX + x * BW, BY + y * BH];

  const CSS = `
  .tb2-ov { position: fixed; inset: 0; z-index: 2147483600; background: rgba(6, 7, 14, .78); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    display: flex; align-items: center; justify-content: center; padding: 18px; animation: tb2-fade .25s ease-out; font-family: -apple-system, system-ui, sans-serif; }
  @keyframes tb2-fade { from { opacity: 0; } }
  .tb2-box { width: min(1240px, 100%); max-height: 100%; display: flex; flex-direction: column; background: #0c0b14; color: #efedf7;
    border: 1px solid #2c2a3b; border-radius: 18px; overflow: hidden; box-shadow: 0 30px 80px rgba(0,0,0,.5); position: relative; }
  .tb2-head { display: flex; align-items: center; gap: 10px; padding: 10px 12px 10px 16px; border-bottom: 1px solid #2c2a3b; flex-wrap: wrap; }
  .tb2-head b { letter-spacing: .12em; color: #f0a83a; font-size: 15px; }
  .tb2-head .sub { font-size: 12px; color: #9a98b0; }
  .tb2-head .sp { flex: 1; }
  .tb2-head button, .tb2-bar button { border: 1px solid #343850; background: #17161f; color: #efedf7; border-radius: 16px; padding: 7px 13px;
    font-size: 13px; cursor: pointer; font-weight: 600; min-height: 36px; }
  .tb2-head .chat { border-color: #f0a83a; color: #f0a83a; }
  .tb2-head .x { width: 36px; padding: 0; border-radius: 50%; }
  .tb2-scroll { overflow: auto; -webkit-overflow-scrolling: touch; position: relative; }
  .tb2-stage { position: relative; width: min(100%, calc((100vh - 200px) * 16 / 9)); aspect-ratio: 16 / 9; margin: 0 auto; overflow: hidden;
    background: radial-gradient(ellipse at 40% 50%, #1a1630 0%, #0c0b14 70%); user-select: none; -webkit-user-select: none; }
  .tb2-stage.small { min-width: 880px; }
  .tb2-l { position: absolute; inset: 0; width: 100%; height: 100%; display: block; pointer-events: none; }
  .tb2-brain { transition: opacity .6s; }
  .tb2-stage.lined .tb2-brain, .tb2-stage.lined .tb2-wires { opacity: .18; }
  .tb2-stage.lined .tb2-chip { opacity: 0; }
  .tb2-region { transition: opacity .6s; }
  .tb2-wire { stroke-width: .28; fill: none; opacity: .55; }
  .tb2-wire.hot { stroke-width: .7; opacity: 1; stroke-dasharray: 1.2 .9; animation: tb2-flow .5s linear infinite; }
  @keyframes tb2-flow { to { stroke-dashoffset: -4.2; } }
  .tb2-pulse { fill: #fff6c8; filter: drop-shadow(0 0 1.2px #ffd27a); }
  .tb2-ag { position: absolute; aspect-ratio: 1; transform: translateX(-50%); cursor: pointer; contain: layout;
    transition: left 1.3s ease-in-out, bottom 1.3s ease-in-out, width .5s, opacity .4s; }
  .tb2-ag.planned { opacity: .55; }
  .tb2-ag.planned::after { content: "🛠"; position: absolute; right: -16%; top: -12%; font-size: 9px; }
  .tb2-ag.mgr::before { content: "★"; position: absolute; left: 50%; top: -26%; transform: translateX(-50%); color: #ffd27a; font-size: 11px;
    text-shadow: 0 0 4px rgba(0,0,0,.8); z-index: 1; }
  .tb2-ag:hover { filter: drop-shadow(0 0 5px rgba(255,210,122,.9)); }
  .tb2-chip { position: absolute; transform: translate(-50%, 0); white-space: nowrap; font-size: 10.5px; font-weight: 700; color: #fff; pointer-events: none;
    background: rgba(12, 11, 20, .78); border: 1px solid var(--c); padding: 1px 7px 2px; border-radius: 9px; line-height: 1.25; text-align: center; transition: opacity .4s; }
  .tb2-chip small { display: block; font-weight: 500; font-size: 9px; color: #cfcbe6; }
  .tb2-col { position: absolute; transform: translateX(-50%); white-space: nowrap; font-size: 9.5px; font-weight: 700; color: #fff; background: #1d2433;
    padding: 1px 6px; border-radius: 7px; opacity: 0; transition: opacity .5s; pointer-events: none; }
  .tb2-stage.lined .tb2-col { opacity: 1; }
  .tb2-eye { position: absolute; transform: translate(-50%, -50%); width: 2.4%; aspect-ratio: 1; pointer-events: none; }
  .tb2-eye::before { content: ""; position: absolute; inset: 0; background: #ffd27a; transform: rotate(45deg) scale(.62); border-radius: 2px;
    box-shadow: 0 0 10px 3px rgba(255, 210, 122, .75); animation: tb2-glow 2.4s ease-in-out infinite; }
  @keyframes tb2-glow { 50% { box-shadow: 0 0 18px 6px rgba(255, 210, 122, .95); } }
  .tb2-say { position: absolute; transform: translate(-50%, -100%); background: #fff; color: #1d1d29; font-size: 11px; font-weight: 600;
    padding: 3px 8px; border-radius: 9px; max-width: 240px; text-align: center; line-height: 1.25; box-shadow: 0 2px 8px rgba(0,0,0,.4);
    animation: tb2-pop .25s ease-out; z-index: 6; pointer-events: none; }
  .tb2-say.ceo { background: #ffd27a; }
  @keyframes tb2-pop { from { opacity: 0; transform: translate(-50%, -80%) scale(.85); } }
  .tb2-feed { position: absolute; right: 1.4%; top: 3%; width: 22%; background: rgba(12, 11, 20, .82); border: 1px solid #2c2a3b; border-radius: 12px;
    padding: 8px 10px; font-size: 11px; line-height: 1.4; color: #cfe9ff; pointer-events: none; }
  .tb2-feed b { color: #ffd27a; font-size: 11.5px; letter-spacing: .06em; } .tb2-feed .n { color: #9a98b0; font-size: 10.5px; margin: 2px 0 5px; }
  .tb2-feed div.l { border-top: 1px solid #23212f; padding: 3px 0; } .tb2-feed .wait { color: #6b7a90; }
  .tb2-card { position: absolute; transform: translate(-50%, -100%); width: 230px; background: #12141f; color: #eceaf6; border: 1px solid #343850;
    border-radius: 12px; padding: 9px 11px; font-size: 12px; line-height: 1.4; box-shadow: 0 10px 30px rgba(0,0,0,.5); z-index: 8; pointer-events: none; }
  .tb2-card b { font-size: 13px; } .tb2-card .t { color: #f0a83a; font-size: 11px; } .tb2-card .st { font-size: 10.5px; color: #9a98b0; margin-top: 4px; }
  .tb2-bar { display: flex; gap: 6px; padding: 10px 12px; border-top: 1px solid #2c2a3b; flex-wrap: wrap; align-items: center; }
  .tb2-bar input { flex: 1; min-width: 170px; background: #17161f; color: #efedf7; border: 1px solid #343850; border-radius: 16px; padding: 8px 12px; font-size: 16px; outline: none; }
  .tb2-bar input:focus { border-color: #f0a83a; }
  .tb2-side { position: absolute; right: 0; top: 57px; bottom: 0; width: min(400px, 94%); background: rgba(13, 12, 20, .97); border-left: 1px solid #2c2a3b;
    overflow-y: auto; padding: 14px 16px 20px; font-size: 12.5px; line-height: 1.5; z-index: 10; animation: tb2-slide .3s ease-out; }
  @keyframes tb2-slide { from { transform: translateX(30px); opacity: 0; } }
  .tb2-side h3 { margin: 0 0 6px; font-size: 15px; color: #f0a83a; } .tb2-side h4 { margin: 14px 0 4px; font-size: 13px; color: #ffd27a; }
  .tb2-side .close { position: sticky; top: 0; float: right; border: 1px solid #343850; background: #17161f; color: #efedf7; border-radius: 12px; padding: 3px 9px; cursor: pointer; }
  .tb2-side .team { margin: 10px 0 0; padding-top: 8px; border-top: 1px solid #2c2a3b; }
  .tb2-side .about, .tb2-side .muted { color: #9a98b0; } .tb2-side .mgr { color: #ffd27a; margin: 4px 0 2px; }
  .tb2-side ul { margin: 0; padding-left: 16px; } .tb2-side li { margin: 2px 0; } .tb2-side li.planned { opacity: .6; }
  .tb2-side table { border-collapse: collapse; width: 100%; font-size: 11.5px; margin: 4px 0; }
  .tb2-side td, .tb2-side th { border-bottom: 1px solid #23212f; padding: 3px 4px; text-align: left; } .tb2-side th { color: #9a98b0; font-weight: 600; }
  .tb2-steps { list-style: none; margin: 8px 0 4px; padding: 0; counter-reset: s; }
  .tb2-steps li { display: flex; gap: 10px; align-items: flex-start; padding: 7px 0; border-bottom: 1px solid #23212f; }
  .tb2-steps li span { font-size: 18px; width: 26px; text-align: center; flex: none; }
  .tb2-side a { color: #f0a83a; }
  .tb2-side code { background: #1d1b2a; padding: 0 4px; border-radius: 4px; font-size: 11.5px; }
  .tb2-swipe { position: sticky; left: 50%; bottom: 8px; width: max-content; transform: translateX(-50%); margin-top: -34px; background: rgba(15,14,22,.88);
    color: #fff; font-size: 12px; padding: 5px 12px; border-radius: 14px; pointer-events: none; }
  [hidden] { display: none !important; }
  @media (max-width: 700px) { .tb2-ov { padding: 0; } .tb2-box { border-radius: 0; height: 100%; } .tb2-head .sub { display: none; } }
  @media (prefers-reduced-motion: reduce) { .tb2-ov *, .tb2-ov { animation: none !important; transition: none !important; } }`;
  function injectCSS(node) {
    const root = node.getRootNode ? node.getRootNode() : document, host = root === document ? document.head : root;
    if (host.querySelector?.("style[data-trinetra-brain]")) return;
    const st = document.createElement("style"); st.dataset.trinetraBrain = ""; st.textContent = CSS; host.appendChild(st);
  }

  // ---------- the maths ----------
  const graicunas = (n) => n * (2 ** (n - 1) + n - 1);
  // members on an arc round the manager (opening towards the hub): the radius that keeps neighbours apart
  // r ≥ (manager + member)/2 · 1.2 (clear of the manager) and r ≥ s(n−1)/(1.45π) · 1.25 (neighbours on the arc apart)
  const ringRadius = (n, s, g = s * 1.36) => Math.max(((g + s) / 2) * 1.2, (s * 1.25 * Math.max(1, n - 1)) / (1.45 * Math.PI), (s * 1.25) / (2 * Math.sin(Math.PI / Math.max(2, n))));
  // place the clusters: as close to their anatomy as possible without overlapping (min Σ‖p − a‖², s.t. ‖pᵢ − pⱼ‖ ≥ rᵢ + rⱼ)
  function placeClusters(items, hub, hubR, box) {
    const p = items.map((it) => [...it.anchor]);
    for (let it = 0; it < 600; it++) {
      for (let i = 0; i < p.length; i++) {
        for (let j = i + 1; j < p.length; j++) {
          const dx = p[j][0] - p[i][0], dy = p[j][1] - p[i][1], d = Math.hypot(dx, dy) || 0.01, need = items[i].R + items[j].R + 1.2;
          if (d < need) { const push = (need - d) / 2, ux = dx / d, uy = dy / d; p[i][0] -= ux * push; p[i][1] -= uy * push; p[j][0] += ux * push; p[j][1] += uy * push; }
        }
        const dx = p[i][0] - hub[0], dy = p[i][1] - hub[1], d = Math.hypot(dx, dy) || 0.01, need = items[i].R + hubR;
        if (d < need) { p[i][0] = hub[0] + (dx / d) * need; p[i][1] = hub[1] + (dy / d) * need; }
        const k = 0.04;  // the pull back towards its true region
        p[i][0] += (items[i].anchor[0] - p[i][0]) * k; p[i][1] += (items[i].anchor[1] - p[i][1]) * k;
        p[i][0] = Math.min(box[2] - items[i].R, Math.max(box[0] + items[i].R, p[i][0]));
        p[i][1] = Math.min(box[3] - items[i].R * 0.9, Math.max(box[1] + items[i].R * 0.75, p[i][1]));
      }
    }
    const disp = p.map((q, i) => Math.hypot(q[0] - items[i].anchor[0], q[1] - items[i].anchor[1]));
    let overlaps = 0;
    for (let i = 0; i < p.length; i++) for (let j = i + 1; j < p.length; j++) if (Math.hypot(p[i][0] - p[j][0], p[i][1] - p[j][1]) < items[i].R + items[j].R - 0.01) overlaps++;
    return { p, meanDisp: disp.reduce((a, b) => a + b, 0) / disp.length, overlaps };
  }

  function brainSVG(hub) {
    // a side view: frontal lobe on the left, cerebellum at the back-bottom, brainstem below
    const cx = (x) => BX + x * BW, cy = (y) => BY + y * BH;
    let g = `<defs><radialGradient id="tb2b" cx="45%" cy="40%" r="70%"><stop offset="0" stop-color="#4a3554"/><stop offset="1" stop-color="#2a2036"/></radialGradient>
      <radialGradient id="tb2c" cx="50%" cy="40%" r="70%"><stop offset="0" stop-color="#3d2f4a"/><stop offset="1" stop-color="#241b30"/></radialGradient></defs>`;
    g += `<path d="M${cx(0.62)} ${cy(0.76)} C ${cx(0.62)} ${cy(0.9)}, ${cx(0.66)} ${cy(1.02)}, ${cx(0.69)} ${cy(1.06)} L ${cx(0.75)} ${cy(1.06)} C ${cx(0.72)} ${cy(0.96)}, ${cx(0.72)} ${cy(0.86)}, ${cx(0.74)} ${cy(0.76)} Z" fill="#2c2238" stroke="#5a4668" stroke-width=".4"/>`;
    g += `<ellipse cx="${cx(0.84)}" cy="${cy(0.8)}" rx="${BW * 0.14}" ry="${BH * 0.13}" fill="url(#tb2c)" stroke="#5a4668" stroke-width=".4"/>`;
    for (let i = 1; i < 5; i++) g += `<path d="M${cx(0.72)} ${cy(0.72 + i * 0.035)} Q ${cx(0.84)} ${cy(0.68 + i * 0.05)} ${cx(0.97)} ${cy(0.74 + i * 0.03)}" stroke="#4b3a58" stroke-width=".35" fill="none"/>`;
    g += `<path d="M${cx(0.03)} ${cy(0.52)} C ${cx(-0.02)} ${cy(0.22)}, ${cx(0.2)} ${cy(0.0)}, ${cx(0.48)} ${cy(0.0)} C ${cx(0.78)} ${cy(0.0)}, ${cx(1.0)} ${cy(0.18)}, ${cx(0.99)} ${cy(0.48)}
      C ${cx(0.99)} ${cy(0.62)}, ${cx(0.9)} ${cy(0.66)}, ${cx(0.78)} ${cy(0.67)} C ${cx(0.66)} ${cy(0.69)}, ${cx(0.58)} ${cy(0.74)}, ${cx(0.46)} ${cy(0.82)}
      C ${cx(0.34)} ${cy(0.9)}, ${cx(0.16)} ${cy(0.84)}, ${cx(0.1)} ${cy(0.74)} C ${cx(0.05)} ${cy(0.67)}, ${cx(0.04)} ${cy(0.6)}, ${cx(0.03)} ${cy(0.52)} Z"
      fill="url(#tb2b)" stroke="#6b5580" stroke-width=".5"/>`;
    // gyri / sulci (decoration) and the big folds: central sulcus, lateral fissure
    const folds = [[0.1, 0.3, 0.22, 0.18, 0.3, 0.28], [0.08, 0.5, 0.2, 0.42, 0.26, 0.52], [0.36, 0.05, 0.44, 0.2, 0.4, 0.34], [0.55, 0.06, 0.6, 0.22, 0.56, 0.36],
      [0.7, 0.12, 0.8, 0.24, 0.9, 0.2], [0.78, 0.36, 0.88, 0.44, 0.96, 0.4], [0.22, 0.66, 0.34, 0.62, 0.46, 0.68], [0.3, 0.12, 0.26, 0.24, 0.32, 0.36]];
    for (const [a, b, c, d, e, f] of folds) g += `<path d="M${cx(a)} ${cy(b)} Q ${cx(c)} ${cy(d)} ${cx(e)} ${cy(f)}" stroke="#5c4870" stroke-width=".5" fill="none" stroke-linecap="round"/>`;
    g += `<path d="M${cx(0.5)} ${cy(0.0)} C ${cx(0.47)} ${cy(0.15)}, ${cx(0.52)} ${cy(0.24)}, ${cx(0.48)} ${cy(0.38)}" stroke="#7a6290" stroke-width=".7" fill="none"/>`;
    g += `<path d="M${cx(0.2)} ${cy(0.54)} C ${cx(0.34)} ${cy(0.5)}, ${cx(0.5)} ${cy(0.5)}, ${cx(0.66)} ${cy(0.44)}" stroke="#7a6290" stroke-width=".7" fill="none"/>`;
    g += `<ellipse cx="${hub[0]}" cy="${hub[1]}" rx="9" ry="6.5" fill="#ffd27a" opacity=".07"/>`;
    return g;
  }

  function build(stage, data, look, hooks) {
    injectCSS(stage);
    const B = window.TrinetraBuddy, fuzzy = look.style === "fuzzy";
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    let timers = [], mode = "work", cardEl = null;
    const later = (ms, fn) => { const t = setTimeout(fn, ms); timers.push(t); return t; };
    const every = (ms, fn) => { const t = setInterval(fn, ms); timers.push(t); return t; };
    const hub = toStage(HUB), sM = 3.3, sG = 4.5, sC = 6.6;  // sizes (% of width): members, managers, CEO
    // units: x in 0..160, y in 0..90 (the stage), so 1 unit is the same distance both ways
    const W = (pct) => (pct * 160) / 100;  // a width % in stage units
    const teams = data.teams.filter((t) => REGION[t.id]).concat(data.teams.filter((t) => !REGION[t.id]));
    const items = teams.map((t, i) => {
      const reg = REGION[t.id] || ["Cortex", "", 0.1 + (i % 5) * 0.2, 0.3, "saffron", "#f0a83a"];
      const n = t.members.length - 1, r = ringRadius(n, W(sM), W(sG));
      return { t, reg, n, r, R: r + W(sM) * 0.65, anchor: toStage([reg[2], reg[3]]) };
    });
    const solved = placeClusters(items, hub, W(sC) * 0.9, [3, 4, 128, 87]);
    items.forEach((it, i) => (it.p = solved.p[i]));

    // ---- layers ----
    stage.innerHTML = "";
    const svg = (cls, inner, vb = "0 0 160 90") => { const el = document.createElementNS("http://www.w3.org/2000/svg", "svg"); el.setAttribute("viewBox", vb); el.setAttribute("preserveAspectRatio", "none"); el.setAttribute("class", "tb2-l " + cls); el.innerHTML = inner; stage.appendChild(el); return el; };
    svg("tb2-brain", brainSVG(hub));
    let regions = "", wires = "";
    for (const it of items) {
      const [x, y] = it.p, col = it.reg[5];
      regions += `<ellipse class="tb2-region" cx="${x}" cy="${y}" rx="${it.R + 1.2}" ry="${it.R + 0.6}" fill="${col}" opacity=".10" stroke="${col}" stroke-opacity=".35" stroke-width=".3"/>`;
      const mx = (x + hub[0]) / 2 + (y - hub[1]) * 0.12, my = (y + hub[1]) / 2 - (x - hub[0]) * 0.12;
      wires += `<path class="tb2-wire" data-team="${it.t.id}" d="M${x} ${y} Q ${mx} ${my} ${hub[0]} ${hub[1]}" stroke="${col}"/>`;
    }
    svg("tb2-brain", regions);
    const wireSvg = svg("tb2-wires", wires);
    const layer = document.createElement("div"); layer.style.cssText = "position:absolute;inset:0"; stage.appendChild(layer);
    const top = document.createElement("div"); top.style.cssText = "position:absolute;inset:0;pointer-events:none"; stage.appendChild(top);
    const feed = document.createElement("div"); feed.className = "tb2-feed";
    feed.innerHTML = `<b>SIGNALS → TRINETRA</b><div class="n">${data.total} agents · ${data.teams.length} teams · ${data.active} live</div><div class="l wait">waiting for the first signal…</div>`;
    stage.appendChild(feed);
    const eye = document.createElement("div"); eye.className = "tb2-eye";
    eye.style.left = ((hub[0] + 3.6) / 160) * 100 + "%"; eye.style.top = ((hub[1] - 8.8) / 90) * 100 + "%"; eye.title = "the pineal gland — the 'third eye'";
    stage.appendChild(eye);

    // ---- the agents ----
    const pctX = (x) => (x / 160) * 100, pctB = (y, w) => 100 - (y / 90) * 100 - (w * 16 / 9) / 2;  // centre → left / bottom %
    const agents = [];
    function spawn(a, it, x, y, w, mgr) {
      const el = document.createElement("div");
      el.className = "tb2-ag" + (mgr ? " mgr" : "") + (a.status !== "active" ? " planned" : "");
      el.style.cssText = `left:${pctX(x)}%;bottom:${pctB(y, w)}%;width:${w}%`;
      el.setAttribute("aria-label", `${a.name}: ${a.role}`);
      layer.appendChild(el);
      const inner = document.createElement("div"); inner.style.cssText = "width:100%;height:100%"; el.appendChild(inner);
      const api = B.create(inner, { style: look.style || "pixel", raster: fuzzy, static: true, palette: it.reg[4],
        suit: { jacket: mgr ? "#1c2030" : "#2f3647", tie: it.reg[5], badge: mgr ? "#ffd27a" : null } });
      api.setActivity("watching");
      const ag = { a, el, api, it, mgr, home: [pctX(x), pctB(y, w), w], xy: [x, y] };
      el.addEventListener("click", (e) => { e.stopPropagation(); card(ag); });
      agents.push(ag); return ag;
    }
    let memberWires = "";
    for (const it of items) {
      const [x, y] = it.p, mgrA = it.t.members.find((m) => m.id === it.t.manager) || it.t.members[0];
      const others = it.t.members.filter((m) => m !== mgrA), n = others.length;
      const toHub = Math.atan2(hub[1] - y, hub[0] - x), span = Math.PI * 1.45;
      others.forEach((m, k) => {
        const ang = toHub + Math.PI + (n === 1 ? 0 : -span / 2 + (span * k) / (n - 1));
        const mx = x + Math.cos(ang) * it.r, my = y + Math.sin(ang) * it.r * 0.92;
        memberWires += `<line x1="${x}" y1="${y}" x2="${mx}" y2="${my}" stroke="${it.reg[5]}" stroke-width=".18" opacity=".45"/>`;
        spawn(m, it, mx, my, sM, false);
      });
      it.mgr = spawn(mgrA, it, x, y, sG, true);
      const chip = document.createElement("div"); chip.className = "tb2-chip"; chip.style.setProperty("--c", it.reg[5]);
      chip.innerHTML = `${it.t.emoji} ${it.t.title}<small>${it.reg[0]}</small>`;
      const below = y < hub[1] ? y - it.R - 4.6 : y + it.R + 0.6;  // above the cluster if it's in the top half, else below
      chip.style.left = pctX(x) + "%"; chip.style.top = (Math.max(0.5, Math.min(93, (below / 90) * 100))) + "%";
      top.appendChild(chip);
      const colLabel = document.createElement("div"); colLabel.className = "tb2-col"; colLabel.textContent = `${it.t.emoji} ${it.t.title}`;
      top.appendChild(colLabel); it.col = colLabel;
    }
    wireSvg.insertAdjacentHTML("afterbegin", memberWires);
    // TRINETRA at the thalamus
    const ceoEl = document.createElement("div"); ceoEl.className = "tb2-ag";
    ceoEl.style.cssText = `left:${pctX(hub[0])}%;bottom:${pctB(hub[1], sC)}%;width:${sC}%`;
    layer.appendChild(ceoEl);
    const ceoIn = document.createElement("div"); ceoIn.style.cssText = "width:100%;height:100%"; ceoEl.appendChild(ceoIn);
    const ceo = B.create(ceoIn, { style: look.style || "pixel", palette: look.palette || "saffron", raster: fuzzy, suit: { jacket: "#1c2030", tie: "#ffd27a", badge: "#ffd27a" } });
    ceo.setActivity("watching");
    const ceoAg = { el: ceoEl, a: { name: "TRINETRA", role: "Sits at the thalamus — the relay every signal passes through. The 10 managers report here; it decides and speaks for Tarun.", status: "active" }, ceo: true };
    ceoEl.addEventListener("click", (e) => { e.stopPropagation(); card(ceoAg); });

    // ---- speech, cards, the feed ----
    const posOf = (el) => [parseFloat(el.style.left), parseFloat(el.style.bottom), parseFloat(el.style.width)];
    function say(el, text, ms = 2400, cls = "") {
      if (cls === "ceo") top.querySelectorAll(".tb2-say.ceo").forEach((o) => o.remove());
      const [x, b, w] = posOf(el), s = document.createElement("div");
      s.className = "tb2-say " + cls; s.textContent = text;
      s.style.left = Math.min(91, Math.max(9, x)) + "%"; s.style.top = `calc(${Math.max(8, 100 - b - w * 16 / 9)}% - 4px)`;
      top.appendChild(s); setTimeout(() => s.remove(), ms); return s;
    }
    function card(ag) {
      cardEl?.remove();
      const [x, b, w] = posOf(ag.el), c = document.createElement("div"); c.className = "tb2-card";
      c.innerHTML = `<b></b><div class="t"></div><div class="r"></div><div class="st"></div>`;
      const mgrName = ag.it ? ag.it.mgr?.a.name : "";
      c.querySelector("b").textContent = ag.a.name;
      c.querySelector(".t").textContent = ag.ceo ? "CEO · thalamus" : ag.mgr ? `★ Manager · ${ag.it.t.title} (${ag.it.reg[0]}) → reports to TRINETRA` : `${ag.it.t.title} (${ag.it.reg[0]}) · reports to ${mgrName}`;
      c.querySelector(".r").textContent = ag.a.role;
      c.querySelector(".st").textContent = ag.a.status === "active" ? "● live" : "🛠 still being built";
      c.style.left = Math.min(86, Math.max(14, x)) + "%";
      const topPct = 100 - b - w * 16 / 9;
      if (topPct < 32) { c.style.transform = "translate(-50%, 0)"; c.style.top = `calc(${100 - b}% + 6px)`; } else c.style.top = `calc(${topPct}% - 6px)`;
      top.appendChild(c); cardEl = c;
      later(5600, () => { if (cardEl === c) { c.remove(); cardEl = null; } });
    }
    stage.addEventListener("click", () => { cardEl?.remove(); cardEl = null; });
    const lines = [];
    function log(line) {
      lines.unshift(line); lines.length = Math.min(lines.length, 5);
      feed.querySelectorAll(".l").forEach((l) => l.remove());
      for (const l of lines) { const d = document.createElement("div"); d.className = "l"; d.textContent = l; feed.appendChild(d); }
    }
    const short = (t, n = 46) => (t.length > n ? t.slice(0, n - 1).replace(/[\s,;:—-]+\S*$/, "") + "…" : t);
    // a pulse of light travelling a path (member → manager → thalamus)
    function pulse(from, to, ms, color = "#fff6c8") {
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("r", ".9"); c.setAttribute("class", "tb2-pulse"); c.setAttribute("fill", color); wireSvg.appendChild(c);
      const t0 = performance.now();
      const step = (t) => {
        const k = Math.min(1, (t - t0) / ms), e = k < 0.5 ? 2 * k * k : 1 - Math.pow(-2 * k + 2, 2) / 2;
        c.setAttribute("cx", from[0] + (to[0] - from[0]) * e); c.setAttribute("cy", from[1] + (to[1] - from[1]) * e);
        if (k < 1 && c.isConnected) requestAnimationFrame(step); else c.remove();
      };
      requestAnimationFrame(step);
    }

    // ---- the work loop: member → manager → TRINETRA → decision (and the output goes out via the motor cortex) ----
    let turn = 0;
    function signal(it = items[turn++ % items.length]) {
      if (mode !== "work") return;
      const team = agents.filter((g) => g.it === it && !g.mgr), from = team[Math.floor(Math.random() * team.length)];
      const wire = wireSvg.querySelector(`.tb2-wire[data-team="${it.t.id}"]`);
      if (from) { from.api.setActivity("thinking"); say(from.el, `→ ${it.mgr.a.name}: ${short(from.a.role, 34)}`, 1700); pulse(from.xy, it.p, 900); }
      later(1100, () => {
        from?.api.setActivity("watching"); it.mgr.api.celebrate();
        say(it.mgr.el, `${it.t.emoji} ${REPORT[it.t.id] || "Update ready"}`, 2000);
        wire?.classList.add("hot"); pulse(it.p, hub, 1100, "#ffd27a");
      });
      later(2400, () => {
        wire?.classList.remove("hot");
        const d = it.t.id === "communications" ? "Keep building 🛠" : DECIDE[Math.floor(Math.random() * DECIDE.length)];
        say(ceoEl, d, 1800, "ceo"); ceo.setEmotion(it.t.id === "communications" ? "firm" : "proud");
        later(1500, () => ceo.setEmotion("neutral"));
        const out = items.find((x) => x.t.id === "reminders");
        if (out && it !== out && /send|Ship|Do it/.test(d)) pulse(hub, out.p, 900, "#7ee0c3");
        log(`${it.t.emoji} ${it.t.title} → ${REPORT[it.t.id] || "update"} · ${d}`);
      });
    }
    // ---- orders ----
    function assemble() {
      mode = "lined"; cardEl?.remove(); stage.classList.add("lined");
      say(ceoEl, "Team, assemble! 📣", 2000, "ceo"); ceo.setEmotion("proud");
      items.forEach((it, ci) => {
        const x = 5.5 + ci * 9.9, team = agents.filter((g) => g.it === it && !g.mgr);
        it.col.style.cssText = `left:${x}%;bottom:0.6%`;
        Object.assign(it.mgr.el.style, { transitionDelay: ci * 60 + "ms", left: x + "%", bottom: "5%" });
        team.forEach((g, k) => Object.assign(g.el.style, { transitionDelay: ci * 60 + (k + 1) * 70 + "ms", left: x + "%", bottom: 12.5 + k * 6.4 + "%" }));
      });
      later(1900, () => { agents.forEach((g) => g.api.setEmotion("happy")); say(ceoEl, `All ${data.total} in line ✓ · ${data.teams.length} teams, managers in front`, 3000, "ceo"); });
    }
    function backToWork() {
      mode = "work"; stage.classList.remove("lined"); cardEl?.remove();
      agents.forEach((g, i) => { const [x, b] = g.home; Object.assign(g.el.style, { transitionDelay: (i % 12) * 50 + "ms", left: x + "%", bottom: b + "%" }); g.api.setEmotion("neutral"); });
      say(ceoEl, "Back to work 💼", 1800, "ceo"); ceo.setEmotion("neutral");
    }
    let roleRun = 0;
    function whatDoYouDo() {  // each team in turn: the manager says what the team does, every member its own task
      const run = ++roleRun;
      say(ceoEl, "Team — tell them what you do 🎤", 2200, "ceo");
      items.forEach((it, ci) => later(1500 + ci * 3300, () => {
        if (run !== roleRun) return;
        say(it.mgr.el, `${it.t.emoji} ${it.reg[0]}: ${short(it.t.about, 58)}`, 3100); it.mgr.api.celebrate();
        agents.filter((g) => g.it === it && !g.mgr).forEach((g, k) => later(300 + k * 360, () => { if (run === roleRun) say(g.el, short(g.a.role, 40), 2500); }));
      }));
      hooks.roster?.();
    }
    // ---- live: replay what really happened to the visitor's last message, team by team ----
    let replayRun = 0;
    function replay(trace) {
      if (!trace?.length) return;
      const run = ++replayRun;
      if (mode === "lined") backToWork();
      mode = "replay"; cardEl?.remove();
      say(ceoEl, "Here's how I answered your last message 👇", 2400, "ceo");
      trace.forEach((st, i) => later(1600 + i * 2300, () => {
        if (run !== replayRun) return;
        const it = items.find((x) => x.t.id === st.team);
        const wire = it && wireSvg.querySelector(`.tb2-wire[data-team="${it.t.id}"]`);
        log(`${i + 1}. ${it ? it.t.emoji + " " + it.t.title + " · " : ""}${st.did}`);
        if (!it || it.t.id === "command") { say(ceoEl, short(st.did, 70), 2200, "ceo"); ceo.setEmotion("proud"); return; }
        it.mgr.api.celebrate(); say(it.mgr.el, short(st.did, 64), 2200);
        wire?.classList.add("hot"); pulse(it.p, hub, 1100, "#7ee0c3");
        later(1500, () => wire?.classList.remove("hot"));
      }));
      later(1600 + trace.length * 2300 + 600, () => { if (run === replayRun) { ceo.setEmotion("neutral"); mode = "work"; } });
    }
    if (!still) { every(3800, () => signal()); every(330, () => agents[Math.floor(Math.random() * agents.length)]?.api.blink()); }
    if (!hooks.trace?.length) later(500, () => say(ceoEl, `I'm TRINETRA 👁️ ${data.total} agents in ${data.teams.length} teams, working live. Try “assemble”!`, 4000, "ceo"));
    return {
      assemble, backToWork, whatDoYouDo, replay, items, agents, solved,
      report() { const lined = mode === "lined"; if (lined) backToWork(); later(lined ? 1400 : 0, () => signal()); },
      get mode() { return mode; },
      destroy() { timers.forEach((t) => { clearTimeout(t); clearInterval(t); }); agents.forEach((g) => g.api.destroy()); ceo.destroy(); stage.innerHTML = ""; },
    };
  }

  // The plain story first (what happens to a message, in order); the maths stays one tap away for the curious.
  function howIThink(data) {
    const steps = [
      ["👂", "Hear", "Every message, check-in, tap and timer becomes a signal."],
      ["🧭", "Understand", "A language model reads the whole conversation, not just the last line, and works out what you mean, typos and all."],
      ["📓", "Remember", "The Memory team pulls up only what matters for this moment. Visitors only ever get Tarun's public facts."],
      ["🧑‍🤝‍🧑", "Teams work", `${data.teams.length} teams of specialists (${data.total} agents) each handle their part. Every team has a ★ manager who sums it up.`],
      ["👁️", "Decide", "The managers report to TRINETRA at the centre. It weighs their advice, says yes or no, and picks one answer."],
      ["💬", "Act", "The reply goes out: spoken, shown on the face, or sent to Tarun's phone."],
      ["🔁", "Learn", "What worked and what didn't is saved, so the next decision is better."],
    ];
    return `<button class="close" type="button">✕</button><h3>How I think</h3>
      <p class="muted">Each message travels this path in a second or two. Tap ▶ under any of my chat replies to watch it happen live.</p>
      <ol class="tb2-steps">${steps.map(([e, h, t]) => `<li><span>${e}</span><div><b>${h}</b><br>${t}</div></li>`).join("")}</ol>
      <h4>Why teams and managers?</h4>
      <p>If all ${data.total} agents talked to each other, there would be ${((data.total + 1) * data.total / 2).toLocaleString()} conversations going on. With a manager per team,
      only ${data.teams.length} voices reach TRINETRA, so it stays fast and clear. Big companies, and Anthropic's own research agents, are organised the same way.</p>
      <p class="muted">${data.active} agents are live now · ${data.total - data.active} are still being built 🛠 (Gmail and WhatsApp) ·
      <a href="#" data-c="math">the maths behind the layout →</a></p>`;
  }

  function explainer(data, brain) {
    const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
    const n = data.total + 1, mesh = (n * (n - 1)) / 2, tree = n - 1;
    const rows = brain.items.map((it) => `<tr><td>${it.t.emoji} ${esc(it.t.title)}</td><td>${esc(it.reg[0])}</td><td>${it.n}</td><td>${graicunas(it.n).toLocaleString()}</td></tr>`).join("");
    return `<button class="close" type="button">✕</button><h3>How TRINETRA's brain works</h3>
      <p>Every message, check-in and timer becomes a <b>signal</b>. An agent handles it and reports to its team's <b>★ manager</b>.
      The manager condenses the team's work and passes it to <b>TRINETRA at the thalamus</b>, the relay hub that almost every signal in a real
      brain passes through. TRINETRA decides, and the answer goes out to Tarun (through the motor cortex, the Reminders team).
      The <b>pineal "third eye"</b> above it is where TRINETRA gets its name.</p>
      <h4>Why a tree, not a crowd</h4>
      <p>${n} members who all talk to each other: n(n−1)/2 = <b>${mesh.toLocaleString()}</b> links. As a tree (agents → managers → TRINETRA): n−1 = <b>${tree}</b> links,
      ${Math.round(mesh / tree)}× fewer. Only ${data.teams.length} voices ever reach TRINETRA. Anthropic's multi-agent research system uses the same
      orchestrator → workers shape: a lead agent splits the work, the subagents report back summaries.</p>
      <h4>Why every team has a manager</h4>
      <p>Graicunas' span-of-control law: someone with n direct reports has <code>R = n(2ⁿ⁻¹ + n − 1)</code> possible relationships.
      A team of 4 → 44, of 8 → 1,080. If TRINETRA managed all ${data.total} directly, R would be astronomical. With 10 managers, its own span is
      10 → ${graicunas(10).toLocaleString()} relationships, and each manager keeps a small team.</p>
      <table><tr><th>Team</th><th>Brain region</th><th>Reports</th><th>R</th></tr>${rows}</table>
      <h4>Why it looks like this</h4>
      <p>• <b>One cluster per team</b> (Gestalt "common region"): the eye takes in about 4 ± 1 chunks at a time (Cowan), so you see 10 teams, not ${data.total} dots.<br>
      • <b>Members on an arc round their manager</b>, the opening facing TRINETRA, at radius r ≥ s(n−1)/(1.45π), so neighbours never touch.<br>
      • <b>Positions solved, not guessed</b>: each team goes as close to its real brain region as it can without overlapping another.
      That minimises Σ‖p − anatomy‖², with ‖pᵢ − pⱼ‖ ≥ rᵢ + rⱼ, by iterative projection. Here: mean shift ${brain.solved.meanDisp.toFixed(1)} units, ${brain.solved.overlaps} overlaps.<br>
      • <b>Wires only go hub → manager → member</b>, so no two cross.<br>
      • <b>5 orders, big buttons</b>: Hick's law, choice time ∝ log₂(n + 1) = 2.6 bits for 5; Fitts's law favours large targets.</p>
      <h4>The regions</h4><p class="muted">${brain.items.map((it) => `<b>${esc(it.reg[0])}</b> (${esc(it.reg[1])}) → ${it.t.emoji} ${esc(it.t.title)}`).join("<br>")}</p>
      <p class="muted">${data.active} agents are live. ${data.total - data.active} are still being built (🛠), mostly Communications: Gmail and WhatsApp.</p>`;
  }

  function open(container, opts = {}) {
    injectCSS(container);
    const ov = document.createElement("div"); ov.className = "tb2-ov"; ov.setAttribute("role", "dialog"); ov.setAttribute("aria-label", "TRINETRA's Brain");
    ov.innerHTML = `<div class="tb2-box">
      <div class="tb2-head"><b>🧠 TRINETRA'S BRAIN</b><span class="sub"></span><span class="sp"></span>
        <button class="chat" type="button">💬 Chat</button><button class="x" type="button" aria-label="Close">✕</button></div>
      <div class="tb2-scroll"><div class="tb2-stage"></div></div>
      <div class="tb2-bar"><button data-c="assemble">🧍 Assemble</button><button data-c="roles">❓ What do you do?</button>
        <button data-c="work">💼 Back to work</button><button data-c="report">⚡ Report</button><button data-c="how">📘 How it works</button>${opts.trace?.length ? '<button data-c="replay">▶ Replay my last message</button>' : ""}
        <input placeholder="Give the team an order… (try “assemble”)" aria-label="Order for the team" maxlength="80"></div></div>`;
    container.appendChild(ov);
    const $ = (q) => ov.querySelector(q), stage = $(".tb2-stage"), scroll = $(".tb2-scroll");
    $(".sub").textContent = `the real agents, live · ${clockLA()} LA`;
    const fit = () => stage.classList.toggle("small", innerWidth < 880);
    fit(); addEventListener("resize", fit);
    let brain = null, data = null, side = null, closed = false;
    const ready = Promise.resolve(opts.agents).catch(() => null).then((d) => {
      if (closed) return;
      data = d;
      if (!data?.teams?.length) { stage.innerHTML = `<div style="padding:30px;color:#9a98b0">The brain is resting for a moment — try again soon.</div>`; return; }
      brain = build(stage, data, opts.look || {}, { roster: showRoster, trace: opts.trace });
      if (scroll.scrollWidth > scroll.clientWidth) {  // a phone sees part of it: start on TRINETRA, swipe for the rest
        scroll.scrollLeft = (scroll.scrollWidth - scroll.clientWidth) * 0.45;
        const hint = document.createElement("div"); hint.className = "tb2-swipe"; hint.textContent = "← swipe to see the whole brain →";
        scroll.appendChild(hint); setTimeout(() => hint.remove(), 4000);
      }
      if (opts.cmd) setTimeout(() => order(opts.cmd), 900);
      else if (opts.trace?.length) setTimeout(() => brain?.replay(opts.trace), 400);
      else if (innerWidth >= 880) panel(howIThink(data));  // first look: the plain story of how it works, beside the live brain
    });
    function panel(html) {
      side?.remove();
      side = document.createElement("aside"); side.className = "tb2-side"; side.innerHTML = html;
      side.querySelector(".close").onclick = () => { side.remove(); side = null; };
      side.addEventListener("click", (e) => { const a = e.target.closest("a[data-c]"); if (a) { e.preventDefault(); order(a.dataset.c); } });
      ov.querySelector(".tb2-box").appendChild(side);  // fixed to the window, not the sideways-scrolling stage (phones)
    }
    function showRoster() {
      if (!data || !brain) return;
      const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
      panel(`<button class="close" type="button">✕</button><h3>Who does what</h3>
        <div class="mgr">👁️ <b>TRINETRA</b>, the CEO at the thalamus. The 10 managers report to it; it decides and speaks for Tarun.</div>
        <div class="muted">${data.total} agents · ${data.teams.length} teams · ${data.active} live, ${data.total - data.active} being built</div>` +
        brain.items.map((it) => {
          const m = it.mgr.a;
          return `<div class="team"><b>${it.t.emoji} ${esc(it.t.title)}</b> <span class="about">· ${esc(it.reg[0])} — ${esc(it.t.about)}</span>
            <div class="mgr">★ Manager: <b>${esc(m.name)}</b> — ${esc(m.role)}</div>
            <ul>${it.t.members.filter((x) => x.id !== m.id).map((x) => `<li class="${x.status === "active" ? "" : "planned"}"><b>${esc(x.name)}</b> — ${esc(x.role)}${x.status === "active" ? "" : " 🛠"}</li>`).join("")}</ul></div>`;
        }).join(""));
    }
    function order(c) {
      if (!brain || closed) return;
      const t = String(c).toLowerCase();
      if (t === "replay") return brain.replay(opts.trace);
      if (/math|theorem|formula|layout/.test(t)) return panel(explainer(data, brain));
      if (/\bhow\b|explain|think/.test(t) && !/back to work/.test(t)) return panel(howIThink(data));
      if (/assemble|line ?up|fall in|gather|attention/.test(t)) brain.assemble();
      else if (/what|task|job|role|do you do|who does|roster/.test(t)) brain.whatDoYouDo();
      else if (/work|dismiss|go back|desk/.test(t)) brain.backToWork();
      else if (/report|update|status|signal/.test(t)) brain.report();
    }
    const bar = $(".tb2-bar"), input = bar.querySelector("input");
    bar.addEventListener("click", (e) => { const b = e.target.closest("button[data-c]"); if (b) order(b.dataset.c); });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && input.value.trim()) { order(input.value); input.value = ""; } });
    const close = () => { if (closed) return; closed = true; brain?.destroy(); brain = null; removeEventListener("resize", fit); ov.remove(); opts.onClose?.(); };
    $(".x").onclick = close;
    $(".chat").onclick = () => { close(); opts.onChat?.(); };
    ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
    ov.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
    ov.tabIndex = -1; setTimeout(() => ov.focus(), 30);
    return { close, order, ready, get el() { return ov; }, get brain() { return brain; } };
  }

  window.TrinetraBrain = { open, graicunas, ringRadius, placeClusters, REGION };
})();
