---
name: full_scan
description: Run the full 120-keyword ranking scan and build the Excel report.
label: Starting full scan
order: 6
deterministic_answer: true
args: {}
triggers:
  - full scan
  - all keyword
  - scan all
  - everything
  - "120"
---

# full_scan

The heavy batch job: every tracked keyword × location, exported to Excel/CSV.

## When to use
- "Run the full scan", "scan all 120 keywords", "run everything".

## Behaviour
- This skill does **not** run the batch itself — it returns an `action: full_scan`
  signal. `run_turn` emits a `{"step": "action", "action": "full_scan"}` event and
  `app.py` launches the batch in the background, streaming progress to the run log.
- Keep it cheap and side-effect-free here so the chat turn returns immediately.
