---
name: competitor_analysis
description: Aggregate competitor footprint across the latest scan, or a live competitor drill-down for one keyword.
label: Analysing competitors
order: 2
deterministic_answer: true
args:
  keyword: optional — a single keyword for a live, fresh competitor drill-down; omit for the aggregate footprint across the latest scan
  domain: optional website; omit to use the active client
triggers:
  - competitor analysis
  - competitor footprint
  - competitor report
  - who dominates
  - competitor landscape
  - top competitors
  - overall competitors
---

# competitor_analysis

The full Competitor Analysis feature: who we actually compete with, rolled up across
every tracked keyword — distinct from `compare_competitors`, which answers one keyword.

## When to use
- **Aggregate** (no keyword): "competitor analysis", "who dominates our SERPs",
  "top competitors overall", "competitor footprint/landscape". Reads the active
  client's most recent scan and ranks competitor domains by how often they appear,
  how often they outrank us, and their best/average position.
- **Live drill-down** (a keyword given): "competitor analysis for *home care in Troy MI*"
  → runs a fresh `check_rank` for that keyword and returns the live competitor list.

## Behaviour
- Aggregate path calls `llm_insights.competitor_report(domain)` — no new searches.
- Live path reuses `check_rank` (one search) and reshapes its competitor list.
- `deterministic_answer: true` — `render()` text is final, so a common turn stays at
  ≤ 1 LLM call (0 for the aggregate path).
