#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""list_keywords — the active client's tracked-keyword catalog. See SKILL.md."""
from __future__ import annotations

from typing import Any


def run(ctx: dict, **_) -> dict[str, Any]:
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


def render(data: dict[str, Any]) -> str:
    return (f"I track **{data['total_keywords']} keywords** across "
            f"**{data['total_locations']} locations**. Examples: "
            + ", ".join(data["sample_keywords"][:5]) + " …")
