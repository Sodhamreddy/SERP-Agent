---
name: check_rank
description: Check a website's Google ranking position for ONE specific keyword.
label: Checking ranking
order: 1
deterministic_answer: false
args:
  keyword: the exact keyword/phrase to check
  location: optional city, e.g. 'Detroit, MI'
  domain: "optional website to check (e.g. 'example.com'); omit to use the active client"
triggers:
  - rank
  - ranking
  - position
  - where do we
  - place
---

# check_rank

The agent's primary capability: where does a site sit on Google for one query.

## When to use
- The user names a keyword and wants its ranking position.
- A bare search-looking phrase with no other intent (the router defaults here).
- Upstream step for `compare_competitors` and `recommend`, which call this skill.

## Behaviour
- Targets the active client's domain by default, or an explicit `domain` for an
  ad-hoc check of any site.
- Resolves a `location` from the client's keyword catalog when not supplied, and
  appends it to the query so the SERP is locale-correct.
- Passes the target to `search_keyword(stop_domain=...)` so the search early-exits
  once the site is found — fast when the site ranks well.

## Answer note
`render()` is intentionally terse; multi-intent turns let the LLM reword rank
numbers into a sentence, so `deterministic_answer` is **false**. A "Not Found"
result must never be phrased as "the site does not rank" — it was simply not seen
among the limited sources this check returned.
