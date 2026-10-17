# TRINETRA in the cloud (serverless, no card)

| Piece | Where | What it does |
|---|---|---|
| App + brain | Vercel project `trinetra` → https://trinetra-tarun.vercel.app | FastAPI (`api/index.py`), PWA, agents |
| Memory | Neon Postgres (`NEON_DATABASE_URL` in `.env`) | conversations, timetable, emotions, neural core |
| Heartbeat | Cloudflare Worker `trinetra-heartbeat` (`cloudflare/heartbeat`) | calls `/cron/tick` every minute |

- **Ship changes:** `deploy/ship.sh` (tests → Vercel → health check).
- **Heartbeat changes:** `cd cloudflare/heartbeat && npx wrangler@4 deploy` (with `CLOUDFLARE_API_TOKEN`/`CLOUDFLARE_ACCOUNT_ID` from `.env` exported).
- **Settings/secrets** live as Vercel env vars (set from `.env`). Changing the passcode = update `TRINETRA_PASSCODE` there + redeploy.
- **Size budget:** the Vercel bundle must stay < 250 MB (now ~174 MB) — no litellm / scikit-learn / ffmpeg.
- `migrate_to_neon.py` was the one-time move from the Mac's SQLite.
