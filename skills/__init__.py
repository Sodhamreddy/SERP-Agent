#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Skill registry — the agent's capabilities as self-contained, discoverable units.

Each capability lives in ``skills/<name>/`` as two files:

    SKILL.md   YAML frontmatter + human/agent-readable card. Frontmatter fields:
                 name                 unique tool id (defaults to the folder name)
                 description          one line — what it does (shown to the planner)
                 label                progress label shown in the chat UI
                 args                 {arg: "help text"} map passed to the planner
                 triggers             phrases the deterministic fast-router matches
                 deterministic_answer true → render() text is final, skip the LLM
                 order                router/listing priority (lower runs first)
               The markdown body below the frontmatter is the "when to use" guide
               a developer (or a future LLM) reads to understand the skill.

    skill.py   run(ctx, **args) -> dict          the tool implementation (required)
               render(data) -> str               friendly answer text (optional)

``load_registry()`` discovers every skill and returns the list-of-dicts the agent
coordinator (``agent_chat.py``) consumes. Adding a capability is therefore a matter
of dropping a new folder in here — no edit to the coordinator's tool list.
"""
from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

_SKILLS_DIR = Path(__file__).resolve().parent
_REGISTRY: list[dict[str, Any]] | None = None


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md into (frontmatter dict, markdown body)."""
    if text.lstrip().startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            meta = yaml.safe_load(parts[1]) or {}
            return (meta if isinstance(meta, dict) else {}), parts[2].strip()
    return {}, text.strip()


def load_registry(force: bool = False) -> list[dict[str, Any]]:
    """Discover every skill folder and build the tool registry.

    Cached after the first call (skills are static at runtime); pass ``force=True``
    to rescan, e.g. after editing a SKILL.md during development.
    """
    global _REGISTRY
    if _REGISTRY is not None and not force:
        return _REGISTRY

    skills: list[dict[str, Any]] = []
    for sub in sorted(p for p in _SKILLS_DIR.iterdir()
                      if p.is_dir() and not p.name.startswith(("_", "."))):
        md = sub / "SKILL.md"
        if not md.exists():
            continue
        meta, doc = _parse_frontmatter(md.read_text(encoding="utf-8"))
        module = importlib.import_module(f"{__name__}.{sub.name}.skill")
        run = getattr(module, "run", None)
        if run is None:
            continue  # a card without an implementation is documentation only
        name = str(meta.get("name") or sub.name)
        skills.append({
            "name": name,
            "description": str(meta.get("description", "")),
            "label": str(meta.get("label", name)),
            "args": meta.get("args") or {},
            "triggers": meta.get("triggers") or [],
            "deterministic_answer": bool(meta.get("deterministic_answer", False)),
            "order": int(meta.get("order", 999)),
            "fn": run,
            "render": getattr(module, "render", None),
            "doc": doc,
        })

    skills.sort(key=lambda s: (s["order"], s["name"]))
    _REGISTRY = skills
    return skills


def catalog() -> list[dict[str, str]]:
    """Name + description for every skill (no callables) — safe for the UI / help."""
    return [{"name": s["name"], "description": s["description"]} for s in load_registry()]
