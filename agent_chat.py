#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Agent-mode chat layer for the AHNS SERP Tracker.

The client talks to the agent in a chat window. A local Ollama model reads each
message, picks ONE tool with arguments, Python executes only that tool, and the
agent replies in natural language. This is a thin coordinator on top of the
functions already in websearch_agent.py / serp_agent.py — it does NOT re-run the
whole 120-keyword batch unless the client explicitly asks for a full scan.

Public entry point:
    run_turn(message) -> generator yielding step-event dicts (for SSE streaming)

Each yielded event is one of:
    {"step": "thinking"}
    {"step": "tool",   "tool": <name>, "args": {...}, "label": <human label>}
    {"step": "result", "tool": <name>, "data": {...}}
    {"step": "answer", "text": <markdown-ish answer>}
    {"step": "error",  "text": <message>}
    {"step": "done"}
"""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any, Iterator
from urllib.parse import urlparse

import requests

import websearch_agent as wa


# ───────────────────────────────────────────────────────────────
# CONTEXT — each chat turn carries the active client's domain + keywords so
# the tools are stateless per request (safe for concurrent multi-user use).
#   ctx = {"domain": str, "keywords": [(loc, kw), ...], "last": dict|None}
# ───────────────────────────────────────────────────────────────

def make_ctx(domain: str, keywords) -> dict[str, Any]:
    pairs = [(str(p[0]), str(p[1])) if isinstance(p, (list, tuple)) else ("", str(p))
             for p in (keywords or [])]
    return {"domain": (domain or "").strip(), "keywords": pairs, "last": None}


# ───────────────────────────────────────────────────────────────
# TOOLS  — each takes the turn ctx and returns a JSON-serializable dict
# ───────────────────────────────────────────────────────────────

def _resolve_location(ctx: dict, keyword: str) -> str:
    """Best-effort: match a keyword to a known location from this client's catalog."""
    kw_low = keyword.lower()
    for location, kw in ctx["keywords"]:
        if kw.lower() == kw_low:
            return location
    for location, _ in ctx["keywords"]:
        city = location.split(",")[0].strip().lower()
        if city and city in kw_low:
            return location
    return ""


def tool_check_rank(ctx: dict, keyword: str = "", location: str = "", domain: str = "", **_) -> dict[str, Any]:
    """Check a website's ranking position for ONE keyword.

    Checks the active client's domain by default, OR an explicit `domain` if the user
    named a specific website (ad-hoc check of any site).
    """
    keyword = (keyword or "").strip()
    if not keyword:
        return {"ok": False, "error": "No keyword provided. Tell me which keyword to check."}

    # Target website: explicit domain if given, else the active client's.
    target = wa._normalize_domain(domain) if domain else ""
    target = target or ctx["domain"]
    adhoc = bool(domain and target != ctx["domain"])

    if not location:
        location = _resolve_location(ctx, keyword)
    query = keyword
    if location:
        city = location.split(",")[0].strip()
        if city and city.lower() not in keyword.lower():
            query = f"{keyword} in {location}"

    # Pass the target so the search can early-exit once it's found (fast when the site
    # ranks well; only a deep/absent site pages the full depth).
    results = wa.search_keyword(query, stop_domain=target)
    pos, found_url, competitors = wa.parse_ranking(results, target)
    approximate = wa._search_backend() in {"gemini", "gemini_grounding", "google_gemini"}
    data = {
        "ok": True,
        "keyword": keyword,
        "query": query,
        "location": location,
        "target_domain": target,
        "adhoc": adhoc,
        "position": pos or "Not Found",
        "found": bool(pos),
        "approximate": approximate,
        "url_found": found_url,
        "results_scanned": len(results),
        "backend": wa._search_backend(),
        "competitors": competitors[:wa.COMPETITOR_LIMIT],
    }
    ctx["last"] = data
    return data


def tool_compare_competitors(ctx: dict, keyword: str = "", domain: str = "", **_) -> dict[str, Any]:
    """Show who outranks a website for a keyword."""
    data = tool_check_rank(ctx, keyword=keyword, domain=domain)
    if not data.get("ok"):
        return data
    return {
        "ok": True,
        "keyword": data["keyword"],
        "target_domain": data["target_domain"],
        "target_position": data["position"],
        "target_found": data["found"],
        "competitors": data["competitors"],
    }


class _AuditParser(HTMLParser):
    """Pull SEO basics out of a page's static HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.title: list[str] = []
        self.h1: list[str] = []
        self.meta_description = ""
        self._in_title = False
        self._in_h1 = False
        self._text_chars = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag == "h1" and not self.h1:
            self._in_h1 = True
        elif tag == "meta":
            attr = {name.lower(): (value or "") for name, value in attrs}
            if attr.get("name", "").lower() == "description":
                self.meta_description = attr.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if self._in_title:
            self.title.append(stripped)
        if self._in_h1:
            self.h1.append(stripped)
        # Rough word count of visible text.
        if stripped:
            self._text_chars += len(stripped.split())


def tool_audit_website(ctx: dict, url: str = "", **_) -> dict[str, Any]:
    """Fetch a page and report SEO basics: title, meta, H1, reviews, word count."""
    url = (url or "").strip()
    if not url:
        url = f"https://{ctx['domain']}"
    if "://" not in url:
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=wa.REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not fetch {url}: {exc}"}

    html = resp.text
    parser = _AuditParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        pass

    low = html.lower()
    # US-style phone: optional +1, 3-digit area code, then 3-4 split by space/dot/dash.
    phone_match = re.search(r"(\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}", html)
    title = " ".join(" ".join(parser.title).split())
    h1 = " ".join(" ".join(parser.h1).split())

    return {
        "ok": True,
        "url": url,
        "title": title,
        "title_length": len(title),
        "meta_description": parser.meta_description,
        "meta_length": len(parser.meta_description),
        "h1": h1,
        "word_count": parser._text_chars,
        "has_reviews": ("review" in low or "testimonial" in low or "rating" in low),
        "phone_found": phone_match.group(0).strip() if phone_match else "",
        "https": urlparse(url).scheme == "https",
    }


def tool_recommend(ctx: dict, keyword: str = "", **_) -> dict[str, Any]:
    """Generate SEO recommendations for a keyword (LLM analysis layer)."""
    last = ctx.get("last") or {}
    keyword = (keyword or "").strip() or last.get("keyword", "")
    if not keyword:
        return {"ok": False, "error": "Tell me which keyword you want recommendations for."}

    # Reuse this turn's prior rank check when it matches (saves a search), else fetch.
    rank = last if last.get("keyword") == keyword else tool_check_rank(ctx, keyword=keyword)
    if not rank.get("ok"):
        return rank

    row = {
        "Keyword": rank["keyword"],
        "Location": rank.get("location", ""),
        "Position": rank["position"],
        "URL Found": rank.get("url_found", ""),
        "Competitors": rank.get("competitors", []),
    }
    report = wa.analyze_with_ollama([row], ctx["domain"])
    if not isinstance(report, dict):
        return {
            "ok": True,
            "keyword": keyword,
            "source": "local",
            "recommendations": [
                "Improve on-page targeting of the exact keyword in title, H1, and meta description.",
                "Add a location-specific service page and local business schema.",
                "Collect and display client reviews/testimonials to build trust signals.",
            ],
        }
    report["ok"] = True
    report["keyword"] = keyword
    report["source"] = "ollama"
    return report


def tool_list_keywords(ctx: dict, **_) -> dict[str, Any]:
    """Return the active client's keyword catalog (sample + count)."""
    kws = ctx["keywords"]
    locations = sorted({loc for loc, _ in kws if loc})
    return {
        "ok": True,
        "total_keywords": len(kws),
        "total_locations": len(locations),
        "locations": locations,
        "sample_keywords": [kw for _, kw in kws[:8]],
    }


def tool_clarify(ctx: dict, question: str = "", options=None, need: str = "",
                 keyword: str = "", **_) -> dict[str, Any]:
    """Ask the user to clarify a missing detail (which website / which keyword)."""
    opts = [str(o) for o in (options or []) if str(o).strip()][:5]
    return {"ok": True, "action": "clarify",
            "question": (question or "Could you clarify your request?").strip(),
            "options": opts, "need": (need or "").strip(), "keyword": (keyword or "").strip()}


def tool_help(ctx: dict, **_) -> dict[str, Any]:
    """Describe what the agent can do."""
    return {
        "ok": True,
        "tools": [{"name": t["name"], "description": t["description"]} for t in TOOLS],
    }


def tool_full_scan(ctx: dict, **_) -> dict[str, Any]:
    """Signal that the heavy keyword batch should run (handled by app.py)."""
    return {
        "ok": True,
        "action": "full_scan",
        "total_keywords": len(ctx["keywords"]),
        "note": "Starting the full scan in the background.",
    }


# ── Tool registry ───────────────────────────────────────────────
TOOLS: list[dict[str, Any]] = [
    {
        "name": "check_rank",
        "description": "Check a website's Google ranking position for ONE specific keyword.",
        "args": {"keyword": "the exact keyword/phrase to check",
                 "location": "optional city, e.g. 'Detroit, MI'",
                 "domain": "optional website to check (e.g. 'example.com'); omit to use the active client"},
        "label": "Checking ranking",
        "fn": tool_check_rank,
    },
    {
        "name": "compare_competitors",
        "description": "Show which competitor websites outrank a site for a keyword.",
        "args": {"keyword": "the keyword to compare competitors for",
                 "domain": "optional website; omit to use the active client"},
        "label": "Comparing competitors",
        "fn": tool_compare_competitors,
    },
    {
        "name": "audit_website",
        "description": "Audit a web page for SEO basics (title, meta, H1, reviews, word count). Defaults to our own site.",
        "args": {"url": "optional page URL; defaults to our website"},
        "label": "Auditing website",
        "fn": tool_audit_website,
    },
    {
        "name": "recommend",
        "description": "Generate SEO recommendations to improve ranking for a keyword.",
        "args": {"keyword": "the keyword to get recommendations for"},
        "label": "Generating recommendations",
        "fn": tool_recommend,
    },
    {
        "name": "list_keywords",
        "description": "List the keywords and locations the tracker covers.",
        "args": {},
        "label": "Listing keywords",
        "fn": tool_list_keywords,
    },
    {
        "name": "full_scan",
        "description": "Run the full 120-keyword ranking scan and build the Excel report.",
        "args": {},
        "label": "Starting full scan",
        "fn": tool_full_scan,
    },
    {
        "name": "clarify",
        "description": ("Ask the user to specify a missing detail when a ranking request is "
                        "ambiguous — e.g. which website to check, or which keyword. Provide a "
                        "short question and 2-4 quick options."),
        "args": {"question": "the question to ask", "options": ["short option the user can click"]},
        "label": "Need a detail",
        "fn": tool_clarify,
    },
    {
        "name": "help",
        "description": "Explain what the agent can do.",
        "args": {},
        "label": "Showing help",
        "fn": tool_help,
    },
]

_TOOLS_BY_NAME = {t["name"]: t for t in TOOLS}


def tool_catalog() -> list[dict[str, str]]:
    """Public catalog for the UI (name + description, no callables)."""
    return [{"name": t["name"], "description": t["description"]} for t in TOOLS]


# ───────────────────────────────────────────────────────────────
# ROUTER  — Ollama picks the tool; deterministic fallback if unavailable
# ───────────────────────────────────────────────────────────────

def _route_with_ollama(message: str) -> dict[str, Any] | None:
    prompt = {
        "role": "Tool router for an SEO SERP assistant",
        "task": (
            "Read the user's message and choose exactly ONE tool to call, plus its "
            "arguments. If the message is small talk or unclear, set tool to 'help' "
            "and put a friendly reply in 'chat_reply'."
        ),
        "user_message": message,
        "available_tools": [
            {"name": t["name"], "description": t["description"], "args": t["args"]}
            for t in TOOLS
        ],
        "required_json": {
            "tool": "one of the tool names",
            "args": "object of arguments for that tool (extract keyword/url from the message)",
            "chat_reply": "optional friendly text if no real tool is needed",
        },
    }
    out = wa._call_llm(prompt, timeout=30)
    if isinstance(out, dict) and out.get("tool") in _TOOLS_BY_NAME:
        return {"tool": out["tool"], "args": out.get("args") or {}, "chat_reply": out.get("chat_reply", "")}
    return None


def _extract_keyword(message: str) -> str:
    """Pull a quoted phrase or 'for <phrase>' out of the message."""
    quoted = re.search(r"[\"'“”‘’]([^\"'“”‘’]{3,})[\"'“”‘’]", message)
    if quoted:
        return quoted.group(1).strip()
    m = re.search(r"\bfor\s+(.+)$", message, flags=re.IGNORECASE)
    if m:
        return m.group(1).strip().rstrip("?.!")
    return ""


def _extract_domain(message: str) -> str:
    m = re.search(r"\b([a-z0-9][a-z0-9-]*\.[a-z]{2,}(?:\.[a-z]{2,})?)\b", (message or "").lower())
    return m.group(1) if m else ""


def _route_fallback(message: str) -> dict[str, Any]:
    low = message.lower()
    kw = _extract_keyword(message)
    domain = _extract_domain(message)
    if any(w in low for w in ("full scan", "all keyword", "120", "everything", "scan all")):
        return {"tool": "full_scan", "args": {}, "chat_reply": ""}
    if any(w in low for w in ("audit", "my website", "my site", "homepage", "page seo", "site seo")):
        url = ""
        m = re.search(r"https?://\S+", message)
        if m:
            url = m.group(0)
        return {"tool": "audit_website", "args": {"url": url}, "chat_reply": ""}
    if any(w in low for w in ("competitor", "outrank", "beat us", "who ranks", "compare")):
        return {"tool": "compare_competitors", "args": {"keyword": kw, "domain": domain}, "chat_reply": ""}
    if any(w in low for w in ("recommend", "improve", "advice", "suggestion", "how do i rank", "boost")):
        return {"tool": "recommend", "args": {"keyword": kw}, "chat_reply": ""}
    if "keyword" in low and any(w in low for w in ("list", "track", "what", "which", "all", "show")):
        return {"tool": "list_keywords", "args": {}, "chat_reply": ""}
    if any(w in low for w in ("list keyword", "locations you", "what locations")):
        return {"tool": "list_keywords", "args": {}, "chat_reply": ""}
    if any(w in low for w in ("rank", "position", "ranking", "where do we", "place")):
        return {"tool": "check_rank", "args": {"keyword": kw, "domain": domain}, "chat_reply": ""}
    # No explicit intent verb, but it still looks like a search phrase (e.g. a bare
    # keyword like "Best pharmacy in Independence MO"). Rank-checking is this app's
    # primary job, so default a plausible query to check_rank instead of 'help'.
    if _looks_like_query(message):
        return {"tool": "check_rank",
                "args": {"keyword": kw or message.strip().rstrip("?.!"), "domain": domain},
                "chat_reply": ""}
    return {
        "tool": "help",
        "args": {},
        "chat_reply": "I can check a keyword's ranking, audit your website, compare competitors, "
                      "give SEO recommendations, or run a full scan. What would you like?",
    }


_SMALLTALK_RE = re.compile(
    r"^\s*(hi|hello|hey|yo|thanks|thank you|ok|okay|help|menu|what\s+can\s+you|"
    r"who\s+are\s+you|how\s+are\s+you|what\s+do\s+you|good\s+(morning|afternoon|evening))\b",
    re.IGNORECASE,
)


def _looks_like_query(message: str) -> bool:
    """True if the message reads like a real search request rather than small talk."""
    m = (message or "").strip()
    if len(m.split()) < 2:
        return False
    return not _SMALLTALK_RE.match(m)


def route(message: str) -> dict[str, Any]:
    return _route_with_ollama(message) or _route_fallback(message)


# ───────────────────────────────────────────────────────────────
# PLANNER  — agentic: break the request into an ordered list of tool steps
# ───────────────────────────────────────────────────────────────

MAX_PLAN_STEPS = 3   # cap so a plan never runs too many rate-limited searches


def _looks_like_domain(text: str) -> bool:
    """True if the text contains a domain-like token (e.g. example.com)."""
    return bool(re.search(r"\b[a-z0-9][a-z0-9-]*\.[a-z]{2,}\b", (text or "").lower()))


def _plan_with_ollama(message: str, ctx: dict | None = None) -> dict[str, Any] | None:
    active_domain = (ctx or {}).get("domain", "")
    sample_kw = [kw for _, kw in (ctx or {}).get("keywords", [])][:8]
    prompt = {
        "role": "Planner for an autonomous SEO SERP agent",
        "task": (
            "Break the user's request into an ordered list of 1-3 tool steps that, run "
            "in sequence, fully satisfy it. Use the FEWEST steps needed. Each step calls "
            "exactly one tool. Example: 'check rank and tell me how to improve' -> "
            "[check_rank, recommend].\n"
            "RANKING RULE — a ranking/position request needs BOTH a clear KEYWORD and a "
            "target WEBSITE (domain):\n"
            "• If the user clearly named a website domain (e.g. 'stadiumrx.com'), pass it as "
            "check_rank's 'domain' arg and proceed.\n"
            "• If the user wants a SPECIFIC website but did NOT give a domain, you MUST use the "
            "'clarify' tool: set need='domain', put the keyword in 'keyword', ask "
            "'Which website should I check for \"<keyword>\"?', and offer the active client "
            "domain as one option. NEVER assume the active client when the user wants a specific "
            "site.\n"
            "• If the keyword itself is unclear, use 'clarify' with need='keyword'.\n"
            "Only default to the active client when the user did NOT ask about a specific other "
            "website. Never use 'help' for a ranking request."
        ),
        "user_message": message,
        "active_client_domain": active_domain,
        "active_client_keywords": sample_kw,
        "available_tools": [
            {"name": t["name"], "description": t["description"], "args": t["args"]}
            for t in TOOLS
        ],
        "required_json": {
            "goal": "one-line restatement of what the user wants",
            "steps": [{"tool": "tool name",
                       "args": {"keyword": "", "domain": "", "question": "", "need": "", "options": []},
                       "why": "short reason"}],
        },
    }
    out = wa._call_llm(prompt, timeout=25, max_tokens=320)
    if not isinstance(out, dict) or not isinstance(out.get("steps"), list):
        return None
    steps = [
        {"tool": s["tool"], "args": s.get("args") or {}, "why": str(s.get("why", ""))}
        for s in out["steps"]
        if isinstance(s, dict) and s.get("tool") in _TOOLS_BY_NAME
    ]
    if not steps:
        return None
    return {"goal": str(out.get("goal", "")), "steps": steps[:MAX_PLAN_STEPS]}


_CMD_PHRASES = [
    "check a specific website", "check the specific website", "specific website",
    "a specific site", "specific site", "check a website", "check the website",
    "a website", "the website", "general seo advice", "seo advice",
    "ranking position", "rank position", "what position", "which position",
    "position of", "position for", "check position", "check rank for", "check rank",
    "check the rank", "rank of", "rank for", "ranking for", "ranking", "rank",
    "position", "need", "please",
]


def _derive_keyword(message: str) -> str:
    """Best-effort keyword from a free-form message (used when clarifying)."""
    kw = _extract_keyword(message)
    if kw:
        return kw
    s = " " + (message or "") + " "
    for ph in _CMD_PHRASES:
        s = re.sub(r"(?i)\b" + re.escape(ph) + r"\b", " ", s)
    return re.sub(r"\s+", " ", s).strip(" ?.!-\"'")


# Generic search-modifier words that say nothing about WHICH business a keyword
# belongs to ("best", "near me", "services"...). Ignored by the relevance check.
_KW_STOPWORDS = {
    "best", "top", "good", "great", "cheap", "affordable", "local", "near", "the",
    "for", "and", "with", "service", "services", "company", "companies", "agency",
    "agencies", "review", "reviews", "cost", "costs", "price", "prices", "hour",
    "hours", "find", "get",
}

# "our rank", "my site", "where do we stand" — the user means the active client.
_OWN_SITE_RE = re.compile(r"\b(we|our|ours|my|us|mine)\b", re.IGNORECASE)


def _keyword_matches_client(ctx: dict | None, keyword: str) -> bool:
    """Cheap relevance check (no LLM): does this keyword look like the active
    client's business? Compares the keyword's service words (minus stopwords and
    location names) against the client's tracked-keyword vocabulary and domain
    name. 'Best Pharmacy in Independence MO' shares no service word with a
    home-nursing catalog → False, so the agent asks which website to check."""
    ctx = ctx or {}
    pairs = ctx.get("keywords") or []
    domain = (ctx.get("domain") or "").lower()
    if not keyword or (not pairs and not domain):
        return True  # nothing to judge against — keep the default behavior
    kw_low = keyword.lower().strip()
    if any(k.lower().strip() == kw_low for _, k in pairs):
        return True  # exact tracked keyword
    loc_tokens = {t for loc, _ in pairs for t in re.findall(r"[a-z]+", loc.lower())}
    vocab = {t for _, k in pairs for t in re.findall(r"[a-z]+", k.lower())
             if len(t) >= 3 and t not in _KW_STOPWORDS and t not in loc_tokens}
    tokens = [t for t in re.findall(r"[a-z]+", kw_low)
              if len(t) >= 3 and t not in _KW_STOPWORDS and t not in loc_tokens]
    if not tokens:
        return True  # pure location/modifier query — nothing to compare
    for t in tokens:
        stem = t[:-1] if t.endswith("s") else t
        if t in vocab or stem in vocab or (t + "s") in vocab:
            return True
        if domain and (t in domain or stem in domain):
            return True
    return False


def _enforce_website_clarify(p: dict, message: str, ctx: dict | None) -> dict:
    """Safety net for ranking requests:
    - inject an explicit domain the LLM may have missed,
    - if a specific website is implied but no domain given, ask for the website URL
      (with a text input) instead of silently assuming the active client,
    - if a bare keyword doesn't look like the active client's business, ask which
      website to check instead of silently checking the active client."""
    steps = p.get("steps") or []
    if not steps:
        return p
    first = steps[0]
    t0 = first["tool"]
    args0 = first.get("args") or {}
    msg_domain = _extract_domain(message)

    active = (ctx or {}).get("domain", "")

    # Inject a domain the planner may have missed (so ad-hoc checks always work).
    if t0 in ("check_rank", "compare_competitors") and not str(args0.get("domain", "")).strip() and msg_domain:
        args0["domain"] = msg_domain
        first["args"] = args0

    # Normalize ANY clarify the planner produced so the UI ALWAYS gets a usable
    # prompt (active-client chip + a free-text "Enter a website" box). The LLM
    # often omits need='domain'/keyword/options, which left the user with a dead
    # chip and no input — and an endless re-clarify loop.
    if t0 == "clarify":
        need = str(args0.get("need", "")).strip().lower()
        kw = str(args0.get("keyword", "")).strip() or _derive_keyword(message)
        if need == "keyword":
            return p  # keyword clarify already works in the UI
        # If the user already named a website, DON'T ask again — just check it.
        if msg_domain:
            return {"goal": p.get("goal", ""), "steps": [{"tool": "check_rank",
                    "args": {"keyword": kw, "domain": msg_domain}, "why": "domain provided"}]}
        opts = [str(o).strip() for o in (args0.get("options") or []) if str(o).strip()]
        if active and active not in opts:
            opts.insert(0, active)
        q = str(args0.get("question", "")).strip() or (
            "Which website should I check" + (f' for "{kw}"' if kw else "") + "?")
        return {"goal": p.get("goal", ""), "steps": [{"tool": "clarify", "args": {
            "need": "domain", "keyword": kw, "question": q, "options": opts[:4],
        }, "why": first.get("why", "website not specified")}]}

    has_domain = bool(str(args0.get("domain", "")).strip()) or bool(msg_domain)
    low = message.lower()
    # If the user explicitly wants a specific website but gave no domain, ALWAYS ask for
    # the URL (whatever tool the planner guessed) — never assume the active client.
    wants_specific = any(w in low for w in ("specific website", "a website", "another site",
                                            "this site", "this website", "specific site",
                                            "check a website"))
    if wants_specific and not has_domain:
        kw = str(args0.get("keyword", "")).strip() or _derive_keyword(message)
        q = "Which website should I check" + (f' for "{kw}"' if kw else "") + "?"
        return {"goal": p.get("goal", ""), "steps": [{"tool": "clarify", "args": {
            "need": "domain", "keyword": kw, "question": q,
            "options": [active] if active else [],
        }, "why": "website not specified"}]}

    # Off-niche keyword gate: a bare keyword with no domain that doesn't look like
    # the active client's business (e.g. 'Best Pharmacy ...' for a home-nursing
    # client) — ask which website to check instead of silently using the client.
    if (t0 in ("check_rank", "compare_competitors") and not has_domain
            and not _OWN_SITE_RE.search(message)):
        kw = str(args0.get("keyword", "")).strip() or _derive_keyword(message)
        if kw and not _keyword_matches_client(ctx, kw):
            q = (f'"{kw}" doesn\'t look like one of **{active}**\'s keywords — '
                 "which website should I check it for?") if active else (
                 f'Which website should I check for "{kw}"?')
            return {"goal": p.get("goal", ""), "steps": [{"tool": "clarify", "args": {
                "need": "domain", "keyword": kw, "question": q,
                "options": [active] if active else [],
            }, "why": "keyword does not match the active client"}]}
    return p


# Intent groups used to decide whether a request needs the (slower) LLM planner.
# Each entry: category -> trigger words. A message touching 2+ categories is treated
# as multi-step and worth an LLM plan; anything else takes the instant route.
_INTENT_GROUPS = {
    "rank": ("rank", "position", "ranking", "where do we", "place"),
    "audit": ("audit", "my website", "my site", "homepage", "page seo", "site seo"),
    "competitors": ("competitor", "outrank", "beat us", "who ranks", "compare"),
    "recommend": ("recommend", "improve", "advice", "suggestion", "how do i rank", "boost"),
    "scan": ("full scan", "all keyword", "scan all", "everything", "120"),
}
_CHAIN_RE = re.compile(r"\b(and|then|also|plus|after that|as well|followed by)\b", re.IGNORECASE)


def _is_multistep(message: str) -> bool:
    """Cheap heuristic: does this request likely need more than one tool?

    Only multi-intent requests (e.g. 'check rank AND tell me how to improve') justify
    the LLM planner round-trip; single-intent messages take the deterministic path.
    """
    low = (message or "").lower()
    hits = sum(1 for words in _INTENT_GROUPS.values() if any(w in low for w in words))
    return hits >= 2 and bool(_CHAIN_RE.search(low))


def _deterministic_plan(message: str) -> dict[str, Any]:
    """Build a single-step plan from the offline router — no LLM call."""
    decision = _route_fallback(message)
    return {
        "goal": "",
        "steps": [{"tool": decision["tool"], "args": decision.get("args") or {}, "why": ""}],
        "chat_reply": decision.get("chat_reply", ""),
    }


def plan(message: str, ctx: dict | None = None) -> dict[str, Any]:
    """Return an execution plan: {goal, steps:[{tool,args,why}], chat_reply?}.

    Fast path: single-intent requests skip the LLM planner entirely and route
    deterministically. Only genuine multi-step requests pay for an LLM plan.
    """
    if _is_multistep(message):
        planned = _plan_with_ollama(message, ctx) or _deterministic_plan(message)
    else:
        planned = _deterministic_plan(message)
    return _enforce_website_clarify(planned, message, ctx)


# ───────────────────────────────────────────────────────────────
# ANSWER  — turn the raw tool result into a friendly reply
# ───────────────────────────────────────────────────────────────

def _answer_fallback(tool_name: str, data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("error", "Sorry, something went wrong with that request.")

    if tool_name == "check_rank":
        approx = "approximately " if data.get("approximate") else ""
        if data["found"]:
            return (f"**{data['keyword']}** ranks at {approx}position **{data['position']}** "
                    f"for {data['target_domain']} ({data['url_found']}).")
        return (f"I didn't see **{data['target_domain']}** among the {data['results_scanned']} "
                f"sources this check returned for **{data['keyword']}**. It may still rank deeper "
                f"than this check can see — this isn't a confirmed absence.")

    if tool_name == "compare_competitors":
        comps = data.get("competitors", [])
        if not comps:
            return f"No competitors captured for **{data['keyword']}**."
        top = "; ".join(f"#{c['position']} {c['title']}" for c in comps[:5])
        status = (f"We rank at {data['target_position']}" if data["target_found"]
                  else "We are not ranking in the scanned results")
        return f"For **{data['keyword']}**: {status}. Top competitors: {top}."

    if tool_name == "audit_website":
        flags = []
        if data["title_length"] == 0:
            flags.append("missing <title>")
        if data["meta_length"] == 0:
            flags.append("missing meta description")
        if not data["h1"]:
            flags.append("missing H1")
        if not data["has_reviews"]:
            flags.append("no visible reviews/testimonials")
        issues = ("Issues: " + ", ".join(flags)) if flags else "No major on-page issues found."
        return (f"Audit of {data['url']} — Title: \"{data['title']}\" ({data['title_length']} chars), "
                f"H1: \"{data['h1'] or '—'}\", ~{data['word_count']} words. {issues}")

    if tool_name == "recommend":
        recs = data.get("recommendations", [])
        if recs:
            return "Recommendations for **{}**:\n".format(data.get("keyword", "")) + \
                   "\n".join(f"- {r}" for r in recs[:6])
        return data.get("executive_summary", "No recommendations available.")

    if tool_name == "list_keywords":
        return (f"I track **{data['total_keywords']} keywords** across "
                f"**{data['total_locations']} locations**. Examples: "
                + ", ".join(data["sample_keywords"][:5]) + " …")

    if tool_name == "full_scan":
        return "Starting the full 120-keyword scan now — progress will appear in the run log."

    if tool_name == "help":
        tools = data.get("tools", [])
        return "Here's what I can do:\n" + "\n".join(f"- **{t['name']}** — {t['description']}" for t in tools)

    return "Done."


def _answer_with_ollama(message: str, tool_name: str, data: dict[str, Any]) -> str | None:
    prompt = {
        "role": "SEO assistant replying in chat",
        "task": "Write a short, friendly reply (1-3 sentences) to the user based on the tool result. "
                "Be concrete and use the numbers from the data. Return JSON only. "
                "IMPORTANT: if position is 'Not Found', do NOT say the site does not rank. Say it "
                "was not seen among the limited sources checked and may rank deeper — this is a "
                "limitation of the check, not a confirmed absence.",
        "user_message": message,
        "tool_used": tool_name,
        "tool_result": data,
        "required_json": {"reply": "the chat reply text"},
    }
    # A 1-3 sentence reply needs few tokens; cap output + tighten the timeout so the
    # final wording returns quickly instead of waiting on a long, slow generation.
    out = wa._call_llm(prompt, timeout=20, max_tokens=200)
    if isinstance(out, dict) and isinstance(out.get("reply"), str) and out["reply"].strip():
        return out["reply"].strip()
    return None


# Tools whose deterministic answer text is already complete and readable. Rewording
# these with an LLM adds latency but little value, so we skip that round-trip and only
# spend an LLM call where natural phrasing matters (turning rank numbers into a sentence).
_DETERMINISTIC_ANSWER_TOOLS = {"recommend", "list_keywords", "audit_website", "full_scan", "help"}


def _synthesize(message: str, observations: list[dict[str, Any]]) -> str | None:
    """Combine all step results into one friendly reply (multi-step agent answer)."""
    if len(observations) == 1:
        obs = observations[0]
        if obs["tool"] in _DETERMINISTIC_ANSWER_TOOLS:
            return _answer_fallback(obs["tool"], obs["data"])
        return _answer_with_ollama(message, obs["tool"], obs["data"])
    prompt = {
        "role": "SEO assistant summarizing an agent run",
        "task": "The agent ran several tools to answer the user. Write ONE cohesive, friendly "
                "reply (2-4 sentences) that combines the findings. Use concrete numbers. JSON only. "
                "IMPORTANT: if a ranking position is 'Not Found', do NOT claim the site does not "
                "rank; say it was not seen among the limited sources checked and may rank deeper.",
        "user_message": message,
        "steps": [{"tool": o["tool"], "result": o["data"]} for o in observations],
        "required_json": {"reply": "the combined chat reply"},
    }
    out = wa._call_llm(prompt, timeout=30, max_tokens=320)
    if isinstance(out, dict) and isinstance(out.get("reply"), str) and out["reply"].strip():
        return out["reply"].strip()
    return None


def _multi_fallback(observations: list[dict[str, Any]]) -> str:
    """Deterministic combined answer when Ollama synthesis is unavailable."""
    return "\n\n".join(_answer_fallback(o["tool"], o["data"]) for o in observations)


# ───────────────────────────────────────────────────────────────
# TURN RUNNER  — generator of SSE step events
# ───────────────────────────────────────────────────────────────

def run_turn(message: str, ctx: dict[str, Any]) -> Iterator[dict[str, Any]]:
    """Agentic turn: plan the steps, execute each one, then synthesize a reply.

    `ctx` (from make_ctx) carries the active client's domain + keywords so tools are
    stateless per request and safe for concurrent multi-user use.
    """
    message = (message or "").strip()
    if not message:
        yield {"step": "answer", "text": "Type a request and I'll get to work."}
        yield {"step": "done"}
        return

    yield {"step": "thinking"}

    try:
        the_plan = plan(message, ctx)
    except Exception as exc:  # noqa: BLE001
        yield {"step": "error", "text": f"Planning failed: {exc}"}
        yield {"step": "done"}
        return

    steps = the_plan["steps"]

    # Clarify shortcut: if the agent needs a missing detail (which website / keyword),
    # ask the user with options + an input instead of running tools or showing help.
    if steps and steps[0]["tool"] == "clarify":
        data = tool_clarify(ctx, **(steps[0].get("args") or {}))
        yield {"step": "clarify", "question": data["question"], "options": data["options"],
               "need": data["need"], "keyword": data["keyword"]}
        yield {"step": "done"}
        return

    # Announce the plan so the UI can show the agent's intended steps up front.
    yield {
        "step": "plan",
        "goal": the_plan.get("goal", ""),
        "steps": [
            {"tool": s["tool"], "label": _TOOLS_BY_NAME[s["tool"]]["label"], "why": s.get("why", "")}
            for s in steps
        ],
    }

    observations: list[dict[str, Any]] = []
    for idx, s in enumerate(steps):
        tool_name = s["tool"]
        args = s.get("args") or {}
        spec = _TOOLS_BY_NAME[tool_name]

        yield {"step": "tool", "index": idx, "tool": tool_name, "args": args, "label": spec["label"]}
        try:
            data = spec["fn"](ctx, **args)
        except Exception as exc:  # noqa: BLE001
            data = {"ok": False, "error": f"{tool_name} failed: {exc}"}
        yield {"step": "result", "index": idx, "tool": tool_name, "data": data}
        observations.append({"tool": tool_name, "data": data})

        # full_scan is launched by the caller (app.py) when it sees this action.
        if tool_name == "full_scan" and data.get("ok"):
            yield {"step": "action", "action": "full_scan"}

    answer = _synthesize(message, observations) or _multi_fallback(observations)
    if the_plan.get("chat_reply") and len(steps) == 1 and steps[0]["tool"] == "help":
        answer = the_plan["chat_reply"] + "\n\n" + answer
    yield {"step": "answer", "text": answer}
    yield {"step": "done"}
