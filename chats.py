#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Per-user chat history — past conversations restored into the sidebar.

Stored in chats.json as a dict keyed by the logged-in user's email:
  { "<email>": [ {id, title, msgs:[{role, html}], created_at, updated_at}, ... ] }
Newest conversation first; both the per-user count and per-chat message count are
capped so the file stays bounded.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

CHATS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chats.json")

MAX_CHATS_PER_USER = 50   # keep the sidebar (and file) bounded
MAX_MSGS_PER_CHAT = 200   # guard against a single runaway conversation


def _load_all() -> dict:
    try:
        with open(CHATS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_all(data: dict) -> None:
    with open(CHATS_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def chats_for(email: str) -> list[dict]:
    """All of one user's conversations, newest first."""
    if not email:
        return []
    items = _load_all().get(email, [])
    return sorted(items, key=lambda c: c.get("updated_at", ""), reverse=True)


def _clean_msgs(msgs) -> list[dict]:
    out: list[dict] = []
    for m in (msgs or []):
        if not isinstance(m, dict):
            continue
        role = "agent" if m.get("role") == "agent" else "user"
        html = str(m.get("html", ""))
        if html:
            out.append({"role": role, "html": html})
    return out[-MAX_MSGS_PER_CHAT:]


def save_chat(email: str, chat: dict) -> dict | None:
    """Upsert one conversation for a user (matched by id). Returns the stored chat,
    or None if there was nothing worth saving."""
    if not email or not isinstance(chat, dict):
        return None
    cid = str(chat.get("id", "")).strip()
    msgs = _clean_msgs(chat.get("msgs"))
    if not cid or not msgs:
        return None
    title = (str(chat.get("title", "")).strip() or "New chat")[:80]

    data = _load_all()
    user_chats = data.get(email, [])
    existing = next((c for c in user_chats if c.get("id") == cid), None)
    if existing:
        existing["title"] = title
        existing["msgs"] = msgs
        existing["updated_at"] = _now()
        stored = existing
    else:
        stored = {
            "id": cid, "title": title, "msgs": msgs,
            "created_at": _now(), "updated_at": _now(),
        }
        user_chats.append(stored)
    # Keep only the most-recently-updated conversations.
    user_chats = sorted(user_chats, key=lambda c: c.get("updated_at", ""),
                        reverse=True)[:MAX_CHATS_PER_USER]
    data[email] = user_chats
    _save_all(data)
    return stored


def delete_chat(email: str, chat_id: str) -> bool:
    if not email or not chat_id:
        return False
    data = _load_all()
    user_chats = data.get(email, [])
    kept = [c for c in user_chats if c.get("id") != chat_id]
    if len(kept) == len(user_chats):
        return False
    data[email] = kept
    _save_all(data)
    return True
