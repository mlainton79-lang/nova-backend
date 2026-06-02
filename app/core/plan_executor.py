"""
Plan Executor v0 — R2.4.

Walks a plan (from app.core.goal_planner.plan_goal) and executes its
steps in order, exercising every prior brick of the self-extending-agent
track end-to-end:

  goal → planner (R2.2) → registry lookup (R2.1) → governor (R2.1b)
       → executor (this) → verified result → gate → resume

This is the LITMUS test for the four-layer engine, not a feature pass.
Per master_plan_v3_self_extending_agent.md: "The Vinted worker is the
convenient first test [...] chosen as a litmus for the engine, not
because selling is a priority."

v0 scope:
- In-memory execution. No plan-persistence table — plans flow through
  one HTTP request, paused state returned to caller, resumed by caller
  passing approval_token on a follow-up call. Plan persistence
  (`tony_plans`) lands later if/when long-running agents need to span
  HTTP requests.
- Tiny capability dispatcher. v0 knows how to execute exactly two
  capabilities (`brave_search`, `chat`) — enough to prove the engine
  runs end-to-end on a non-trivial goal. Adding more capabilities is
  one dispatch case each; deliberately not generalised yet.
- Halts on first non-ready step (gap, needs_approval, or execution
  failure) and returns the paused state. Caller decides what to do
  next: supply an approval_token and re-run; or fix the gap; or
  accept the partial result.

Acceptance criterion: a goal can be planned, executed where ready,
paused on governor-required approval, and resumed by passing an
approval_token. The executor never bypasses the governor — every
needs_approval step is re-evaluated with the token before execution.
"""
from typing import Any, Dict, List, Optional


def _format_prior_results(prior_results: Optional[List[Dict[str, Any]]]) -> str:
    """Compact preamble describing earlier-step outputs. Used by dispatchers
    that opt in to chain-aware execution (today: chat, gmail_send). Empty
    list / None returns "" so callers can do `prefix =
    _format_prior_results(...); if prefix: prompt = prefix + prompt`.

    Dict/list results are dumped as JSON (capped at 1500 chars each)
    rather than stringified with per-key truncation — the old shape
    hid inner fields like gmail_read's parsed from_address from
    downstream LLMs even when those fields existed. String results
    are truncated at 800 chars; other types stringified and capped.
    """
    if not prior_results:
        return ""
    import json as _json
    lines = ["Earlier steps in this plan produced these results:"]
    for r in prior_results:
        cap_key = r.get("capability_key", "?")
        sn = r.get("step_number", "?")
        verified = r.get("verified", False)
        result = r.get("result")
        if isinstance(result, (dict, list)):
            try:
                summary = _json.dumps(result, default=str)[:1500]
            except Exception:
                summary = str(result)[:1500]
        elif isinstance(result, str):
            summary = result[:800]
        else:
            summary = str(result)[:400]
        lines.append(f"- Step {sn} ({cap_key}, verified={verified}): {summary}")
    lines.append("")
    return "\n".join(lines) + "\n"


async def _execute_step(step: Dict[str, Any],
                         payload: Optional[Dict[str, Any]] = None,
                         prior_results: Optional[List[Dict[str, Any]]] = None,
                         goal_text: Optional[str] = None) -> Dict[str, Any]:
    """Execute one step's underlying capability.

    Returns:
      {ok: bool, result: any, verified: bool, method: str, [error: str]}

    Args:
      step: the planner-produced step dict (description + registry_match)
      payload: optional caller-supplied dict for structured/binary inputs
        that can't be extracted from a description (e.g. uploaded photos,
        CSV files, audio). Capabilities that need such inputs read from
        this dict by a documented key (e.g. vinted_draft_create reads
        payload["images"]).
      prior_results: optional list of {step_number, capability_key,
        description, result, verified} dicts from steps that already
        executed in this plan run. Opt-in per dispatcher — capabilities
        that benefit from chain-aware context (chat especially) inject
        them into their prompts via _format_prior_results. Capabilities
        that don't need it ignore the param.

    Dispatcher branches are one elif each. Adding a new capability is:
    pick a stable capability_key, write a branch returning the
    {ok, result, verified, method} contract, optionally read inputs from
    `payload` and/or `prior_results`. Unknown capabilities return ok=False
    with a clear error.
    """
    cap = step.get("registry_match") or {}
    capability_key = (cap.get("capability_key") or cap.get("name") or "").strip()
    capability_type = cap.get("capability_type", "")
    description = (step.get("description") or "").strip()
    payload = payload or {}
    prior_results = prior_results or []

    if not capability_key:
        return {
            "ok": False,
            "error": "step has no registry_match — cannot dispatch",
            "verified": False,
            "method": "none",
        }

    # --- Dispatcher (v0: 2 capabilities) -----------------------------------

    if capability_key == "news_check":
        # Brave news API — read-only fresh-items search biased to the
        # past week. Distinct from brave_search (general web) because
        # the news endpoint surfaces articles with `age` + source
        # metadata that downstream chat/reason steps can use to
        # prioritise recency. The step description is the query
        # verbatim (no LLM extraction needed; Brave handles natural
        # language fine).
        try:
            from app.core.news_monitor import search_news
            results = await search_news(query=description, count=8)
            compact = []
            for r in (results or [])[:8]:
                if not isinstance(r, dict):
                    continue
                compact.append({
                    "title": (r.get("title") or "")[:200],
                    "url": r.get("url"),
                    "description": (r.get("description") or "")[:400],
                    "age": r.get("age") or r.get("age_friendly"),
                    "source": (r.get("meta_url", {}) or {}).get("hostname") if isinstance(r.get("meta_url"), dict) else None,
                })
            return {
                "ok": bool(compact),
                "result": compact,
                "verified": bool(compact),
                "method": "news_check",
                "count": len(compact),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"news_check failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "news_check",
            }

    if capability_key == "brave_search":
        try:
            from app.core.brave_search import brave_search
            result = await brave_search(description)
            return {
                "ok": bool(result),
                "result": (result or "")[:1000],
                "verified": bool(result),
                "method": "brave_search",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"brave_search failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "brave_search",
            }

    if capability_key == "weather":
        # Current weather + 3-day forecast for Matthew's location
        # (Rotherham, hardcoded in weather.py). Pure read via the
        # free Open-Meteo API — no API key, no auth, no persistence.
        # Returns the structured dict from get_weather() so downstream
        # chat/reason steps see all fields (current_temp, condition,
        # wind, precipitation, today_max/min, advice). The `summary`
        # field is a one-line text version suitable for chat output.
        try:
            from app.core.weather import get_weather
            w = await get_weather()
            if not isinstance(w, dict) or w.get("error"):
                return {
                    "ok": False,
                    "error": (w.get("error") if isinstance(w, dict) else "weather call returned non-dict"),
                    "verified": False,
                    "method": "weather",
                }
            return {
                "ok": True,
                "result": w,
                "verified": True,
                "method": "weather",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"weather failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "weather",
            }

    if capability_key == "web_fetch":
        # Single-URL fetch returning readable text body. Complements
        # brave_search (snippets) by giving downstream reason/chat
        # steps the full page content.
        #
        # URL resolution priority:
        #   1. http(s) URL in step description (regex)
        #   2. http(s) URL in original goal_text (regex)
        #   3. LLM extractor over prior_results (chain-aware — when a
        #      prior brave_search produced a list of URLs and the
        #      description says "fetch the first/BBC/official one")
        # If no URL found at any layer → clean refusal.
        try:
            import re as _re_local
            from app.core.research import fetch_page

            url_regex = r"https?://[^\s'\"<>)]+"
            url: Optional[str] = None
            extracted_via = None
            for haystack in ((description or ""), (goal_text or "")):
                m = _re_local.search(url_regex, haystack)
                if m:
                    url = m.group(0).rstrip(".,;:")
                    extracted_via = "regex"
                    break

            prior_block = _format_prior_results(prior_results)
            if not url and prior_block:
                from app.core.model_router import gemini_json
                extract_prompt = (
                    prior_block
                    + "Extract the URL to fetch for this step.\n\n"
                    f"Description: {description}\n\n"
                    "Rules:\n"
                    "- The URL must be a full http(s)://... value.\n"
                    "- If prior step results above include search results "
                    "with `url` fields, match the description's cues "
                    "('first result', 'BBC one', 'official site') against "
                    "those entries and pick the matching URL.\n"
                    "- If no URL can be confidently identified, return null.\n\n"
                    'Respond in JSON: {"url": "<url_or_null>"}'
                )
                params = await gemini_json(
                    extract_prompt, task="general", max_tokens=256,
                    disable_thinking=True,
                )
                if isinstance(params, dict):
                    candidate = params.get("url")
                    if isinstance(candidate, str) and _re_local.match(url_regex, candidate):
                        url = candidate.rstrip(".,;:")
                        extracted_via = "llm"

            if not url:
                return {
                    "ok": False,
                    "error": (
                        "no URL found in step description, goal, or prior "
                        "results — refusing to fetch. Either include an "
                        "explicit https:// URL or pair this step with a "
                        "prior brave_search."
                    ),
                    "verified": False,
                    "method": "web_fetch",
                }

            content = await fetch_page(url)
            if not content:
                return {
                    "ok": False,
                    "error": f"fetch_page returned empty body for {url} (non-200, blocked, or empty)",
                    "verified": False,
                    "method": "web_fetch",
                    "url": url,
                    "extracted_via": extracted_via,
                }
            return {
                "ok": True,
                "result": {
                    "url": url,
                    "content_chars": len(content),
                    "content": content[:5000],
                },
                "verified": True,
                "method": "web_fetch",
                "extracted_via": extracted_via,
                "used_prior_results": extracted_via == "llm",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"web_fetch failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "web_fetch",
            }

    if capability_key == "chat":
        try:
            from app.core.model_router import gemini
            # Chain-aware: prepend prior step results so chat steps that
            # follow a search/read/vision step can actually reason about
            # what those steps found. _format_prior_results returns ""
            # when there are none, so step 1 chat behaviour is unchanged.
            prior_block = _format_prior_results(prior_results)
            full_prompt = prior_block + description if prior_block else description
            text = await gemini(full_prompt, task="general", max_tokens=1024)
            return {
                "ok": bool(text),
                "result": (text or "")[:1500],
                "verified": bool(text and text.strip()),
                "method": "gemini_general",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"chat failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gemini_general",
            }

    if capability_key == "reason":
        # Gap-bridge reasoning capability. The planner naturally
        # decomposes goals into [read → analyse → write] but the
        # `analyse` step has no concrete read/write capability to
        # match — it becomes a `gap` and the executor halts. `reason`
        # exists to satisfy those intermediate steps. Same underlying
        # gemini call as chat, but the prompt frames the model as a
        # bridge in a multi-step plan, biasing toward structured
        # concrete output the downstream step can consume rather than
        # a conversational reply.
        try:
            from app.core.model_router import gemini
            from datetime import datetime
            prior_block = _format_prior_results(prior_results)
            today_str = datetime.utcnow().strftime("%Y-%m-%d (%A)")
            prompt = (
                (prior_block if prior_block else "")
                + "You are running an intermediate REASONING step inside "
                "a multi-step plan. The next steps will use your output "
                "to act. Analyse the prior step results above (if any) "
                "and the request below. Be brief, structured, and "
                "concrete — output exactly what the next step needs, "
                "no preamble, no conversational fluff. If the request "
                "is to pick a value (a time slot, a recipient, an item) "
                "give that value plainly. If it's to summarise, give "
                "the bullet points without commentary.\n\n"
                f"Today's date is {today_str} UTC. Any relative dates "
                "you produce ('tomorrow', 'next Tuesday', a specific "
                "time slot) MUST resolve against this date, not against "
                "your training cutoff. ISO timestamps must use this "
                "year.\n\n"
                "Request:\n"
                + description
            )
            # task="general" → flash tier, no Google Search grounding.
            # Reasoning here is over the prior_results context (internal
            # data), not the open web — grounding wastes tokens. Flash
            # keeps thinking-mode enabled at a lower thinking-budget than
            # pro, leaving enough output budget for the structured answer.
            # Original task="reasoning" attempt landed thoughts=2045
            # output=0 (per Litmus 14a).
            text = await gemini(prompt, task="general", max_tokens=2048)
            return {
                "ok": bool(text),
                "result": (text or "")[:1500],
                "verified": bool(text and text.strip()),
                "method": "gemini_reason",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"reason failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gemini_reason",
            }

    if capability_key == "fact_extractor":
        # Structured fact extraction over a text block. Returns a list
        # of {subject, predicate, object, confidence} triples that
        # downstream steps can consume (memory_save, reason, chat).
        #
        # Text source priority:
        #   1. prior_results — concatenate verbatim text content from
        #      previous steps (web_fetch body, gmail_read snippets,
        #      calendar_read events, anything). This is the common case
        #      because fact extraction usually runs AFTER a read.
        #   2. description fallback — if no prior_results, use the
        #      description itself. Less common but supported.
        # Refuses cleanly when there's nothing to extract from.
        try:
            from app.core.fact_extractor import extract_facts_from_text
            import json as _json

            # Source extraction: prefer raw-text fields over JSON
            # wrappers. web_fetch returns {url, content_chars, content}
            # — passing the whole dict JSON-wrapped to the LLM hides the
            # actual page text in escaped JSON noise. Look for common
            # content-keyed string fields first (content, text, body,
            # snippet); fall back to JSON-dump only when there's no
            # natural text field.
            _TEXT_KEYS = ("content", "text", "body", "snippet", "message")

            def _extract_text(result: Any) -> str:
                if isinstance(result, str):
                    return result
                if isinstance(result, dict):
                    for k in _TEXT_KEYS:
                        v = result.get(k)
                        if isinstance(v, str) and v.strip():
                            return v
                    try:
                        return _json.dumps(result, default=str)
                    except Exception:
                        return str(result)
                if isinstance(result, list):
                    pieces = [_extract_text(item) for item in result]
                    return "\n".join(p for p in pieces if p)
                if result is not None:
                    return str(result)
                return ""

            text_source = ""
            if prior_results:
                parts = []
                for r in prior_results:
                    t = _extract_text(r.get("result"))
                    if t:
                        parts.append(t)
                text_source = "\n\n".join(parts)[:6000]

            # Fallbacks for when there are no prior_results to draw
            # from: try description, then goal_text. The planner often
            # paraphrases concrete content out of step descriptions
            # (same failure mode that bit vinted_draft_review's id
            # extraction), so the original goal is the more reliable
            # haystack when the user put the fact-source text directly
            # in their goal.
            if not text_source.strip():
                text_source = (description or "").strip()
            if not text_source or len(text_source) < 80:
                gt = (goal_text or "").strip()
                if gt and len(gt) > len(text_source):
                    text_source = gt

            if not text_source:
                return {
                    "ok": False,
                    "error": (
                        "no text source to extract from — pair with a "
                        "prior read step (web_fetch / gmail_read / "
                        "calendar_read / memory_recall) or put the text "
                        "in the step description."
                    ),
                    "verified": False,
                    "method": "fact_extractor",
                }

            facts = await extract_facts_from_text(text_source, max_facts=10)
            return {
                "ok": True,
                "result": facts,
                "verified": True,
                "method": "fact_extractor",
                "count": len(facts),
                "used_prior_results": bool(prior_results),
                "source_chars": len(text_source),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"fact_extractor failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "fact_extractor",
            }

    if capability_key == "memory_save":
        # Persist a new memory. LLM extracts {text, category} from the
        # step description so the saved row is the FACT itself, not the
        # planner's preamble ("Save to memory that X" → text="X"). The
        # underlying add_semantic_memory dedupes by exact text match
        # AND embeds for downstream cosine search.
        try:
            from app.core.semantic_memory import add_semantic_memory
            from app.core.model_router import gemini_json

            allowed_cats = ("family", "preferences", "work", "health", "personal", "fact", "auto")
            extract_prompt = (
                _format_prior_results(prior_results)
                + "Extract the FACT to remember from this step description.\n\n"
                f"Description: {description}\n\n"
                "Rules:\n"
                "- `text` is the factual content TO REMEMBER, NOT the "
                "planner's instruction. Strip preamble like 'remember "
                "that', 'save to memory', 'note that', etc. Save the "
                "underlying fact as a self-contained statement.\n"
                f"- `category` is one of: {', '.join(allowed_cats)}. "
                "Pick the best fit; default to 'auto' if uncertain.\n"
                "- If the description has no extractable fact (e.g. it's "
                "a meta-instruction with no content), return text=null.\n\n"
                "Respond in JSON:\n"
                '{"text": "<fact_or_null>", "category": "<one_of_allowed>"}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=512,
                disable_thinking=True,
            )
            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "memory_save",
                }
            text = (params.get("text") or "").strip()
            category = (params.get("category") or "auto").strip().lower()
            if category not in allowed_cats:
                category = "auto"
            if not text:
                return {
                    "ok": False,
                    "error": (
                        "extractor returned no fact text — refusing to "
                        "save. Either the description has no concrete "
                        "fact or the extractor couldn't isolate one."
                    ),
                    "verified": False,
                    "method": "memory_save",
                    "extracted": {"text": params.get("text"), "category": category},
                }

            saved = await add_semantic_memory(category=category, text=text, importance=1.0)
            if not saved:
                return {
                    "ok": False,
                    "error": (
                        "add_semantic_memory returned False — either a "
                        "near-duplicate already exists (semantically "
                        "still satisfied) or the write failed. Check "
                        "observability events under memory.semantic_memories."
                    ),
                    "verified": False,
                    "method": "memory_save",
                    "attempted": {"text": text[:200], "category": category},
                }
            return {
                "ok": True,
                "result": {
                    "saved_text": text[:300],
                    "category": category,
                    "importance": 1.0,
                },
                "verified": True,
                "method": "memory_save",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"memory_save failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "memory_save",
            }

    if capability_key == "diary_read":
        # Pure read of Tony's auto-written diary for the last 7 days.
        #
        # Source: the `tony_journal` table, populated nightly by the
        # think_worker cron's `daily_reflection` task (calls
        # tony_journal.write_daily_reflection). Each row has title +
        # free-form content + entry_type + created_at.
        #
        # Two-tables history (2026-06-02 investigation): a sibling
        # `tony_diary_entries` table exists from a planned
        # successor system with structured observations/concerns/
        # followups/mood_read columns, but its write path (tony_diary.
        # write_todays_entry) is never invoked by the cron — table is
        # empty. The dispatcher's first ship pointed at the empty
        # table; corrected here to point at the populated one. The
        # tech debt of two parallel systems is captured for follow-up;
        # for the engine's purposes, `tony_journal` is the source of
        # truth today.
        try:
            import psycopg2
            import os as _os
            conn = psycopg2.connect(_os.environ["DATABASE_URL"], sslmode="require")
            cur = conn.cursor()
            try:
                cur.execute(
                    """
                    SELECT id, entry_type, title, content, created_at
                    FROM tony_journal
                    WHERE created_at > NOW() - INTERVAL '7 days'
                    ORDER BY created_at DESC
                    LIMIT 10
                    """
                )
                rows = cur.fetchall()
                entries = [
                    {
                        "id": r[0],
                        "entry_type": r[1],
                        "title": r[2],
                        "content": (r[3] or "")[:2000],
                        "created_at": str(r[4]),
                    }
                    for r in rows
                ]
            finally:
                try:
                    cur.close()
                    conn.close()
                except Exception:
                    pass
            return {
                "ok": True,
                "result": {
                    "entries": entries,
                    "count": len(entries),
                    "days_covered": 7,
                    "source_table": "tony_journal",
                },
                "verified": len(entries) > 0,
                "method": "diary_read",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"diary_read failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "diary_read",
            }

    if capability_key == "goal_list":
        # Pure read of Matthew's active goals from tony_goals. The
        # ordering inside get_active_goals (urgent → high → normal →
        # other, then updated_at DESC) gives downstream chat/reason
        # steps a sensible default — they can re-rank if a goal
        # description explicitly asks for a different lens.
        try:
            from app.core.goals import get_active_goals
            goals = get_active_goals() or []
            urgent = sum(1 for g in goals if (g.get("priority") or "").lower() == "urgent")
            high = sum(1 for g in goals if (g.get("priority") or "").lower() == "high")
            normal = sum(1 for g in goals if (g.get("priority") or "").lower() == "normal")
            return {
                "ok": True,
                "result": {
                    "goals": goals,
                    "count": len(goals),
                    "urgent_count": urgent,
                    "high_count": high,
                    "normal_count": normal,
                },
                "verified": len(goals) > 0,
                "method": "goal_list",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"goal_list failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "goal_list",
            }

    if capability_key == "memory_recall":
        # Semantic search over Tony's persistent memory. The step
        # description IS the query — pgvector cosine similarity
        # handles natural language well, no LLM extraction needed.
        # Returns the top-10 closest matches. Read-only (with the
        # caveat that search_memories updates access_count +
        # last_accessed as a side effect — same shape as a Postgres
        # LRU cache touch, semantically still a read).
        try:
            from app.core.semantic_memory import search_memories
            query = (description or "").strip()
            if not query:
                return {
                    "ok": False,
                    "error": "memory_recall step description was empty — nothing to query",
                    "verified": False,
                    "method": "memory_recall",
                }
            memories = await search_memories(query=query, top_k=10)
            compact = [
                {
                    "id": m.get("id"),
                    "category": m.get("category"),
                    "text": (m.get("text") or "")[:300],
                    "similarity": round(float(m.get("similarity") or 0), 4),
                    "importance": m.get("importance"),
                    "created_at": str(m.get("created_at") or ""),
                }
                for m in (memories or [])
            ]
            return {
                "ok": True,
                "result": compact,
                "verified": True,
                "method": "memory_recall",
                "count": len(compact),
                "query": query[:200],
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"memory_recall failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "memory_recall",
            }

    if capability_key == "gmail_send":
        # Sends email. Three layers of safety:
        #   1. Governor (R2.1b) default-denies external_effect+approval_required
        #      — only an approval_token from the caller unlocks reaching this
        #      branch (registry row corrected R2.4+ via seed_capabilities_v1).
        #   2. LLM parameter extraction: gemini_json against the step
        #      description, expected fields {account, to, subject, body}.
        #   3. Strict validation before send: account must be in the
        #      connected Gmail accounts list; `to` must look like a real
        #      email address; all four fields must be non-empty strings.
        #      Any failure → refuse cleanly with the reason. No fallback
        #      "best guess" send.
        try:
            from app.core.gmail_service import get_all_accounts, send_email
            from app.core.model_router import gemini_json
            import re as _re

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no Gmail accounts connected — cannot send",
                    "verified": False,
                    "method": "gmail_send",
                }

            accounts_list = ", ".join(accounts)
            # Chain-aware: if prior steps produced gmail_read results,
            # inject them as context so the extractor can resolve
            # "reply to John" → look up John's address rather than
            # refusing/guessing. The safety rule shifts from "don't
            # guess" to "look in prior results first, return null only
            # if not found there."
            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured email-send parameters from this step "
                f"description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts to send FROM (pick exactly one): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts above, "
                f"verbatim.\n"
                f"- `to` must be a complete valid email address. If the "
                f"description names a person without an explicit email "
                f"address, FIRST check the prior step results above for "
                f"that person's address (e.g. the `from` field of a prior "
                f"gmail_read result). If found there, use it. If NOT "
                f"found, return null for `to` — do NOT guess or invent.\n"
                f"- `subject` and `body` must both be non-empty strings.\n"
                f"- If ANY field cannot be determined safely, return null "
                f"for that field rather than guessing.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<from_account>", "to": "<recipient_email>", '
                f'"subject": "<subject>", "body": "<body>"}}'
            )
            # disable_thinking: structured-extraction is trivial-shape (one
            # small dict). Without this, gemini-2.5-flash's thinking-mode
            # consumes the budget on internal reasoning, returns null, and
            # the dispatcher then can't validate. Forces flash + thinkingBudget=0.
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=1024,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "gmail_send",
                }

            account = (params.get("account") or "").strip()
            to_addr = (params.get("to") or "").strip()
            subject = (params.get("subject") or "").strip()
            body = (params.get("body") or "").strip()

            # Strict validation — refuse rather than send wrong-shaped mail.
            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts list — refusing to send. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "gmail_send",
                    "extracted": {"account": account, "to": to_addr,
                                  "subject_chars": len(subject), "body_chars": len(body)},
                }
            email_re = _re.compile(r"^[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}$")
            if not to_addr or not email_re.match(to_addr):
                return {
                    "ok": False,
                    "error": (
                        f"extracted `to` is not a valid email address "
                        f"(got {to_addr!r}) — refusing to send. The "
                        f"description must contain an explicit recipient "
                        f"email; v0 dispatcher does not guess from name."
                    ),
                    "verified": False,
                    "method": "gmail_send",
                    "extracted": {"account": account, "to": to_addr,
                                  "subject_chars": len(subject), "body_chars": len(body)},
                }
            if not subject:
                return {
                    "ok": False,
                    "error": "extracted subject is empty — refusing to send",
                    "verified": False,
                    "method": "gmail_send",
                }
            if not body:
                return {
                    "ok": False,
                    "error": "extracted body is empty — refusing to send",
                    "verified": False,
                    "method": "gmail_send",
                }

            success = await send_email(account, to_addr, subject, body)
            return {
                "ok": bool(success),
                "result": {
                    "from": account,
                    "to": to_addr,
                    "subject": subject,
                    "body_chars": len(body),
                    "sent": bool(success),
                },
                "verified": bool(success),
                "method": "gmail_send",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_send failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_send",
            }

    if capability_key == "vision_image":
        # Analyse an image with Gemini Vision. Read-only — vision analysis
        # doesn't mutate anything external. Reads image from payload the
        # same way vinted_draft_create does (images[0] OR image_base64).
        # The step description doubles as the vision prompt — what should
        # Tony look for / report on. Returns the analysis text.
        try:
            from app.core.vision import tony_see
            images = payload.get("images") or []
            if images:
                first = images[0] if isinstance(images[0], dict) else {}
                image_base64 = first.get("base64") or ""
                image_mime = first.get("mime") or "image/jpeg"
            else:
                image_base64 = payload.get("image_base64") or ""
                image_mime = payload.get("image_mime") or "image/jpeg"

            if not image_base64:
                return {
                    "ok": False,
                    "error": (
                        "vision_image requires an image in the payload "
                        "(payload.images=[{base64, mime}] or payload.image_base64). "
                        "Step descriptions cannot carry binary data."
                    ),
                    "verified": False,
                    "method": "vision_image",
                }

            prompt = description or "Describe what's in this image. Be specific about objects, text, colours, and condition."
            text = await tony_see(image_base64, prompt, image_mime)
            return {
                "ok": bool(text),
                "result": (text or "")[:2000],
                "verified": bool(text and text.strip() and "error" not in (text or "").lower()[:80]),
                "method": "vision_image",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"vision_image failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "vision_image",
            }

    if capability_key == "gmail_delete_permanent":
        # IRREVERSIBLE permanent delete. Two-layer kill-switch on top of
        # all the standard destructive-dispatcher safety:
        #   1. Governor (R2.1b) default-denies absent approval_token.
        #   2. GMAIL_PERMANENT_DELETE_ENABLED env var must be true. Even
        #      with a valid approval_token the dispatcher refuses if the
        #      env var is off — defense in depth so a leaked or
        #      misapplied token can't trigger an irreversible purge.
        # Then the standard gmail_delete safety stack: extractor with
        # match_evidence, strict validation, verify-by-GET, evidence
        # cross-check, then permanent delete via gmail_service.delete_email.
        # Prefer gmail_delete (reversible trash) for any case where Trash
        # would be acceptable — this capability exists only for genuine
        # permanent-purge requirements.
        import os as _os
        if _os.environ.get("GMAIL_PERMANENT_DELETE_ENABLED", "false").strip().lower() not in ("true", "1", "yes", "on"):
            return {
                "ok": False,
                "error": (
                    "GMAIL_PERMANENT_DELETE_ENABLED is off — refusing. "
                    "Permanent gmail delete is double-gated: governor "
                    "approval AND this env var. Use gmail_delete "
                    "(reversible trash) instead, or set "
                    "GMAIL_PERMANENT_DELETE_ENABLED=true on the web "
                    "service if a permanent purge is genuinely needed."
                ),
                "verified": False,
                "method": "gmail_delete_permanent",
            }

        try:
            from app.core.gmail_service import (
                get_all_accounts, delete_email, get_email_body
            )
            from app.core.model_router import gemini_json

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no Gmail accounts connected",
                    "verified": False,
                    "method": "gmail_delete_permanent",
                }
            accounts_list = ", ".join(accounts)

            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured Gmail-message-PERMANENT-DELETE "
                f"parameters from this step description.\n\n"
                f"⚠ WARNING: this is PERMANENT, IRREVERSIBLE deletion. "
                f"There is no Trash. No 30-day grace. If you pick the "
                f"wrong message it is gone forever. Be conservative.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (pick the one that owns the message): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts, verbatim.\n"
                f"- `message_id` is the Gmail message id. Typically hex-"
                f"alphanumeric 16-20 chars.\n"
                f"- If prior step results above include a gmail_read with "
                f"emails, match the description's explicit cues against "
                f"those emails (subject, sender, date). If multiple match, "
                f"OR no email's fields match the cues, OR the description "
                f"is ambiguous, return null for message_id. Do NOT guess.\n"
                f"- `match_evidence` is your stated reason for picking "
                f"this id: a substring of subject/from/date that justifies "
                f"the match. VERIFIED against the actual message before "
                f"the delete proceeds. If you cannot articulate it, "
                f"return null for both message_id and match_evidence.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<account>", '
                f'"message_id": "<gmail_message_id_or_null>", '
                f'"match_evidence": "<substring_from_subject_or_from_or_date>"}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=512,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "gmail_delete_permanent",
                }

            account = (params.get("account") or "").strip()
            message_id = (params.get("message_id") or "").strip()
            match_evidence = (params.get("match_evidence") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts — refusing. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not message_id:
                return {
                    "ok": False,
                    "error": "extracted message_id is empty — refusing permanent delete.",
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not match_evidence:
                return {
                    "ok": False,
                    "error": (
                        "extractor did not provide match_evidence — refusing "
                        "permanent delete. Even more important here than for "
                        "trash since this is irreversible."
                    ),
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }

            existing = await get_email_body(account, message_id)
            if not existing or not existing.get("id"):
                return {
                    "ok": False,
                    "error": (
                        f"could not fetch message {message_id} before "
                        f"permanent delete — refusing."
                    ),
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            deleted_from = (existing.get("from") or "")[:120]
            deleted_subject = (existing.get("subject") or "")[:120]
            deleted_date = (existing.get("date") or "")[:32]

            # Match-evidence cross-check.
            ev_lower = match_evidence.lower()
            haystack = (deleted_subject + " " + deleted_from + " " + deleted_date).lower()
            if ev_lower not in haystack:
                return {
                    "ok": False,
                    "error": (
                        f"match_evidence '{match_evidence}' does NOT appear "
                        f"in the fetched message's subject/from/date — "
                        f"refusing PERMANENT delete. LLM extractor picked "
                        f"an id that doesn't match its own stated evidence."
                    ),
                    "verified": False,
                    "method": "gmail_delete_permanent",
                    "extracted": {
                        "account": account,
                        "message_id": message_id,
                        "match_evidence": match_evidence,
                        "fetched_subject": deleted_subject,
                        "fetched_from": deleted_from,
                        "fetched_date": deleted_date,
                    },
                }

            success = await delete_email(account, message_id)
            return {
                "ok": bool(success),
                "result": {
                    "account": account,
                    "message_id": message_id,
                    "deleted_from": deleted_from,
                    "deleted_subject": deleted_subject,
                    "deleted_date": deleted_date,
                    "deleted": bool(success),
                    "permanent": True,
                    "reversible": False,
                },
                "verified": bool(success),
                "method": "gmail_delete_permanent",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_delete_permanent failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_delete_permanent",
            }

    if capability_key == "gmail_reply":
        # Threaded reply to an existing email. Strictly safer than
        # gmail_send for replies because the recipient and subject come
        # from the FETCHED original message — not from the LLM. The
        # LLM only picks the message_id (with match_evidence verified)
        # and writes the body.
        #
        # Three-layer safety (same as gmail_send/delete) plus
        # verify-by-GET + match-evidence cross-check.
        try:
            from app.core.gmail_service import get_all_accounts, get_email_body, send_email
            from app.core.model_router import gemini_json
            import re as _re

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no Gmail accounts connected — cannot reply",
                    "verified": False,
                    "method": "gmail_reply",
                }
            accounts_list = ", ".join(accounts)

            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + "Extract structured gmail-REPLY parameters from this step "
                "description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts: {accounts_list}\n\n"
                "Rules:\n"
                "- `account` must be one of the available accounts, verbatim. "
                "Pick the account where the original email LIVES (prior "
                "gmail_read results will indicate this via each email's "
                "`account` field).\n"
                "- `message_id` is the Gmail message id of the email being "
                "replied TO. If prior gmail_read results are above, match "
                "the description against them by subject/from/date and pick "
                "the matching `id`. Do NOT guess.\n"
                "- `match_evidence` is a substring of the matching email's "
                "subject, from, or date that justified the id. VERIFIED "
                "against the fetched original before send — if your stated "
                "evidence doesn't appear in the actual email, the reply is "
                "REFUSED.\n"
                "- `body` is the reply text. Write it directly — the To, "
                "From, Subject (with Re: prefix), and threading headers are "
                "derived automatically from the fetched original. Do NOT "
                "include 'On <date> X wrote:' quote blocks unless the "
                "description explicitly says to quote.\n"
                "- If you can't articulate a specific match_evidence, "
                "return null for message_id AND match_evidence.\n\n"
                "Respond in JSON:\n"
                '{"account": "<account>", '
                '"message_id": "<gmail_id_or_null>", '
                '"match_evidence": "<substring>", '
                '"body": "<reply_body>"}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=1024,
                disable_thinking=True,
            )
            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "gmail_reply",
                }

            account = (params.get("account") or "").strip()
            message_id = (params.get("message_id") or "").strip()
            match_evidence = (params.get("match_evidence") or "").strip()
            body = (params.get("body") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": f"extracted account '{account}' is not in connected accounts — refusing. Available: {accounts_list}",
                    "verified": False,
                    "method": "gmail_reply",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not message_id:
                return {
                    "ok": False,
                    "error": "extracted message_id is empty — refusing. Either no prior gmail_read provided context, or the description didn't match any prior email.",
                    "verified": False,
                    "method": "gmail_reply",
                    "extracted": params,
                }
            if not match_evidence:
                return {
                    "ok": False,
                    "error": "extractor did not provide match_evidence — refusing. Reply to wrong recipient is much worse than refusing a reply.",
                    "verified": False,
                    "method": "gmail_reply",
                    "extracted": params,
                }
            if not body:
                return {
                    "ok": False,
                    "error": "extracted reply body is empty — refusing.",
                    "verified": False,
                    "method": "gmail_reply",
                    "extracted": params,
                }

            # Verify-by-GET: fetch the original to derive To/Subject AND
            # verify match_evidence.
            try:
                original = await get_email_body(account, message_id)
            except Exception as e:
                return {
                    "ok": False,
                    "error": f"could not fetch original message {message_id} — refusing. {type(e).__name__}: {e}",
                    "verified": False,
                    "method": "gmail_reply",
                    "extracted": params,
                }
            if not original or not original.get("id"):
                return {
                    "ok": False,
                    "error": f"original message {message_id} not found in account {account} — refusing.",
                    "verified": False,
                    "method": "gmail_reply",
                    "extracted": params,
                }

            orig_subject = (original.get("subject") or "").strip()
            orig_from_raw = (original.get("from") or "").strip()
            orig_date = (original.get("date") or "").strip()

            # Match-evidence cross-check against fetched subject/from/date.
            haystack = (orig_subject + " " + orig_from_raw + " " + orig_date).lower()
            if match_evidence.lower() not in haystack:
                return {
                    "ok": False,
                    "error": f"match_evidence '{match_evidence}' does NOT appear in the fetched original's subject/from/date — refusing.",
                    "verified": False,
                    "method": "gmail_reply",
                    "extracted": params,
                    "fetched": {"subject": orig_subject, "from": orig_from_raw, "date": orig_date},
                }

            # Parse from-line into an email address (handles "Name <addr>"
            # and bare addresses). Same pattern as gmail_read dispatcher.
            addr_match = _re.search(r"<([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})>", orig_from_raw)
            bare_match = _re.match(r"^[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}$", orig_from_raw)
            if addr_match:
                to_addr = addr_match.group(1)
            elif bare_match:
                to_addr = orig_from_raw
            else:
                return {
                    "ok": False,
                    "error": f"could not parse a valid email address from the original's From header '{orig_from_raw[:120]}' — refusing.",
                    "verified": False,
                    "method": "gmail_reply",
                    "extracted": params,
                    "fetched": {"from": orig_from_raw},
                }

            # Derive subject — prepend "Re: " unless already present.
            subj_stripped = orig_subject.strip()
            if subj_stripped.lower().startswith("re:"):
                reply_subject = subj_stripped
            elif subj_stripped:
                reply_subject = f"Re: {subj_stripped}"
            else:
                reply_subject = "Re:"

            sent = await send_email(
                email=account,
                to=to_addr,
                subject=reply_subject,
                body=body,
                reply_to_id=message_id,
            )
            return {
                "ok": bool(sent),
                "result": {
                    "account": account,
                    "in_reply_to_message_id": message_id,
                    "to": to_addr,
                    "subject": reply_subject,
                    "body_chars": len(body),
                    "original_subject": orig_subject,
                    "original_from": orig_from_raw,
                    "sent": bool(sent),
                    "threaded": True,
                },
                "verified": bool(sent),
                "method": "gmail_reply",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_reply failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_reply",
            }

    if capability_key == "gmail_delete":
        # Destructive sibling of gmail_send. Uses trash_email — REVERSIBLE
        # 30-day-retention destructive, not permanent. Same three-layer
        # safety as calendar_delete:
        #   1. Registry: external_effect=True, approval_required=True →
        #      governor default-denies without approval_token.
        #   2. LLM extraction of {account, message_id} with disable_thinking
        #      and chain-aware prior_results — typically resolves the id
        #      by matching the description against a prior gmail_read's
        #      `id` field.
        #   3. Strict validation + verify-by-GET BEFORE trash: fetch via
        #      get_email_body, surface from/subject/date in the trace,
        #      then trash. If GET fails → refuse cleanly.
        try:
            from app.core.gmail_service import (
                get_all_accounts, trash_email, get_email_body
            )
            from app.core.model_router import gemini_json

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no Gmail accounts connected",
                    "verified": False,
                    "method": "gmail_delete",
                }
            accounts_list = ", ".join(accounts)

            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured Gmail-message-DELETE parameters from "
                f"this step description. The action is MOVE TO TRASH "
                f"(reversible — 30 days retention).\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (pick the one that owns the message): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts, verbatim.\n"
                f"- `message_id` is the Gmail message id of the email to "
                f"trash. It is a hex-alphanumeric string typically 16-20 "
                f"characters.\n"
                f"- If prior step results above include a gmail_read with "
                f"emails, FIRST match the description against those emails. "
                f"For each candidate, the description usually quotes a "
                f"subject, names a sender, or gives a date — use ONLY those "
                f"explicit cues. If multiple emails could match, OR no "
                f"email's subject/from/date matches the description's "
                f"explicit cues, return null for message_id. Do NOT guess "
                f"or pick the first one in the list.\n"
                f"- `match_evidence` is your stated reason for picking this "
                f"id: a substring of the matching email's subject, OR a "
                f"substring of the from-line, OR a substring of the date. "
                f"This will be verified against the actual message before "
                f"the trash proceeds — if the fetched message doesn't "
                f"contain your stated evidence, the trash is REFUSED. So "
                f"only return evidence you're certain matches.\n"
                f"- If you cannot articulate a specific match_evidence "
                f"substring, return null for both message_id and "
                f"match_evidence.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<account>", '
                f'"message_id": "<gmail_message_id_or_null>", '
                f'"match_evidence": "<substring_from_subject_or_from_or_date>"}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=512,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "gmail_delete",
                }

            account = (params.get("account") or "").strip()
            message_id = (params.get("message_id") or "").strip()
            match_evidence = (params.get("match_evidence") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts — refusing. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not message_id:
                return {
                    "ok": False,
                    "error": (
                        "extracted message_id is empty — refusing to trash. "
                        "Either no prior gmail_read provided context, or "
                        "the description didn't match any prior message."
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            if not match_evidence:
                return {
                    "ok": False,
                    "error": (
                        "extractor did not provide match_evidence — refusing "
                        "to trash. Destructive actions require the LLM to "
                        "state which subject/from/date substring justified "
                        "the id resolution, so the dispatcher can verify "
                        "against the fetched message."
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }

            # Verify-by-GET before trash. If the GET fails (wrong id,
            # message deleted), refuse cleanly — trashing the wrong
            # message would be worse than refusing.
            existing = await get_email_body(account, message_id)
            if not existing or not existing.get("id"):
                return {
                    "ok": False,
                    "error": (
                        f"could not fetch message {message_id} before "
                        f"trash — refusing. Message may not exist or be "
                        f"accessible to this account."
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {"account": account, "message_id": message_id, "match_evidence": match_evidence},
                }
            trashed_from = (existing.get("from") or "")[:120]
            trashed_subject = (existing.get("subject") or "")[:120]
            trashed_date = (existing.get("date") or "")[:32]

            # Match-evidence cross-check: the fetched message MUST contain
            # the LLM's stated match_evidence in subject, from, or date.
            # Catches the failure mode where the LLM picked an arbitrary
            # id from prior_results without actually matching the goal —
            # exactly what trashed Matthew's April draft in the first
            # gmail_delete live test (2026-06-02).
            ev_lower = match_evidence.lower()
            haystack = (
                (trashed_subject + " " + trashed_from + " " + trashed_date).lower()
            )
            if ev_lower not in haystack:
                return {
                    "ok": False,
                    "error": (
                        f"match_evidence '{match_evidence}' does NOT appear "
                        f"in the fetched message's subject/from/date — "
                        f"refusing to trash. LLM extractor picked an id "
                        f"that doesn't match its own stated evidence."
                    ),
                    "verified": False,
                    "method": "gmail_delete",
                    "extracted": {
                        "account": account,
                        "message_id": message_id,
                        "match_evidence": match_evidence,
                        "fetched_subject": trashed_subject,
                        "fetched_from": trashed_from,
                        "fetched_date": trashed_date,
                    },
                }

            success = await trash_email(account, message_id)
            return {
                "ok": bool(success),
                "result": {
                    "account": account,
                    "message_id": message_id,
                    "trashed_from": trashed_from,
                    "trashed_subject": trashed_subject,
                    "trashed_date": trashed_date,
                    "trashed": bool(success),
                    "reversible": True,
                    "retention_days": 30,
                },
                "verified": bool(success),
                "method": "gmail_delete",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_delete failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_delete",
            }

    if capability_key == "calendar_delete":
        # Destructive sibling of calendar_write. Same three-layer safety:
        #   1. Registry: external_effect=True, approval_required=True
        #      (seed_capabilities_v1) → governor default-denies absent
        #      approval_token.
        #   2. LLM extraction of {account, event_id} with disable_thinking
        #      and chain-aware context — typically resolves event_id by
        #      matching the description against a prior calendar_read
        #      result's `id` field.
        #   3. Strict validation + EXTRA verify-by-GET BEFORE DELETE.
        #      Fetch the event via get_event, surface its title/start in
        #      the trace, then call delete_event. If the event doesn't
        #      exist or the GET errors, refuse cleanly — destroying the
        #      wrong event is much worse than refusing a delete.
        try:
            from app.core.gmail_service import get_all_accounts
            from app.core.calendar_service import delete_event, get_event
            from app.core.model_router import gemini_json

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no connected accounts — calendar uses Gmail OAuth tokens",
                    "verified": False,
                    "method": "calendar_delete",
                }
            accounts_list = ", ".join(accounts)

            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured calendar-event-DELETE parameters from "
                f"this step description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (calendar uses Gmail OAuth — pick one): "
                f"{accounts_list}\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts, verbatim.\n"
                f"- `event_id` is the Google Calendar event id of the event "
                f"to delete. Typically 20-30 char alphanumeric.\n"
                f"- If prior step results above include a calendar_read with "
                f"events, FIRST match the description against those events "
                f"by title and/or start time. If multiple match, OR no "
                f"event's title/start matches the description's explicit "
                f"cues, return null for event_id. Do NOT guess.\n"
                f"- `match_evidence` is your stated reason for picking this "
                f"id: a substring of the matching event's title OR a "
                f"substring of its start datetime. This is VERIFIED against "
                f"the fetched event before delete — if the actual event "
                f"doesn't contain your stated evidence, the delete is "
                f"REFUSED. So only return evidence you're certain matches.\n"
                f"- If you cannot articulate a specific match_evidence, "
                f"return null for both event_id and match_evidence.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<account>", '
                f'"event_id": "<google_event_id_or_null>", '
                f'"match_evidence": "<substring_from_title_or_start>"}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=512,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "calendar_delete",
                }

            account = (params.get("account") or "").strip()
            event_id = (params.get("event_id") or "").strip()
            match_evidence = (params.get("match_evidence") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts — refusing. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {"account": account, "event_id": event_id, "match_evidence": match_evidence},
                }
            if not event_id:
                return {
                    "ok": False,
                    "error": (
                        "extracted event_id is empty — refusing to delete. "
                        "Either no prior calendar_read provided context, or "
                        "the description didn't match any prior event."
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {"account": account, "event_id": event_id, "match_evidence": match_evidence},
                }
            if not match_evidence:
                return {
                    "ok": False,
                    "error": (
                        "extractor did not provide match_evidence — refusing "
                        "to delete. Destructive actions require the LLM to "
                        "state which title/start substring justified the id "
                        "resolution, so the dispatcher can verify against "
                        "the fetched event."
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {"account": account, "event_id": event_id, "match_evidence": match_evidence},
                }

            # Extra safety: GET the event first, surface what's about to be
            # destroyed in the trace, then DELETE. If the GET fails, refuse.
            existing = await get_event(account, event_id)
            if not existing.get("ok"):
                return {
                    "ok": False,
                    "error": (
                        f"could not fetch event {event_id} before delete — "
                        f"refusing. {existing.get('error', '')[:200]}"
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {"account": account, "event_id": event_id, "match_evidence": match_evidence},
                }
            event_obj = existing.get("event", {}) or {}
            event_title = event_obj.get("summary", "(no title)")
            event_start = (event_obj.get("start") or {}).get("dateTime") \
                          or (event_obj.get("start") or {}).get("date") or ""

            # Match-evidence cross-check: the fetched event MUST contain
            # the LLM's stated match_evidence in title or start. Same
            # safety pattern as gmail_delete — catches the case where the
            # LLM picks an arbitrary id from prior_results without
            # actually matching the goal.
            ev_lower = match_evidence.lower()
            haystack = (event_title + " " + event_start).lower()
            if ev_lower not in haystack:
                return {
                    "ok": False,
                    "error": (
                        f"match_evidence '{match_evidence}' does NOT appear "
                        f"in the fetched event's title or start — refusing "
                        f"to delete. LLM extractor picked an id that "
                        f"doesn't match its own stated evidence."
                    ),
                    "verified": False,
                    "method": "calendar_delete",
                    "extracted": {
                        "account": account,
                        "event_id": event_id,
                        "match_evidence": match_evidence,
                        "fetched_title": event_title,
                        "fetched_start": event_start,
                    },
                }

            result = await delete_event(account, event_id)
            success = bool(result.get("ok"))
            return {
                "ok": success,
                "result": {
                    "account": account,
                    "event_id": event_id,
                    "deleted_title": event_title,
                    "deleted_start": event_start,
                    "deleted": success,
                    "calendar_api_response": result.get("error", "")[:200]
                                              if not success
                                              else f"HTTP {result.get('status_code')}",
                },
                "verified": success,
                "method": "calendar_delete",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"calendar_delete failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "calendar_delete",
            }

    if capability_key == "calendar_update":
        # Modify an existing calendar event. Same three-layer safety as
        # calendar_delete (governor + LLM extract + verify-by-GET +
        # match-evidence cross-check) — destruction of intent is just
        # as bad as destruction of the row when the wrong event gets
        # silently rewritten.
        #
        # Extra v0 guard: at least one updateable field must be present
        # in the extractor's response. A "PATCH with no fields" would
        # be a no-op API call but a footgun in autonomous flows.
        try:
            from app.core.gmail_service import get_all_accounts
            from app.core.calendar_service import update_event, get_event
            from app.core.model_router import gemini_json
            from datetime import datetime as _dt

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no connected accounts — calendar uses Gmail OAuth tokens",
                    "verified": False,
                    "method": "calendar_update",
                }
            accounts_list = ", ".join(accounts)

            prior_block = _format_prior_results(prior_results)
            today_str = _dt.utcnow().strftime("%Y-%m-%d (%A)")
            extract_prompt = (
                (prior_block if prior_block else "")
                + "Extract structured calendar-event-UPDATE parameters from "
                "this step description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (calendar uses Gmail OAuth — pick one): "
                f"{accounts_list}\n\n"
                f"Today's date is {today_str} UTC. Any relative date "
                "you produce ('tomorrow', '2pm') MUST resolve against "
                "this date.\n\n"
                "Rules:\n"
                "- `account` must be one of the available accounts, verbatim.\n"
                "- `event_id` is the Google Calendar event id to update. If "
                "prior step results above include a calendar_read with "
                "events, FIRST match the description against those events "
                "by title and/or start. If no match → return null.\n"
                "- `match_evidence` is a substring of the matching event's "
                "title OR start datetime. VERIFIED against the fetched "
                "event before update — refused if not present.\n"
                "- `updates` is a dict of fields to change. Include ONLY "
                "fields the description explicitly modifies. Valid keys:\n"
                "    title (str), description (str), location (str),\n"
                "    start_iso (str, ISO 8601 like '2026-06-03T14:00:00'),\n"
                "    end_iso (str, ISO 8601).\n"
                "- If only start_iso is given without end_iso, the dispatcher "
                "preserves the original event's duration — return start_iso "
                "alone in that case.\n"
                "- If no update fields can be extracted → return updates={}.\n\n"
                "Respond in JSON:\n"
                '{"account": "<account>", '
                '"event_id": "<id_or_null>", '
                '"match_evidence": "<substring>", '
                '"updates": {"title": "...", "start_iso": "...", "end_iso": "...", "description": "...", "location": "..."}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=768,
                disable_thinking=True,
            )
            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "calendar_update",
                }

            account = (params.get("account") or "").strip()
            event_id = (params.get("event_id") or "").strip()
            match_evidence = (params.get("match_evidence") or "").strip()
            updates_in = params.get("updates") or {}
            if not isinstance(updates_in, dict):
                updates_in = {}

            if account not in accounts:
                return {
                    "ok": False,
                    "error": f"extracted account '{account}' not in connected accounts. Available: {accounts_list}",
                    "verified": False,
                    "method": "calendar_update",
                    "extracted": params,
                }
            if not event_id:
                return {
                    "ok": False,
                    "error": "extracted event_id is empty — refusing to update. Either no prior calendar_read context, or description didn't match any prior event.",
                    "verified": False,
                    "method": "calendar_update",
                    "extracted": params,
                }
            if not match_evidence:
                return {
                    "ok": False,
                    "error": "extractor did not provide match_evidence — refusing. Destructive-by-overwrite actions require a verifiable justification.",
                    "verified": False,
                    "method": "calendar_update",
                    "extracted": params,
                }

            # Verify-by-GET (BEFORE state).
            existing = await get_event(account, event_id)
            if not existing.get("ok"):
                return {
                    "ok": False,
                    "error": f"could not fetch event {event_id} before update — refusing. {existing.get('error', '')[:200]}",
                    "verified": False,
                    "method": "calendar_update",
                    "extracted": params,
                }
            before_obj = existing.get("event", {}) or {}
            before_title = before_obj.get("summary", "(no title)")
            before_start_obj = before_obj.get("start") or {}
            before_end_obj = before_obj.get("end") or {}
            before_start = before_start_obj.get("dateTime") or before_start_obj.get("date") or ""
            before_end = before_end_obj.get("dateTime") or before_end_obj.get("date") or ""

            # Match-evidence cross-check.
            ev_lower = match_evidence.lower()
            haystack = (before_title + " " + before_start).lower()
            if ev_lower not in haystack:
                return {
                    "ok": False,
                    "error": f"match_evidence '{match_evidence}' does NOT appear in the fetched event's title/start — refusing.",
                    "verified": False,
                    "method": "calendar_update",
                    "extracted": params,
                    "fetched": {"title": before_title, "start": before_start},
                }

            # Shape the PATCH payload. Title → summary, start_iso →
            # start.dateTime, etc. Preserve duration when only start_iso
            # given.
            tz = "Europe/London"
            patch: Dict[str, Any] = {}
            new_title = (updates_in.get("title") or "").strip()
            if new_title:
                patch["summary"] = new_title
            new_desc = updates_in.get("description")
            if isinstance(new_desc, str) and new_desc.strip():
                patch["description"] = new_desc.strip()
            new_loc = updates_in.get("location")
            if isinstance(new_loc, str) and new_loc.strip():
                patch["location"] = new_loc.strip()

            start_iso = (updates_in.get("start_iso") or "").strip()
            end_iso = (updates_in.get("end_iso") or "").strip()
            if start_iso:
                try:
                    new_start_dt = _dt.fromisoformat(start_iso)
                except ValueError:
                    return {
                        "ok": False,
                        "error": f"start_iso '{start_iso}' is not valid ISO 8601 — refusing.",
                        "verified": False,
                        "method": "calendar_update",
                        "extracted": params,
                    }
                patch["start"] = {"dateTime": start_iso, "timeZone": tz}
                if end_iso:
                    try:
                        new_end_dt = _dt.fromisoformat(end_iso)
                    except ValueError:
                        return {
                            "ok": False,
                            "error": f"end_iso '{end_iso}' is not valid ISO 8601 — refusing.",
                            "verified": False,
                            "method": "calendar_update",
                            "extracted": params,
                        }
                    if new_end_dt <= new_start_dt:
                        return {
                            "ok": False,
                            "error": "end_iso must be strictly after start_iso — refusing.",
                            "verified": False,
                            "method": "calendar_update",
                            "extracted": params,
                        }
                    patch["end"] = {"dateTime": end_iso, "timeZone": tz}
                else:
                    # Preserve original duration: shift end by the same
                    # delta the start moved.
                    try:
                        old_start_dt = _dt.fromisoformat(before_start.replace("Z", "+00:00"))
                        old_end_dt = _dt.fromisoformat(before_end.replace("Z", "+00:00"))
                        duration = old_end_dt - old_start_dt
                        # new_start_dt may be naive; use replace-tzinfo-free arithmetic
                        new_end_dt = new_start_dt + duration
                        patch["end"] = {"dateTime": new_end_dt.isoformat(), "timeZone": tz}
                    except Exception:
                        # If we can't parse before_start/end, refuse rather
                        # than send a start-without-end PATCH (Google's
                        # API would 400 anyway, and silent misbehaviour
                        # is worse than explicit refusal).
                        return {
                            "ok": False,
                            "error": "could not preserve original duration (before_start/end unparseable) and no end_iso supplied — refusing.",
                            "verified": False,
                            "method": "calendar_update",
                            "extracted": params,
                            "fetched": {"start": before_start, "end": before_end},
                        }
            elif end_iso:
                return {
                    "ok": False,
                    "error": "end_iso supplied without start_iso — ambiguous, refusing. Provide both or neither.",
                    "verified": False,
                    "method": "calendar_update",
                    "extracted": params,
                }

            if not patch:
                return {
                    "ok": False,
                    "error": "no updateable fields extracted — refusing to send empty PATCH.",
                    "verified": False,
                    "method": "calendar_update",
                    "extracted": params,
                }

            # PATCH and capture AFTER state.
            patch_result = await update_event(account, event_id, patch)
            success = bool(patch_result.get("ok"))
            after_obj = patch_result.get("event", {}) if success else {}
            after_title = after_obj.get("summary", "")
            after_start = (after_obj.get("start") or {}).get("dateTime") \
                          or (after_obj.get("start") or {}).get("date") or ""
            after_end = (after_obj.get("end") or {}).get("dateTime") \
                        or (after_obj.get("end") or {}).get("date") or ""

            return {
                "ok": success,
                "result": {
                    "account": account,
                    "event_id": event_id,
                    "before": {"title": before_title, "start": before_start, "end": before_end},
                    "after": {"title": after_title, "start": after_start, "end": after_end},
                    "patch_sent": patch,
                    "calendar_api_response": patch_result.get("error", "")[:200]
                                              if not success
                                              else "HTTP 200",
                },
                "verified": success,
                "method": "calendar_update",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"calendar_update failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "calendar_update",
            }

    if capability_key == "vinted_drafts_list":
        # Pure read of the recent tony_drafts rows. Returns a compact
        # array shaped for downstream chain-aware draft_id resolution
        # (vinted_draft_review's extractor scans for entries with an
        # `id` field plus discriminating fields like title and
        # created_at). No params extracted from the description for v0
        # — always returns the 20 most recent active drafts. If goal-
        # shaped filtering proves needed later (e.g. "list drafts
        # waiting for review"), add an LLM extractor + status filter
        # the same shape as vinted_draft_review's id extractor.
        try:
            from app.selling.drafts import list_drafts
            drafts = list_drafts(limit=20)
            compact = []
            for d in drafts:
                pricing = d.get("pricing_json") or {}
                images = d.get("images_json") or []
                compact.append({
                    "id": d.get("id"),
                    "title": (d.get("canonical_title") or "")[:120],
                    "status": d.get("status"),
                    "approval_state": d.get("approval_state"),
                    "image_count": len(images) if isinstance(images, list) else 0,
                    "price": pricing.get("price") if isinstance(pricing, dict) else None,
                    "created_at": str(d.get("created_at") or ""),
                })
            return {
                "ok": True,
                "result": compact,
                "verified": True,
                "method": "vinted_drafts_list",
                "count": len(compact),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"vinted_drafts_list failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "vinted_drafts_list",
            }

    if capability_key == "vinted_draft_archive":
        # Soft-delete a Vinted draft. Internal write (no governor
        # approval gate per registry) but destructive within Tony's
        # local data — so the dispatcher enforces match_evidence
        # cross-check + verify-by-GET to make sure the right draft is
        # being archived. Reversible (un-archive is a single SQL
        # update) so over-archiving has bounded blast radius.
        #
        # draft_id resolution priority (mirrors vinted_draft_review):
        #   1. regex over description for explicit integer ids
        #   2. regex over goal_text (catches planner paraphrases)
        #   3. LLM extractor for chain-aware resolution from
        #      prior_results (vinted_drafts_list especially)
        try:
            from app.selling.drafts import get_draft, archive_draft
            from app.core.model_router import gemini_json
            import re as _re_local

            draft_id: Optional[int] = None
            extracted_via = None
            id_regex = r"\b(?:draft\s*(?:id|#|number|no\.?)?\s*|id\s+|#)(\d+)\b"
            for haystack in ((description or ""), (goal_text or "")):
                m = _re_local.search(id_regex, haystack.lower())
                if m:
                    try:
                        draft_id = int(m.group(1))
                        extracted_via = "regex"
                        break
                    except (TypeError, ValueError):
                        draft_id = None

            prior_block = _format_prior_results(prior_results)
            match_evidence = ""
            if draft_id is None or draft_id <= 0:
                extract_prompt = (
                    (prior_block if prior_block else "")
                    + "Extract structured vinted-draft-ARCHIVE parameters from "
                    "this step description.\n\n"
                    f"Description: {description}\n\n"
                    "Rules:\n"
                    "- `draft_id` is a positive integer (the tony_drafts row id).\n"
                    "- If the description contains an explicit integer id, "
                    "use it.\n"
                    "- If prior step results above include a vinted_drafts_list, "
                    "match the description's cues against those entries' "
                    "TITLES. If a draft's title clearly matches what the "
                    "description names, pick its `id`. If NO draft's title "
                    "matches the description's stated title — INCLUDING when "
                    "only one draft exists in the list whose title doesn't "
                    "match — return null. The presence of a single draft is "
                    "NOT a reason to pick it; only a title match is.\n"
                    "- `match_evidence` MUST be a distinctive substring of the "
                    "matching draft's TITLE (NOT status, NOT approval_state — "
                    "those are generic words like 'needs_review' that match "
                    "anything). Minimum 4 characters. Pick a substring that "
                    "uniquely identifies the draft. Example: for title "
                    "'Paperback Book Cover Template 5x8\"' good evidence is "
                    "'Paperback' or 'Book Cover'; bad evidence is 'a' or "
                    "'needs_review'.\n"
                    "- VERIFIED against the fetched draft's title before "
                    "archive — refused if not present.\n"
                    "- If you can't articulate a specific title-substring "
                    "match_evidence, return null for both fields.\n\n"
                    "Respond in JSON:\n"
                    '{"draft_id": <integer_or_null>, '
                    '"match_evidence": "<title_substring_or_null>"}'
                )
                params = await gemini_json(
                    extract_prompt, task="general", max_tokens=512,
                    disable_thinking=True,
                )
                if not isinstance(params, dict):
                    return {
                        "ok": False,
                        "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                        "verified": False,
                        "method": "vinted_draft_archive",
                    }
                raw = params.get("draft_id")
                try:
                    draft_id = int(raw) if raw is not None else None
                    extracted_via = "llm"
                except (TypeError, ValueError):
                    draft_id = None
                match_evidence = (params.get("match_evidence") or "").strip()

            if draft_id is None or draft_id <= 0:
                return {
                    "ok": False,
                    "error": (
                        "extracted draft_id is empty or non-positive — "
                        "refusing to archive. Either no prior vinted_drafts_list "
                        "provided context, or the description didn't match any "
                        "draft."
                    ),
                    "verified": False,
                    "method": "vinted_draft_archive",
                    "extracted": {"draft_id": None, "match_evidence": match_evidence},
                }

            # Verify-by-GET: confirm the draft exists and capture metadata
            # for the trace + match_evidence cross-check.
            draft = get_draft(draft_id)
            if not draft:
                return {
                    "ok": False,
                    "error": f"no draft found with id {draft_id} — refusing to archive.",
                    "verified": False,
                    "method": "vinted_draft_archive",
                    "extracted": {"draft_id": draft_id, "match_evidence": match_evidence},
                }
            draft_title = (draft.get("canonical_title") or "")[:120]
            draft_status = draft.get("status") or ""
            draft_approval_state = draft.get("approval_state") or ""

            # Match-evidence cross-check: when the LLM picked the id from
            # prior_results (extracted_via=llm), the evidence MUST appear
            # in the fetched draft's title or status. For the regex
            # fast-path (explicit numeric id in description/goal),
            # match_evidence is optional — the user typed an explicit id
            # so they took responsibility for the target.
            if extracted_via == "llm":
                if not match_evidence or len(match_evidence) < 4:
                    return {
                        "ok": False,
                        "error": (
                            "match_evidence missing or too short (<4 chars) — "
                            "refusing. Destructive picks from prior_results "
                            "must come with a distinctive title-substring "
                            "justification."
                        ),
                        "verified": False,
                        "method": "vinted_draft_archive",
                        "extracted": {"draft_id": draft_id, "match_evidence": match_evidence},
                    }
                # Title-ONLY haystack — status/approval_state are generic
                # words ('needs_review', 'pending_review') that match
                # almost any phrasing and let the LLM pass the check
                # for the wrong draft. The TITLE is the unique
                # identifier and the only safe cross-check surface.
                ev_lower = match_evidence.lower()
                if ev_lower not in draft_title.lower():
                    return {
                        "ok": False,
                        "error": (
                            f"match_evidence '{match_evidence}' does NOT "
                            f"appear in the fetched draft's TITLE — refusing "
                            f"to archive. (Title is the only allowed cross-"
                            f"check surface; status/approval_state too "
                            f"generic.)"
                        ),
                        "verified": False,
                        "method": "vinted_draft_archive",
                        "extracted": {"draft_id": draft_id, "match_evidence": match_evidence},
                        "fetched": {"title": draft_title, "status": draft_status},
                    }

            outcome = archive_draft(draft_id)
            ok = bool(outcome.get("ok"))
            return {
                "ok": ok,
                "result": {
                    "draft_id": draft_id,
                    "archived_title": draft_title,
                    "archived_status_before": draft_status,
                    "approval_state_before": draft_approval_state,
                    "already_archived": bool(outcome.get("already_archived")),
                    "archived": ok and not outcome.get("already_archived"),
                    "reversible": True,
                },
                "verified": ok,
                "method": "vinted_draft_archive",
                "extracted_via": extracted_via,
                "used_prior_results": extracted_via == "llm",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"vinted_draft_archive failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "vinted_draft_archive",
            }

    if capability_key == "vinted_draft_review":
        # Pure read of a single Vinted draft by id. Returns a compact
        # summary suitable for downstream chat/reason steps to inspect.
        # No external_effect (drafts are local artefacts in tony_drafts).
        # No approval needed.
        #
        # Chain-aware: when prior steps include a vinted_drafts_list,
        # the draft_id can be resolved by description (e.g. "review my
        # latest draft" → pick the most recent from prior_results).
        # When no prior list exists, the description must contain an
        # explicit integer id.
        try:
            from app.selling.drafts import get_draft
            from app.core.model_router import gemini_json
            import re as _re_local

            # Deterministic fast path: pull an explicit integer id from
            # common phrasings before invoking the LLM. The 2026-06-02
            # litmus showed gemini-flash-lite being overly conservative
            # on goals like "Review Vinted draft with id 1" — returning
            # null despite the explicit integer. Regex first, LLM only
            # when no explicit id is present (chain-aware resolution).
            #
            # Scan both the step description AND the original goal_text —
            # the planner's decomposer sometimes paraphrases concrete
            # values out of step descriptions (e.g. "id 1" → "the
            # specified ID"), so the goal is the more reliable haystack
            # for explicit-id phrasings.
            draft_id: Optional[int] = None
            raw: Any = None
            id_regex = r"\b(?:draft\s*(?:id|#|number|no\.?)?\s*|id\s+|#)(\d+)\b"
            for haystack in ((description or ""), (goal_text or "")):
                m = _re_local.search(id_regex, haystack.lower())
                if m:
                    try:
                        draft_id = int(m.group(1))
                        raw = draft_id
                        break
                    except (TypeError, ValueError):
                        draft_id = None

            prior_block = _format_prior_results(prior_results)
            used_llm = False
            if draft_id is None or draft_id <= 0:
                used_llm = True
                extract_prompt = (
                    (prior_block if prior_block else "")
                    + f"Extract the Vinted draft_id to review from this step "
                    f"description.\n\n"
                    f"Description: {description}\n\n"
                    f"Rules:\n"
                    f"- `draft_id` is a positive integer (the tony_drafts row id).\n"
                    f"- If the description contains an explicit integer id, "
                    f"use it (e.g. 'draft id 1' → 1, 'draft #7' → 7).\n"
                    f"- If prior step results above include a vinted_drafts_list "
                    f"(or any list with draft entries containing an id field), "
                    f"match the description's cues ('latest', 'the Schott "
                    f"jacket one', 'draft 7') against those entries and pick "
                    f"the matching draft's `id` field.\n"
                    f"- If no draft_id can be confidently identified, return "
                    f"null.\n\n"
                    f"Respond in JSON:\n"
                    f'{{"draft_id": <integer_or_null>}}'
                )
                params = await gemini_json(
                    extract_prompt, task="general", max_tokens=256,
                    disable_thinking=True,
                )

                if not isinstance(params, dict):
                    return {
                        "ok": False,
                        "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                        "verified": False,
                        "method": "vinted_draft_review",
                    }

                raw = params.get("draft_id")
                try:
                    draft_id = int(raw) if raw is not None else None
                except (TypeError, ValueError):
                    draft_id = None
            if draft_id is None or draft_id <= 0:
                return {
                    "ok": False,
                    "error": (
                        "extracted draft_id is empty or non-positive — "
                        "refusing to review. Either no prior "
                        "vinted_drafts_list provided context, or the "
                        "description didn't name an integer id."
                    ),
                    "verified": False,
                    "method": "vinted_draft_review",
                    "extracted": {"draft_id": raw},
                }

            draft = get_draft(draft_id)
            if not draft:
                return {
                    "ok": False,
                    "error": (
                        f"no draft found with id {draft_id} — refusing. "
                        f"Either the id is wrong or the draft was archived."
                    ),
                    "verified": False,
                    "method": "vinted_draft_review",
                    "extracted": {"draft_id": draft_id},
                }

            images = draft.get("images_json") or []
            warnings = draft.get("warnings_json") or []
            pricing = draft.get("pricing_json") or {}
            item_facts = draft.get("item_facts_json") or {}

            return {
                "ok": True,
                "result": {
                    "draft_id": draft_id,
                    "status": draft.get("status"),
                    "approval_state": draft.get("approval_state"),
                    "title": (draft.get("canonical_title") or "")[:120],
                    "description_chars": len(draft.get("canonical_description") or ""),
                    "price": pricing.get("price") if isinstance(pricing, dict) else None,
                    "condition": item_facts.get("condition_visible") if isinstance(item_facts, dict) else None,
                    "image_count": len(images) if isinstance(images, list) else 0,
                    "warnings": warnings if isinstance(warnings, list) else [],
                    "created_at": str(draft.get("created_at") or ""),
                },
                "verified": True,
                "method": "vinted_draft_review",
                "used_prior_results": bool(prior_block) and used_llm,
                "extracted_via": "llm" if used_llm else "regex",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"vinted_draft_review failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "vinted_draft_review",
            }

    if capability_key == "vinted_draft_create":
        # Generates a Vinted listing draft from photo(s). This is the first
        # capability that needs binary input not extractable from a step
        # description — payload threading was added to execute_plan for this
        # class of capability.
        #
        # Caller passes payload={"images": [{"base64": "...", "mime": "image/jpeg"}, ...]}
        # OR payload={"image_base64": "...", "image_mime": "image/jpeg"} (single).
        # Without images the dispatcher refuses cleanly — full_listing_pipeline
        # would otherwise fall back to "Unknown item" and produce a useless
        # draft.
        #
        # Read-only by registry classification (low risk, no approval needed)
        # — drafts are local artefacts; nothing is posted externally. The
        # downstream "actually post to Vinted" capability is the separate
        # vinted_playwright_operator (status=not_built, approval_required=True).
        try:
            images = payload.get("images") or []
            image_base64 = payload.get("image_base64") or ""
            image_mime = payload.get("image_mime") or "image/jpeg"
            user_notes = payload.get("user_notes") or description  # description doubles as notes
            condition = payload.get("condition") or "good"

            if not images and not image_base64:
                return {
                    "ok": False,
                    "error": (
                        "vinted_draft_create requires images in the payload "
                        "(payload.images=[{base64, mime}] or payload.image_base64). "
                        "Step descriptions cannot carry binary data — caller "
                        "must supply photos via the run-goal payload field."
                    ),
                    "verified": False,
                    "method": "vinted_draft_create",
                }

            from app.core.vinted import full_listing_pipeline
            result = await full_listing_pipeline(
                image_base64=image_base64,
                image_mime=image_mime,
                platform="vinted",
                condition=condition,
                user_notes=user_notes,
                images=images,
            )
            listing = (result or {}).get("listing") or {}
            warnings = (result or {}).get("warnings") or []
            # Verified = pipeline didn't fall back AND produced a non-Unknown title
            verified = (
                "vision_identification" not in warnings
                and bool(listing.get("title"))
                and listing.get("title", "").lower() != "unknown item"
            )
            return {
                "ok": bool(listing),
                "result": {
                    "title": (listing.get("title") or "")[:120],
                    "description_chars": len(listing.get("description") or ""),
                    "price": listing.get("price"),
                    "category": listing.get("category"),
                    "condition": listing.get("condition"),
                    "warnings": warnings,
                    "fallbacks_used": warnings,
                },
                "verified": verified,
                "method": "vinted_draft_create",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"vinted_draft_create failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "vinted_draft_create",
            }

    if capability_key == "calendar_read":
        # Read-only: upcoming events from the first connected Gmail account
        # (calendar uses the same OAuth tokens with calendar scope). Returns
        # compact event summary suitable for downstream chat/summarise steps.
        try:
            from app.core.gmail_service import get_all_accounts
            from app.core.calendar_service import get_upcoming_events
            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no connected accounts — calendar uses Gmail OAuth tokens",
                    "verified": False,
                    "method": "calendar_read",
                }
            account = accounts[0]
            events = await get_upcoming_events(account, days=7)
            # Include the Google event `id` so chain-aware consumers
            # (calendar_delete especially) can resolve "delete the test
            # event tomorrow" → match by title/time, then use the id.
            # Same pattern as gmail_read returning from_address.
            summary = [
                {
                    "id": e.get("id"),
                    "title": e.get("title") or e.get("summary") or "(no title)",
                    "start": (e.get("start") or "")[:19],
                    "end": (e.get("end") or "")[:19],
                    "location": (e.get("location") or "")[:80],
                }
                for e in (events or [])[:10]
            ]
            return {
                "ok": True,
                "result": {"account": account, "events": summary, "count": len(events or [])},
                "verified": len(summary) > 0,
                "method": "calendar_read",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"calendar_read failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "calendar_read",
            }

    if capability_key == "calendar_write":
        # Three-layer safety, same pattern as gmail_send:
        #   1. Registry: external_effect=True, approval_required=True
        #      (set by seed_capabilities_v1) → governor default-denies
        #      without approval_token.
        #   2. LLM extraction of {account, title, start_iso, end_iso,
        #      description?, location?} with disable_thinking=True
        #      (trivial-shape JSON, no reasoning needed).
        #   3. Strict validation before create_event: account in connected
        #      accounts; start_iso and end_iso parse as datetimes; end >
        #      start; title non-empty. Any failure → clean refusal with
        #      the named failing field. No fabricated event creation.
        try:
            from app.core.gmail_service import get_all_accounts
            from app.core.calendar_service import create_event
            from app.core.model_router import gemini_json
            from datetime import datetime

            accounts = get_all_accounts()
            if not accounts:
                return {
                    "ok": False,
                    "error": "no connected accounts — calendar uses Gmail OAuth tokens",
                    "verified": False,
                    "method": "calendar_write",
                }
            accounts_list = ", ".join(accounts)

            # Chain-aware: if prior steps produced calendar_read results,
            # inject them so the extractor can pick slots that don't
            # conflict with existing events. Useful for goals like
            # "find a free hour tomorrow and schedule X" or "book a
            # meeting after my last event today."
            prior_block = _format_prior_results(prior_results)
            extract_prompt = (
                (prior_block if prior_block else "")
                + f"Extract structured calendar-event-creation parameters from "
                f"this step description.\n\n"
                f"Description: {description}\n\n"
                f"Available accounts (calendar uses Gmail OAuth — pick one): "
                f"{accounts_list}\n\n"
                f"Today's date: {datetime.utcnow().strftime('%Y-%m-%d')} (UTC)\n\n"
                f"Rules:\n"
                f"- `account` must be one of the available accounts, verbatim.\n"
                f"- `start_iso` and `end_iso` MUST be full ISO 8601 datetimes "
                f"like '2026-06-02T15:00:00'. If the description gives "
                f"relative times (e.g. 'tomorrow 3pm'), resolve them against "
                f"today's date above. End must be after start.\n"
                f"- If prior step results above include calendar_read events, "
                f"prefer a slot that does NOT overlap with any existing "
                f"event (look at each event's start/end). For goals like "
                f"'find a free time' or 'after my last meeting', use those "
                f"events to choose a non-conflicting time. Brief gap-of-15-"
                f"minutes between adjacent events is fine; overlapping is "
                f"not.\n"
                f"- `title` must be a non-empty string.\n"
                f"- `description` and `location` are optional — return empty "
                f"strings if not mentioned.\n"
                f"- If ANY required field cannot be determined safely, "
                f"return null for that field rather than guessing.\n\n"
                f"Respond in JSON:\n"
                f'{{"account": "<account>", "title": "<title>", '
                f'"start_iso": "<YYYY-MM-DDTHH:MM:SS>", '
                f'"end_iso": "<YYYY-MM-DDTHH:MM:SS>", '
                f'"description": "<optional desc>", '
                f'"location": "<optional location>"}}'
            )
            params = await gemini_json(
                extract_prompt, task="general", max_tokens=1024,
                disable_thinking=True,
            )

            if not isinstance(params, dict):
                return {
                    "ok": False,
                    "error": f"parameter extraction returned non-dict: {type(params).__name__}",
                    "verified": False,
                    "method": "calendar_write",
                }

            account = (params.get("account") or "").strip()
            title = (params.get("title") or "").strip()
            start_iso = (params.get("start_iso") or "").strip()
            end_iso = (params.get("end_iso") or "").strip()
            desc = (params.get("description") or "").strip()
            location = (params.get("location") or "").strip()

            if account not in accounts:
                return {
                    "ok": False,
                    "error": (
                        f"extracted account '{account}' is not in connected "
                        f"accounts — refusing. Available: {accounts_list}"
                    ),
                    "verified": False,
                    "method": "calendar_write",
                    "extracted": {"account": account, "title": title,
                                  "start_iso": start_iso, "end_iso": end_iso},
                }
            if not title:
                return {
                    "ok": False,
                    "error": "extracted title is empty — refusing to create event",
                    "verified": False,
                    "method": "calendar_write",
                }
            try:
                start_dt = datetime.fromisoformat(start_iso.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_iso.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                return {
                    "ok": False,
                    "error": (
                        f"start_iso/end_iso did not parse as ISO datetimes "
                        f"(got start={start_iso!r}, end={end_iso!r}) — "
                        f"refusing to create event"
                    ),
                    "verified": False,
                    "method": "calendar_write",
                }
            if end_dt <= start_dt:
                return {
                    "ok": False,
                    "error": (
                        f"end ({end_iso}) is not after start ({start_iso}) "
                        f"— refusing to create event"
                    ),
                    "verified": False,
                    "method": "calendar_write",
                }

            result = await create_event(account, title, start_iso, end_iso,
                                        description=desc, location=location)
            success = bool(result.get("ok"))
            return {
                "ok": success,
                "result": {
                    "account": account,
                    "title": title,
                    "start": start_iso,
                    "end": end_iso,
                    "created": success,
                    "calendar_api_response": (result.get("event") or {}).get("id")
                                              or result.get("error", "")[:200],
                },
                "verified": success,
                "method": "calendar_write",
                "used_prior_results": bool(prior_block),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"calendar_write failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "calendar_write",
            }

    if capability_key == "email_triage":
        # LLM-based per-email categorisation + drafted replies across
        # all connected Gmail accounts. Calls get_smart_digest() which
        # fans out via list_emails per account, then runs triage_emails
        # over the union — each email gets {urgency, category,
        # needs_reply, reply_draft, summary, action} from a Gemini
        # flash call.
        #
        # PERSISTENCE WARNING: results are memoized in tony_email_triage
        # keyed by sha256(message_id) so the same email isn't re-triaged
        # on every call. The dispatcher does NOT expose a "skip cache"
        # flag in v0 — opens a single write path per first-seen email
        # (subsequent calls hit cache + no write). Schema is owned
        # outside this branch (init_triage_tables at boot, router.py
        # line 158). MANDATORY-Codex per the codex-review-discipline
        # policy because of the cache writes.
        #
        # Returns the full smart-digest dict so downstream chat/reason
        # steps can read counts + by_urgency breakdown + the formatted
        # text + the triaged_emails detail. No LLM step needed between
        # this and a user-facing summary.
        try:
            from app.core.email_triage import get_smart_digest
            digest = await get_smart_digest()
            if not isinstance(digest, dict) or not digest.get("ok"):
                return {
                    "ok": False,
                    "error": (digest.get("error") if isinstance(digest, dict) else "email_triage call returned non-dict"),
                    "verified": False,
                    "method": "email_triage",
                }
            return {
                "ok": True,
                "result": digest,
                "verified": digest.get("count", 0) > 0,
                "method": "email_triage",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"email_triage failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "email_triage",
            }

    if capability_key == "gmail_morning_summary":
        # Daily-glance digest of unread emails across all connected
        # accounts. Parallel fan-out via asyncio.gather in
        # get_morning_summary — total runtime is the slowest account,
        # not the sum. Returns the formatted summary string verbatim
        # so downstream chat/reason steps see the per-account
        # breakdown without further extraction (no LLM step needed).
        try:
            from app.core.gmail_service import get_morning_summary
            summary = await get_morning_summary()
            text = summary or ""
            return {
                "ok": True,
                "result": text,
                "verified": bool(text.strip()),
                "method": "gmail_morning_summary",
                "chars": len(text),
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_morning_summary failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_morning_summary",
            }

    if capability_key == "gmail_read":
        # Reads across all connected Gmail accounts via search_all_accounts,
        # which internally calls build_smart_query to translate NL→Gmail
        # operators (e.g. "emails from Christine" → from:Christine). The
        # step description is treated as the search intent verbatim;
        # planner-produced descriptions like "Read recent unread emails"
        # pass through to Gmail's search. Empty results are an honest
        # outcome (verified=False, ok=True — the read ran, found nothing).
        try:
            from app.core.gmail_service import search_all_accounts
            import re as _re
            emails = await search_all_accounts(description, max_per_account=5)

            # Parse "Name <email@domain.com>" RFC-822 from-lines so chain-
            # aware consumers (gmail_send reply-resolution especially) can
            # find the actual email address. Display name and parsed
            # address both kept; raw is preserved too.
            _addr_re = _re.compile(r"<([\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,})>")
            _bare_re = _re.compile(r"^[\w.+\-]+@[\w.\-]+\.[a-zA-Z]{2,}$")
            def _parse_from(raw: str) -> tuple:
                raw = (raw or "").strip()
                m = _addr_re.search(raw)
                if m:
                    addr = m.group(1)
                    name = raw[: m.start()].strip(" \"\t<>")
                    return name or addr, addr, raw
                if _bare_re.match(raw):
                    return raw, raw, raw
                return raw, "", raw

            # Compact summary — full email bodies would bloat the trace.
            # Keep enough to confirm the read worked and feed downstream steps.
            # `id` (Gmail message id) is included so chain-aware consumers
            # (gmail_delete especially) can resolve "trash that vinted email
            # from earlier" → match by subject/from/date → pull the id.
            # Same pattern as calendar_read's id addition.
            summary = []
            for e in (emails or [])[:10]:
                name, addr, raw = _parse_from(e.get("from") or "")
                summary.append({
                    "id": e.get("id"),
                    "account": e.get("account"),
                    "from_name": name,
                    "from_address": addr,  # parsed email (empty if not present)
                    "from": raw,           # raw RFC-822 from-line, preserved
                    "subject": (e.get("subject") or "")[:80],
                    "date": (e.get("date") or "")[:16],
                    "snippet": (e.get("snippet") or "")[:200],
                })
            return {
                "ok": True,
                "result": {"emails": summary, "count": len(emails or [])},
                "verified": len(summary) > 0,
                "method": "gmail_search_all_accounts",
            }
        except Exception as e:
            return {
                "ok": False,
                "error": f"gmail_read failed: {type(e).__name__}: {e}",
                "verified": False,
                "method": "gmail_search_all_accounts",
            }

    # Unknown — refuse cleanly rather than guess.
    return {
        "ok": False,
        "error": (
            f"v0 executor has no dispatcher for capability "
            f"'{capability_key}' (type={capability_type}). "
            f"Add a case to plan_executor._execute_step to extend."
        ),
        "verified": False,
        "method": "none",
    }


async def execute_plan(
    plan: Dict[str, Any],
    approval_token: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Execute a plan produced by app.core.goal_planner.plan_goal.

    Walks steps in order:
      - status='ready'           → execute, capture result + verification
      - status='needs_approval'  → if approval_token absent → halt + return paused;
                                   if present → re-evaluate governor → execute
      - status='gap'             → halt, return paused with gap reason
      - execution exception      → halt, return paused with execution_failed

    Returns:
      {
        ok: bool,
        goal: str,
        executed_steps: [...],   # steps that actually ran (status='done' or 'failed')
        paused_step: dict|None,  # the step that halted execution (None on full success)
        total_steps: int,
        executed_count: int,
      }
    """
    executed_steps = []
    prior_results: List[Dict[str, Any]] = []
    paused_step: Optional[Dict[str, Any]] = None
    steps = plan.get("steps", []) or []

    for step in steps:
        step_number = step.get("step_number")
        status = step.get("status")

        # --- Gap: cannot execute. Halt. -----------------------------------
        if status == "gap":
            paused_step = {
                "step_number": step_number,
                "reason": "gap",
                "step": step,
                "details": (
                    "no registered capability for this step; "
                    "R2.3's detect-and-record path can propose one"
                ),
            }
            break

        # --- Needs approval: re-evaluate governor with the token ----------
        if status == "needs_approval":
            if not approval_token:
                paused_step = {
                    "step_number": step_number,
                    "reason": "needs_approval",
                    "step": step,
                    "details": (
                        f"governor requires approval for action_class="
                        f"{(step.get('governor_decision') or {}).get('action_class', '?')}; "
                        f"resume by re-calling with approval_token"
                    ),
                }
                break
            # Re-evaluate with the token. If governor still denies (e.g.,
            # capability changed since plan was produced), halt.
            try:
                from app.core.governor import evaluate_action
                new_decision = evaluate_action(
                    step.get("registry_match") or {},
                    approval_token=approval_token,
                )
            except Exception as e:
                paused_step = {
                    "step_number": step_number,
                    "reason": "governor_evaluation_failed",
                    "step": step,
                    "details": f"{type(e).__name__}: {e}",
                }
                break
            if not new_decision.get("allowed"):
                paused_step = {
                    "step_number": step_number,
                    "reason": "governor_denied_with_token",
                    "step": step,
                    "details": new_decision,
                }
                break
            # Token accepted — fall through to execution.

        elif status != "ready":
            # Unknown status — be conservative, halt.
            paused_step = {
                "step_number": step_number,
                "reason": "unknown_status",
                "step": step,
                "details": f"unexpected step status: {status!r}",
            }
            break

        # --- Execute -------------------------------------------------------
        outcome = await _execute_step(
            step,
            payload=payload,
            prior_results=prior_results,
            goal_text=plan.get("goal"),
        )
        executed_steps.append({
            **step,
            "execution": outcome,
            "final_status": "done" if outcome.get("ok") else "failed",
        })
        # Build the chain-aware-execution accumulator from successful steps
        # only. Failures don't propagate forward — downstream steps
        # shouldn't reason about garbage outputs.
        if outcome.get("ok"):
            cap_inner = step.get("registry_match") or {}
            prior_results.append({
                "step_number": step_number,
                "capability_key": (cap_inner.get("capability_key") or cap_inner.get("name") or "?"),
                "description": step.get("description"),
                "result": outcome.get("result"),
                "verified": bool(outcome.get("verified")),
            })
        if not outcome.get("ok"):
            paused_step = {
                "step_number": step_number,
                "reason": "execution_failed",
                "step": step,
                "details": outcome.get("error") or "step executor returned ok=False",
            }
            break

    trace = {
        "ok": paused_step is None,
        "goal": plan.get("goal"),
        "executed_steps": executed_steps,
        "paused_step": paused_step,
        "total_steps": len(steps),
        "executed_count": len(executed_steps),
    }
    _emit_execution_event(trace)
    return trace


def _emit_execution_event(trace: Dict[str, Any]) -> None:
    """Best-effort observability — never raises."""
    try:
        from app.observability import record_run_event, EventSeverity
        sev = EventSeverity.INFO if trace["ok"] else EventSeverity.WARNING
        paused = trace.get("paused_step") or {}
        record_run_event(
            event_type="plan_executor_run",
            severity=sev,
            subsystem="plan_executor",
            message=(
                f"plan run: ok={trace['ok']} executed={trace['executed_count']}/"
                f"{trace['total_steps']} paused_reason={paused.get('reason') or 'none'}"
            ),
            metadata={
                "total_steps": trace["total_steps"],
                "executed_count": trace["executed_count"],
                "ok": trace["ok"],
                "paused_reason": paused.get("reason"),
                "paused_step_number": paused.get("step_number"),
            },
        )
    except Exception:
        pass


async def run_goal(
    goal_text: str,
    approval_token: Optional[str] = None,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Compose: plan_goal → execute_plan. The full end-to-end loop.

    Args:
      goal_text: natural-language goal
      approval_token: optional non-empty string greenlighting external-effect
        and self-modify class steps (see app/core/governor.py)
      payload: optional dict for structured/binary step inputs (see
        _execute_step). Threads through to each step's dispatcher.

    Returns:
      {ok, plan, execution, error}
    """
    try:
        from app.core.goal_planner import plan_goal
        plan = await plan_goal(goal_text, approval_token=approval_token)
    except Exception as e:
        return {
            "ok": False,
            "plan": None,
            "execution": None,
            "error": f"plan_goal raised: {type(e).__name__}: {e}",
        }

    if not plan.get("ok"):
        return {
            "ok": False,
            "plan": plan,
            "execution": None,
            "error": plan.get("error") or "plan produced no steps",
        }

    execution = await execute_plan(plan, approval_token=approval_token, payload=payload)
    return {
        "ok": execution.get("ok", False),
        "plan": plan,
        "execution": execution,
        "error": None,
    }
