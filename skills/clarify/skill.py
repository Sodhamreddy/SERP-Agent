#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""clarify — ask the user for a missing ranking detail. See SKILL.md."""
from __future__ import annotations

from typing import Any


def run(ctx: dict, question: str = "", options=None, need: str = "",
        keyword: str = "", **_) -> dict[str, Any]:
    """Ask the user to clarify a missing detail (which website / which keyword)."""
    opts = [str(o) for o in (options or []) if str(o).strip()][:5]
    return {"ok": True, "action": "clarify",
            "question": (question or "Could you clarify your request?").strip(),
            "options": opts, "need": (need or "").strip(), "keyword": (keyword or "").strip()}
