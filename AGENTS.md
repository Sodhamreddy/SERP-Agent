# AGENTS.md — SERP Agent

A chat-driven, **skills-based** SEO agent. The client types a request, the agent
**plans** the steps, runs one or more **skills**, and **synthesizes** one reply —
streamed live into a ChatGPT-style UI. Each capability is a self-contained skill
under [`skills/`](skills/); adding one is a matter of dropping in a folder.

> See [ARCHITECTURE.md](ARCHITECTURE.md) for the data-flow diagrams and search-backend
> table. This file is the **agent contract**: how a turn runs, what a skill is, and how
> to extend the agent.

---

## The agent loop (one chat turn)

```
user message
  → plan()            decide the ordered skill steps  (fast: 0 LLM calls for
                      single-intent; 1 LLM call only for genuine multi-step)
  → run each step     skill.run(ctx, **args) → JSON-serializable dict
  → synthesize        deterministic render() per skill, or 1 LLM call where
                      natural phrasing matters (e.g. turning rank numbers into prose)
  → stream            plan → tool → result cards → answer  (SSE to the UI)
```

Entry point: `agent_chat.run_turn(message, ctx)` — a generator of SSE step events
(`thinking`, `plan`, `tool`, `result`, `clarify`, `action`, `answer`, `done`).
`app.py` consumes this for `POST /chat` and launches the heavy batch when it sees a
`full_scan` action.

### Speed is a hard requirement
Chat must reply in **seconds**. Keep each turn to **0–1 LLM calls**:
- Single-intent messages take the **deterministic** path (`_deterministic_plan`
  → `_route_fallback`) — **no LLM**.
- Only multi-intent requests ("check rank **and** how to improve") pay for the
  `_plan_with_ollama` round-trip.
- Skills with `deterministic_answer: true` skip the answer-rewording LLM call;
  their `render()` text is final.

When you add a skill, count the LLM calls it adds to a common turn and keep it ≤ 1.

---

## What a skill is

Every capability lives in `skills/<name>/`:

| File | Role |
|---|---|
| `SKILL.md` | YAML frontmatter (the machine contract) + a markdown "when to use" card (the human/LLM guide). |
| `skill.py` | `run(ctx, **args) -> dict` (required) and `render(data) -> str` (optional friendly answer). |
| `__init__.py` | Empty — makes the folder an importable package. |

### SKILL.md frontmatter fields

| Field | Meaning |
|---|---|
| `name` | Unique tool id (defaults to the folder name). |
| `description` | One line — shown to the planner and in `/chat/tools`. |
| `label` | Progress label shown in the chat UI while the step runs. |
| `args` | `{arg: "help text"}` map passed to the planner so it fills arguments. |
| `triggers` | Phrases the deterministic fast-router matches (documentation of routing intent). |
| `deterministic_answer` | `true` → `render()` text is final, skip the LLM rewording. |
| `order` | Router / listing priority (lower first). |

`skills/__init__.py:load_registry()` discovers every folder and returns the
list-of-dicts that `agent_chat.py` consumes as `TOOLS`. The coordinator never
hard-codes a tool list.

### The `ctx` object
`make_ctx(domain, keywords)` builds the per-turn context — `{"domain", "keywords",
"last"}` — so skills are **stateless per request** and safe for concurrent multi-user
use. `check_rank` stashes its result in `ctx["last"]` so `recommend` can reuse it
without a second search.

---

## How to add a skill

1. `mkdir skills/<name>` and add an empty `__init__.py`.
2. Write `SKILL.md` with the frontmatter above + a short "when to use" body.
3. Write `skill.py` with `run(ctx, **args) -> {"ok": bool, ...}` and an optional
   `render(data) -> str`.
4. If the deterministic fast-router should reach it without an LLM, add matching
   phrases to `_route_fallback` in `agent_chat.py` (the router stays central so its
   ordered priority and the ranking-clarify safety nets are preserved).
5. Restart the app — the loader picks it up automatically. `help` and `/chat/tools`
   list it with no further changes.

Cross-skill calls are explicit imports, e.g.
`from skills.check_rank.skill import run as check_rank` (used by
`compare_competitors` and `recommend`).

---

## Where the central brain still lives

The router/planner heuristics stay in `agent_chat.py` because they are
cross-cutting (ranking requests need a keyword **and** a website, and the agent must
`clarify` rather than guess):

- `route()` / `_route_fallback()` — deterministic, no-LLM tool selection.
- `plan()` / `_plan_with_ollama()` — multi-step planning (LLM only when needed).
- `_enforce_website_clarify()` — safety net that injects a `clarify` step when a
  ranking request is missing or mismatches the active client's website.
- `_synthesize()` / `_answer_with_ollama()` — final reply (delegates the
  deterministic cases to each skill's `render()`).

| Layer | File |
|---|---|
| UI | `templates/index.html` |
| Server | `app.py` |
| Coordinator (plan · route · synthesize · run_turn) | `agent_chat.py` |
| **Skills** (capabilities) | `skills/<name>/` |
| Core search / parse / analyze | `websearch_agent.py` |
| 120-keyword batch | `serp_agent.py` |
