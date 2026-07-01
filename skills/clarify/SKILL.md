---
name: clarify
description: Ask the user to specify a missing detail when a ranking request is ambiguous — e.g. which website to check, or which keyword. Provide a short question and 2-4 quick options.
label: Need a detail
order: 7
deterministic_answer: false
args:
  question: the question to ask
  options:
    - short option the user can click
---

# clarify

Stop and ask instead of guessing — the agent's safety valve for ranking requests.

## When to use
- A ranking/position request is missing a required detail: which **website**, or
  which **keyword**.
- The planner emits this, and `_enforce_website_clarify` in the coordinator also
  injects it as a safety net (e.g. a bare keyword that doesn't match the active
  client's business → "which website should I check?").

## Behaviour
- Returns `action: clarify` with a question, up to 5 clickable `options`, a `need`
  hint (`domain` / `keyword`), and any partial `keyword`.
- Handled specially in `run_turn`: it emits a `clarify` step (question + options +
  free-text box) and ends the turn — no tools run, no answer is synthesised. There
  is therefore no `render()` for this skill.
