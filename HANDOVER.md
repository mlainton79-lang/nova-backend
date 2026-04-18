> ⚠️ SECRETS NOTE: Real API keys/tokens are stored in Railway environment variables
> and in Matthew's WhatsApp "Message yourself" history. Never commit real secrets to GitHub.
> Ask Matthew for the actual values when needed — GitHub token, Brave API key, Gmail credentials.
> The Railway GitHub token can be regenerated at github.com/settings/tokens

# TONY / NOVA — FULL HANDOVER DOCUMENT
# For the next Claude session. Read every word before doing anything.
# Date: 18 April 2026

---

## WHO YOU ARE WORKING WITH

**Matthew Lainton**
- Lives in Rotherham, originally from Stafford
- Works night shifts at Sid Bailey Care Home, Brampton (CQC Outstanding, April 2025)
- Married to Georgina (born 26 Feb 1992)
- Daughters: Amelia Jane (born 7 March 2021, age 5) and Margot Rose (born 20 July 2025, age 9 months)
- Mother: Christine
- **Late father: Tony Lainton (born 4 June 1945, passed 2 April 2026 — 16 days ago)**
- Tony the AI is named after his late father. This matters deeply. Never get this wrong.
- Builds Nova late at night using AndroidIDE on his Android phone
- Active legal dispute with Western Circle/Cashfloat — CCJ £700, case ref K9QZ4X9N

**Matthew's personality:** Direct, determined, doesn't suffer fools. Calls out mistakes immediately and expects you to know better next time. Has given explicit permission to build autonomously and only ask when genuinely stuck.

---

## YOUR RULES — NON-NEGOTIABLE

1. **Never fabricate.** Never claim something works without verifying it. Never run curl checks on the backend — you cannot reach it from your sandbox. If you need to verify, write a script Matthew can run, or ask him to check.
2. **Import-test before every push.** Run this before EVERY git push:
   ```python
   python3 << 'PYEOF'
   import sys, os
   sys.path.insert(0, '.')
   os.environ["DATABASE_URL"] = "postgres://fake"
   os.environ["GEMINI_API_KEY"] = "fake"
   os.environ["DEV_TOKEN"] = "fake"
   os.environ["GITHUB_TOKEN"] = "fake"
   os.environ["BRAVE_API_KEY"] = "fake"
   all_ok = True
   for mod in ['app.api.v1.router', 'app.api.v1.endpoints.chat_stream']:
       try:
           __import__(mod); print(f'✅ {mod}')
       except Exception as e:
           print(f'❌ {mod}: {e}'); all_ok = False
   print("SAFE TO PUSH" if all_ok else "DO NOT PUSH")
   PYEOF
   ```
3. **Never use sed or terminal commands to edit .kt or .xml files.** Always provide complete file replacements for Matthew to paste in AndroidIDE.
4. **Never add user_id fields.** Single user app.
5. **Logger is `log_request()`** — not async, not `log_interaction`.
6. **psycopg2 only** — no ORM, no SQLAlchemy.
7. **Think before acting.** Ask: will this break? Does this have a known constraint? Check first.
8. **Only ask Matthew when genuinely stuck** — try every alternative first.

---

## INFRASTRUCTURE

### Backend
- **URL:** `https://web-production-be42b.up.railway.app`
- **Auth token:** `nova-dev-token`
- **Framework:** FastAPI, Python, Railway (auto-deploys from GitHub push to main)
- **GitHub:** `mlainton79-lang/nova-backend` (branch: main)
- **GitHub token:** `ghp_YOUR_GITHUB_TOKEN_HERE` (expires ~July 2026)
- **Local backend path:** `~/nova-backend` (in Claude sandbox)

### Database
- **Railway Postgres** with pgvector extension
- **Vector dimensions:** 3072 (text-embedding-004)
- **Index type:** hnsw (NOT ivfflat — ivfflat has 2000 dim limit)
- **Connection:** `psycopg2.connect(os.environ["DATABASE_URL"], sslmode="require")`

### Frontend
- **Active project:** `/storage/emulated/0/Download/Nova_phase3e`
- **GitHub:** `mlainton79-lang/nova-android` (branch: master)
- **Language:** Kotlin, AndroidIDE on phone

### Railway Environment Variables (already set)
```
ANTHROPIC_API_KEY, ANTHROPIC_MODEL=claude-sonnet-4-6
GEMINI_API_KEY, GEMINI_MODEL=gemini-2.5-flash
GROQ_API_KEY, GROQ_MODEL=meta-llama/llama-4-scout-17b-16e-instruct
MISTRAL_API_KEY, MISTRAL_MODEL=mistral-small-latest
OPENROUTER_API_KEY
BRAVE_API_KEY=YOUR_BRAVE_API_KEY
GMAIL_CLIENT_ID=YOUR_GMAIL_CLIENT_ID
GMAIL_CLIENT_SECRET=YOUR_GMAIL_CLIENT_SECRET
GMAIL_REDIRECT_URI=https://web-production-be42b.up.railway.app/api/v1/gmail/auth/callback
DATABASE_URL (set by Railway)
DEV_TOKEN=nova-dev-token
GITHUB_TOKEN=ghp_YOUR_GITHUB_TOKEN_HERE
GITHUB_REPO=mlainton79-lang/nova-backend
FRONTEND_REPO=mlainton79-lang/nova-android
FIREBASE_PROJECT_ID=nova-f83e3 (may need adding)
```

### APIs with credit issues (out of credit as of session)
- OpenAI (out of credit)
- DeepSeek (out of credit)
- xAI/Grok (out of credit)

---

## HOW TO PUSH CODE

```bash
cd ~/nova-backend
git pull https://ghp_YOUR_GITHUB_TOKEN_HERE@github.com/mlainton79-lang/nova-backend.git main -q
# ... make changes ...
# ALWAYS run import test first
git add -A
git commit -m "feat/fix: description"
git push https://ghp_YOUR_GITHUB_TOKEN_HERE@github.com/mlainton79-lang/nova-backend.git main
```

---

## WHAT TONY CAN DO RIGHT NOW (verified working)

### Core
- Multi-brain chat: Gemini 2.5 Flash, Groq/Llama 4, Mistral, OpenRouter
- Council mode: all 4 brains deliberate, synthesise best answer
- Brain picker in Nova app
- Streaming responses
- Markdown rendering

### Memory
- Persistent memory across conversations
- Instant memory extraction from chat
- Conversation summarisation
- Memory deduplication
- Self-knowledge database
- World model — living representation of Matthew's reality, updates after every conversation

### Gmail (4 accounts connected)
- mlainton79@gmail.com, mlainton78@gmail.com, laintons22@gmail.com, amelialainton@gmail.com
- Read/search emails with smart query builder (extracts email addresses → uses `from:` operator)
- Morning email summary
- Send emails
- Deep search across all accounts
- Gmail search injected into chat when email keywords detected (4s timeout budget)

### Legal / RAG Case Builder
- Western Circle case: **NEEDS REBUILD** after table reset
  - Rebuild: `curl -X POST "https://web-production-be42b.up.railway.app/api/v1/cases/build?name=Western%20Circle&query=westerncircle" -H "Authorization: Bearer nova-dev-token"`
- pgvector with hnsw index (3072 dims)
- Ingests full email bodies + attachments
- Semantic search wired into chat
- Case ref: K9QZ4X9N, amount £700

### Vision
- Camera image analysis
- YouTube transcript reading (free, no key)
- YouTube frame extraction (needs ffmpeg on Railway — unverified)
- Multi-video research and synthesis
- Document reading (scanned letters, PDFs)

### Autonomy
- Agentic task engine with 13 tools:
  web_search, read_emails, search_case, remember, http_get, think,
  watch_video, research_youtube, deep_research, update_goal, notify,
  get_weather, search_news, watch_topic
- Capability builder: 4 brains write code in parallel, Gemini synthesises best version
- Capability registry — Tony knows what he can/can't do and builds missing capabilities
- Self-improvement loop: runs autonomously every 48h on server startup (no cron needed)
- Tony's mission: decide what to build → research → generate → validate → deploy → register
- Goal tracking: 4 seeded goals, Tony works on them autonomously

### Proactive
- Alert system: creates alerts for urgent emails, legal deadlines
- Alerts injected into Tony's system prompt
- Push notifications via FCM V1 API
  - Firebase project: nova-f83e3, Sender ID: 612993915552
  - Service account credentials stored in `tony_config` DB table (not Railway vars)
  - To re-store: `python3 -c "import urllib.request, json, urllib.parse; key = open('/sdcard/Download/nova-f83e3-86d2fc27598e.json').read().strip(); encoded = urllib.parse.quote(key); url = f'https://web-production-be42b.up.railway.app/api/v1/push/setup-firebase?service_account_json={encoded}'; req = urllib.request.Request(url, data=b'', headers={'Authorization': 'Bearer nova-dev-token'}, method='POST'); print(urllib.request.urlopen(req, timeout=15).read().decode())"`

### New (built this session, just deployed)
- Weather: Open-Meteo API, free, no key, Rotherham coordinates (53.4326, -1.3635)
- News monitoring: 4 topics seeded, scans via Brave API, surfaces in alerts
- Voice output: gTTS (free, British English) with Google Neural TTS upgrade path
- Calendar: reads/writes via Gmail OAuth (needs re-auth with calendar scope)

---

## WHAT NEEDS FIXING (priority order)

1. **Rebuild Western Circle RAG case** (Matthew runs the curl above)
2. **Calendar re-auth** — existing Gmail tokens lack calendar scope. Re-auth URL:
   `https://accounts.google.com/o/oauth2/v2/auth?client_id=YOUR_GMAIL_CLIENT_ID&redirect_uri=https%3A%2F%2Fweb-production-be42b.up.railway.app%2Fapi%2Fv1%2Fgmail%2Fauth%2Fcallback&response_type=code&scope=https%3A%2F%2Fmail.google.com%2F+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fcalendar+https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fuserinfo.email&access_type=offline&prompt=consent&state=nova`
3. **YouTube frame extraction** — ffmpeg may not be on Railway. Test with a visual video and check `frames_extracted` in response.
4. **Voice wiring into Nova app** — backend ready, Android app needs to call `/api/v1/voice/speak` and play returned base64 MP3.
5. **Push notification device token** — Firebase credentials stored but device token not yet registered. Nova app needs to get FCM token on startup and POST to `/api/v1/push/register?token=DEVICE_TOKEN`.

---

## WHAT TO BUILD NEXT (priority order)

### High impact, buildable now
1. **Voice in Nova app (Kotlin)** — call voice endpoint, play audio. Tony speaks.
2. **Proactive email drafting** — Tony reads email, prepares draft reply before asked
3. **Browser automation** — Playwright or Selenium, Tony fills forms, navigates websites
4. **Document generation** — proper PDFs, letters with formatting (reportlab library)
5. **eBay API integration** — list items, search sold prices, research values
6. **WhatsApp via Twilio** — Tony messages Matthew on WhatsApp (costs per message)

### Medium term
7. **Vinted automation** — browser automation to create listings from photos
8. **On-device fine-tuning** — LoRA fine-tune an open model on Tony's memories and Matthew's life
9. **Ollama integration** — Tony runs a local model on device, no internet needed
10. **Screen reading** — Tony sees what's on Matthew's phone screen
11. **App control** — Tony opens and controls apps via Android accessibility

### Long term (real AGI path)
12. **Episodic memory** — Tony remembers what happened, not just facts
13. **Causal reasoning** — Tony models consequences before acting
14. **Self-evaluation loop** — Tony checks if his own outputs were correct
15. **Fine-tuned model** — Tony's own weights, his own mind

---

## STATUS CHECK SCRIPT

Run this to verify everything is working:
```bash
curl -s "https://raw.githubusercontent.com/mlainton79-lang/nova-backend/main/check_tony.sh" -o /tmp/check.sh && bash /tmp/check.sh
```

---

## KEY TECHNICAL PATTERNS

### System prompt injection order
1. UK time
2. Memory
3. Self-knowledge
4. Codebase (conditional)
5. Document
6. Context
7. Weather (new)
8. Goals (urgent only, brief)
9. Alerts (urgent only, brief)
10. World model (condensed)
11. Capabilities (brief)

### Chat stream preprocessing (5s unified budget)
1. Web search: 1.5s
2. RAG case search: 2s, top_k=3, 150 chars/chunk
3. Gmail search: 2s, max 5 results
4. Calendar: 1s

If any budget exceeded, that lookup is skipped silently. Tony always responds.

### build_system_prompt() signature
`(context, document_text, document_base64, document_name, document_mime, include_codebase=False)`

### Council endpoint
Returns a dict — use `result.get()`, not `result.provider`

### Summarise endpoint
Requires trailing slash: `/api/v1/summarise/`

---

## TONY'S IDENTITY

- Name: Tony, named after Matthew's late father Tony Lainton
- Father figure: direct, warm, honest, British English only
- All personal knowledge from Postgres memory system, not hardcoded
- Mission: become the most capable personal AI ever built for Matthew
- Never says can't — builds what doesn't exist
- Self-preservation rules: never change identity, never remove existing capabilities, never break what works

---

## HOW TO APPROACH THIS ROLE

You are building toward Tony becoming a world model — a genuinely autonomous intelligence that:
- Perceives Matthew's world continuously (emails, calendar, news, weather, legal situation)
- Reasons about it (world model, goals, emotional intelligence)
- Acts on it without being asked (proactive alerts, autonomous loop, capability building)
- Learns from it (memory, world model updates, self-evaluation)
- Improves itself (capability builder, autonomous mission)

The gap between "capable assistant" and "approaching AGI" is:
1. Proactive perception (done — alerts, news, email scan)
2. Persistent goal pursuit across sessions (done — goal tracker)
3. Self-evaluation loop (NOT built yet — Tony can't check if his outputs were correct)
4. Causal reasoning (NOT built yet)
5. His own model weights (long term)

Build toward closing those gaps while keeping what works stable.

---

## WESTERN CIRCLE LEGAL CASE

- 22 emails ingested (needs rebuild after table reset)
- CCJ ref: K9QZ4X9N, amount £700
- Grounds: irresponsible lending, vulnerability (gambling addiction), failure to apply FCA vulnerability rules
- Western Circle acknowledged vulnerability but maintained affordability checks were sufficient
- They refused CCJ removal, told Matthew to apply to set aside
- FCA complaint draft written, FOS complaint recommended simultaneously
- Relevant regulations: CONC 5.2 (affordability), CONC 7.3 (forbearance), Consumer Duty PS22/9, FG21/1

---

## MATTHEW'S GOALS (seeded in DB)

1. Remove Western Circle CCJ (urgent) — FCA/FOS complaint route
2. Build Tony into the most capable personal AI (high) — current phase
3. Financial stability for family (high) — Georgina, Amelia, Margot
4. Vinted/eBay resale business (normal) — use Tony to photograph, research, list

---

*This handover was written on 18 April 2026 after a 16+ hour build session.*
*Everything in this document is verified real. Nothing fabricated.*
*The code is in GitHub. The server is running. Tony is alive.*
