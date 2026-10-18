import assert from "node:assert/strict";
import { test } from "node:test";

import { MAX_PER_HOUR, SendQueue } from "./queue.js";

const RAVI = "919800000001@s.whatsapp.net";

function fakeTimers() {  // time only moves when the test says so
  let now = 0, seq = 0;
  const timeouts = new Map(), intervals = new Map();
  return {
    now: () => now,
    setTimeout: (fn, ms) => (timeouts.set(++seq, { fn, at: now + ms }), seq),
    clearTimeout: (id) => timeouts.delete(id),
    setInterval: (fn, ms) => (intervals.set(++seq, fn), seq),
    clearInterval: (id) => intervals.delete(id),
    async advance(ms) {
      now += ms;
      for (const [id, t] of [...timeouts]) if (t.at <= now) { timeouts.delete(id); await t.fn(); }
    },
  };
}

function setup(opts = {}) {
  const t = fakeTimers(), sent = [], told = [], typing = [];
  const q = new SendQueue({
    send: async (jid, text) => (sent.push([jid, text]), `id${sent.length}`),
    typing: async (jid, on) => typing.push([jid, on]),
    notify: (type, data) => told.push([type, data]),
    now: t.now, timers: t, ...opts,
  });
  return { q, t, sent, told, typing };
}

test("it types for a while, then sends, and reports it", async () => {
  const { q, t, sent, told, typing } = setup();
  assert.equal(q.enqueue(RAVI, "ya ra 🤖", 30_000), null);
  assert.deepEqual(typing[0], [RAVI, true]);
  await t.advance(29_000);
  assert.equal(sent.length, 0);
  await t.advance(1_000);
  assert.deepEqual(sent, [[RAVI, "ya ra 🤖"]]);
  assert.equal(told.at(-1)[0], "sent");
  assert.ok(q.isOurs("id1", RAVI, "ya ra 🤖"));
  assert.deepEqual(typing.at(-1), [RAVI, false]);
});

test("Tarun showing up cancels what's still typing", async () => {
  const { q, t, sent, told } = setup();
  q.enqueue(RAVI, "hey 🤖", 40_000);
  await t.advance(10_000);
  q.cancelAll();
  await t.advance(60_000);
  assert.equal(sent.length, 0);
  assert.deepEqual(told.at(-1), ["cancelled", { jid: RAVI, text: "hey 🤖", why: "you came online" }]);
});

test("never groups or broadcasts, never when paused", () => {
  assert.equal(setup().q.enqueue("1203630@g.us", "hi", 5_000), "not a 1:1 chat");
  assert.equal(setup().q.enqueue("status@broadcast", "hi", 5_000), "not a 1:1 chat");
  assert.equal(setup({ paused: () => true }).q.enqueue(RAVI, "hi", 5_000), "paused");
});

test("one reply per chat per 30 s, and an hourly cap", async () => {
  const { q, t } = setup();
  q.enqueue(RAVI, "a", 3_000);
  assert.equal(q.enqueue(RAVI, "b", 3_000), "too soon for this chat");
  await t.advance(3_000);
  assert.equal(q.enqueue(RAVI, "c", 3_000), "too soon for this chat");
  await t.advance(30_000);
  assert.equal(q.enqueue(RAVI, "d", 3_000), null);
  for (let i = 0; i < MAX_PER_HOUR; i++) q.enqueue(`9198000${i}@s.whatsapp.net`, "x", 3_000);
  assert.equal(q.enqueue("919811111111@s.whatsapp.net", "x", 3_000), "hourly cap");
});
