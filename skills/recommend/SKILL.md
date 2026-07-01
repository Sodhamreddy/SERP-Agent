---
name: recommend
description: Generate SEO recommendations to improve ranking for a keyword.
label: Generating recommendations
order: 4
deterministic_answer: true
args:
  keyword: the keyword to get recommendations for
triggers:
  - recommend
  - improve
  - advice
  - suggestion
  - how do i rank
  - boost
---

# recommend

Turn a ranking situation into concrete next actions for one keyword.

## When to use
- "How do I improve for …", "recommendations for …", "how do we rank higher".
- Common second step after `check_rank` in a multi-step plan
  ("check rank and tell me how to improve").

## Behaviour
- Reuses this turn's prior `check_rank` result when the keyword matches (saves a
  search); otherwise runs `check_rank` first.
- Sends the rank row to `analyze_with_ollama()`; on failure, falls back to three
  solid generic on-page/local recommendations so the user always gets something.

## Answer note
`deterministic_answer` is **true** — `render()` lists the recommendation bullets
directly, no LLM rewording needed.
