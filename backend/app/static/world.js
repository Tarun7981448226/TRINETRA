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
      const now = placeAt(laNow().h);  // a fixed place (the big screen's tabs), or wherever the clock says
      const p = opts.place === "home" ? (now === "sleep" ? "sleep" : "home") : opts.place || now;
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


  // =====================================================================================================
  // TRINETRA HQ — the real team: 10 councils, each run by a manager who reports to TRINETRA (the CEO).
  // Data: GET /guest/agents (from the agents/*.yaml registry). Planned agents are still in the build bay.
  // =====================================================================================================
  const TEAM_LOOK = {  // council → member colour + tie
    command: ["night", "#ffd27a"], time_planning: ["ocean", "#3cc8ff"], reminders: ["coral", "#ff9a3c"], monitoring: ["berry", "#c77dff"],
    learning: ["mint", "#7ed957"], coaching: ["saffron", "#ffd23c"], wellbeing: ["pink", "#ff5c9a"], memory: ["mono", "#9aa0aa"],
    communications: ["red", "#ff5b5b"], mentor_emotion: ["coral", "#ff3d8b"],
  };
  const TEAM_REPORT = {
    command: "All events routed", time_planning: "Tomorrow's plan drafted", reminders: "Today's reminders queued",
    monitoring: "Focus check-ins on track", learning: "Models retrained overnight", coaching: "Daily review written",
    wellbeing: "Breaks and sleep protected", memory: "Profile and memories updated", communications: "Still being built 🛠",
    mentor_emotion: "Mood read, tone set",
  };
  const DECISIONS = ["Approved ✓", "Ship it 🚀", "Good — keep going", "Do it ✓", "Nice. Next."];
  const HQ_CSS = `
  .hq { position: absolute; inset: 0; overflow: hidden; user-select: none; -webkit-user-select: none; font-family: -apple-system, system-ui, sans-serif; }
  .hq svg.hq-l { position: absolute; inset: 0; width: 100%; height: 100%; display: block; }
  .hq-layer { position: absolute; inset: 0; pointer-events: none; }
  .hq-ag { position: absolute; aspect-ratio: 1; transform: translateX(-50%); pointer-events: auto; cursor: pointer;
    transition: left 1.3s ease-in-out, bottom 1.3s ease-in-out, opacity .4s; }
  .hq-ag.planned { opacity: .5; }
  .hq-ag.planned::after { content: "🛠"; position: absolute; right: -18%; top: -14%; font-size: 9px; }
  .hq-ag.mgr::before { content: "★"; position: absolute; left: 50%; top: -30%; transform: translateX(-50%); color: #ffd27a; font-size: 11px;
    text-shadow: 0 0 4px rgba(0,0,0,.6); }
  .hq-ag:hover { filter: brightness(1.15) drop-shadow(0 0 4px rgba(255,210,122,.8)); }
  .hq-sign { position: absolute; transform: translateX(-50%); white-space: nowrap; font-size: 10.5px; font-weight: 700; color: #263041;
    background: rgba(255,255,255,.85); border: 1px solid rgba(0,0,0,.12); padding: 1px 7px; border-radius: 8px; transition: opacity .4s; }
  .hq-sign small { font-weight: 500; color: #5a6b80; }
  .hq.lined .hq-sign.pod { opacity: 0; }
  .hq-sign.col { opacity: 0; background: #1d2433; color: #fff; border-color: transparent; font-size: 9.5px; }
  .hq.lined .hq-sign.col { opacity: 1; }
  .hq-say { position: absolute; transform: translate(-50%, -100%); background: #fff; color: #1d1d29; font-size: 11px; font-weight: 600;
    padding: 3px 8px; border-radius: 9px; max-width: 230px; white-space: normal; text-align: center; line-height: 1.25;
    box-shadow: 0 2px 8px rgba(0,0,0,.3); animation: tw-pop .25s ease-out; z-index: 5; pointer-events: none; }
  .hq-say.ceo { background: #ffd27a; }
  .hq-line { stroke: rgba(240,168,58,.35); stroke-width: .25; stroke-dasharray: .9 .7; fill: none; transition: stroke .3s, stroke-width .3s; }
  .hq-line.hot { stroke: #ffb02e; stroke-width: .55; animation: hq-flow .6s linear infinite; }
  @keyframes hq-flow { to { stroke-dashoffset: -3.2; } }
  .hq.lined .hq-line { opacity: 0; }
  .hq-desks { transition: opacity .6s; } .hq.lined .hq-desks { opacity: .18; }
  .hq-card { position: absolute; transform: translate(-50%, -100%); width: 220px; background: #12141f; color: #eceaf6; border: 1px solid #343850;
    border-radius: 12px; padding: 9px 11px; font-size: 12px; line-height: 1.4; box-shadow: 0 10px 30px rgba(0,0,0,.45); z-index: 6; pointer-events: none; }
  .hq-card b { font-size: 13px; } .hq-card .t { color: #f0a83a; font-size: 11px; } .hq-card .st { font-size: 10.5px; color: #9a98b0; margin-top: 4px; }`;

  function hq(box, opts = {}) {
    injectCSS(box);
    const host = box.getRootNode ? box.getRootNode() : document, where = host === document ? document.head : host;
    if (!where.querySelector?.("style[data-trinetra-hq]")) { const st = document.createElement("style"); st.dataset.trinetraHq = ""; st.textContent = HQ_CSS; where.appendChild(st); }
    const B = window.TrinetraBuddy, data = opts.agents, look = opts.look || {};
    const still = matchMedia("(prefers-reduced-motion: reduce)").matches;
    const root = document.createElement("div"); root.className = "hq"; box.replaceChildren(root);
    let timers = [], mode = "work";
    const later = (ms, fn) => { const t = setTimeout(fn, ms); timers.push(t); return t; };
    const every = (ms, fn) => { const t = setInterval(fn, ms); timers.push(t); return t; };
    const $ = (q) => root.querySelector(q);

    // ---- the room (160 × 90) ----
    let bg = R(0, 0, 160, 36, "#e3e9f2") + R(0, 34, 160, 1, "#c8d2e0") + R(0, 36, 160, 54, "#a3adbd");
    for (let x = 0; x < 160; x += 10) bg += R(x, 36, 0.3, 54, "#97a1b2");
    for (let y = 46; y < 90; y += 11) bg += R(0, y, 160, 0.3, "#97a1b2");
    for (const x of [20, 60, 100, 140]) bg += R(x - 5, 0, 10, 1, "#fff6c8");
    // CEO stage + the wall screen
    bg += R(58, 3, 44, 14, "#3b4a5c") + R(59, 4, 42, 12, "#101b28");
    bg += `<text x="80" y="8.6" text-anchor="middle" font-family="monospace" font-weight="700" font-size="3" fill="#ffd27a">TRINETRA HQ</text>`;
    bg += `<text x="80" y="13" text-anchor="middle" font-family="monospace" font-size="1.9" fill="#7ee0c3">${data.total} AGENTS · ${data.teams.length} TEAMS · ${data.active} LIVE</text>`;
    bg += R(66, 29.5, 28, 2.4, "#6b3a26") + R(64, 31.9, 32, 1.4, "#4a2a18");
    bg += `<text x="80" y="31.4" text-anchor="middle" font-family="monospace" font-weight="700" font-size="1.7" fill="#ffd27a">CEO</text>`;
    // the build bay (top left): the planned agents are made here
    bg += R(3, 3, 40, 26, "#cfd8e4") + R(3, 3, 40, 1.2, "#9aa7b8");
    bg += `<text x="5" y="7.2" font-family="monospace" font-weight="700" font-size="2.2" fill="#3b4a5c">BUILD BAY 🛠</text>`;
    bg += R(5, 9, 26, 7, "#101b28") + `<text class="hq-build" x="18" y="12.2" text-anchor="middle" font-family="monospace" font-size="1.5" fill="#7ee0c3">…</text>`;
    bg += R(7, 13.6, 22, 1, "#22364a") + `<rect class="hq-buildbar" x="7" y="13.6" width="0" height="1" fill="#f0a83a"/>`;
    bg += R(4, 24, 38, 1.4, "#5f6d80") + `<g class="tw-belt">${Array.from({ length: 18 }, (_, i) => R(5 + i * 2, 22.8, 1, 1.2, i % 2 ? "#3b4350" : "#262c36")).join("")}</g>`;
    bg += R(33, 4.2, 1, 6, "#6c7a8c") + `<g class="tw-arm">${R(33.1, 10, 0.8, 6, "#6c7a8c")}${R(31.2, 15.8, 4.6, 1, "#3b4a5c")}</g>`;
    // the decision feed (top right)
    bg += R(110, 3, 47, 26, "#101b28") + R(110, 3, 47, 3.2, "#1d2a3a");
    bg += `<text x="112" y="5.4" font-family="monospace" font-weight="700" font-size="1.9" fill="#ffd27a">REPORTS → TRINETRA</text>`;
    bg += `<text class="hq-feed-wait" x="112" y="9.4" font-family="monospace" font-size="1.75" fill="#6b7a90">waiting for the first report…</text>`;
    for (let i = 0; i < 6; i++) bg += `<text class="hq-feed" data-i="${i}" x="112" y="${9.4 + i * 3.4}" font-family="monospace" font-size="1.75" fill="#cfe9ff"></text>`;

    // ---- pods: 2 rows of 5 ----
    const pods = data.teams.map((t, i) => ({ t, x: 10 + (i % 5) * 20, base: i < 5 ? 36 : 2 }));
    let fg = "";
    for (const p of pods) {
      const x0 = (p.x - 8.5) * 1.6, top = 90 * (1 - (p.base + 11) / 100);
      fg += R(x0, top, 27.2, 1.4, "#5f6d80") + R(x0 + 0.6, top + 1.4, 26, 7, "#c3ccd8") + R(x0 + 0.6, top + 4.2, 26, 0.3, "#a7b2c2");
      fg += R(x0 + 2, top + 8.4, 1, 1.6, "#5f6d80") + R(x0 + 24.2, top + 8.4, 1, 1.6, "#5f6d80");
      const c = TEAM_LOOK[p.t.id]?.[1] || "#f0a83a"; fg += R(x0 + 0.6, top + 1.4, 26, 0.8, c);
    }
    // org lines: managers → CEO (viewBox 0–100, stretched)
    const lines = pods.map((p) => `<path class="hq-line" data-team="${p.t.id}" d="M${p.x} ${100 - p.base - 3} C ${p.x} 55, 50 ${p.base > 10 ? 60 : 70}, 50 ${100 - 66}"/>`).join("");
    root.innerHTML = `<svg class="hq-l" viewBox="0 0 160 90" preserveAspectRatio="none" shape-rendering="crispEdges">${bg}</svg>
      <svg class="hq-l" viewBox="0 0 100 100" preserveAspectRatio="none">${lines}</svg>
      <div class="hq-layer back"></div><svg class="hq-l hq-desks" viewBox="0 0 160 90" preserveAspectRatio="none" shape-rendering="crispEdges">${fg}</svg>
      <div class="hq-layer front"></div><div class="hq-layer top"></div>`;
    const back = $(".back"), front = $(".front"), top = $(".top");

    const agents = [];  // {a, el, api, team, home:[x,b,w], mgr}
    function spawn(layer, a, team, x, b, w, mgr) {
      const el = document.createElement("div"); el.className = "hq-ag" + (mgr ? " mgr" : "") + (a.status !== "active" ? " planned" : "");
      el.style.cssText = `left:${x}%;bottom:${b}%;width:${w}%`; el.title = `${a.name} — ${a.role}`;
      layer.appendChild(el);
      const inner = document.createElement("div"); inner.style.cssText = "width:100%;height:100%"; el.appendChild(inner);
      const [pal, tie] = TEAM_LOOK[team.id] || ["saffron", "#3a7bd5"];
      const api = B.create(inner, { style: "pixel", palette: pal, static: true, suit: { jacket: mgr ? "#1c2030" : "#2f3647", tie, badge: mgr ? "#ffd27a" : null } });
      api.setActivity("watching");
      const ag = { a, el, api, team, home: [x, b, w], mgr };
      el.addEventListener("click", (e) => { e.stopPropagation(); card(ag); });
      agents.push(ag); return ag;
    }
    for (const p of pods) {
      const mgrId = p.t.manager, members = p.t.members.filter((m) => m.id !== mgrId), mgr = p.t.members.find((m) => m.id === mgrId);
      const per = Math.ceil(members.length / 2);
      members.forEach((m, i) => {
        const row = i < per ? 0 : 1, n = row ? members.length - per : per, k = row ? i - per : i;
        const x = p.x - 7 + (14 / Math.max(1, n)) * (k + 0.5) + (row ? 1 : 0);
        spawn(back, m, p.t, x, p.base + (row ? 9.5 : 13.5), 3.4, false);
      });
      p.mgr = spawn(front, mgr, p.t, p.x, p.base + 0.5, 4.6, true);
      const sign = document.createElement("div"); sign.className = "hq-sign pod";
      sign.innerHTML = `${p.t.emoji} ${p.t.title} <small>· ${p.t.members.length}</small>`;
      sign.style.cssText = `left:${p.x}%;bottom:${p.base + 21}%`; top.appendChild(sign);
      const col = document.createElement("div"); col.className = "hq-sign col"; col.textContent = `${p.t.emoji} ${p.t.title}`;
      top.appendChild(col); p.col = col;
    }
    // the CEO
    const ceoEl = document.createElement("div"); ceoEl.className = "hq-ag"; ceoEl.style.cssText = "left:50%;bottom:64.5%;width:6.4%";
    front.appendChild(ceoEl);
    const ceoIn = document.createElement("div"); ceoIn.style.cssText = "width:100%;height:100%"; ceoEl.appendChild(ceoIn);
    const ceo = B.create(ceoIn, { style: look.style || "pixel", palette: look.palette || "saffron", suit: { jacket: "#1c2030", tie: "#ffd27a", badge: "#ffd27a" } });
    ceo.setActivity("watching");
    ceoEl.addEventListener("click", (e) => { e.stopPropagation(); card({ el: ceoEl, a: { name: "TRINETRA", role: "The CEO. The 10 managers report here; it decides and speaks for Tarun.", status: "active" }, ceo: true }); });

    // ---- speech, cards, the feed ----
    const posOf = (el) => [parseFloat(el.style.left), parseFloat(el.style.bottom), parseFloat(el.style.width)];
    function say(el, text, ms = 2400, cls = "") {
      const [x, b, w] = posOf(el), s = document.createElement("div");
      if (cls === "ceo") top.querySelectorAll(".hq-say.ceo").forEach((o) => o.remove());  // its newest line replaces the last
      s.className = "hq-say " + cls; s.textContent = text;
      s.style.left = Math.min(91, Math.max(9, x)) + "%"; s.style.top = `calc(${100 - b - w * 16 / 9}% - 4px)`;  // never off the edge
      top.appendChild(s); setTimeout(() => s.remove(), ms); return s;
    }
    let cardEl = null;
    function card(ag) {
      cardEl?.remove();
      const [x, b, w] = posOf(ag.el), c = document.createElement("div"); c.className = "hq-card";
      const mgrName = ag.team ? ag.team.members.find((m) => m.id === ag.team.manager)?.name : "";
      c.innerHTML = `<b></b><div class="t"></div><div class="r"></div><div class="st"></div>`;
      c.querySelector("b").textContent = ag.a.name;
      c.querySelector(".t").textContent = ag.ceo ? "CEO" : ag.mgr ? `★ Manager · ${ag.team.emoji} ${ag.team.title} → reports to TRINETRA` : `${ag.team.emoji} ${ag.team.title} · reports to ${mgrName}`;
      c.querySelector(".r").textContent = ag.a.role;
      c.querySelector(".st").textContent = ag.a.status === "active" ? "● live" : "🛠 still being built in the build bay";
      c.style.left = Math.min(88, Math.max(12, x)) + "%"; c.style.top = `calc(${100 - b - w * 16 / 9}% - 6px)`;
      if (100 - b - w * 16 / 9 < 30) { c.style.transform = "translate(-50%, 0)"; c.style.top = `calc(${100 - b}% + 6px)`; }
      top.appendChild(c); cardEl = c;
      later(5200, () => { if (cardEl === c) { c.remove(); cardEl = null; } });
    }
    root.addEventListener("click", () => { cardEl?.remove(); cardEl = null; });
    const feed = [];
    function log(line) {
      feed.unshift(line); feed.length = Math.min(feed.length, 6);
      root.querySelector(".hq-feed-wait")?.remove();
      root.querySelectorAll(".hq-feed").forEach((t, i) => { t.textContent = feed[i] ? (feed[i].length > 44 ? feed[i].slice(0, 43) + "…" : feed[i]) : ""; });
    }
    const short = (t, n = 46) => (t.length > n ? t.slice(0, n - 1).replace(/[\s,;:—-]+\S*$/, "") + "…" : t);

    // ---- the work loop: a member reports to its manager, the manager to TRINETRA, TRINETRA decides ----
    let turn = 0;
    function reportRound(p = pods[turn++ % pods.length]) {
      if (mode !== "work") return;
      const team = agents.filter((g) => g.team.id === p.t.id && !g.mgr);
      const from = team[Math.floor(Math.random() * team.length)];
      const line = root.querySelector(`.hq-line[data-team="${p.t.id}"]`);
      if (from) { from.api.setActivity("thinking"); say(from.el, `→ ${p.mgr.a.name}: ${short(from.a.role, 34)}`, 1700); }
      later(1500, () => {
        from?.api.setActivity("watching");
        p.mgr.api.celebrate(); say(p.mgr.el, `${p.t.emoji} ${TEAM_REPORT[p.t.id] || "Update ready"}`, 2000);
        line?.classList.add("hot");
      });
      later(3000, () => {
        line?.classList.remove("hot");
        const d = p.t.id === "communications" ? "Keep building 🛠" : DECISIONS[Math.floor(Math.random() * DECISIONS.length)];
        say(ceoEl, d, 1800, "ceo"); ceo.setEmotion(p.t.id === "communications" ? "firm" : "proud");
        later(1500, () => ceo.setEmotion("neutral"));
        log(`${p.t.title}: ${TEAM_REPORT[p.t.id] || "update"} → ${d}`);
      });
    }
    // the build bay: works through the planned agents
    const planned = agents.filter((g) => g.a.status !== "active");
    let bi = 0, prog = 0;
    function buildTick() {
      const g = planned[bi % Math.max(1, planned.length)]; if (!g) return;
      prog = (prog + 0.1) % 1.05;
      const t = $(".hq-build"), bar = $(".hq-buildbar");
      if (t) t.textContent = `BUILDING ${g.a.name.toUpperCase()}`.slice(0, 26);
      if (bar) bar.setAttribute("width", 22 * Math.min(1, prog));
      root.classList.toggle("arm-down", Math.random() < 0.5);
      if (prog >= 1) { prog = 0; bi++; g.api.celebrate(); }
    }
    // ---- orders ----
    function assemble() {
      mode = "lined"; cardEl?.remove(); root.classList.add("lined");
      say(ceoEl, "Team, assemble! 📣", 2200, "ceo"); ceo.setEmotion("proud");
      pods.forEach((p, ci) => {
        const x = 5.5 + ci * 9.9, team = agents.filter((g) => g.team.id === p.t.id && !g.mgr);
        p.col.style.cssText = `left:${x}%;bottom:0.6%`;
        p.mgr.el.style.transitionDelay = ci * 60 + "ms";
        p.mgr.el.style.left = x + "%"; p.mgr.el.style.bottom = "5%"; p.mgr.el.style.width = "4.6%";
        front.appendChild(p.mgr.el);
        team.forEach((g, k) => {
          g.el.style.transitionDelay = (ci * 60 + (k + 1) * 70) + "ms";
          g.el.style.left = x + "%"; g.el.style.bottom = (13.5 + k * 6.6) + "%"; g.el.style.width = "3.4%";
          front.appendChild(g.el);
        });
      });
      later(1800, () => { agents.forEach((g) => g.api.setEmotion("happy")); say(ceoEl, `All ${data.total} agents in line ✓ · ${data.teams.length} teams, managers in front`, 3000, "ceo"); });
    }
    function backToWork() {
      mode = "work"; root.classList.remove("lined"); cardEl?.remove();
      agents.forEach((g, i) => {
        g.el.style.transitionDelay = (i % 12) * 50 + "ms";
        const [x, b, w] = g.home; g.el.style.left = x + "%"; g.el.style.bottom = b + "%"; g.el.style.width = w + "%";
        (g.mgr ? front : back).appendChild(g.el); g.api.setEmotion("neutral");
      });
      say(ceoEl, "Back to work 💼", 1800, "ceo"); ceo.setEmotion("neutral");
    }
    function whatDoYouDo() {  // each team in turn: the manager says what the team does, every member says its own task
      const run = ++roleRun;
      say(ceoEl, "Team — tell them what you do 🎤", 2200, "ceo");
      pods.forEach((p, ci) => later(1600 + ci * 3400, () => {
        if (run !== roleRun) return;
        say(p.mgr.el, `${p.t.emoji} ${p.t.title}: ${short(p.t.about, 60)}`, 3200); p.mgr.api.celebrate();
        agents.filter((g) => g.team.id === p.t.id && !g.mgr).forEach((g, k) => later(300 + k * 380, () => {
          if (run === roleRun) say(g.el, short(g.a.role, 40), 2600);
        }));
      }));
      opts.onRoster?.();
    }
    let roleRun = 0;
    if (!still) { every(4200, () => reportRound()); every(900, buildTick); every(350, () => agents[Math.floor(Math.random() * agents.length)]?.api.blink()); }
    later(500, () => say(ceoEl, `Welcome to TRINETRA HQ 👋 ${data.total} agents in ${data.teams.length} teams. Try “assemble”!`, 3800, "ceo"));
    return {
      assemble, backToWork, whatDoYouDo, report: () => { const lined = mode === "lined"; if (lined) backToWork(); later(lined ? 1400 : 0, () => reportRound()); },
      get mode() { return mode; }, agents, pods,
      destroy() { timers.forEach((t) => { clearTimeout(t); clearInterval(t); }); agents.forEach((g) => g.api.destroy()); ceo.destroy(); root.remove(); },
    };
  }

  // ---------- the big screen (an overlay inside the portfolio): Lab (HQ) · Lake · Home ----------
  const OV_CSS = `
  .tw-ov { position: fixed; inset: 0; z-index: 2147483600; background: rgba(8, 9, 16, .72); backdrop-filter: blur(6px); -webkit-backdrop-filter: blur(6px);
    display: flex; align-items: center; justify-content: center; padding: 18px; animation: tw-fade .25s ease-out; font-family: -apple-system, system-ui, sans-serif; }
  @keyframes tw-fade { from { opacity: 0; } }
  .tw-box { width: min(1200px, 100%); max-height: 100%; display: flex; flex-direction: column; background: #0f0e16; color: #efedf7;
    border: 1px solid #2c2a3b; border-radius: 18px; overflow: hidden; box-shadow: 0 30px 80px rgba(0,0,0,.5); position: relative; }
  .tw-head { display: flex; align-items: center; gap: 10px; padding: 10px 12px 10px 16px; border-bottom: 1px solid #2c2a3b; flex-wrap: wrap; }
  .tw-head b { letter-spacing: .14em; color: #f0a83a; font-size: 14px; }
  .tw-tabs { display: flex; gap: 6px; }
  .tw-tabs button, .tw-bar button, .tw-head .btn { border: 1px solid #343850; background: #17161f; color: #efedf7; border-radius: 16px; padding: 6px 12px;
    font-size: 13px; cursor: pointer; font-weight: 600; }
  .tw-tabs button.on { background: #f0a83a; color: #1a1205; border-color: #f0a83a; }
  .tw-tabs button .now { font-size: 10px; margin-left: 4px; color: #7ee0c3; }
  .tw-tabs button.on .now { color: #1a1205; }
  .tw-head .sp { flex: 1; }
  .tw-head .where { font-size: 12px; color: #9a98b0; }
  .tw-head .btn.chat { border-color: #f0a83a; color: #f0a83a; }
  .tw-head .x { width: 32px; height: 32px; border-radius: 50%; padding: 0; }
  .tw-scroll { overflow: auto; -webkit-overflow-scrolling: touch; position: relative; }
  .tw-stage { position: relative; width: min(100%, calc((100vh - 200px) * 16 / 9)); aspect-ratio: 16 / 9; margin: 0 auto; background: #101018; }
  .tw-stage.small { min-width: 860px; }
  .tw-bar { display: flex; gap: 6px; padding: 10px 12px; border-top: 1px solid #2c2a3b; flex-wrap: wrap; align-items: center; }
  .tw-bar input { flex: 1; min-width: 160px; background: #17161f; color: #efedf7; border: 1px solid #343850; border-radius: 16px; padding: 7px 12px; font-size: 16px; outline: none; }
  .tw-bar input:focus { border-color: #f0a83a; }
  .tw-bar .hint { font-size: 11px; color: #9a98b0; }
  .tw-roster { position: absolute; right: 0; top: 0; bottom: 0; width: min(380px, 92%); background: rgba(15, 14, 22, .97); border-left: 1px solid #2c2a3b;
    overflow-y: auto; padding: 14px 16px; font-size: 12.5px; line-height: 1.45; z-index: 10; animation: tw-slide .3s ease-out; }
  @keyframes tw-slide { from { transform: translateX(30px); opacity: 0; } }
  .tw-roster h3 { margin: 0 0 4px; font-size: 15px; color: #f0a83a; } .tw-roster .ceo { color: #ffd27a; margin-bottom: 10px; }
  .tw-roster .team { margin: 12px 0 0; padding-top: 10px; border-top: 1px solid #2c2a3b; }
  .tw-roster .team > b { font-size: 13px; } .tw-roster .about { color: #9a98b0; }
  .tw-roster .mgr { margin: 5px 0 3px; color: #ffd27a; }
  .tw-roster ul { margin: 0; padding-left: 16px; } .tw-roster li { margin: 2px 0; } .tw-roster li.planned { opacity: .6; }
  .tw-roster .close { position: sticky; top: 0; float: right; border: 1px solid #343850; background: #17161f; color: #efedf7; border-radius: 12px; padding: 3px 9px; cursor: pointer; }
  .tw-swipe { position: sticky; left: 50%; bottom: 8px; width: max-content; transform: translateX(-50%); margin-top: -34px; background: rgba(15,14,22,.85);
    color: #fff; font-size: 12px; padding: 5px 12px; border-radius: 14px; pointer-events: none; animation: tw-fade .4s ease-out; }
  [hidden] { display: none !important; }
  @media (max-width: 700px) { .tw-ov { padding: 0; } .tw-box { border-radius: 0; height: 100%; } .tw-head .where { display: none; } }`;

  function open(container, opts = {}) {
    const host = container.getRootNode ? container.getRootNode() : document, where = host === document ? document.head : host;
    if (!where.querySelector?.("style[data-trinetra-ov]")) { const st = document.createElement("style"); st.dataset.trinetraOv = ""; st.textContent = OV_CSS; where.appendChild(st); }
    injectCSS(container);
    const ov = document.createElement("div"); ov.className = "tw-ov"; ov.setAttribute("role", "dialog"); ov.setAttribute("aria-label", "TRINETRA's world");
    const now = placeAt(laNow().h), nowTab = now === "sleep" ? "home" : now;
    ov.innerHTML = `<div class="tw-box">
      <div class="tw-head"><b>TRINETRA</b><div class="tw-tabs">
        <button data-p="lab">🧪 Lab</button><button data-p="lake">🌅 Lake</button><button data-p="home">🏠 Home</button></div>
        <span class="sp"></span><span class="where"></span>
        <button class="btn chat" type="button">💬 Chat</button><button class="btn x" type="button" aria-label="Close">✕</button></div>
      <div class="tw-scroll"><div class="tw-stage"></div></div>
      <div class="tw-bar"><button data-c="assemble">🧍 Assemble</button><button data-c="roles">❓ What do you do?</button>
        <button data-c="work">💼 Back to work</button><button data-c="report">📣 Report</button>
        <input placeholder="Give the team an order… (try “assemble”)" aria-label="Order for the team" maxlength="80"></div>
    </div>`;
    container.appendChild(ov);
    const $ = (q) => ov.querySelector(q), stage = $(".tw-stage"), bar = $(".tw-bar");
    const fit = () => stage.classList.toggle("small", innerWidth < 860);
    fit(); addEventListener("resize", fit);
    const labels = { lab: "at the lab", lake: "at the lake", home: "at home", sleep: "asleep at home" };
    $(".where").textContent = `TRINETRA is ${labels[now]} right now · ${clock(laNow())} LA`;
    ov.querySelector(`.tw-tabs [data-p="${nowTab}"]`).insertAdjacentHTML("beforeend", `<span class="now">● now</span>`);
    let scene = null, hqApi = null, roster = null, data = null, goGen = 0;
    const agentsP = Promise.resolve(opts.agents).then((d) => (data = d)).catch(() => null);

    async function go(p) {
      const gen = ++goGen;  // a newer tab click (or close) wins over a slow load
      ov.querySelectorAll(".tw-tabs button").forEach((b) => b.classList.toggle("on", b.dataset.p === p));
      scene?.destroy(); scene = null; hqApi = null; roster?.remove(); roster = null;
      stage.innerHTML = ""; bar.hidden = p !== "lab";
      if (p === "lab") {
        await agentsP;
        if (gen !== goGen || !ov.isConnected) return;
        if (!data) { stage.innerHTML = `<div style="padding:30px;color:#9a98b0">The lab is closed for a moment — try again soon.</div>`; return; }
        hqApi = scene = hq(stage, { agents: data, look: opts.look, onRoster: showRoster });
        const sc = $(".tw-scroll");  // a phone sees part of the room: start on the CEO, swipe for the rest
        if (sc.scrollWidth > sc.clientWidth) {
          sc.scrollLeft = (sc.scrollWidth - sc.clientWidth) / 2;
          const hint = document.createElement("div"); hint.className = "tw-swipe"; hint.textContent = "← swipe to see every team →";
          sc.appendChild(hint); setTimeout(() => hint.remove(), 4000);
        }
      } else {  // the lake / home scenes, big, with its own TRINETRA
        const meBox = document.createElement("div"); meBox.style.cssText = "width:100%;height:100%";
        const meApi = window.TrinetraBuddy.create(meBox, opts.look || {});
        const inner = document.createElement("div"); inner.style.cssText = "position:absolute;inset:0"; stage.appendChild(inner);
        const w = create(inner, { me: { el: meBox, api: meApi }, style: opts.look?.style, place: p });
        w.attach();
        scene = { destroy() { w.destroy(); meApi.destroy(); } };
        if (p === "home") inner.addEventListener("dblclick", () => w.knock());
        inner.title = p === "home" ? "Double-click to knock" : "";
      }
    }
    function showRoster() {
      if (!data) return;
      roster?.remove();
      roster = document.createElement("aside"); roster.className = "tw-roster";
      const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
      roster.innerHTML = `<button class="close" type="button">✕</button><h3>Who does what</h3>
        <div class="ceo">👑 <b>TRINETRA</b> — CEO. The 10 managers report to it; it decides and speaks for Tarun.</div>
        <div>${data.total} agents · ${data.teams.length} teams · ${data.active} live, ${data.total - data.active} being built</div>` +
        data.teams.map((t) => {
          const m = t.members.find((x) => x.id === t.manager);
          return `<div class="team"><b>${t.emoji} ${esc(t.title)}</b> <span class="about">— ${esc(t.about)}</span>
            <div class="mgr">★ Manager: <b>${esc(m.name)}</b> — ${esc(m.role)}</div>
            <ul>${t.members.filter((x) => x.id !== t.manager).map((x) => `<li class="${x.status === "active" ? "" : "planned"}"><b>${esc(x.name)}</b> — ${esc(x.role)}${x.status === "active" ? "" : " 🛠"}</li>`).join("")}</ul></div>`;
        }).join("");
      roster.querySelector(".close").onclick = () => { roster.remove(); roster = null; };
      $(".tw-scroll").appendChild(roster);
    }
    function order(c) {
      if (!hqApi || !ov.isConnected) return;
      const t = String(c).toLowerCase();
      if (/assemble|line ?up|fall in|gather|attention/.test(t)) hqApi.assemble();
      else if (/what|task|job|role|do you do|who does|roster/.test(t)) hqApi.whatDoYouDo();
      else if (/work|dismiss|go back|desk/.test(t)) hqApi.backToWork();
      else if (/report|update|status/.test(t)) hqApi.report();
    }
    bar.addEventListener("click", (e) => { const b = e.target.closest("button[data-c]"); if (b) order(b.dataset.c); });
    const input = bar.querySelector("input");
    input.addEventListener("keydown", (e) => { if (e.key === "Enter" && input.value.trim()) { order(input.value); input.value = ""; } });
    ov.querySelectorAll(".tw-tabs button").forEach((b) => (b.onclick = () => go(b.dataset.p)));
    const close = () => { goGen++; scene?.destroy(); scene = null; hqApi = null; removeEventListener("resize", fit); ov.remove(); opts.onClose?.(); };
    $(".x").onclick = close;
    $(".chat").onclick = () => { close(); opts.onChat?.(); };
    ov.addEventListener("click", (e) => { if (e.target === ov) close(); });
    ov.addEventListener("keydown", (e) => { if (e.key === "Escape") { e.stopPropagation(); close(); } });
    ov.tabIndex = -1; setTimeout(() => ov.focus(), 30);
    const ready = go(opts.place || "lab").then(() => { if (opts.cmd) setTimeout(() => order(opts.cmd), 900); });
    return { close, go, order, ready, get el() { return ov; } };
  }

  window.TrinetraWorld = { create, hq, open, placeAt, laNow };
})();
