#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_rank — Google ranking position for one keyword. See SKILL.md."""
from __future__ import annotations

from typing import Any

import websearch_agent as wa


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


def run(ctx: dict, keyword: str = "", location: str = "", domain: str = "", **_) -> dict[str, Any]:
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


def render(data: dict[str, Any]) -> str:
    approx = "approximately " if data.get("approximate") else ""
    if data["found"]:
        return (f"**{data['keyword']}** ranks at {approx}position **{data['position']}** "
                f"for {data['target_domain']} ({data['url_found']}).")
    return (f"I didn't see **{data['target_domain']}** among the {data['results_scanned']} "
            f"sources this check returned for **{data['keyword']}**. It may still rank deeper "
            f"than this check can see — this isn't a confirmed absence.")
