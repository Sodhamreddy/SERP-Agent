#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""audit_website — static on-page SEO basics for a URL. See SKILL.md."""
from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlparse

import requests

import websearch_agent as wa


class _AuditParser(HTMLParser):
    """Pull SEO basics out of a page's static HTML."""

    def __init__(self) -> None:
        super().__init__()
        self.title: list[str] = []
        self.h1: list[str] = []
        self.meta_description = ""
        self._in_title = False
        self._in_h1 = False
        self._text_chars = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "title":
            self._in_title = True
        elif tag == "h1" and not self.h1:
            self._in_h1 = True
        elif tag == "meta":
            attr = {name.lower(): (value or "") for name, value in attrs}
            if attr.get("name", "").lower() == "description":
                self.meta_description = attr.get("content", "").strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, data: str) -> None:
        stripped = data.strip()
        if self._in_title:
            self.title.append(stripped)
        if self._in_h1:
            self.h1.append(stripped)
        # Rough word count of visible text.
        if stripped:
            self._text_chars += len(stripped.split())


def run(ctx: dict, url: str = "", **_) -> dict[str, Any]:
    """Fetch a page and report SEO basics: title, meta, H1, reviews, word count."""
    url = (url or "").strip()
    if not url:
        url = f"https://{ctx['domain']}"
    if "://" not in url:
        url = "https://" + url

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/136.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=wa.REQUEST_TIMEOUT)
        resp.raise_for_status()
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"Could not fetch {url}: {exc}"}

    html = resp.text
    parser = _AuditParser()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        pass

    low = html.lower()
    # US-style phone: optional +1, 3-digit area code, then 3-4 split by space/dot/dash.
    phone_match = re.search(r"(\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]\d{3}[\s.\-]\d{4}", html)
    title = " ".join(" ".join(parser.title).split())
    h1 = " ".join(" ".join(parser.h1).split())

    return {
        "ok": True,
        "url": url,
        "title": title,
        "title_length": len(title),
        "meta_description": parser.meta_description,
        "meta_length": len(parser.meta_description),
        "h1": h1,
        "word_count": parser._text_chars,
        "has_reviews": ("review" in low or "testimonial" in low or "rating" in low),
        "phone_found": phone_match.group(0).strip() if phone_match else "",
        "https": urlparse(url).scheme == "https",
    }


def render(data: dict[str, Any]) -> str:
    flags = []
    if data["title_length"] == 0:
        flags.append("missing <title>")
    if data["meta_length"] == 0:
        flags.append("missing meta description")
    if not data["h1"]:
        flags.append("missing H1")
    if not data["has_reviews"]:
        flags.append("no visible reviews/testimonials")
    issues = ("Issues: " + ", ".join(flags)) if flags else "No major on-page issues found."
    return (f"Audit of {data['url']} — Title: \"{data['title']}\" ({data['title_length']} chars), "
            f"H1: \"{data['h1'] or '—'}\", ~{data['word_count']} words. {issues}")
