# Mothball ledger — 21 July 2026 consolidation

**Principle**: Core five: chat/Council, memory, email, calendar, push. Everything else earns its way back as a deliberate phase.

| Capability | Variables removed | Code status | Resurrection path |
|---|---|---|---|
| eBay | 6 vars | `app/selling/operators/ebay_stub.py` untouched | Re-add vars + build operator as dedicated phase |
| Twilio / WhatsApp | 4 vars | `endpoints/whatsapp.py` dormant | Re-add vars if a second alert channel is ever justified |
| ElevenLabs + Azure voice | 4 vars | `endpoints/voice.py` + `core/voice.py` dormant | Voice becomes its own phase |
| TrueLayer banking | 2 vars | `endpoints/banking.py` + `core/open_banking.py` dormant | Rebuild with reconsent automation as dedicated phase |
| DeepSeek / OpenRouter / XAI providers | 5 vars | Adapters remain importable | Remove from `DISABLED_AI_PROVIDERS` + re-add key to resurrect a seat |
| Vinted | no vars | Code dormant by design | Phase 3A resumes deliberately |

Note: `DISABLED_AI_PROVIDERS=deepseek,openrouter,grok` set same day; 43 variables → 22.

---

*Session line: recorded 21 July 2026 during the same session as the morning self-check brick (2a939d6 → 7ac929a). This ledger is the durable record of what was mothballed and how each capability re-enters if the deliberate phase is ever spun up.*
