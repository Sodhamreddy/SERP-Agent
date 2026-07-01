# SERP Agent — Architecture

Assured Home Nursing SERP tracker. A **chat-driven, agentic** SEO assistant: the client
types a request, **Gemini plans** the steps, Python **executes** the tools, and the agent
**synthesizes** one answer — streamed live into a ChatGPT-style UI. The local Ollama model
(`gemma4:e4b`) is the **automatic fallback** for reasoning if Gemini is unavailable.

---

## Input → LLM → Tools → Output (flow)

```mermaid
flowchart LR
    subgraph IN["① INPUT"]
        U["💬 User message (chat)<br/>or ▶ Run all 120 keywords"]
    end

    subgraph BRAIN["② LLM — Gemini (Ollama gemma4:e4b fallback)"]
        direction TB
        P["PLAN<br/>break request into ordered tool steps"]
        S["SYNTHESIZE<br/>combine results → one reply"]
    end

    subgraph TOOLS["③ TOOLS (Python)"]
        direction TB
        T1["check_rank"]
        T2["compare_competitors"]
        T3["audit_website"]
        T4["recommend"]
        T5["full_scan (120 kw)"]
    end

    subgraph SRC["data sources"]
        direction TB
        SE["🔎 Serper — Google top 100<br/>(exact positions)"]
        WS["🌐 target website"]
    end

    subgraph OUT["④ OUTPUT"]
        direction TB
        A["Answer + result cards<br/>(streamed live to chat)"]
        X["📄 Excel / CSV report"]
    end

    U --> P
    P -->|chooses steps| T1 & T2 & T3 & T4 & T5
    T1 -->|search_keyword| SE
    T2 --> SE
    T3 -->|fetch + parse| WS
    T5 -->|each keyword| SE
    T4 -->|analyze| S
    SE -->|parse_ranking| S
    WS --> S
    S --> A
    T5 --> X
```

**One line:** `user input → Gemini PLAN → run tools → Serper/website data → Gemini SYNTHESIZE → answer (chat) + Excel (scan)`

---

## High-level diagram (Mermaid)

```mermaid
flowchart TB
    subgraph Browser["🖥️  Browser — templates/index.html"]
        UI["ChatGPT-style Chat UI<br/>sidebar · conversation · composer"]
        DASH["Dashboard view<br/>stats · live log · reports"]
    end

    subgraph Flask["🌐  Flask server — app.py"]
        CHAT["POST /chat  (SSE stream)"]
        TOOLS["GET /chat/tools"]
        RUN["POST /run  →  full scan"]
        STREAM["GET /stream  (batch SSE)"]
        STATUS["/status · /download · /cleanup · /config"]
    end

    subgraph Agent["🤖  Agent layer — agent_chat.py"]
        PLAN["plan()  — Ollama planner<br/>→ ordered steps"]
        RUNTURN["run_turn()  — execute steps,<br/>stream events"]
        REG["Tool registry"]
        SYN["_synthesize()  — Ollama<br/>combines results → 1 reply"]
    end

    subgraph Toolset["🧰  Tools"]
        T1["check_rank"]
        T2["compare_competitors"]
        T3["audit_website"]
        T4["recommend"]
        T5["full_scan"]
        T6["list_keywords / help"]
    end

    subgraph Core["⚙️  Core — websearch_agent.py / serp_agent.py"]
        SK["search_keyword()  →  backend dispatch"]
        PR["parse_ranking()  →  position + competitors"]
        AN["analyze_with_ollama()"]
        BATCH["run_serp_agent() + save_excel()"]
    end

    subgraph External["☁️  External services"]
        OLLAMA["Ollama (local LLM)<br/>plan · route · synthesize · analyze"]
        GEM["Gemini grounding  ★ ACTIVE<br/>~5 results, approximate"]
        ALT["Serper.dev · Google CSE · SerpAPI<br/>(dormant — real top 100)"]
        SITE["Target website<br/>(audit fetch)"]
    end

    OUT["📄 results/*.xlsx + *.csv"]

    UI -- "fetch (ReadableStream)" --> CHAT
    DASH --> RUN & STATUS
    CHAT --> RUNTURN
    RUNTURN --> PLAN --> OLLAMA
    RUNTURN --> REG --> Toolset
    RUNTURN --> SYN --> OLLAMA
    TOOLS --> REG

    T1 & T2 --> SK
    T3 --> SITE
    T4 --> AN --> OLLAMA
    T5 --> BATCH
    SK --> GEM
    SK -. "if keys set" .-> ALT
    T1 & T2 --> PR
    BATCH --> SK
    BATCH --> OUT
    RUN --> BATCH

    CHAT -- "SSE: plan→tool→result→answer" --> UI
```

---

## Agent turn — sequence (what happens on each chat message)

```mermaid
sequenceDiagram
    participant U as Client (chat)
    participant F as Flask /chat
    participant A as agent_chat.run_turn
    participant O as Ollama (local)
    participant S as search backend (Gemini)

    U->>F: POST { message }
    F->>A: run_turn(message)
    A-->>U: ▸ thinking
    A->>O: plan(message)
    O-->>A: steps = [check_rank, recommend]
    A-->>U: ▸ plan (steps shown)
    loop each planned step
        A-->>U: ▸ tool (step active)
        A->>S: search_keyword(query)
        S-->>A: results
        A->>A: parse_ranking()
        A-->>U: ▸ result card (step ✓)
    end
    A->>O: synthesize(all results)
    O-->>A: one combined reply
    A-->>U: ▸ answer  → done
```

---

## Pipeline (one line)

```
Client message
   → Flask /chat (SSE)
   → Ollama PLAN  → ordered tool steps
   → execute tools  → Gemini grounding search + parse ranking / fetch site / analyze
   → Ollama SYNTHESIZE  → single answer
   → stream plan + steps + cards + answer back to the chat UI
```

---

## Components

| Layer | File | Responsibility |
|---|---|---|
| UI | `templates/index.html` | ChatGPT-style chat (sidebar, conversation, composer) + Dashboard; consumes the `/chat` SSE stream |
| Server | `app.py` | Routes; streams agent events; launches the full-scan batch; serves reports |
| Agent | `agent_chat.py` | Planner, router, `run_turn()` executor, answer synthesis (skills loaded via `skills/`) |
| Skills | `skills/<name>/` | One folder per capability — `SKILL.md` (card + metadata) + `skill.py` (`run`/`render`). See [AGENTS.md](AGENTS.md) |
| Core | `websearch_agent.py` | `search_keyword()` backend dispatch, `parse_ranking()`, `analyze_with_ollama()`, search providers |
| Batch | `serp_agent.py` | 120-keyword catalog, `run_serp_agent()`, `save_excel()` |
| Brain (primary) | **Gemini** (JSON mode) | Plans steps, routes intent, synthesizes replies, SEO analysis |
| Brain (fallback) | Ollama `gemma4:e4b` (local) | Used automatically only if Gemini is unavailable/quota-limited |
| Search | Gemini grounding (active) | Returns the sources Google cited (~5, approximate). Serper/CSE/SerpAPI are built but dormant until their key is added |

Set via `REASONING_BACKEND` (default `gemini`) and `SEARCH_BACKEND` (default `gemini`) in `config.json`.

## Search backends (pluggable via `SEARCH_BACKEND`)

| Backend | Results | Positions | Cost | Status |
|---|---|---|---|---|
| `gemini` | ~5–30 | approximate | free (Gemini key) | ★ **active** |
| `serper` | up to 100 | exact | free 2,500/mo | ready (needs key) |
| `google_cse` | up to 100 | exact | free 100/day | ready (needs key + cx) |
| `serpapi` | up to 100 | exact | free 100/mo | ready (needs key) |
| `ollama` | 10 | approximate | free | available |

Adding a backend's key to `config.json` auto-switches the agent to it on next start
(Serper preferred, then Google CSE), otherwise it stays on Gemini grounding.
