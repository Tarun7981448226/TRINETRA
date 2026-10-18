# Where TRINETRA's data goes (draft, 2026-10-18)

This is an internal map of what TRINETRA stores and who sees it, drawn from the code. It is not a legal privacy policy, but it is the starting point for one when TRINETRA has users other than Tarun.

## Stored, in TRINETRA's own database (Neon Postgres)
| What | Tables | How long |
|---|---|---|
| Conversations with Tarun | `messages` | kept |
| What it learned about him | `memories` (facts, habits, insights) | kept. Faded trivia, facts that are no longer true, and anything he says "forget that" about are **archived**: hidden from recall, never deleted, and he can remove them in the app (🧠 → ✕). |
| Timetable, goals, promises, courses | `tasks`, `goals`, `milestones`, `promises`, `courses`, `study_items` | kept |
| Moods, journal, wake-ups, app opens | `mood_entries`, `journal_entries`, `wake_sessions`, `app_opens` | kept. The journal never goes into memory. |
| Its own decisions and outcomes | `decisions` | kept, so it can learn |
| Event log (training data for the ML brain) | `events` | kept |
| Portfolio visitors | `guest_visits`, `guest_asks`, `guest_notes`, `guest_replies` | The **conversation is wiped** when they leave or after 30 minutes idle. Name, company, topics and any contact they chose to leave are kept for Tarun. |

## WhatsApp (other people's words: handle with the most care)
| What | Where | How long |
|---|---|---|
| Text of 1:1 chats (no media, no groups' content) | `wa_messages` in Neon | kept, to learn his style and show the log. Delete by unlinking + dropping the table (no in-app delete yet). |
| Contacts: WhatsApp id, push name, "may TRINETRA reply" | `wa_contacts` | kept |
| Busy sessions and what was done | `wa_sessions` | kept |
| WhatsApp's login keys for the linked device | `wa_auth` (written by the bridge) | until he unlinks the device on his phone |
| His style profile (numbers and his common words, no message text) | kv `wa_style` | rebuilt nightly |
- The event log (`events`) only ever gets message **ids**, never the text.
- Other people's messages go to the model with `sensitive=True`: Groq first, Gemini's free tier (which may train on prompts) only if nothing else answers.
- Every reply TRINETRA sends carries a 🤖, so people know it's his assistant.
- The bridge runs on Render's free plan (`bridge/`): it sees everything his WhatsApp sees while linked. Unlink it any time: WhatsApp → Linked devices.

## Sent to outside services
| Service | What it sees | Notes |
|---|---|---|
| **Google Gemini** (free tier) | Prompts: his message, recent history, recalled memories, today's and tomorrow's timetable | Free-tier terms allow use for product improvement. Sensitive turns (distress, low mood, journal, wellbeing, nightly reflection) are sent to Groq first, and to Gemini only if nothing else answers. **Before real users: move to a paid tier or a no-training provider.** |
| **Groq** | The same kinds of prompts, plus voice audio for speech-to-text (Whisper), plus WhatsApp messages being answered | Used first for visitors, sensitive turns and WhatsApp |
| **Render** | The WhatsApp bridge: every message on his linked WhatsApp passes through it (it keeps nothing on disk) | Free plan |
| **WhatsApp (Meta)** | It's his own account, linked as a device through the unofficial Baileys library — against WhatsApp's terms; he accepted the ban risk. Delays, caps and a kill switch keep it human-like. | |
| **Microsoft Edge TTS** | The text of replies that are spoken aloud | No account; text only |
| **Web Push** (Apple / Google push services) | The title and text of each notification | Only devices he subscribed |
| **Cloudflare** (cron) | Only a ping to `/cron/tick` every minute | No personal data |
| **Vercel** | Hosts the app; request logs kept about 30 minutes on the free plan | |

## Never leaves TRINETRA's server
- **Memory search** (`core/embed.py`): his memories are embedded and ranked locally. No embedding API is used.
- **Emotion reading** (`core/feel.py`): his own trained model, on CPU.
- **Visitors never see private data**: the guest persona only gets the public brief (`guest_brief.md`) and the visitor's own conversation. A test checks this (`test_visitors_never_see_private_data`).

## Safety
- Crisis language always gets a real way to get help (988 in the US, Tele-MANAS 14416 in India, or local emergency numbers), in the app and on the portfolio.
- Insulting Tarun on the portfolio closes the page. There is no ban.

## Before TRINETRA has other users
- Separate data per user (row-level ownership, or a database per user).
- Explicit consent at sign-up for each kind of data, and for fine-tuning on their conversations.
- Export already exists (`GET /export`, which the nightly backup uses; it covers every table except device push keys). Still missing: a delete-everything action in the app, since archiving is not enough for "delete my data".
- A no-training LLM tier; optionally an on-device model for the most private turns.
- Encrypt memories and the journal at rest.
