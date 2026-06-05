#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Simple file-based auth for the SERP Agent (internal team accounts).

Users live in users.json as a list of {email, name, password_hash, created_at}.
Passwords are hashed with Werkzeug (never stored in plaintext). Sign-up is gated
by a shared organization code so only internal staff can register.
"""
from __future__ import annotations

import json
import os
from datetime import datetime

from werkzeug.security import check_password_hash, generate_password_hash

USERS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "users.json")


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def load_users() -> list[dict]:
    try:
        with open(USERS_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _save_users(users: list[dict]) -> None:
    with open(USERS_PATH, "w", encoding="utf-8") as fh:
        json.dump(users, fh, ensure_ascii=False, indent=2)


def user_exists(email: str) -> bool:
    email = _normalize_email(email)
    return any(u.get("email") == email for u in load_users())


def has_any_user() -> bool:
    return len(load_users()) > 0


def display_name(email: str) -> str:
    """Return a user's display name from their email (for owner labels)."""
    email = _normalize_email(email)
    for u in load_users():
        if u.get("email") == email:
            return u.get("name") or email
    return email or "—"


def create_user(name: str, email: str, password: str, company: str = "",
                 role: str = "member") -> dict:
    """Create a new user. Raises ValueError on bad input or duplicate email."""
    name = (name or "").strip()
    company = (company or "").strip()
    role = role if role in ("admin", "member") else "member"
    email = _normalize_email(email)
    if not email or "@" not in email:
        raise ValueError("Enter a valid email address.")
    if len(password or "") < 6:
        raise ValueError("Password must be at least 6 characters.")
    if user_exists(email):
        raise ValueError("An account with that email already exists.")
    user = {
        "email": email,
        "name": name or email.split("@")[0],
        "company": company,
        "role": role,
        "password_hash": generate_password_hash(password),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    users = load_users()
    users.append(user)
    _save_users(users)
    return {"email": user["email"], "name": user["name"],
            "company": user["company"], "role": user["role"]}


def verify_user(email: str, password: str) -> dict | None:
    """Return {email,name} if credentials are valid, else None."""
    email = _normalize_email(email)
    for u in load_users():
        if u.get("email") == email and check_password_hash(u.get("password_hash", ""), password or ""):
            return {"email": u["email"], "name": u.get("name", email),
                    "company": u.get("company", ""), "role": u.get("role", "member")}
    return None
