---
name: llm_overview
description: AI-search visibility — whether and where AI answers cite the site, across the latest scan or one live keyword.
label: Reading AI visibility
order: 3
deterministic_answer: true
args:
  keyword: optional — a single keyword for a live AI-citation check; omit for the AI-visibility overview across the latest scan
  domain: optional website; omit to use the active client
triggers:
  - llm overview
  - ai overview
  - ai search
  - ai visibility
  - llm ranking
  - llm visibility
  - cited by ai
  - chatgpt ranking
  - perplexity
  - generative search
---

# llm_overview

LLM / AI-search visibility for the client. The active search backend is Gemini
grounding, so a scan's position **is** the site's rank among the sources the AI
answer cited — i.e. its AI-Overview citation rank. This skill reframes that as a
visibility summary: how often AI answers cite us, where, and who gets cited instead.

## When to use
- **Overview** (no keyword): "LLM overview", "AI visibility", "are we cited by AI",
  "AI search ranking". Reads the latest scan and reports citation rate, average
  cited position, a top-3 / top-10 / deeper / not-cited split, and which competitor
  domains AI answers cite alongside (or instead of) us.
- **Live** (a keyword given): "is AI citing us for *home care in Troy MI*" → one
  fresh `check_rank`, reported as an AI-citation check.

## Behaviour
- Overview path calls `llm_insights.llm_visibility_report(domain)` — no new searches.
- Live path reuses `check_rank` (one search).
- Single platform today (whatever `SEARCH_BACKEND` resolves to — Google AI Overview
  via Gemini by default). The report carries the platform label so more AI platforms
  (SE Ranking AI Search) can be added later without changing the UI.
- `deterministic_answer: true` keeps a common turn at ≤ 1 LLM call.
