// TRINETRA's WhatsApp bridge: one linked device on Tarun's WhatsApp, always connected (Render, free plan).
// It only listens and reports; TRINETRA decides. It sends only what TRINETRA asks, with "typing…" and a human delay,
// and drops it the moment Tarun shows up on his phone.
//
// Env: TRINETRA_URL (https://trinetra-tarun.vercel.app), BRIDGE_KEY (= TRINETRA_BRIDGE_KEY), DATABASE_URL (Neon),
//      PORT (Render sets it), PAUSED=1 (listen only, never send).
import http from "node:http";

import makeWASocket, {
  Browsers, DisconnectReason, fetchLatestBaileysVersion, jidNormalizedUser, makeCacheableSignalKeyStore,
} from "@whiskeysockets/baileys";
import pg from "pg";
import pino from "pino";
import QRCode from "qrcode";

import { usePgAuthState } from "./authState.js";
import { SendQueue } from "./queue.js";

const { TRINETRA_URL = "https://trinetra-tarun.vercel.app", BRIDGE_KEY = "", DATABASE_URL = "", PORT = "10000" } = process.env;
const paused = () => process.env.PAUSED === "1";
const logger = pino({ level: process.env.LOG_LEVEL || "warn" });
if (!BRIDGE_KEY || !DATABASE_URL) throw new Error("BRIDGE_KEY and DATABASE_URL are required");

// ---------- talking to TRINETRA ----------
async function notify(type, data) {
  for (let i = 0; i < 3; i++) {
    try {
      const r = await fetch(`${TRINETRA_URL}/whatsapp/event`, {
        method: "POST", headers: { "content-type": "application/json", authorization: `Bearer ${BRIDGE_KEY}` },
        body: JSON.stringify({ type, data }), signal: AbortSignal.timeout(55_000),
      });
      if (r.ok || r.status < 500) return r.ok;
    } catch (e) { logger.warn({ err: String(e) }, "TRINETRA unreachable"); }
    await new Promise((res) => setTimeout(res, 2_000 * (i + 1)));
  }
  return false;
}

// ---------- the same person, one id ----------
// WhatsApp v7 gives each person two ids: their phone number (…@s.whatsapp.net) and a private "lid" (…@lid). History
// mostly arrives under the lid, live messages often under the number — so everything is turned into the number form,
// or TRINETRA would think an old friend is a stranger.
async function chatOf(key) {
  const a = key.remoteJid || "", b = key.remoteJidAlt || "";
  if (!a.endsWith("@lid")) return a.endsWith("@s.whatsapp.net") ? jidNormalizedUser(a) : a;
  if (b.endsWith("@s.whatsapp.net")) return jidNormalizedUser(b);
  const pn = await sock?.signalRepository?.lidMapping?.getPNForLID(a).catch(() => null);
  return pn ? jidNormalizedUser(pn) : a;
}

async function sendAliases(pairs) { // {lid, pn} → TRINETRA merges anything it filed under the lid
  for (let i = 0; i < pairs.length; i += 1000) await notify("aliases", { pairs: pairs.slice(i, i + 1000) });
}

async function sendKnownAliases() { // every pair Baileys has stored (rows "lid-mapping-<lid>_reverse" = <phone>)
  const r = await pool.query("SELECT id, data FROM wa_auth WHERE id LIKE 'lid-mapping-%\\_reverse'");
  const pairs = r.rows.map((row) => ({ lid: `${row.id.slice("lid-mapping-".length, -"_reverse".length)}@lid`,
                                       pn: `${JSON.parse(row.data)}@s.whatsapp.net` }));
  if (pairs.length) await sendAliases(pairs);
}
const isGroup = (jid) => jid.endsWith("@g.us");
const skip = (jid) => !jid || jid === "status@broadcast" || jid.endsWith("@broadcast") || jid.endsWith("@newsletter");
const textOf = (m) => {
  const c = m.message || {};
  const inner = c.ephemeralMessage?.message || c.viewOnceMessage?.message || c;
  return inner.conversation || inner.extendedTextMessage?.text || inner.imageMessage?.caption || inner.videoMessage?.caption || "";
};
const tsOf = (m) => new Date(Number(m.messageTimestamp || 0) * 1000 || Date.now()).toISOString();

// ---------- WhatsApp ----------
const pool = new pg.Pool({ connectionString: DATABASE_URL, ssl: DATABASE_URL.includes("localhost") ? false : { rejectUnauthorized: false }, max: 3 });
let sock = null, lastQr = null, state = "starting", lastActivity = 0;

const queue = new SendQueue({
  send: async (jid, text) => (await sock.sendMessage(jid, { text }))?.key?.id,
  typing: async (jid, on) => sock?.sendPresenceUpdate(on ? "composing" : "paused", jid),
  notify, paused,
});

function heIsHere() { // he sent or read something on his phone: stand down, tell TRINETRA (at most every 20 s)
  queue.cancelAll();
  const t = Date.now();
  if (t - lastActivity > 20_000) {
    lastActivity = t;
    notify("activity", { at: new Date(t).toISOString() });
  }
}

async function connect() {
  const auth = await usePgAuthState(pool);
  const { version } = await fetchLatestBaileysVersion().catch(() => ({ version: undefined }));
  sock = makeWASocket({
    version, logger,
    auth: { creds: auth.state.creds, keys: makeCacheableSignalKeyStore(auth.state.keys, logger) },
    // "Desktop" would get the fullest history, but WhatsApp now refuses it (428 at the handshake; checked 2026-10-18).
    // A Chrome link gets recent history; his "Export chat" uploads fill in the rest.
    browser: Browsers.macOS("Chrome"),
    syncFullHistory: true,
    markOnlineOnConnect: false, // never look "online" as him — and his phone keeps getting notifications
  });
  sock.ev.on("creds.update", auth.saveCreds);

  sock.ev.on("connection.update", async ({ connection, lastDisconnect, qr }) => {
    if (qr) { lastQr = qr; state = "qr"; notify("status", { state: "qr" }); }
    if (connection === "open") {
      lastQr = null; state = "open";
      notify("status", { state: "open", me: sock.user?.name || sock.user?.id?.split(":")[0] });
      sendKnownAliases().catch((e) => logger.warn({ err: String(e) }, "aliases"));
    }
    if (connection === "close") {
      const code = lastDisconnect?.error?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) { // unlinked from the phone: forget the keys, show a fresh QR
        state = "logged_out"; notify("status", { state: "logged_out" });
        await auth.clear();
      } else {
        state = "reconnecting";
      }
      setTimeout(() => connect().catch((e) => logger.error(e)), code === DisconnectReason.loggedOut ? 1_000 : 3_000);
    }
  });

  sock.ev.on("messages.upsert", async ({ messages, type }) => {
    if (type !== "notify" && type !== "append") return;
    for (const m of messages) {
      const jid = await chatOf(m.key), text = textOf(m);
      if (skip(jid) || !text) continue;
      const mine = !!m.key.fromMe, ours = mine && queue.isOurs(m.key.id, jid, text);
      if (ours) continue; // TRINETRA's own reply: already reported as "sent"
      if (mine) heIsHere(); // he's typing on his phone (or another linked device)
      if (type === "append" && !mine) continue; // old messages coming in on reconnect
      await notify("message", { id: m.key.id, jid, text, ts: tsOf(m), from_me: mine, group: isGroup(jid), name: m.pushName || null });
    }
  });

  sock.ev.on("messages.update", (updates) => { // READ on someone else's message = he read it on his phone
    if (updates.some((u) => !u.key.fromMe && (u.update?.status ?? 0) >= 4)) heIsHere();
  });

  sock.ev.on("lid-mapping.update", (pair) => { if (pair?.lid && pair?.pn) sendAliases([pair]); });

  sock.ev.on("messaging-history.set", async ({ messages, lidPnMappings }) => { // the history WhatsApp shares when he links
    if (lidPnMappings?.length) await sendAliases(lidPnMappings);
    const rows = [];
    for (const m of messages || []) {
      const jid = await chatOf(m.key), text = textOf(m);
      if (skip(jid) || isGroup(jid) || !text) continue;
      rows.push({ id: m.key.id, jid, text, ts: tsOf(m), from_me: !!m.key.fromMe, name: m.pushName || null });
    }
    for (let i = 0; i < rows.length; i += 500) await notify("history", { messages: rows.slice(i, i + 500) });
  });
}

// ---------- HTTP: health (the heartbeat keeps the free plan awake), the QR, and sending ----------
const authed = (req) => (req.headers.authorization || "") === `Bearer ${BRIDGE_KEY}`;
const reply = (res, code, body, type = "application/json") => {
  res.writeHead(code, { "content-type": type, "cache-control": "no-store" });
  res.end(type === "application/json" ? JSON.stringify(body) : body);
};

http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, "http://x");
    if (url.pathname === "/health") return reply(res, 200, { state, paused: paused(), pending: queue.pending.size });
    if (!authed(req)) return reply(res, 401, { error: "key" });
    if (url.pathname === "/qr.png") {
      if (state === "open") return reply(res, 204, "");
      if (!lastQr) return reply(res, 503, { error: "no QR yet" });
      return reply(res, 200, await QRCode.toBuffer(lastQr, { width: 360, margin: 2 }), "image/png");
    }
    if (url.pathname === "/send" && req.method === "POST") {
      let raw = "";
      for await (const chunk of req) raw += chunk;
      const { jid, text, delay_ms } = JSON.parse(raw || "{}");
      if (state !== "open") return reply(res, 503, { error: "not connected" });
      const why = queue.enqueue(jid, String(text || "").slice(0, 2000), delay_ms);
      return why ? reply(res, 429, { error: why }) : reply(res, 202, { queued: true });
    }
    reply(res, 404, { error: "not found" });
  } catch (e) {
    logger.error(e);
    reply(res, 500, { error: "bridge error" });
  }
}).listen(Number(PORT), () => logger.warn(`bridge listening on ${PORT}`));

connect().catch((e) => { logger.error(e); process.exit(1); });
