#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""llm_overview — AI-search visibility for the client. See SKILL.md."""
from __future__ import annotations

from typing import Any

import llm_insights
from skills.check_rank.skill import run as check_rank


def run(ctx: dict, keyword: str = "", domain: str = "", **_) -> dict[str, Any]:
    """No keyword → AI-visibility overview across the latest scan.
    A keyword → live AI-citation check for that keyword."""
    keyword = (keyword or "").strip()
    if keyword:
        data = check_rank(ctx, keyword=keyword, domain=domain)
        if not data.get("ok"):
            return data
        return {
            "ok": True,
            "mode": "live",
            "keyword": data["keyword"],
            "target_domain": data["target_domain"],
            "position": data["position"],
            "cited": data["found"],
            "platform": llm_insights._PLATFORM.get(data.get("backend"), data.get("backend")),
            "approximate": data.get("approximate", True),
            "url": data.get("url_found", ""),
        }
    return llm_insights.llm_visibility_report(domain or ctx["domain"])


def render(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("error", "The LLM overview is unavailable right now.")

    if data.get("mode") == "live":
        if data["cited"]:
            return (f"On **{data['platform']}**, **{data['keyword']}** cites us at "
                    f"position **{data['position']}** ({data['url']}).")
        return (f"On **{data['platform']}**, I didn't see {data['target_domain']} cited "
                f"for **{data['keyword']}** in this check.")

    b = data.get("buckets", {})
    avg = data.get("avg_cited_position")
    avg_txt = f", average cited position **{avg}**" if avg else ""
    lead = ""
    if data.get("also_cited"):
        names = ", ".join(c["domain"] for c in data["also_cited"][:3])
        lead = f" AI answers most often cite {names} alongside us."
    note = ("" if data.get("matched_client", True)
            else " (The latest scan on file may belong to another client.)")
    return (f"On **{data['platform']}** across {data['total_keywords']} keywords "
            f"({data['generated_at']}): we're cited for **{data['cited']}** "
            f"({data['citation_rate']}%){avg_txt} — {b.get('top3', 0)} in the top 3, "
            f"{b.get('top10', 0)} in 4–10, {b.get('not_cited', 0)} not cited.{lead}{note}")
