/* TRINETRA's world — where the little character lives on Tarun's portfolio, on Tarun's clock (Los Angeles):
     9 am – 5 pm   the LAB: it's the CEO (gold tie); suited mini-agents design, build and test small mini versions
     5 pm – 8 pm   the LAKE: sunset, a pond with ducks, a dock — it hangs out with the other dolls
     8 pm – 12 am  HOME: awake, in the lit window
     12 am – 9 am  HOME: asleep (window dark, z z)
   Double-click = knock: at home the door opens and it comes out (sleepy at night); at the lab / lake it comes over and waves.

   const w = TrinetraWorld.create(box, { me: { el, api }, style, feel(emotion|null) });
   w.attach() / w.detach()  — the host's own character moves into / out of the world (it chats outside it)
   w.knock()  · w.place  · ?trinetra-hour=14 in the page URL shows that hour (for testing)
   Needs buddy.js (TrinetraBuddy). Works inside a Shadow DOM (brings its own CSS). */
(() => {
  if (window.TrinetraWorld) return;
  const TZ = "America/Los_Angeles";

  function laNow() {
    const forced = new URLSearchParams(location.search).get("trinetra-hour");
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: TZ, hour: "numeric", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date());
    const get = (t) => +parts.find((p) => p.type === t).value;
    const h = forced != null && forced !== "" && isFinite(+forced) ? +forced % 24 : get("hour") % 24;
    return { h, m: forced != null && forced !== "" ? 0 : get("minute") };
  }
  const placeAt = (h) => (h >= 9 && h < 17 ? "lab" : h >= 17 && h < 20 ? "lake" : h >= 20 ? "home" : "sleep");
  const clock = ({ h, m }) => `${((h + 11) % 12) + 1}:${String(m).padStart(2, "0")} ${h < 12 ? "am" : "pm"}`;
  const CEO = { jacket: "#1c2030", tie: "#ffd27a", badge: "#ffd27a" };
  const CAPTION = { lab: "🧪 Lab", lake: "🌅 Lake", home: "🏠 Home", sleep: "🌙 Asleep" };

  // ---------- pixel-art scenery (96 × 60 cells) ----------
  const R = (x, y, w, h, c, a = "") => `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${c}"${a}/>`;
  const rnd = (seed) => () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  function tree(x, y, s = 1) {
    return R(x + 2 * s, y + 6 * s, 2 * s, 5 * s, "#6b4423") + R(x, y + 2 * s, 6 * s, 5 * s, "#2f7d3b") + R(x + 1 * s, y, 4 * s, 3 * s, "#3d9a49")
      + R(x + 1 * s, y + 1 * s, 2 * s, 1 * s, "#5cbf63");
  }
  const SCENES = {
    lab: () => {
      let bg = R(0, 0, 96, 46, "#e6ecf4") + R(0, 30, 96, 1, "#c8d2e0") + R(0, 46, 96, 14, "#8f99ab");
      for (let x = 0; x < 96; x += 8) bg += R(x, 46, 0.4, 14, "#7f899b");
      bg += R(0, 52, 96, 0.4, "#7f899b");
      for (const x of [14, 46, 78]) bg += R(x, 0, 8, 1, "#fff6c8") + R(x + 1, 1, 6, 0.6, "#fffbe6");
      bg += `<text x="13" y="25" font-family="monospace" font-weight="700" font-size="2.4" fill="#5a6b80">TRINETRA LABS</text>` + R(13, 26, 18, 0.4, "#f0a83a");
      // the big screen: what's being built right now
      bg += R(38, 5, 22, 13, "#3b4a5c") + R(39, 6, 20, 11, "#101b28");
      bg += `<text class="tw-screen" x="49" y="11" text-anchor="middle" font-family="monospace" font-size="2.3" fill="#7ee0c3">BOOTING…</text>`;
      bg += R(40.5, 13.4, 17, 1.4, "#22364a") + `<rect class="tw-prog" x="40.5" y="13.4" width="0" height="1.4" fill="#f0a83a"/>`;
      // shelf of finished minis + the door minis leave by
      bg += R(62, 15, 32, 1.2, "#8a5a2b") + R(64, 16.2, 1, 2, "#6b4423") + R(91, 16.2, 1, 2, "#6b4423");
      bg += `<text x="78" y="13.5" text-anchor="middle" font-family="monospace" font-size="2.2" fill="#5a6b80">SHIPPED ✓</text>`;
      bg += R(2, 26, 9, 20, "#7a8aa0") + R(3, 27, 7, 19, "#a8b6c8") + R(8.4, 36, 1, 1, "#f0a83a");
      // the robot arm over the assembly line
      bg += R(47.4, 0, 1.2, 4, "#6c7a8c") + `<g class="tw-arm">${R(47.6, 17, 0.8, 9, "#6c7a8c")}${R(45.6, 25.6, 4.8, 1.2, "#3b4a5c")}${R(45.6, 26.8, 0.8, 1.6, "#3b4a5c")}${R(49.6, 26.8, 0.8, 1.6, "#3b4a5c")}</g>`;
      let fg = "";
      for (const [x, w, kind] of [[4, 22, "design"], [35, 26, "build"], [66, 24, "test"]]) {
        fg += R(x, 42.5, w, 1.6, "#5f6d80") + R(x + 0.6, 44.1, w - 1.2, 6.4, "#aab5c5") + R(x + 0.6, 46.9, w - 1.2, 0.4, "#8c98aa")
          + R(x + 1.4, 50.5, 1, 3, "#5f6d80") + R(x + w - 2.4, 50.5, 1, 3, "#5f6d80");
        if (kind === "design") fg += R(x + 2, 36.5, 7, 5, "#2b3442") + R(x + 2.6, 37.1, 5.8, 3.8, "#3cc8ff") + R(x + 5, 41.5, 1, 1, "#2b3442")
          + R(x + 3.2, 37.9, 3, 0.5, "#e6ecf4") + R(x + 3.2, 39.1, 2, 0.5, "#e6ecf4");
        if (kind === "build") fg += `<g class="tw-belt">${Array.from({ length: 14 }, (_, i) => R(x + 1 + i * 2, 41.1, 1, 1.4, i % 2 ? "#3b4350" : "#262c36")).join("")}</g>`;
        if (kind === "test") fg += R(x + 15, 36.9, 7, 5.4, "#2b3442") + R(x + 15.6, 37.5, 5.8, 3.4, "#7ed957")
          + `<text x="${x + 18.5}" y="40.1" text-anchor="middle" font-family="monospace" font-size="2" font-weight="700" fill="#173d12">QA</text>`
          + R(x + 2, 38.5, 1, 4, "#ff5b5b") + R(x + 3.4, 38.5, 1, 4, "#3cc8ff") + R(x + 4.8, 38.5, 1, 4, "#ffd23c") + R(x + 1.6, 41.9, 5, 0.8, "#5f6d80");
      }
      return { bg, fg };
    },
    lake: (h) => {
      const sky = [["#7fb6e6", "#ffd59a"], ["#6a7fd0", "#ff9a6a"], ["#3d3f7a", "#ff7a7a"]][Math.max(0, Math.min(2, h - 17))];
      let bg = `<defs><linearGradient id="twsky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sky[0]}"/><stop offset="1" stop-color="${sky[1]}"/></linearGradient></defs>`;
      bg += `<rect width="96" height="34" fill="url(#twsky)"/>`;
      const sunY = 10 + (h - 17) * 7;
      bg += `<circle cx="72" cy="${sunY}" r="5.5" fill="#ffdf7a" opacity=".35"/><circle cx="72" cy="${sunY}" r="4" fill="#ffd26a"/>`;
      bg += `<ellipse cx="18" cy="34" rx="30" ry="9" fill="#3f7f4f"/><ellipse cx="74" cy="35" rx="34" ry="8" fill="#356d44"/>`;
      bg += R(0, 32, 96, 28, "#6cbf5a") + R(0, 32, 96, 1, "#86d470");
      const r = rnd(7);
      for (let i = 0; i < 40; i++) bg += R(Math.floor(r() * 96), 34 + Math.floor(r() * 25), 0.6, 1.2, "#4fa542");
      bg += tree(2, 20, 1.6) + tree(84, 18, 1.8) + tree(12, 24, 1.1);
      // the pond, the dock, lily pads, ducks
      bg += `<ellipse cx="40" cy="45" rx="31" ry="10.5" fill="#8fd0ff"/><ellipse cx="40" cy="45.4" rx="29.6" ry="9.6" fill="#3d8fd6"/>`;
      bg += `<ellipse cx="72" cy="${45 - (h - 17)}" rx="0" ry="0"/>` + R(26, 41, 8, 0.5, "#a9dcff", ' opacity=".6"') + R(36, 48, 10, 0.5, "#a9dcff", ' opacity=".6"');
      for (const [cx, cy] of [[22, 44], [33, 47], [46, 43]]) bg += `<circle class="tw-ripple" cx="${cx}" cy="${cy}" r="2" fill="none" stroke="#cbeaff" stroke-width=".35"/>`;
      bg += `<circle class="tw-splash" cx="30" cy="45" r="1" fill="none" stroke="#ffffff" stroke-width=".45" opacity="0"/>`;
      bg += R(17, 47, 3, 1.2, "#4fa542") + R(50, 48.6, 3, 1.2, "#4fa542") + `<circle cx="18.5" cy="46.8" r=".7" fill="#ff8fc8"/>`;
      bg += `<g class="tw-ducks">${R(28, 42, 3, 1.6, "#ffffff")}${R(30, 40.6, 1.6, 1.6, "#ffffff")}${R(31.6, 41.2, 1, 0.6, "#ffb23c")}${R(36, 43, 2.2, 1.2, "#f5f5f5")}${R(37.6, 42, 1.2, 1.2, "#f5f5f5")}${R(38.8, 42.4, 0.8, 0.5, "#ffb23c")}</g>`;
      bg += R(52, 38.6, 20, 2.2, "#a0662f") + R(52, 40.8, 20, 0.6, "#6b4423");
      for (let x = 53; x < 72; x += 4) bg += R(x, 41.4, 1, 4, "#6b4423") + R(x + 2, 38.6, 0.3, 2.2, "#8a5528");
      if (h >= 19) for (let i = 0; i < 9; i++) bg += `<circle class="tw-fly" cx="${6 + r() * 86}" cy="${22 + r() * 18}" r=".45" fill="#fff59a" style="animation-delay:${(r() * 3).toFixed(2)}s"/>`;
      return { bg, fg: "" };
    },
    home: (h, asleep) => {
      const dawn = asleep && h >= 6;
      const sky = asleep ? (dawn ? ["#4a5a9a", "#f5b38a"] : ["#070b1f", "#18214a"]) : ["#0d1330", "#2a3670"];
      let bg = `<defs><linearGradient id="twnight" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="${sky[0]}"/><stop offset="1" stop-color="${sky[1]}"/></linearGradient></defs>`;
      bg += `<rect width="96" height="48" fill="url(#twnight)"/>`;
      const r = rnd(11);
      if (!dawn) for (let i = 0; i < 26; i++) bg += `<rect class="tw-star" x="${(r() * 96).toFixed(1)}" y="${(r() * 26).toFixed(1)}" width=".6" height=".6" fill="#fff" style="animation-delay:${(r() * 3).toFixed(2)}s"/>`;
      bg += dawn ? `<circle cx="14" cy="40" r="5" fill="#ffd59a"/>` : `<circle cx="82" cy="9" r="4.2" fill="#f4f1d8"/><circle cx="83.8" cy="8" r="3.6" fill="${sky[0]}"/>`;
      bg += R(0, 45, 96, 15, asleep && !dawn ? "#1f3a28" : "#2f5b3a") + R(0, 45, 96, 0.8, "#3d7049");
      for (let x = 2; x < 28; x += 4) bg += R(x, 41, 0.8, 5, "#c9b28a") + R(x - 1, 42.4, 4, 0.6, "#c9b28a");
      for (let x = 72; x < 95; x += 4) bg += R(x, 41, 0.8, 5, "#c9b28a") + R(x - 1, 42.4, 4, 0.6, "#c9b28a");
      bg += tree(84, 28, 1.5);
      // the house
      bg += `<polygon points="28,23 50,8 72,23" fill="#7a3b2e"/><polygon points="31,22.4 50,10 69,22.4" fill="#8e4636"/>` + R(60, 10, 4, 9, "#5e2c22");
      if (asleep) bg += `<text class="tw-smoke" x="62" y="8" font-size="3" fill="#c7cbe0" opacity=".7">~</text>`;
      bg += R(31, 22, 38, 24, "#c9785a") + R(31, 22, 38, 1, "#a8603f");
      const lit = asleep ? "#26304a" : "#ffd27a";
      bg += R(34, 27, 10, 9, "#6b3a26") + R(35, 28, 8, 7, lit) + R(56, 27, 10, 9, "#6b3a26") + R(57, 28, 8, 7, lit);
      if (!asleep) bg += R(57.6, 28.6, 2.4, 6, "#ffe9b0") + R(62.4, 31, 2, 3.4, "#b0603a");
      bg += R(45, 31, 10, 15, "#4a2a18");
      bg += `<g class="tw-door">${R(45.6, 31.6, 8.8, 14.4, "#7a4528")}${R(46.6, 32.6, 6.8, 5.4, "#8a5532")}${R(46.6, 39, 6.8, 6, "#8a5532")}${R(52.4, 38.6, 1, 1, "#ffd27a")}</g>`;
      bg += `<polygon points="45,46 55,46 60,60 40,60" fill="#8f8a80"/>` + R(47, 50, 3, 1.2, "#a8a296") + R(51, 55, 3, 1.2, "#a8a296");
      bg += R(18, 38, 1, 8, "#5e5e66") + R(15.6, 35, 6, 3.6, "#c0392b") + `<text x="18.6" y="37.8" text-anchor="middle" font-size="2.4" font-weight="700" font-family="monospace" fill="#fff">T</text>`;
      bg += R(80, 30, 1, 16, "#3a3a44") + R(78.6, 28, 3.8, 2.4, asleep ? "#4a4a55" : "#ffe9a8");
      if (!asleep) bg += `<circle cx="80.5" cy="30" r="6" fill="#ffe9a8" opacity=".18"/>`;
      return { bg, fg: "" };
    },
  };

  // ---------- styles ----------
  const CSS = `
  .tw { position: absolute; inset: 0; overflow: hidden; border-radius: inherit; user-select: none; -webkit-user-select: none; font-family: -apple-system, system-ui, sans-serif; }
  .tw svg.tw-l { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
  .tw-back, .tw-front, .tw-top { position: absolute; inset: 0; pointer-events: none; }
  .tw-a { position: absolute; aspect-ratio: 1; transform: translateX(-50%);
    transition: left var(--t, 1.6s) ease-in-out, bottom var(--t, 1.6s) ease-in-out, width .5s, opacity .5s; }
  .tw-a.fast { --t: .7s; }
  .tw-win { position: absolute; overflow: hidden; left: 36.4%; top: 46.6%; width: 8.4%; height: 11.8%; }
  .tw-win .tw-a { width: 120%; left: 50%; bottom: -34%; }
  .tw-cap { position: absolute; left: 6px; top: 5px; font-size: 10px; font-weight: 700; color: #fff; background: rgba(10, 12, 24, .55);
    padding: 2px 7px; border-radius: 9px; letter-spacing: .02em; white-space: nowrap; }
  .tw-cap small { font-weight: 500; opacity: .8; }
  .tw-say { position: absolute; transform: translate(-50%, -100%); background: #fff; color: #1d1d29; font-size: 10px; font-weight: 600;
    padding: 3px 7px; border-radius: 9px; white-space: nowrap; box-shadow: 0 2px 6px rgba(0, 0, 0, .25); animation: tw-pop .25s ease-out; }
  .tw-say::after { content: ""; position: absolute; left: 50%; bottom: -3px; margin-left: -3px; border: 3px solid transparent; border-top-color: #fff; border-bottom: 0; }
  @keyframes tw-pop { from { opacity: 0; transform: translate(-50%, -80%) scale(.8); } }
  .tw-fx { position: absolute; font-weight: 800; pointer-events: none; animation: tw-fx 1.2s ease-out forwards; }
  @keyframes tw-fx { 0% { opacity: 0; transform: translate(-50%, 0) scale(.5); } 25% { opacity: 1; } 100% { opacity: 0; transform: translate(-50%, -14px) scale(1.1); } }
  .tw-ok { position: absolute; transform: translate(-50%, -100%); color: #1e7d32; background: #d8f7d0; font: 700 8px monospace; padding: 1px 4px; border-radius: 4px; }
  .tw.out .tw-zz { display: none; }
  .tw-zz { position: absolute; left: 40%; top: 36%; color: #c7cbe0; font-weight: 800; font-size: 11px; animation: tw-zz 2.8s ease-in-out infinite; }
  @keyframes tw-zz { 0% { opacity: 0; transform: translate(0, 4px); } 40% { opacity: 1; } 100% { opacity: 0; transform: translate(10px, -12px); } }
  .tw-door { transform-box: fill-box; transform-origin: 0 50%; transition: transform .5s ease-in-out; }
  .tw.door-open .tw-door { transform: scaleX(.14); }
  .tw.rattle .tw-door { animation: tw-rattle .12s linear 6; }
  @keyframes tw-rattle { 50% { transform: translateX(.3px); } }
  .tw-arm { transition: transform .6s ease-in-out; }
  .tw.arm-down .tw-arm { transform: translateY(12px); }
  .tw-belt { animation: tw-belt .9s linear infinite; }
  @keyframes tw-belt { to { transform: translateX(2px); } }
  .tw-ducks { animation: tw-ducks 14s ease-in-out infinite alternate; }
  @keyframes tw-ducks { to { transform: translateX(12px); } }
  .tw-ripple { transform-box: fill-box; transform-origin: center; animation: tw-ripple 3.2s ease-out infinite; }
  .tw-ripple:nth-of-type(2n) { animation-delay: 1.1s; } .tw-ripple:nth-of-type(3n) { animation-delay: 2.2s; }
  @keyframes tw-ripple { 0% { transform: scale(.3); opacity: .9; } 100% { transform: scale(1.8); opacity: 0; } }
  .tw.splash .tw-splash { animation: tw-splash .9s ease-out; }
  @keyframes tw-splash { 0% { opacity: 1; r: .5; } 100% { opacity: 0; r: 4; } }
  .tw-star, .tw-fly { animation: tw-twinkle 3s ease-in-out infinite; }
  @keyframes tw-twinkle { 50% { opacity: .25; } }
  .tw-smoke { animation: tw-zz 4s ease-in-out infinite; }
  .tw-stone { position: absolute; width: 3px; height: 3px; border-radius: 50%; background: #e8e8e8; transition: left .8s linear, bottom .8s cubic-bezier(.2,-0.9,.8,1.4); }
  @media (prefers-reduced-motion: reduce) { .tw * { animation: none !important; transition: none !important; } }`;
  function injectCSS(node) {
    const root = node.getRootNode ? node.getRootNode() : document;
    const host = root === document ? document.head : root;
    if (host.querySelector?.("style[data-trinetra-world]")) return;
    const st = document.createElement("style"); st.dataset.trinetraWorld = ""; st.textContent = CSS; host.appendChild(st);
  }

  // ---------- a knock on the door ----------
  let actx = null;
  function knockSound() {
    try {
      actx ??= new (window.AudioContext || window.webkitAudioContext)();
      if (actx.state !== "running") actx.resume();
      const t0 = actx.currentTime + 0.02;
      [0, 0.2, 0.4].forEach((d) => {
        const o = actx.createOscillator(), g = actx.createGain(), f = actx.createBiquadFilter();
        o.type = "triangle"; o.frequency.setValueAtTime(140, t0 + d); o.frequency.exponentialRampToValueAtTime(70, t0 + d + 0.08);
        f.type = "lowpass"; f.frequency.value = 600;
        g.gain.setValueAtTime(0.0001, t0 + d); g.gain.exponentialRampToValueAtTime(0.5, t0 + d + 0.005); g.gain.exponentialRampToValueAtTime(0.0001, t0 + d + 0.14);
        o.connect(f); f.connect(g); g.connect(actx.destination); o.start(t0 + d); o.stop(t0 + d + 0.16);
      });
    } catch {}
  }

  function create(box, opts = {}) {
    injectCSS(box);
    const B = window.TrinetraBuddy, style = opts.style || "pixel", feel = opts.feel || (() => {});
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const root = document.createElement("div"); root.className = "tw";
    box.replaceChildren(root);
    let place = null, timers = [], cast = [], attached = false, knocking = false, built = 0, tick = null;
    const me = opts.me;  // { el, api } — the host's character
    const later = (ms, fn) => { const t = setTimeout(fn, ms); timers.push(t); return t; };
    const every = (ms, fn) => { const t = setInterval(fn, ms); timers.push(t); return t; };
    const clear = () => { timers.forEach((t) => { clearTimeout(t); clearInterval(t); }); timers = []; };
    const $ = (s) => root.querySelector(s);

    function actor(layer, x, bottom, w, look = {}) {  // a doll at (x %, bottom %) with width w % of the scene
      const el = document.createElement("div"); el.className = "tw-a";
      el.style.cssText = `left:${x}%;bottom:${bottom}%;width:${w}%`;
      layer.appendChild(el);
      const box = document.createElement("div"); box.style.cssText = "width:100%;height:100%"; el.appendChild(box);
      const api = B.create(box, { style, ...look });
      const a = { el, api, at(nx, nb, nw) { el.style.left = nx + "%"; el.style.bottom = nb + "%"; if (nw) el.style.width = nw + "%"; } };
      cast.push(a); return a;
    }
    // the host's character, placed in this world
    const meSlot = document.createElement("div"); meSlot.className = "tw-a";
    const meA = { el: meSlot, at(nx, nb, nw) { meSlot.style.left = nx + "%"; meSlot.style.bottom = nb + "%"; if (nw) meSlot.style.width = nw + "%"; } };
    const say = (text, x, top, ms = 2600) => {
      const b = document.createElement("div"); b.className = "tw-say"; b.textContent = text;
      b.style.left = x + "%"; b.style.top = top + "%"; $(".tw-top").appendChild(b); setTimeout(() => b.remove(), ms);
    };
    const fx = (ch, x, top, color = "#ffd27a") => {
      const s = document.createElement("span"); s.className = "tw-fx"; s.textContent = ch; s.style.cssText = `left:${x}%;top:${top}%;color:${color};font-size:11px`;
      $(".tw-top").appendChild(s); setTimeout(() => s.remove(), 1300);
    };
    const meWalk = (on) => me.api.hold(on ? "walking" : heldRest());  // feet patter while it walks
    const heldRest = () => (place === "sleep" ? "sleeping" : null);
    const moveMe = (x, b, w, ms = 1600) => {
      meSlot.style.setProperty("--t", ms + "ms"); meWalk(true); meA.at(x, b, w);
      later(ms, () => me.api.hold(knocking ? null : heldRest()));
    };

    function build(p) {  // draw the scene and its cast
      clear(); cast.forEach((a) => a.api.destroy()); cast = []; knocking = false;
      meSlot.style.opacity = ""; meSlot.style.removeProperty("--t"); me?.api.setSuit(null);  // work clothes only at work
      const t = laNow(), art = p === "lab" ? SCENES.lab() : p === "lake" ? SCENES.lake(t.h) : SCENES.home(t.h, p === "sleep");
      root.className = "tw tw-" + p;
      root.innerHTML = `<svg class="tw-l" viewBox="0 0 96 60" preserveAspectRatio="xMidYMid slice" shape-rendering="crispEdges">${art.bg}</svg>
        <div class="tw-back"></div><svg class="tw-l" viewBox="0 0 96 60" preserveAspectRatio="xMidYMid slice" shape-rendering="crispEdges">${art.fg}</svg>
        <div class="tw-front"></div><div class="tw-top"></div><div class="tw-cap">${CAPTION[p]} <small>· ${clock(t)} LA</small></div>`;
      const back = $(".tw-back"), front = $(".tw-front");
      if (p === "lab") lab(back, front);
      else if (p === "lake") lake(back, front);
      else home(back, front, p === "sleep");
      every(30000, () => { const c = $(".tw-cap small"); if (c) c.textContent = `· ${clock(laNow())} LA`; });
    }

    // ---- the lab: the CEO walks the floor; the team designs, builds and tests a new mini every ~9 s ----
    function lab(back, front) {
      const team = [  // designer · builder · tester, all in suits
        actor(back, 15, 25, 15, { palette: "ocean", suit: { jacket: "#2b3142", tie: "#3cc8ff" } }),
        actor(back, 44, 25, 15, { palette: "mint", suit: { jacket: "#33384a", tie: "#7ed957" } }),
        actor(back, 85, 25, 15, { palette: "berry", suit: { jacket: "#2b3142", tie: "#ff5b5b" } }),
      ];
      team.forEach((a) => a.api.setActivity("watching"));
      if (attached) { front.appendChild(meSlot); meA.at(30, 2, 21); me.api.setSuit(CEO); }  // the boss: gold tie and badge
      feel(null); me?.api.hold(null);
      const shelf = [];
      const palettes = ["coral", "mint", "berry", "ocean", "night", "red", "saffron", "pink"];
      const screen = (txt, prog) => { const s = $(".tw-screen"), p = $(".tw-prog"); if (s) s.textContent = txt; if (p) p.setAttribute("width", 17 * prog); };
      const minutes = Math.max(0, (laNow().h - 9) * 60 + laNow().m);
      built = Math.floor(minutes * 60 / 9);
      function cycle() {
        const n = ++built, mini = actor(back, 38, 29.5, 7, { palette: "mono", static: true });
        mini.el.style.opacity = ".35"; mini.el.classList.add("fast");
        team[0].api.setActivity("thinking"); screen(`DESIGN #${n}`, 0.15);
        later(900, () => { team[0].api.setActivity("watching").celebrate(); team[1].api.setActivity("thinking"); mini.at(48, 29.5); root.classList.add("arm-down"); screen(`BUILD #${n}`, 0.4); });
        later(1900, () => { fx("✦", 48, 50); fx("✦", 52, 46, "#fff"); });
        later(2900, () => {
          root.classList.remove("arm-down"); mini.el.style.opacity = "1";
          mini.api.setPalette(palettes[n % palettes.length]).setEmotion("surprised");
          later(500, () => mini.api.setEmotion("happy"));
          team[1].api.setActivity("watching").setEmotion("happy"); screen(`#${n} AWAKE`, 0.6);
        });
        later(3800, () => { mini.at(78, 29.5); team[2].api.setActivity("thinking"); screen(`TEST #${n}…`, 0.8); });
        later(5600, () => {
          const ok = document.createElement("div"); ok.className = "tw-ok"; ok.textContent = "✓ TESTED"; ok.style.left = "78%"; ok.style.top = "42%";
          $(".tw-top").appendChild(ok); setTimeout(() => ok.remove(), 1400);
          team[2].api.setActivity("watching").setEmotion("proud").celebrate(); screen(`#${n} ✓ SHIPPED`, 1);
          team.forEach((a) => later(1600, () => a.api.setEmotion("neutral")));
        });
        later(6800, () => {  // onto the shelf; when it's full the oldest walks out the door
          mini.el.style.setProperty("--t", ".8s");
          const slot = shelf.length < 6 ? shelf.length : 5;
          if (shelf.length >= 6) { const old = shelf.shift(); shelf.forEach((m, i) => m.at(68 + i * 4.6, 74)); old.at(4, 25); later(1200, () => { old.api.destroy(); old.el.remove(); cast = cast.filter((c) => c !== old); }); }
          mini.at(68 + slot * 4.6, 74); shelf.push(mini);
        });
      }
      if (!still) { cycle(); every(9000, cycle); }
      // the CEO: walks between the benches, checks in, cheers the team on
      const stops = [[22, "Looks great 👌"], [50, "Ship it! 🚀"], [76, "Test it again 🧪"], [50, "Nice work, team"], [34, null]];
      let k = 0;
      if (!still) every(5200, () => {
        if (!attached || knocking) return;
        const [x, line] = stops[k++ % stops.length];
        moveMe(x, 2, 21, 1500);
        later(1600, () => { me.api.look(0, -40); if (line && Math.random() < 0.6) say(line, x, 52); if (line?.includes("Ship")) me.api.celebrate(); });
      });
    }

    // ---- the lake: sunset with friends ----
    function lake(back, front) {
      const pink = actor(back, 66, 36, 17, { palette: "pink", bow: true }), mint = actor(front, 18, 6, 15, { palette: "mint" }),
        ocean = actor(front, 84, 4, 14, { palette: "ocean" });
      pink.api.setEmotion("happy"); [pink, mint, ocean].forEach((a) => a.api.setActivity("watching"));
      if (attached) { back.appendChild(meSlot); meA.at(57, 36, 18); }
      feel("happy"); me?.api.hold(null);
      const scenes = [
        () => {  // on the dock together
          if (attached) moveMe(57, 36, 18, 1400);
          pink.at(66, 36); later(1500, () => { if (Math.random() < 0.7) fx("♥", 61, 30, "#ff5c9a"); pink.api.celebrate(); });
        },
        () => {  // skipping a stone
          mint.el.style.setProperty("--t", "1s"); mint.at(30, 14);
          later(1100, () => {
            const s = document.createElement("div"); s.className = "tw-stone"; s.style.left = "32%"; s.style.bottom = "26%"; $(".tw-top").appendChild(s);
            requestAnimationFrame(() => { s.style.left = "50%"; s.style.bottom = "28%"; });
            later(850, () => { s.remove(); root.classList.remove("splash"); void root.offsetWidth; root.classList.add("splash"); mint.api.setEmotion("excited").celebrate(); });
            later(2400, () => { mint.api.setEmotion("neutral"); mint.at(18, 6); });
          });
        },
        () => {  // a chase along the grass
          ocean.el.style.setProperty("--t", "2.2s"); mint.el.style.setProperty("--t", "2.4s");
          ocean.api.setActivity("walking"); mint.api.setActivity("walking"); ocean.at(10, 4); mint.at(26, 5);
          later(2500, () => { ocean.at(84, 4); mint.at(70, 6); });
          later(5000, () => { ocean.api.setActivity("watching"); mint.api.setActivity("watching"); mint.at(18, 6); });
        },
        () => {  // TRINETRA wanders to the shore and waves at the ducks
          if (!attached) return;
          moveMe(40, 8, 20, 1800); later(1900, () => { me.api.act("wave"); say("Hi ducks 🦆", 40, 50); });
          later(4500, () => { if (attached && !knocking) moveMe(57, 36, 18, 1800); });
        },
      ];
      let i = 0;
      if (!still) every(6500, () => { if (!knocking) scenes[i++ % scenes.length](); });
    }

    // ---- home: awake in the window, or asleep ----
    function home(back, front, asleep) {
      if (attached) inWindow(asleep);
      if (asleep) { const z = document.createElement("div"); z.className = "tw-zz"; z.textContent = "z z"; $(".tw-top").appendChild(z); }
      feel(asleep ? "sleepy" : null);
      if (!asleep && !still) every(7000, () => { if (attached && !knocking) me.api.look(Math.random() < 0.5 ? -30 : 30, 0); });
    }
    function inWindow(asleep) {
      let win = $(".tw-win");
      if (!win) { win = document.createElement("div"); win.className = "tw-win"; $(".tw-back").appendChild(win); }
      meSlot.style.cssText = ""; win.appendChild(meSlot);
      me.api.hold(asleep ? "sleeping" : null);
      if (asleep) meSlot.style.opacity = ".55";
    }

    function knock() {
      if (!attached || knocking || !place) return;
      knocking = true;
      knockSound();
      if (place === "home" || place === "sleep") {
        const asleep = place === "sleep";
        say("knock knock 🚪", 50, 46, 1400); root.classList.add("rattle");
        later(800, () => root.classList.remove("rattle"));
        later(asleep ? 1900 : 1100, () => {  // the door opens, out it comes
          root.classList.add("door-open", "out");
          me.api.hold(null); meSlot.style.opacity = "1";
          $(".tw-front").appendChild(meSlot); meSlot.style.setProperty("--t", "0s"); meA.at(50, 23, 14);
          feel(asleep ? "sleepy" : "happy");
          requestAnimationFrame(() => requestAnimationFrame(() => { if (attached) moveMe(50, 4, 24, 900); }));
          later(1000, () => {
            if (asleep) { me.api.setActivity("watching"); say("*yawn* …who's there? 🥱", 50, 30, 3200); }
            else { me.api.act("wave"); say("Hi! 👋 Click me to chat", 50, 30, 3200); }
          });
        });
        later(asleep ? 11000 : 10000, () => {  // back inside
          if (!attached) return;
          moveMe(50, 23, 14, 900);
          later(950, () => { root.classList.remove("door-open", "out"); inWindow(asleep); feel(asleep ? "sleepy" : null); knocking = false; });
        });
      } else {  // lab / lake: it comes over to say hi
        const line = place === "lab" ? "Welcome to TRINETRA Labs 🧪" : "Come hang out at the lake! 🌊";
        moveMe(50, 2, 26, 900);
        later(1000, () => { me.api.act(place === "lab" ? "wave" : "jump"); say(line, 50, 44, 3400); feel("happy"); });
        later(5200, () => { knocking = false; feel(place === "lake" ? "happy" : null); });
      }
    }

    function refresh() {  // the right place for the time of day
      if (!attached) return;  // resting while it chats
      const p = placeAt(laNow().h);
      if (p !== place) { place = p; build(p); }
    }
    const api = {
      get place() { return place; },
      knock,
      attach() {  // the host's character comes back into the world
        if (attached || !me) return api;
        attached = true;
        meSlot.replaceChildren(me.el);
        place = null; refresh();
        tick ??= setInterval(refresh, 30000);
        return api;
      },
      detach() {  // it leaves to chat; the world rests
        if (!attached) return api;
        attached = false; knocking = false;
        clear(); cast.forEach((a) => a.api.destroy()); cast = []; place = null;
        me.api.hold(null); me.api.setSuit(null); feel(null);
        meSlot.remove(); root.innerHTML = "";
        return api;
      },
      destroy() { api.detach(); clearInterval(tick); tick = null; root.remove(); },
    };
    return api;
  }

  window.TrinetraWorld = { create, placeAt, laNow };
})();
