#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Multi-platform AI-search position lookup.

For a keyword, ask each AI platform the same query and report where the target
domain appears among the sources that platform cites — i.e. its citation rank on
that platform. This is the "someone searches X — which position do we show on
each platform" view.

Pluggable, same spirit as websearch_agent's SEARCH_BACKEND: each platform is a
provider that is **enabled** only when its API key is present. Google AI Overview
(Gemini) works today with the existing key; ChatGPT (OpenAI) and Claude (Anthropic)
light up the moment their key is added to config.json — nothing breaks without them.

Position semantics are consistent across platforms: ChatGPT/Claude don't return a
ranked organic list, so "position" is the target's rank among the answer's cited
sources (1 = first source cited). Gemini grounding returns ranked sources directly.
"""
from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlparse

import gemini_agent

REQUEST_TIMEOUT = 40
_ANSWER_MODEL_OPENAI = "gpt-4.1"
_ANSWER_MODEL_CLAUDE = "claude-opus-4-8"


def _key(env_name: str) -> str:
    """API key from the environment, falling back to config.json."""
    return (os.getenv(env_name, "").strip() or gemini_agent._config_value(env_name))


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url if "//" in url else "//" + url).netloc.lower()
    except Exception:  # noqa: BLE001
        host = ""
    return host[4:] if host.startswith("www.") else host


def _normalize(domain: str) -> str:
    import re
    d = (domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    return d[4:] if d.startswith("www.") else d


def _rank_in(urls: list[str], target: str) -> tuple[int | None, str]:
    """1-based rank of the first cited URL whose domain matches target."""
    seen: list[str] = []
    for u in urls:
        dom = _domain_of(u)
        if not dom or dom in seen:
            continue
        seen.append(dom)
        if dom == target or dom.endswith("." + target) or target.endswith("." + dom):
            return len(seen), u
    return None, ""


# ── providers ─────────────────────────────────────────────────────
# Each returns {ok, cited, position, url, note?} or {ok: False, error}.

def _google_ai_overview(keyword: str, target: str) -> dict[str, Any]:
    import websearch_agent as wa
    results = wa.search_keyword(keyword, stop_domain=target)
    pos, url, _ = wa.parse_ranking(results, target)
    return {
        "ok": True,
        "cited": bool(pos),
        "position": pos or "Not cited",
        "url": url,
        "note": f"{len(results)} sources cited",
    }


def _openai_chatgpt(keyword: str, target: str) -> dict[str, Any]:
    import requests
    key = _key("OPENAI_API_KEY")
    resp = requests.post(
        "https://api.openai.com/v1/responses",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": _ANSWER_MODEL_OPENAI,
            "tools": [{"type": "web_search"}],
            "input": f"Search the web for: {keyword}. List the best sources you'd cite, best first.",
        },
        timeout=REQUEST_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    # Collect url_citation annotations in answer order.
    urls: list[str] = []
    for item in data.get("output", []):
        for block in item.get("content", []) or []:
            for ann in block.get("annotations", []) or []:
                if ann.get("type") == "url_citation" and ann.get("url"):
                    urls.append(ann["url"])
    pos, url = _rank_in(urls, target)
    return {"ok": True, "cited": bool(pos), "position": pos or "Not cited",
            "url": url, "note": f"{len(urls)} sources cited"}


def _claude(keyword: str, target: str) -> dict[str, Any]:
    import anthropic
    client = anthropic.Anthropic(api_key=_key("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=_ANSWER_MODEL_CLAUDE,
        max_tokens=1024,
        tools=[{"type": "web_search_20260209", "name": "web_search"}],
        messages=[{"role": "user",
                   "content": f"Search the web for: {keyword}. List the best sources "
                              f"you'd cite for this query, best first."}],
    )
    # Walk content blocks in order; collect citation URLs as they appear.
    urls: list[str] = []
    for block in msg.content:
        for cit in (getattr(block, "citations", None) or []):
            u = getattr(cit, "url", None)
            if u:
                urls.append(u)
        if getattr(block, "type", "") == "web_search_tool_result":
            for r in (getattr(block, "content", None) or []):
                u = getattr(r, "url", None)
                if u:
                    urls.append(u)
    pos, url = _rank_in(urls, target)
    return {"ok": True, "cited": bool(pos), "position": pos or "Not cited",
            "url": url, "note": f"{len(urls)} sources cited"}


# id, name, the key it needs, the query fn, and an "extra requirement" probe.
_PLATFORMS = [
    {"id": "google_ai_overview", "name": "Google AI Overview (Gemini)",
     "key": "GEMINI_API_KEY", "fn": _google_ai_overview, "needs": None},
    {"id": "chatgpt", "name": "ChatGPT (OpenAI)",
     "key": "OPENAI_API_KEY", "fn": _openai_chatgpt, "needs": None},
    {"id": "claude", "name": "Claude (Anthropic)",
     "key": "ANTHROPIC_API_KEY", "fn": _claude, "needs": "anthropic"},
]


def _disabled_reason(p: dict) -> str:
    if not _key(p["key"]):
        return f"Add {p['key']} to config.json to enable."
    if p["needs"]:
        try:
            __import__(p["needs"])
        except ImportError:
            return f"Run `pip install {p['needs']}` to enable."
    return ""


def platform_status() -> list[dict[str, Any]]:
    """Which platforms are wired up and why the others aren't."""
    out = []
    for p in _PLATFORMS:
        reason = _disabled_reason(p)
        out.append({"id": p["id"], "name": p["name"],
                    "enabled": not reason, "reason": reason})
    return out


def check_keyword(keyword: str, target_domain: str) -> dict[str, Any]:
    """Live multi-platform citation check for one keyword."""
    keyword = (keyword or "").strip()
    if not keyword:
        return {"ok": False, "error": "No keyword provided."}
    target = _normalize(target_domain)
    platforms: list[dict[str, Any]] = []
    for p in _PLATFORMS:
        row = {"id": p["id"], "name": p["name"]}
        reason = _disabled_reason(p)
        if reason:
            row.update({"enabled": False, "ok": False, "cited": False,
                        "position": "—", "note": reason})
            platforms.append(row)
            continue
        row["enabled"] = True
        try:
            row.update(p["fn"](keyword, target))
        except Exception as exc:  # noqa: BLE001
            row.update({"ok": False, "cited": False, "position": "—",
                        "note": f"Error: {str(exc)[:120]}"})
        platforms.append(row)
    return {"ok": True, "keyword": keyword, "target_domain": target_domain,
            "platforms": platforms}
