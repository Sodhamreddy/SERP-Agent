#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Support tickets — members raise issues, the admin is alerted in-app.

Stored in tickets.json as a list of:
  {id, user_email, user_name, client_id, subject, message,
   status: "open"|"resolved", created_at, resolved_at}
"""
from __future__ import annotations

import json
import os
from datetime import datetime

TICKETS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tickets.json")


def load_tickets() -> list[dict]:
    try:
        with open(TICKETS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save(tickets: list[dict]) -> None:
    with open(TICKETS_PATH, "w", encoding="utf-8") as fh:
        json.dump(tickets, fh, ensure_ascii=False, indent=2)


def _next_id(tickets: list[dict]) -> int:
    return (max((t.get("id", 0) for t in tickets), default=0)) + 1


def create_ticket(user_email: str, user_name: str, subject: str,
                  message: str, client_id: str = "") -> dict:
    subject = (subject or "").strip()
    message = (message or "").strip()
    if not subject and not message:
        raise ValueError("Please describe the issue.")
    tickets = load_tickets()
    ticket = {
        "id": _next_id(tickets),
        "user_email": user_email,
        "user_name": user_name,
        "client_id": client_id or "",
        "subject": subject or "(no subject)",
        "message": message,
        "status": "open",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "resolved_at": "",
    }
    tickets.append(ticket)
    _save(tickets)
    return ticket


def tickets_for(email: str, is_admin: bool) -> list[dict]:
    """Admin → all tickets (newest first); member → only their own."""
    tickets = load_tickets()
    if not is_admin:
        tickets = [t for t in tickets if t.get("user_email") == email]
    return sorted(tickets, key=lambda t: t.get("id", 0), reverse=True)


def resolve_ticket(ticket_id: int) -> bool:
    tickets = load_tickets()
    for t in tickets:
        if t.get("id") == ticket_id:
            t["status"] = "resolved"
            t["resolved_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            _save(tickets)
            return True
    return False


def open_count() -> int:
    return sum(1 for t in load_tickets() if t.get("status") == "open")
