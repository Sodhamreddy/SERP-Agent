---
name: compare_competitors
description: Show which competitor websites outrank a site for a keyword.
label: Comparing competitors
order: 2
deterministic_answer: false
args:
  keyword: the keyword to compare competitors for
  domain: optional website; omit to use the active client
triggers:
  - competitor
  - outrank
  - beat us
  - who ranks
  - compare
---

# compare_competitors

Who is ahead of us on the SERP for a keyword, and where do we sit relative to them.

## When to use
- "Who outranks us for …", "show competitors for …", "who beats us on …".

## Behaviour
- Runs `check_rank` for the keyword (reusing its search + parse), then reshapes the
  result into the target's position plus the captured competitor list.
- Inherits `check_rank`'s domain handling: explicit `domain` for an ad-hoc site,
  else the active client.
