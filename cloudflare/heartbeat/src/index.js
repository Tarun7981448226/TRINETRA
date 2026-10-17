// Every minute: tell TRINETRA what time it is. It decides what (if anything) is due.
export default {
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(beat(env));
  },
  // Visiting the worker URL just says whether TRINETRA answered (no details — this URL is public).
  async fetch(_req, env) {
    const r = await beat(env);
    const alive = r.status === 200;
    return new Response(JSON.stringify({ trinetra: alive ? "alive" : "not answering" }),
      { status: alive ? 200 : 502, headers: { "content-type": "application/json" } });
  },
};

async function beat(env) {
  try {
    const r = await fetch(`${env.TRINETRA_URL}/cron/tick`, {
      method: "POST",
      headers: { authorization: `Bearer ${env.TRINETRA_CRON_SECRET}` },
    });
    const body = await r.text();
    if (!r.ok) console.error(`tick failed ${r.status}: ${body.slice(0, 300)}`);
    return { status: r.status, body: body.slice(0, 500) };
  } catch (e) {
    console.error("tick error", e);
    return { error: String(e) };
  }
}
