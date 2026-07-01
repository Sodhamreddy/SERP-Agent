#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""recommend — SEO recommendations for a keyword (LLM analysis layer). See SKILL.md."""
from __future__ import annotations

from typing import Any

import websearch_agent as wa
from skills.check_rank.skill import run as check_rank


def run(ctx: dict, keyword: str = "", **_) -> dict[str, Any]:
    """Generate SEO recommendations for a keyword (LLM analysis layer)."""
    last = ctx.get("last") or {}
    keyword = (keyword or "").strip() or last.get("keyword", "")
    if not keyword:
        return {"ok": False, "error": "Tell me which keyword you want recommendations for."}

    # Reuse this turn's prior rank check when it matches (saves a search), else fetch.
    rank = last if last.get("keyword") == keyword else check_rank(ctx, keyword=keyword)
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


def render(data: dict[str, Any]) -> str:
    recs = data.get("recommendations", [])
    if recs:
        return "Recommendations for **{}**:\n".format(data.get("keyword", "")) + \
               "\n".join(f"- {r}" for r in recs[:6])
    return data.get("executive_summary", "No recommendations available.")
