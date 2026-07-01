---
name: help
description: Explain what the agent can do.
label: Showing help
order: 8
deterministic_answer: true
args: {}
triggers: []
---

# help

The fallback skill: when a message is small talk or has no clear intent, describe
the agent's capabilities.

## When to use
- Greetings, "what can you do", unclear messages — the central router defaults here
  (with a friendly `chat_reply`) when nothing else matches and the text doesn't look
  like a search query.

## Behaviour
- Lists every registered skill (name + description) by reading the live registry via
  `skills.catalog()`, so new skills appear in help automatically.
