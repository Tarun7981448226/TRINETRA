// WhatsApp's login keys, kept in TRINETRA's Neon database instead of files: Render's free disk is wiped on every
// restart, and re-scanning the QR each time would be useless. One row per key (table wa_auth).
import { BufferJSON, initAuthCreds, proto } from "@whiskeysockets/baileys";

export async function usePgAuthState(pool) {
  await pool.query("CREATE TABLE IF NOT EXISTS wa_auth (id text PRIMARY KEY, data text NOT NULL)");
  const read = async (id) => {
    const r = await pool.query("SELECT data FROM wa_auth WHERE id = $1", [id]);
    return r.rows[0] ? JSON.parse(r.rows[0].data, BufferJSON.reviver) : null;
  };
  const write = (id, value) =>
    pool.query("INSERT INTO wa_auth (id, data) VALUES ($1, $2) ON CONFLICT (id) DO UPDATE SET data = EXCLUDED.data",
      [id, JSON.stringify(value, BufferJSON.replacer)]);

  const creds = (await read("creds")) || initAuthCreds();
  return {
    state: {
      creds,
      keys: {
        get: async (type, ids) => {
          const out = {};
          if (!ids.length) return out;
          const r = await pool.query("SELECT id, data FROM wa_auth WHERE id = ANY($1)", [ids.map((i) => `${type}-${i}`)]);
          const found = new Map(r.rows.map((row) => [row.id, JSON.parse(row.data, BufferJSON.reviver)]));
          for (const id of ids) {
            let value = found.get(`${type}-${id}`) ?? null;
            if (type === "app-state-sync-key" && value) value = proto.Message.AppStateSyncKeyData.fromObject(value);
            out[id] = value;
          }
          return out;
        },
        set: async (data) => {
          const jobs = [];
          for (const type of Object.keys(data)) {
            for (const id of Object.keys(data[type])) {
              const value = data[type][id];
              jobs.push(value ? write(`${type}-${id}`, value) : pool.query("DELETE FROM wa_auth WHERE id = $1", [`${type}-${id}`]));
            }
          }
          await Promise.all(jobs);
        },
      },
    },
    saveCreds: () => write("creds", creds),
    clear: () => pool.query("DELETE FROM wa_auth"), // logged out from the phone: start over with a new QR
  };
}
