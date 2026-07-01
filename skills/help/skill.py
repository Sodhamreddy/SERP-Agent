#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""help — describe the agent's capabilities. See SKILL.md."""
from __future__ import annotations

from typing import Any


def run(ctx: dict, **_) -> dict[str, Any]:
    """Describe what the agent can do (read live from the skill registry)."""
    from skills import catalog
    return {"ok": True, "tools": catalog()}


def render(data: dict[str, Any]) -> str:
    tools = data.get("tools", [])
    return "Here's what I can do:\n" + "\n".join(
        f"- **{t['name']}** — {t['description']}" for t in tools)
