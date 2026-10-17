# TRINETRA Roadmap

| # | Phase | Status |
|---|---|---|
| 1 | Foundation: brain, agent registry, LLM layer, database, chat screen, voice in/out, long-term memory | ✅ |
| 2 | Timetable by talking, routines, reminders, check-ins, heartbeat ✅ — Telegram channel waiting on bot token | 🟡 |
| 3 | iPhone + Mac apps installed, passcode lock, lock-screen push to both, private HTTPS via Tailscale | ✅ |
| 3b | Emotion Engine ✅ · Mentor ✅ (goals→milestones→approved weekly plan, promises + deadline check-ins, progressive overload, Sunday session, 🎯 screen) | ✅ |
| 4 | Thinking before acting ✅ (Planner → Sleep Guardian, Buffer Manager, Deadline Tracker, Neural odds → Critic → Arbiter) + timetable dashboard (week grid / phone day view, voice edits) | ✅ |
| 5 | Monitoring: Focus Guard · red alerts · silence · proof of work (TUF + Coursera) · Focus mode + places | ✅ |
| 5b | Gmail + WhatsApp + n8n | ⬜ |
| 6 | ML brain: Neural Core ✅ (growing MLP, nightly retrain, completion prediction) · more models + coaching reports ⬜ | 🟡 |
| 7 | Cloud LIVE ✅ (Vercel + Neon + Cloudflare cron, works with the Mac off) · remaining agents ⬜ | 🟡 |

## 🗺️ Route map to 100% (set 2026-10-16) — 27 of 66 agents live (2026-10-17), ~75% of the product
Built in this order; each stage ships and gets tested on the iPhone before the next starts.

**Stage A · Monitoring — "is he actually working?"** (Phase 5) ← *we are here*
1. ✅ Focus Guard (live; needs the iPhone automation set up): opening Instagram/YouTube/etc. during a focus block → TRINETRA's voice calls it out (iOS app automation), firmer each time, logged
2. ✅ Escalation: important block (priority 4–5) ignored through all 3 follow-ups → 🚨 red alert push + full-screen alarm in the app, twice (free, no new service)
3. ✅ Silence Detector: a started block + an hour with no word from you → a light "still on it?" (👍 On it · ✅ Done · ⏭ Stopped), at most twice
4. ✅ Proof of Work (built; real syllabus + progress from Tarun on Mon 19 Oct): 📚 TUF DSA + ML Specialization tracker — each block gets a target, at the end you tick what you finished and where you stopped, TRINETRA reacts
5. ✅ Focus mode + places (iPhone automations → /sc/focus, /sc/place): Focus on = working (pauses free-time check-ins, counts as life, offers Start); off mid-block → "break or done?"; gym arrive → Start; home during class / leaving USC mid-class → asked

**Stage B · Daily rhythm & wellbeing** (Phase 2/3b gaps)
6. ✅ Planning ahead: Daily Planner (9 pm briefing + catch-up proposal when TUF/ML need more time than the blocks), Replanner (a course block ended short → today's free time, once a day), Weekly Planner (Sunday: next week's load vs hours → weekend blocks), Explainer (what changed and why after you approve). Nothing is added without Approve
7. ✅ Streaks (wake-up, TUF/DSA, gym, ML) on the 📚 screen + milestone cheers + "keep it alive" in the 9 pm briefing; water/stretch after 90 min of unbroken work (max 4/day), a real break after 3 h — meal times stay ping-free
8. ✅ Mood Tracker (every mood read from your messages is kept: /moods, Sunday report) + Stress Monitor (9 pm: 9h+ day or 3+ stressed moods in 48h → offers to drop the least important block)
9. ✅ Vision Keeper (1/3/5-year vision from what you say or the 🎯 screen; Monday briefings tie the week to it) + Motivation Coach (skip something important → your why, once a day) + Profile Keeper (nightly patterns → one memory the chat uses) + Tone Adapter (built in: every line in the current mood)

**Stage C · Coaching & learning** (Phase 6)
10. ✅ Evening wrap after your last block (not mid-TUF): Daily Review (win, miss, one lesson) → Lag Detector (7-day pace vs deadline, with numbers, every few days) → tomorrow's plan; Focus Recommender ("what should I do now?" + free-time check-ins name the topic that fits)
11. ✅ Learning from your history (app/ml/insights.py, shown on 📊): real durations per kind + Time Estimator (offers the realistic length), energy curve (peak/slump hours), Procrastination Detector (what you push off, which day; named in your why), Pattern Miner (gym days, first-ring mornings, low moods vs done-rate); Feature Engineer = the Neural Core's features
12. ✅ Skill Coach ("quiz me" → a question on a topic you ticked, graded, spaced repetition 1/3/7/14/30 days; "explain X" → a spoken lesson) + 📓 private Journal (offered after the evening review; never goes into memory)

**Stage D · Communications** (Phase 5b)
13. ⬜ Gmail triage + drafts · Google Calendar sync
14. ⬜ WhatsApp listener/replier (smart-mix: auto-send vs ask first) · Telegram

**Stage E · Ship**
15. ⬜ Private GitHub repo — local commit done, push waiting on Tarun's OK
16. ✅ Nightly backup to iCloud (03:30, deploy/install-backup.sh; 30 days kept; GET /export) · ✅ old local trinetra.db checked: only 8 test messages from 16 Oct, nothing to migrate · ⬜ Mac desktop pet (later)

## 🚩 Before shipping (remind at ~90%)
- [x] Nightly memory backup to `iCloud Drive/TRINETRA Backups/` (30 days kept) — live since 2026-10-17
- [ ] Private GitHub repo for the code
- [x] Migrate local `trinetra.db` → cloud Postgres — checked: only 8 test messages, nothing to keep
- [x] iCloud as archive for journals / reports (they're in the nightly export; voice is generated on the fly, never stored)

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
