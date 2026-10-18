/* TRINETRA's music — made up on the spot, never the same twice.
   The tunes come from what it learned from 909 real songs (static/music/model.json, trained by music/train.py):
   which note tends to follow which, and which chord follows which, for major and minor keys. Each mood picks the key,
   tempo, energy and feel; each instrument plays the tune its own way (strums, arpeggios, rolls, a drone, a groove).
   Sounds: real instrument samples (static/music/samples, FluidR3 GM, CC BY 3.0); drums are synthesised.

   TrinetraMusic.show(buddy, { show: "play", instrument: "guitar", mood: "sad" }, { feel, onEnd }) → handle.stop()
   TrinetraMusic.show(buddy, { show: "dance", seconds: 10 }, …)   // a pink partner joins for a 10 s dance
   TrinetraMusic.stopAll()   // also: Esc, or tapping the character (the host wires that)  */
(() => {
  if (window.TrinetraMusic) return;
  const BASE = new URL("music/", document.currentScript?.src || location.href).href;

  // ---------- moods → how the music feels ----------
  const MOODS = {  // mode · tempo · energy (0–1) · how adventurous the tune is · drum feel
    neutral: { mode: "maj", bpm: 96, energy: 0.5, temp: 1, drums: "pop" },
    happy: { mode: "maj", bpm: 108, energy: 0.65, temp: 1, drums: "pop" },
    excited: { mode: "maj", bpm: 124, energy: 0.9, temp: 1.1, drums: "four" },
    proud: { mode: "maj", bpm: 88, energy: 0.7, temp: 0.9, drums: "rock" },
    caring: { mode: "maj", bpm: 70, energy: 0.35, temp: 0.85, drums: "half" },
    shy: { mode: "maj", bpm: 84, energy: 0.3, temp: 0.9, drums: "half" },
    surprised: { mode: "maj", bpm: 112, energy: 0.6, temp: 1.3, drums: "pop" },
    sad: { mode: "min", bpm: 60, energy: 0.3, temp: 0.85, drums: "half" },
    firm: { mode: "min", bpm: 92, energy: 0.6, temp: 0.9, drums: "half" },
    angry: { mode: "min", bpm: 136, energy: 1, temp: 1.1, drums: "rock" },
    sleepy: { mode: "maj", bpm: 54, energy: 0.15, temp: 0.8, drums: "brush" },
  };
  // instruments → sample set, the notes the tune may use, how it accompanies itself, room size
  const INST = {
    guitar: { set: "guitar", mel: [55, 79], comp: "strum", verb: 0.22 },
    electric: { set: "electric", mel: [52, 76], comp: "power", verb: 0.18, drums: true, sustain: true },
    ukulele: { set: "nylon", mel: [64, 84], comp: "strum", verb: 0.18, compRange: [60, 76] },
    bass: { set: "bass", mel: [33, 55], comp: "bassline", verb: 0.08, drums: true, noTune: true },
    banjo: { set: "banjo", mel: [57, 81], comp: "roll", verb: 0.15 },
    sitar: { set: "sitar", mel: [55, 79], comp: "drone", verb: 0.3 },
    violin: { set: "violin", mel: [62, 91], comp: "pad", verb: 0.35, sustain: true },
    cello: { set: "cello", mel: [43, 67], comp: "pad", verb: 0.32, sustain: true },
    piano: { set: "piano", mel: [60, 84], comp: "piano", verb: 0.28 },
    harp: { set: "harp", mel: [60, 88], comp: "arp", verb: 0.4 },
    flute: { set: "flute", mel: [67, 93], comp: "pad", verb: 0.35, sustain: true },
    sax: { set: "sax", mel: [52, 76], comp: "pad", verb: 0.25, sustain: true },
    trumpet: { set: "trumpet", mel: [58, 82], comp: "pad", verb: 0.25, sustain: true },
    xylophone: { set: "xylophone", mel: [69, 96], comp: "none", verb: 0.25 },
    drums: { set: null, comp: "none", drums: true, noTune: true },
  };
  const DEFAULT_FOR = { happy: "guitar", excited: "electric", proud: "trumpet", caring: "piano", shy: "ukulele", surprised: "xylophone",
    sad: "piano", firm: "cello", angry: "electric", sleepy: "harp", neutral: "piano" };
  const SETS = {  // the sampled range of each set (every 4th semitone; see music/fetch_samples.py)
    guitar: [40, 84], electric: [40, 84], nylon: [44, 84], bass: [28, 64], banjo: [48, 84], sitar: [48, 84], violin: [56, 96],
    cello: [36, 76], piano: [36, 96], epiano: [40, 88], harp: [36, 96], flute: [60, 96], sax: [48, 84], trumpet: [52, 88],
    xylophone: [64, 104], lead: [48, 88],
  };

  // ---------- audio ----------
  let ctx = null, model = null;
  const audio = () => (ctx ??= new (window.AudioContext || window.webkitAudioContext)());
  function unlock() { try { const c = audio(); if (c.state !== "running") c.resume(); } catch {} }
  for (const ev of ["pointerdown", "keydown", "touchend"]) addEventListener(ev, unlock, { passive: true, capture: true });
  let modelP = null;
  const loadModel = () => (modelP ??= fetch(BASE + "model.json").then((r) => r.json()).then((m) => (model = m)));
  const sets = {};
  function loadSet(name) {
    if (!name || !SETS[name]) return Promise.resolve(null);
    return (sets[name] ??= (async () => {
      const [lo, hi] = SETS[name], notes = [];
      for (let m = lo - (lo % 4); m <= hi; m += 4) if (m >= lo - 2) notes.push(m);
      // start as soon as most are in (a slow one fills in later; until then its neighbour plays, shifted)
      const bank = { keys: [], map: new Map() };
      let settled = 0, ready;
      const enough = new Promise((ok) => (ready = ok));
      notes.forEach(async (m) => {
        try {
          const raw = await (await fetch(`${BASE}samples/${name}/${m}.mp3`)).arrayBuffer();
          bank.map.set(m, await new Promise((ok, no) => audio().decodeAudioData(raw, ok, no)));
          bank.keys = [...bank.map.keys()].sort((a, b) => a - b);
        } catch {}
        if (++settled >= Math.ceil(notes.length * 0.75)) ready();
      });
      await Promise.race([enough, new Promise((ok) => setTimeout(ok, 2500))]);
      return bank.keys.length ? bank : (await enough, bank.keys.length ? bank : null);
    })());
  }
  function makeRoom(c) {  // a soft hall: decaying noise as the reverb's impulse
    const len = Math.floor(c.sampleRate * 2.2), ir = c.createBuffer(2, len, c.sampleRate);
    for (let ch = 0; ch < 2; ch++) {
      const d = ir.getChannelData(ch);
      for (let i = 0; i < len; i++) d[i] = (Math.random() * 2 - 1) * Math.pow(1 - i / len, 3.2);
    }
    const v = c.createConvolver(); v.buffer = ir; return v;
  }
  let noiseBuf = null;
  const noise = (c) => {
    if (noiseBuf) return noiseBuf;
    noiseBuf = c.createBuffer(1, c.sampleRate, c.sampleRate);
    const d = noiseBuf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
    return noiseBuf;
  };

  // one performance's mixer: master → compressor → speakers, plus a reverb send
  function Mixer(volume, verbAmt) {
    const c = audio(), master = c.createGain(), comp = c.createDynamicsCompressor(), dry = c.createGain(), wet = c.createGain(), room = makeRoom(c);
    comp.threshold.value = -16; comp.ratio.value = 4;
    master.gain.value = volume; wet.gain.value = verbAmt;
    dry.connect(master); dry.connect(room); room.connect(wet); wet.connect(master); master.connect(comp); comp.connect(c.destination);
    const live = new Set();
    const track = (src) => { live.add(src); src.onended = () => live.delete(src); };
    return {
      c, input: dry, track,
      fade(sec = 0.4) {
        const t = c.currentTime;
        master.gain.cancelScheduledValues(t); master.gain.setValueAtTime(master.gain.value, t); master.gain.linearRampToValueAtTime(0, t + sec);
        setTimeout(() => { for (const s of live) { try { s.stop(); } catch {} } try { comp.disconnect(); } catch {} }, sec * 1000 + 80);
      },
    };
  }

  // play one sampled note: nearest sample, pitch-shifted (±2 semitones), with an envelope
  function sampled(mx, bank, midi, t, dur, vel, o = {}) {
    if (!bank) return synthNote(mx, midi, t, dur, vel);
    const keys = bank.keys;
    let m = keys[0]; for (const k of keys) if (Math.abs(k - midi) < Math.abs(m - midi)) m = k;
    const c = mx.c, src = c.createBufferSource(), g = c.createGain();
    src.buffer = bank.map.get(m); src.playbackRate.value = Math.pow(2, (midi - m) / 12);
    const att = o.attack ?? 0.004, rel = o.release ?? 0.25, peak = Math.max(0.0001, vel);
    g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(peak, t + att);
    if (o.sustain) g.gain.setValueAtTime(peak, t + Math.max(att, dur - 0.02));
    g.gain.setTargetAtTime(0.0001, t + dur, rel / 3);
    src.connect(g); g.connect(mx.input);
    src.start(t); src.stop(t + dur + rel * 2 + 0.05); mx.track(src);
  }
  function synthNote(mx, midi, t, dur, vel) {  // if a sample set can't load: a soft triangle
    const c = mx.c, o = c.createOscillator(), g = c.createGain();
    o.type = "triangle"; o.frequency.value = 440 * Math.pow(2, (midi - 69) / 12);
    g.gain.setValueAtTime(0.0001, t); g.gain.linearRampToValueAtTime(vel * 0.5, t + 0.01); g.gain.setTargetAtTime(0.0001, t + dur, 0.08);
    o.connect(g); g.connect(mx.input); o.start(t); o.stop(t + dur + 0.5); mx.track(o);
  }
  function drum(mx, kind, t, vel) {  // synthesised kit
    const c = mx.c, g = c.createGain(); g.connect(mx.input);
    const env = (peak, decay) => { g.gain.setValueAtTime(peak * vel, t); g.gain.exponentialRampToValueAtTime(0.0001, t + decay); };
    if (kind === "K" || kind === "T" || kind === "t") {  // kick / toms: a falling sine
      const o = c.createOscillator(), [f0, f1, d] = kind === "K" ? [150, 42, 0.38] : kind === "T" ? [220, 120, 0.3] : [160, 90, 0.34];
      o.frequency.setValueAtTime(f0, t); o.frequency.exponentialRampToValueAtTime(f1, t + d * 0.6);
      env(kind === "K" ? 1.1 : 0.7, d); o.connect(g); o.start(t); o.stop(t + d + 0.05); mx.track(o);
      return;
    }
    const n = c.createBufferSource(), f = c.createBiquadFilter(); n.buffer = noise(c);
    n.connect(f); f.connect(g);
    if (kind === "S") {  // snare: noise + a short tone
      f.type = "highpass"; f.frequency.value = 1200; env(0.7, 0.2);
      const o = c.createOscillator(), og = c.createGain(); o.type = "triangle"; o.frequency.value = 190;
      og.gain.setValueAtTime(0.45 * vel, t); og.gain.exponentialRampToValueAtTime(0.0001, t + 0.1);
      o.connect(og); og.connect(mx.input); o.start(t); o.stop(t + 0.12); mx.track(o);
    } else if (kind === "h") { f.type = "highpass"; f.frequency.value = 7500; env(0.32, 0.05); }   // closed hat
    else if (kind === "H") { f.type = "highpass"; f.frequency.value = 6500; env(0.3, 0.28); }    // open hat
    else if (kind === "C") { f.type = "highpass"; f.frequency.value = 4500; env(0.38, 1.4); }    // crash
    else if (kind === "B") { f.type = "bandpass"; f.frequency.value = 3000; env(0.12, 0.18); }   // brush
    n.start(t); n.stop(t + 1.5); mx.track(n);
  }

  // ---------- composing (walks the learned chains) ----------
  const pick = (a) => a[Math.floor(Math.random() * a.length)];
  function weighted(list, temp = 1) {
    let sum = 0; const w = list.map(([, n]) => (sum += Math.pow(n, 1 / temp)));
    const r = Math.random() * sum; return list[w.findIndex((x) => x >= r)][0];
  }
  function Song(mood, opts = {}) {
    const M = { ...(MOODS[mood] || MOODS.neutral), ...(opts.feel || {}) }, mode = M.mode;
    const mel = model.melody[mode], chm = model.chords[mode];
    const tonic = pick(mode === "maj" ? [0, 2, 4, 5, 7, 9] : [9, 4, 2, 7, 0, 5]);
    const scale = mode === "maj" ? [0, 2, 4, 5, 7, 9, 11] : [0, 2, 3, 5, 7, 8, 10];
    const home = mode === "maj" ? "0M" : "0m";
    let h = ["^", "^"], c2 = home, c1 = home;
    const tones = (deg, q) => [0, q === "m" || q === "d" ? 3 : 4, q === "d" ? 6 : 7].map((x) => (deg + x) % 12);
    const snapScale = (rel) => {
      const pc = ((rel % 12) + 12) % 12;
      if (scale.includes(pc)) return rel;
      return scale.includes((pc + 1) % 12) ? rel + 1 : rel - 1;
    };
    function nextChord() {
      const tok = weighted(chm.o2[`${c2} ${c1}`] || chm.o1[c1] || [[home, 1]], M.temp);
      c2 = c1; c1 = tok; return { deg: parseInt(tok, 10), q: tok.slice(-1) };
    }
    function chordsFor() {  // one bar: one chord, or two halves
      const len = weighted(chm.len, 1);
      const a = nextChord();
      return len <= 8 ? [{ at: 0, len: 8, ...a }, { at: 8, len: 8, ...nextChord() }] : [{ at: 0, len: 16, ...a }];
    }
    function nextTok() {
      const two = mel.o2[`${h[0]} ${h[1]}`];
      if (two && Math.random() > 0.08) return weighted(two, M.temp);
      const one = mel.o1[h[1]];
      return one ? weighted(one, M.temp) : weighted(mel.start, M.temp);
    }
    function melodyBar(chords) {
      const out = []; let at = 0, rests = 0;
      while (at < 16) {
        let tok = null, p = "r", d = 2;
        for (let tries = 0; tries < 10; tries++) {
          tok = nextTok();
          if (tok === "$") { h = ["^", "^"]; tok = null; continue; }
          [p, d] = tok.split(","); d = +d;
          if (p === "r" && (rests || (at === 0 && tries < 8))) { tok = null; continue; }  // a breath, not silence
          if (d <= 16 - at || tries >= 8) break;
        }
        if (!tok) { tok = weighted(mel.start, M.temp); [p, d] = tok.split(","); d = +d; }
        h = [h[1], tok];
        d = Math.max(1, Math.min(d, 16 - at));
        if (p === "r") { rests++; out.push({ at, len: d, rest: true }); }
        else {
          let rel = snapScale(+p);
          const chord = chords.find((c) => at >= c.at && at < c.at + c.len) || chords[0];
          if (at % 8 === 0) {  // strong beats land on a chord note
            const ct = tones(chord.deg, chord.q), pc = ((rel % 12) + 12) % 12;
            if (!ct.includes(pc)) {
              const near = [-1, 1, -2, 2].find((x) => ct.includes((pc + x + 12) % 12));
              if (near !== undefined) rel += near;
            }
          }
          out.push({ at, len: d, rel });
        }
        at += d;
      }
      return out;
    }
    const bar = () => { const chords = chordsFor(); return { chords, notes: melodyBar(chords) }; };
    const vary = (b) => ({ chords: b.chords, notes: b.notes.map((n) => {
      if (n.rest || Math.random() > 0.25) return n;
      const i = scale.indexOf(((n.rel % 12) + 12) % 12), step = Math.random() < 0.5 ? -1 : 1;
      if (i < 0) return n;
      const j = (i + step + 7) % 7, oct = Math.floor(n.rel / 12) * 12 + (step > 0 && j < i ? 12 : step < 0 && j > i ? -12 : 0);
      return { ...n, rel: oct + scale[j] };
    }) });
    const ending = (b) => {
      const notes = b.notes.filter((n) => n.at < 8);
      const last = [...notes].reverse().find((n) => !n.rest);
      const target = last ? Math.round(last.rel / 12) * 12 : 0;
      notes.push({ at: 8, len: 8, rel: target });
      return { chords: [{ ...b.chords[0], at: 0, len: 8 }, { at: 8, len: 8, deg: 0, q: home.slice(-1) }], notes, end: true };
    };
    let queue = [];
    function section() {  // A A' B B · A A'' C end — a motif, an answer, the motif again, then home
      c2 = home; c1 = home;
      const a = [bar(), bar()], b = [bar(), bar()], c = [bar(), bar()];
      queue = [a[0], a[1], b[0], b[1], a[0], vary(a[1]), c[0], ending(c[1])];
    }
    return { M, tonic, mode, next() { if (!queue.length) section(); return queue.shift(); } };
  }

  // ---------- performing a song ----------
  const PATTERNS = {  // 16 steps per bar
    four: { K: "x...x...x...x...", S: "....x.......x...", h: "x.x.x.x.x.x.x.x.", H: "..x...x...x...x." },
    pop: { K: "x......x..x.....", S: "....x.......x...", h: "x.x.x.x.x.x.x.x." },
    rock: { K: "x.x...x.x.x...x.", S: "....x.......x...", h: "x.x.x.x.x.x.x.x." },
    half: { K: "x.........x.....", S: "........x.......", h: "x...x...x...x..." },
    brush: { B: "x...x...x...x...", K: "x.......x......." },
  };
  async function perform(o) {
    const mood = MOODS[o.mood] ? o.mood : "neutral";
    const inst = INST[o.instrument] ? o.instrument : DEFAULT_FOR[mood];
    const I = INST[inst], dance = !!o.dance;
    unlock();
    await loadModel();
    const [bank, pad, bassBank, lead] = await Promise.all([
      loadSet(dance ? "epiano" : I.set),
      loadSet(!dance && I.comp === "pad" ? "epiano" : null),
      loadSet(dance || inst === "bass" ? "bass" : null),
      loadSet(dance ? "lead" : null),
    ]);
    if (o.cancelled?.()) return null;
    const song = Song(mood, { feel: dance ? { bpm: mood === "sad" ? 96 : 120, energy: 0.95, drums: "four" } : null });
    const M = song.M, u = 60 / M.bpm / 4, barDur = 16 * u;
    const mx = Mixer(0.55 + 0.35 * Math.min(1, M.energy + 0.2), dance ? 0.18 : I.verb ?? 0.25);
    const c = mx.c, root = 60 + song.tonic;
    const melRange = dance ? [62, 84] : I.mel || [60, 84];
    const oct = 12 * Math.round(((melRange[0] + melRange[1]) / 2 - (root + 7)) / 12);
    const fold = (m, [lo, hi]) => { while (m < lo) m += 12; while (m > hi) m -= 12; return m; };
    const voice = (deg, q, [lo, hi], n = 3) => {  // chord notes inside a range, low to high
      const pcs = [0, q === "m" || q === "d" ? 3 : 4, q === "d" ? 6 : 7, 12].map((x) => (song.tonic + deg + x) % 12);
      const out = [];
      for (let m = lo; m <= hi && out.length < n; m++) if (pcs.includes(m % 12)) out.push(m);
      return out;
    };
    const bassOf = (deg, lo = 36) => fold(root + deg, [lo, lo + 11]);
    const vel = (at, base) => base * (at % 4 === 0 ? 1 : 0.8) * (0.9 + Math.random() * 0.2) * (0.55 + 0.45 * M.energy);
    const human = () => (Math.random() - 0.5) * 0.012;
    const cb = (t, fn) => setTimeout(fn, Math.max(0, (t - c.currentTime) * 1000));
    let barNo = 0;

    function drums(bar, t0, loud) {
      const style = PATTERNS[M.drums] || PATTERNS.pop, fill = barNo % 4 === 3, start = barNo % 8 === 0;
      for (const [k, pat] of Object.entries(style)) for (let i = 0; i < 16; i++) {
        if (pat[i] !== "x" || (fill && i >= 12 && k !== "K")) continue;
        drum(mx, k, t0 + i * u + human(), loud * (k === "h" ? (i % 4 ? 0.6 : 0.9) : 1));
        if (k === "K" || k === "S") cb(t0 + i * u, () => o.onNote?.({ drum: k }));
      }
      if (Math.random() < 0.3) drum(mx, "S", t0 + pick([3, 6, 7, 11, 14, 15]) * u, loud * 0.25);  // ghost notes
      if (fill) for (let i = 12; i < 16; i++) { drum(mx, i < 14 ? "T" : "t", t0 + i * u, loud * 0.8); cb(t0 + i * u, () => o.onNote?.({ drum: "T" })); }
      if (start && barNo) { drum(mx, "C", t0, loud * 0.8); cb(t0, () => o.onNote?.({ drum: "C" })); }
    }
    function comp(bar, t0) {
      const kind = dance ? "dance" : I.comp, set = dance ? bank : kind === "pad" ? pad : bank;
      for (const ch of bar.chords) {
        const t = t0 + ch.at * u, L = ch.len * u;
        if (kind === "piano") {
          sampled(mx, set, bassOf(ch.deg), t, L, vel(0, 0.55), { release: 0.6 });
          const notes = voice(ch.deg, ch.q, [53, 67], 3);
          if (M.energy >= 0.6) for (let s = 0; s < ch.len; s += 4) notes.forEach((m) => sampled(mx, set, m, t + s * u + human(), u * 3, vel(s, 0.32)));
          else { const arp = [...notes, notes[1] + 12, notes[2]]; for (let s = 0; s < ch.len; s += 2) sampled(mx, set, arp[(s / 2) % arp.length], t + s * u + human(), u * 4, vel(s, 0.3), { release: 0.5 }); }
        } else if (kind === "strum") {
          const notes = voice(ch.deg, ch.q, I.compRange || [45, 66], 5);
          const steps = M.energy >= 0.6 ? [[0, 1], [4, 1], [6, 0], [10, 0], [12, 1], [14, 0]] : M.energy >= 0.3 ? [[0, 1], [6, 0], [8, 1], [12, 0]] : [[0, 1], [8, 1]];
          for (const [s, down] of steps) {
            if (s >= ch.len) continue;
            const order = down ? notes : [...notes].reverse(), gap = M.energy < 0.3 ? 0.03 : 0.012;
            order.forEach((m, i) => sampled(mx, set, m, t + s * u + i * gap, u * 4, vel(s, down ? 0.3 : 0.2), { release: 0.4 }));
            cb(t + s * u, () => o.onStrum?.(down));
          }
        } else if (kind === "power") {
          const r = bassOf(ch.deg, 40), step = M.energy >= 0.9 ? 1 : 2;
          for (let s = 0; s < ch.len; s += step) [r, r + 7, r + 12].forEach((m) => sampled(mx, set, m, t + s * u, u * step * 0.8, vel(s, 0.22), { release: 0.05 }));
        } else if (kind === "roll") {
          const notes = voice(ch.deg, ch.q, [55, 76], 4), roll = [0, 1, 2, 3, 0, 2, 1, 3];
          for (let s = 0; s < ch.len; s++) sampled(mx, set, notes[roll[s % 8] % notes.length], t + s * u, u * 2, vel(s, 0.2));
        } else if (kind === "arp") {
          const notes = voice(ch.deg, ch.q, [48, 79], 7), up = [...notes, ...notes.slice(1, -1).reverse()];
          const step = M.energy >= 0.5 ? 1 : 2;
          for (let s = 0; s < ch.len; s += step) sampled(mx, set, up[(s / step) % up.length], t + s * u, u * 6, vel(s, 0.24), { release: 1 });
        } else if (kind === "drone") {
          if (ch.at === 0) [root - 12, root - 5].forEach((m) => sampled(mx, set, fold(m, [48, 60]), t, barDur, 0.22, { release: 1.2 }));
        } else if (kind === "pad") {
          voice(ch.deg, ch.q, [52, 70], 3).forEach((m) => sampled(mx, set, m, t, L, 0.14, { attack: 0.08, sustain: true, release: 0.8 }));
          sampled(mx, set, bassOf(ch.deg), t, L, 0.16, { attack: 0.05, sustain: true, release: 0.8 });
        } else if (kind === "bassline") {
          const r = bassOf(ch.deg, 33), line = [0, 0, 7, 0, 12, 0, 7, 10];
          for (let s = 0; s < ch.len; s += 2) {
            const m = s === ch.len - 2 && Math.random() < 0.5 ? r + pick([-1, 2, 5]) : r + line[(s / 2) % 8];
            sampled(mx, bank, m, t + s * u + human(), u * 1.7, vel(s, 0.7), { release: 0.08 });
            cb(t + s * u, () => o.onStrum?.(s % 4 === 0));
          }
        } else if (kind === "dance") {
          for (let s = 2; s < ch.len; s += 4) voice(ch.deg, ch.q, [55, 72], 3).forEach((m) => sampled(mx, set, m, t + s * u, u * 1.5, 0.2, { release: 0.1 }));
          for (let s = 0; s < ch.len; s += 2) sampled(mx, bassBank, bassOf(ch.deg, 33) + (s % 4 ? 12 : 0), t + s * u, u * 1.6, 0.55, { release: 0.06 });
        }
      }
    }
    function tune(bar, t0) {
      const set = dance ? lead : bank;
      for (const n of bar.notes) {
        if (n.rest) continue;
        const m = fold(root + n.rel + oct, melRange), t = t0 + n.at * u + human(), L = n.len * u * (I.sustain || dance ? 0.95 : 1);
        sampled(mx, set, m, t, L, vel(n.at, dance ? 0.32 : 0.72), I.sustain ? { attack: 0.03, sustain: true, release: 0.25 } : { release: 0.35 });
        cb(t, () => o.onNote?.({ midi: m, len: L }));
      }
    }
    function schedule(t0) {
      const bar = song.next();
      if (!I.noTune || dance) tune(bar, t0);
      if (inst !== "drums" || dance) comp(bar, t0);
      if (dance || inst === "drums") drums(bar, t0, inst === "drums" ? 0.9 : 0.75);
      else if (I.drums && M.energy >= 0.3) drums(bar, t0, 0.5);
      for (let b = 0; b < 4; b++) cb(t0 + b * 4 * u, () => o.onBeat?.(barNo * 4 + b, 4 * u));
      barNo++;
    }
    let next = c.currentTime + 0.12, stopped = false;
    const timer = setInterval(() => { while (!stopped && next < c.currentTime + 0.35) { schedule(next); next += barDur; } }, 50);
    const handle = {
      mood, instrument: inst, beat: 4 * u,
      stop(sec = 0.4) { if (stopped) return; stopped = true; clearInterval(timer); mx.fade(sec); },
    };
    if (o.seconds) setTimeout(() => handle.stop(1.2), o.seconds * 1000);
    return handle;
  }

  // ---------- the show: the character + the music ----------
  let current = null;
  function stopAll() { const cur = current; current = null; cur?.end(); return !!cur; }
  const EMO_FOR_MOOD = (m) => (m === "neutral" || !m ? "happy" : m);
  const MOVES = [  // the dance, two beats per move: [me, partner]
    ["sway-l", "sway-r"], ["sway-r", "sway-l"], ["hop", "hop"], ["arms", "arms"], ["step-in", "step-in"], ["spin", "spin"],
    ["sway-l", "sway-r"], ["wave", "wave"], ["dip", "dip"], ["hop", "hop"],
  ];
  function show(buddy, s, host = {}) {
    stopAll();
    const feel = (e) => host.feel?.(e);
    let ended = false, music = null, timers = [], partner = null;
    const later = (ms, fn) => { const id = setTimeout(() => { timers = timers.filter((x) => x !== id); fn(); }, ms); timers.push(id); };
    const me = {
      kind: s.show,
      end() {
        if (ended) return; ended = true;
        timers.forEach(clearTimeout); music?.stop(); music = null;
        buddy.setProp(null); buddy.move(null);
        if (partner) { partner.move("leave"); setTimeout(() => buddy.partner(false), 700); }
        feel(null); host.onEnd?.();
        if (current === me) current = null;
      },
    };
    current = me;
    if (!["play", "dance", "act"].includes(s.show)) { me.end(); return me; }  // "stop", or something that isn't a show
    if (s.show === "act") {  // one move, or several in a row ("jump and spin")
      const EMO = { cry: "sad", laugh: "happy", sleep: "sleepy", jump: "excited", spin: "excited", wave: "happy" };
      let t = 0;
      for (const a of s.actions?.length ? s.actions : [s.action]) {
        later(t, () => { feel(EMO[a]); buddy.act(a); });
        t += a === "sleep" ? 6000 : 2900;
      }
      later(t + 300, () => me.end());
      return me;
    }
    const mood = s.mood || host.mood || "neutral";
    feel(EMO_FOR_MOOD(mood));
    if (s.show === "dance") {  // with her (default) or solo; 10 s unless told otherwise; 0 = until you say stop
      if (s.partner !== false) partner = buddy.partner(true);
      const secs = s.seconds === 0 ? 0 : s.seconds || 10;
      perform({ mood, dance: true, seconds: secs || undefined, cancelled: () => ended,
        onBeat(n) {
          if (ended) return;
          const [a, b] = MOVES[Math.floor(n / 2) % MOVES.length];
          buddy.move(a, n); partner?.move(b, n);
          if (n % 4 === 0) buddy.sparkle("♪");
          if (n % 8 === 6) buddy.sparkle("♥");
        },
      }).then((h) => { music = h; if (ended) h?.stop(); });
      if (secs) later(secs * 1000 + 300, () => { buddy.celebrate(); partner?.celebrate?.(); buddy.sparkle("♥"); later(900, () => me.end()); });
      return me;
    }
    // instruments: one, several in turn ("guitar then piano"), or all 15 — it plays until you say stop, press Esc, or tap it
    const list = s.instrument === "all" ? Object.keys(INST)
      : Array.isArray(s.instrument) ? s.instrument.filter((i) => INST[i])
      : [INST[s.instrument] ? s.instrument : DEFAULT_FOR[mood] || "piano"];
    if (!list.length) list.push(DEFAULT_FOR[mood] || "piano");
    const SEGMENT = s.instrument === "all" ? 7000 : 9000;
    let k = 0, seg = 0;
    const next = () => {
      if (ended) return;
      const inst = list[k++ % list.length], mine = ++seg;
      music?.stop(0.5); music = null;
      buddy.setProp(inst); host.onInstrument?.(inst);
      perform({ mood, instrument: inst, cancelled: () => ended || mine !== seg,
        onBeat(n) { if (!ended && mine === seg) buddy.beat(n); },
        onStrum(down) { if (!ended && mine === seg) buddy.strum(down); },
        onNote(nn) { if (ended || mine !== seg) return; buddy.hit(nn); if (nn.midi && Math.random() < 0.18) buddy.sparkle(pick(["♪", "♫", "♩"])); },
      }).then((h) => {
        if (ended || mine !== seg) return h?.stop(0.2);
        music = h;
        if (list.length > 1) later(SEGMENT, next);  // the next one only once this one is actually playing (slow connections)
      });
    };
    next();
    return me;
  }
  addEventListener("keydown", (e) => {  // Esc stops the music (and nothing else happens with that press)
    if (e.key === "Escape" && current) { stopAll(); e.stopPropagation(); e.preventDefault(); }
  }, true);

  window.TrinetraMusic = {
    show, stopAll, unlock, perform, INST, MOODS, DEFAULT_FOR,
    get playing() { return current?.kind || null; },
    preload(inst) { loadModel(); return loadSet(INST[inst]?.set); },
  };
})();
