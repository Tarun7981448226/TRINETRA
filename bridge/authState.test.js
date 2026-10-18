// Runs only when WA_TEST_DB points at a Postgres (e.g. postgres://localhost/wa_bridge_test).
import assert from "node:assert/strict";
import { test } from "node:test";

import pg from "pg";

import { usePgAuthState } from "./authState.js";

const url = process.env.WA_TEST_DB;

test("the WhatsApp login survives a restart (no new QR)", { skip: !url && "set WA_TEST_DB" }, async () => {
  const pool = new pg.Pool({ connectionString: url });
  await pool.query("DROP TABLE IF EXISTS wa_auth");
  const first = await usePgAuthState(pool);
  first.state.creds.me = { id: "919800000000:1@s.whatsapp.net", name: "Tarun" };
  await first.saveCreds();
  await first.state.keys.set({ "pre-key": { 1: { public: Buffer.from([1, 2, 3]), private: Buffer.from([4, 5]) }, 2: null } });

  const again = await usePgAuthState(pool); // a restart
  assert.equal(again.state.creds.me.name, "Tarun");
  assert.deepEqual(again.state.creds.noiseKey.public, first.state.creds.noiseKey.public);
  const keys = await again.state.keys.get("pre-key", ["1", "2"]);
  assert.ok(Buffer.isBuffer(keys["1"].public) && keys["1"].public.equals(Buffer.from([1, 2, 3])));
  assert.equal(keys["2"], null);

  await again.clear(); // logged out from the phone
  const fresh = await usePgAuthState(pool);
  assert.equal(fresh.state.creds.me, undefined);
  await pool.end();
});
