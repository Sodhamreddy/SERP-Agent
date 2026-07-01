# skills/ — the agent's capabilities

Each subfolder is one **skill**: a self-contained unit the agent can plan, run, and
phrase an answer from. `__init__.py:load_registry()` discovers them at startup and
builds the tool registry that `agent_chat.py` drives. Drop in a new folder to add a
capability — no edit to the coordinator's tool list.

See [`../AGENTS.md`](../AGENTS.md) for the agent loop, the SKILL.md frontmatter
contract, and the step-by-step "how to add a skill" guide.

## Anatomy of a skill

```
skills/<name>/
├── __init__.py   # empty — makes the folder importable
├── SKILL.md      # YAML frontmatter (contract) + "when to use" card
└── skill.py      # run(ctx, **args) -> dict   +   render(data) -> str (optional)
```

## Current skills

| Skill | Does | Deterministic answer | Routed by phrases like |
|---|---|:---:|---|
| `check_rank` | Google ranking position for one keyword | no | rank, ranking, position |
| `compare_competitors` | Who outranks a site for a keyword | no | competitor, outrank, who ranks |
| `audit_website` | On-page SEO basics for a URL | yes | audit, my website, page seo |
| `recommend` | SEO recommendations for a keyword | yes | recommend, improve, how do I rank |
| `list_keywords` | The tracked-keyword catalog | yes | list keywords, what locations |
| `full_scan` | Launch the 120-keyword batch + Excel | yes | full scan, scan all, everything |
| `clarify` | Ask for a missing detail (which site/keyword) | — | (planner / safety-net only) |
| `help` | Describe what the agent can do | yes | (fallback for small talk) |

`clarify` has no `render()` — `run_turn` handles it specially (emits a question +
options + free-text box and ends the turn). `compare_competitors` and `recommend`
call `check_rank` internally via an explicit import.
