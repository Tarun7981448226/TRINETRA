// The send queue: "typing…" for a human-looking while, then send — unless Tarun shows up first.
// Pure logic (no WhatsApp here), so it's tested on its own (queue.test.js).

export const PER_CHAT_GAP_MS = 30_000; // one reply per chat per 30 s at most
export const MAX_PER_HOUR = 20;
export const TYPING_REFRESH_MS = 20_000; // WhatsApp drops "typing…" after ~25 s

export class SendQueue {
  /**
   * send(jid, text) → Promise<id>, typing(jid, on) → Promise, notify(type, data) → reports to TRINETRA,
   * paused() → true when sending is switched off (PAUSED=1).
   */
  constructor({ send, typing, notify, paused = () => false, now = () => Date.now(), timers = globalThis }) {
    Object.assign(this, { sendFn: send, typingFn: typing, notify, paused, now, timers });
    this.pending = new Map(); // jid → { text, timer, refresh }
    this.lastSent = new Map(); // jid → ms
    this.sentAt = []; // ms of every send in the last hour
    this.sentIds = new Set(); // ids of messages TRINETRA sent (so they aren't mistaken for Tarun typing)
    this.sending = new Map(); // jid → text being sent right now (WhatsApp can echo it back before send() returns)
  }

  /** Returns null when queued, or why it was refused. */
  enqueue(jid, text, delayMs) {
    if (this.paused()) return "paused";
    if (!jid || !text) return "empty";
    if (!jid.endsWith("@s.whatsapp.net") && !jid.endsWith("@lid")) return "not a 1:1 chat"; // never groups or broadcasts
    const t = this.now();
    this.sentAt = this.sentAt.filter((x) => t - x < 3_600_000);
    if (this.sentAt.length + this.pending.size >= MAX_PER_HOUR) return "hourly cap";
    const last = this.lastSent.get(jid);
    if (this.pending.has(jid) || (last !== undefined && t - last < PER_CHAT_GAP_MS)) return "too soon for this chat";
    const delay = Math.max(3_000, Math.min(120_000, delayMs | 0));
    const item = { text };
    item.refresh = this.timers.setInterval(() => this.typingFn(jid, true).catch(() => {}), TYPING_REFRESH_MS);
    item.timer = this.timers.setTimeout(() => this.#fire(jid), delay);
    this.pending.set(jid, item);
    this.typingFn(jid, true).catch(() => {});
    return null;
  }

  async #fire(jid) {
    const item = this.pending.get(jid);
    if (!item) return;
    this.#drop(jid, item);
    if (this.paused()) return this.notify("cancelled", { jid, text: item.text, why: "paused" });
    this.sending.set(jid, item.text);
    this.timers.setTimeout(() => this.sending.get(jid) === item.text && this.sending.delete(jid), 15_000);
    try {
      const id = await this.sendFn(jid, item.text);
      if (id) this.sentIds.add(id);
      const t = this.now();
      this.lastSent.set(jid, t);
      this.sentAt.push(t);
      this.notify("sent", { id, jid, text: item.text, ts: new Date(t).toISOString() });
    } catch (e) {
      this.notify("cancelled", { jid, text: item.text, why: "send failed" });
    } finally {
      this.typingFn(jid, false).catch(() => {});
    }
  }

  #drop(jid, item) {
    this.timers.clearTimeout(item.timer);
    this.timers.clearInterval(item.refresh);
    this.pending.delete(jid);
  }

  /** Was this message (seen coming back from WhatsApp) one of TRINETRA's own? */
  isOurs(id, jid, text) {
    return this.sentIds.has(id) || this.sending.get(jid) === text;
  }

  /** Tarun is on WhatsApp: every reply still "typing" is dropped, and TRINETRA hears which. */
  cancelAll(why = "you came online") {
    for (const [jid, item] of [...this.pending]) {
      this.#drop(jid, item);
      this.typingFn(jid, false).catch(() => {});
      this.notify("cancelled", { jid, text: item.text, why });
    }
  }
}
