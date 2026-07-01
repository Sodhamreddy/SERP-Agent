#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""compare_competitors — who outranks a site for a keyword. See SKILL.md."""
from __future__ import annotations

from typing import Any

from skills.check_rank.skill import run as check_rank


def run(ctx: dict, keyword: str = "", domain: str = "", **_) -> dict[str, Any]:
    """Show who outranks a website for a keyword."""
    data = check_rank(ctx, keyword=keyword, domain=domain)
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


def render(data: dict[str, Any]) -> str:
    comps = data.get("competitors", [])
    if not comps:
        return f"No competitors captured for **{data['keyword']}**."
    top = "; ".join(f"#{c['position']} {c['title']}" for c in comps[:5])
    status = (f"We rank at {data['target_position']}" if data["target_found"]
              else "We are not ranking in the scanned results")
    return f"For **{data['keyword']}**: {status}. Top competitors: {top}."
