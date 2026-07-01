#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""full_scan — signal app.py to launch the 120-keyword batch. See SKILL.md."""
from __future__ import annotations

from typing import Any


def run(ctx: dict, **_) -> dict[str, Any]:
    """Signal that the heavy keyword batch should run (handled by app.py)."""
    return {
        "ok": True,
        "action": "full_scan",
        "total_keywords": len(ctx["keywords"]),
        "note": "Starting the full scan in the background.",
    }


def render(data: dict[str, Any]) -> str:
    return "Starting the full 120-keyword scan now — progress will appear in the run log."
