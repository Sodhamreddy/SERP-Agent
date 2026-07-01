#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""competitor_analysis — aggregate competitor footprint, or a live drill-down. See SKILL.md."""
from __future__ import annotations

from typing import Any

import llm_insights
from skills.check_rank.skill import run as check_rank


def run(ctx: dict, keyword: str = "", domain: str = "", **_) -> dict[str, Any]:
    """No keyword → aggregate footprint across the latest scan.
    A keyword → live, fresh competitor drill-down for that keyword."""
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
            "target_position": data["position"],
            "target_found": data["found"],
            "competitors": data["competitors"],
        }
    return llm_insights.competitor_report(domain or ctx["domain"])


def render(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return data.get("error", "Competitor analysis is unavailable right now.")

    if data.get("mode") == "live":
        comps = data.get("competitors", [])
        status = (f"we rank at {data['target_position']}" if data["target_found"]
                  else "we are not ranking in the scanned results")
        if not comps:
            return f"For **{data['keyword']}**, {status}. No competitors were captured."
        top = "; ".join(f"#{c['position']} {c['title']}" for c in comps[:5])
        return f"For **{data['keyword']}**, {status}. Top competitors: {top}."

    comps = data.get("competitors", [])
    if not comps:
        return (f"No competitors were captured in the latest scan "
                f"({data.get('report', 'n/a')}).")
    scope = (f"Across {data['total_keywords']} keywords in the latest scan "
             f"({data['generated_at']}), {data['unique_competitors']} competitor "
             f"domains showed up.")
    lead = data["competitors"][:5]
    lines = "\n".join(
        f"- **{c['domain']}** — appears for {c['appearances']} keyword(s), "
        f"outranks us on {c['beats_us']}"
        + (f", best position {c['best_position']}" if c['best_position'] else "")
        for c in lead)
    note = ("" if data.get("matched_client", True)
            else "\n\n_Note: the latest scan on file may belong to another client — "
                 "run a scan for this client for an exact footprint._")
    return f"{scope} The biggest players:\n{lines}{note}"
