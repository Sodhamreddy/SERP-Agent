---
name: list_keywords
description: List the keywords and locations the tracker covers.
label: Listing keywords
order: 5
deterministic_answer: true
args: {}
triggers:
  - list keyword
  - locations you
  - what locations
---

# list_keywords

Show the active client's tracked-keyword catalog — a count plus a sample.

## When to use
- "What keywords do you track", "list keywords", "which locations".
- Note: the central router matches this only when "keyword" co-occurs with a
  list/show verb, so a ranking request like "rank for X keyword" still routes to
  `check_rank`.

## Behaviour
- Reads `ctx["keywords"]`; returns total keyword count, distinct locations, the
  sorted location list, and the first 8 keywords as a sample. No network calls.
