# TRINETRA Roadmap

| # | Phase | Status |
|---|---|---|
| 1 | Foundation: brain, agent registry, LLM layer, database, chat screen, voice in/out, long-term memory | ✅ |
| 2 | Timetable by talking, routines, reminders, check-ins, heartbeat ✅ — Telegram channel waiting on bot token | 🟡 |
| 3 | iPhone + Mac apps installed, passcode lock, lock-screen push to both, private HTTPS via Tailscale | ✅ |
| 3b | Emotion Engine ✅ · Mentor ✅ (goals→milestones→approved weekly plan, promises + deadline check-ins, progressive overload, Sunday session, 🎯 screen) | ✅ |
| 4 | Thinking before acting ✅ (Planner → Sleep Guardian, Buffer Manager, Deadline Tracker, Neural odds → Critic → Arbiter) + timetable dashboard (week grid / phone day view, voice edits) | ✅ |
| 5 | Monitoring (iOS Shortcuts, distraction/silence detection, escalation) | ⬜ |
| 5b | Gmail + WhatsApp + n8n | ⬜ |
| 6 | ML brain: Neural Core ✅ (growing MLP, nightly retrain, completion prediction) · more models + coaching reports ⬜ | 🟡 |
| 7 | Cloud LIVE ✅ (Vercel + Neon + Cloudflare cron, works with the Mac off) · remaining agents ⬜ | 🟡 |

## 🚩 Before shipping (remind at ~90%)
- [ ] Nightly memory backup to `iCloud Drive/TRINETRA Backups/` (30 days kept)
- [ ] Private GitHub repo for the code
- [ ] Migrate local `trinetra.db` → cloud Postgres (keep everything TRINETRA learned)
- [ ] iCloud as archive for voice notes / journals / reports

## Wake-up, nagging & weekly report (2026-10-16)
- ✅ 6am wake-up via iOS Shortcut "TRINETRA Wake": TRINETRA's voice, 3 medium math questions, angrier on the 06:10/06:20 re-runs; lock-screen nags every 5 min until solved; every morning logged
- ✅ Block reminders: follow-ups every 5 min, up to 3 (Tarun's choice); ignoring all = frustration
- ✅ "TRINETRA Now" Shortcut speaks the block that's due (time-of-day automations)
- ✅ Sunday report: built from 23:00 (metrics + 6 × ~5-min chapters ≈ 30 min), announced + played 23:30 via "TRINETRA Report", stored and compared week over week; 📊 screen
- Shortcut sources: shortcuts/build.py (signed with `shortcuts sign`); key = TRINETRA_SHORTCUT_KEY (opens only /sc/*)

## The living Eye + portfolio (2026-10-16)
- ✅ Free-time check-ins: in any 30+ min gap between blocks, "what are you doing?" every 30 min (quiet before wake-up and after 23:30)
- ✅ Voice switched to Christopher (~2 s instead of 10–15 s); wake lines no longer play twice
- ✅ The Eye: a living amulet that lives in the mic's spot — tap once for a hands-free conversation (it hears when you stop, answers, listens again; 8 s of silence → home), follows your cursor, time ring shows the current block
- ✅ On tarundeepreddy.com: greets visitors, learns their name, explains TRINETRA, 13-stop guided tour (~10 s a stop, architecture diagram per project), "what is Tarun doing now?" relayed live to the iPhone (60 s → asks for their email), 👥 visitor log, 21:30 digest, forgets visitors when they leave
- Edit what visitors hear: backend/app/guest_brief.md (facts) and backend/app/core/tour.py (tour)
