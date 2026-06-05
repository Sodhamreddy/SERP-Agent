#!/usr/bin/env python3
"""Gemini-powered analysis layer for the SERP dashboard."""

from __future__ import annotations

import json
import os
from collections import Counter
from dataclasses import dataclass
from typing import Any

import requests


DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def _config_value(key: str) -> str:
    """Read a value from config.json (used as a fallback when env is unset)."""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return str(data.get(key, "")).strip() if isinstance(data, dict) else ""
    except Exception:
        return ""


def _get_model() -> str:
    return (
        os.getenv("GEMINI_MODEL", "").strip()
        or _config_value("GEMINI_MODEL")
        or DEFAULT_GEMINI_MODEL
    )


def _get_endpoint(model: str) -> str:
    return "https://generativelanguage.googleapis.com/v1beta/models/" f"{model}:generateContent"


@dataclass
class GeminiConfig:
    configured: bool
    model: str
    status: str


def _get_api_key() -> str:
    return os.getenv("GEMINI_API_KEY", "").strip() or _config_value("GEMINI_API_KEY")


def _is_configured_api_key(api_key: str) -> bool:
    if not api_key:
        return False
    placeholders = {
        "your-gemini-api-key",
        "your_api_key",
        "your-api-key",
        "gemini-api-key",
        "api-key",
    }
    if api_key.lower() in placeholders:
        return False
    # Google API keys normally start with AIza. This avoids showing "connected"
    # when a placeholder or accidental text value is present.
    return api_key.startswith("AIza") and len(api_key) >= 30


def get_config() -> GeminiConfig:
    api_key = _get_api_key()
    return GeminiConfig(
        configured=_is_configured_api_key(api_key),
        model=_get_model(),
        status="configured" if _is_configured_api_key(api_key) else "not_configured",
    )


def build_local_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    ranked_rows = [r for r in rows if r.get("Position") != "Not Found"]
    page1_rows = [
        r for r in ranked_rows
        if str(r.get("Position", "")).startswith("1.")
    ]
    review_rows = [r for r in rows if r.get("Reviews") == "Yes"]
    locations = Counter(r.get("Location", "Unknown") for r in rows)

    return {
        "total_keywords": total,
        "ranked": len(ranked_rows),
        "not_found": total - len(ranked_rows),
        "page_1": len(page1_rows),
        "with_reviews": len(review_rows),
        "locations_checked": len(locations),
        "top_locations": [
            {"location": location, "keywords": count}
            for location, count in locations.most_common(8)
        ],
    }


def _compact_rows(rows: list[dict[str, Any]], limit: int = 80) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for row in rows[:limit]:
        compact.append({
            "location": row.get("Location"),
            "keyword": row.get("Keyword"),
            "position": row.get("Position"),
            "reviews": row.get("Reviews"),
            "our_url": row.get("URL Found"),
            "competitors": row.get("Competitors", [])[:5],
        })
    return compact


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        cleaned = cleaned[start:end + 1]
    return json.loads(cleaned)


def analyze_serp_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Return a dashboard-ready SERP analysis.

    Uses Gemini when GEMINI_API_KEY exists. If Gemini is unavailable, returns a
    deterministic local summary so the dashboard stays useful.
    """
    local_summary = build_local_summary(rows)
    config = get_config()

    fallback = {
        "source": "local",
        "summary": local_summary,
        "executive_summary": (
            "Free local AI mode is active. The dashboard is using SERP metrics, "
            "ranking gaps, review signals, and competitor snippets collected by the agent."
        ),
        "intent": "Local SERP visibility analysis",
        "wins": [],
        "risks": [],
        "recommendations": [
            "Review keywords marked Not Found first because they are the biggest visibility gap.",
            "Prioritize page-one opportunities where rankings already exist but reviews are missing.",
            "Study repeated competitor domains and titles to identify content patterns to improve.",
        ],
        "competitor_insights": [],
        "page_changes": [],
        "content_brief": {
            "recommended_title": "",
            "recommended_meta_description": "",
            "recommended_h1": "",
            "recommended_h2s": [],
            "content_sections": [],
        },
        "next_steps": [
            "Review missing keywords by city.",
            "Update pages for services and locations with weak rankings.",
            "Run the SERP agent again after changes to compare movement.",
        ],
    }

    api_key = _get_api_key()
    if not config.configured:
        return fallback

    prompt = {
        "role": "SERP SEO analyst",
        "task": (
            "Analyze this direct-Google SERP tracking run and return only valid JSON. "
            "Use the competitor titles/URLs to explain who is ranking, why they may be "
            "ranking, why the target domain may not be ranking as well, and what page "
            "changes should be made. Be specific and practical. Do not claim you crawled "
            "competitor pages; this is SERP-based analysis."
        ),
        "required_schema": {
            "executive_summary": "2-3 sentence plain English summary",
            "intent": "dominant search intent",
            "wins": ["short bullet"],
            "risks": ["short bullet"],
            "recommendations": ["specific SEO action"],
            "competitor_insights": [
                {
                    "competitor": "domain or title",
                    "why_they_rank": "SERP-based reason",
                    "what_to_copy_ethically": "pattern to learn from"
                }
            ],
            "page_changes": [
                {
                    "area": "meta title | meta description | H1 | H2 | content | reviews | local signals",
                    "current_issue": "what appears weak from SERP data",
                    "recommended_change": "specific change"
                }
            ],
            "content_brief": {
                "recommended_title": "SEO title for the target page",
                "recommended_meta_description": "150-160 character meta description",
                "recommended_h1": "recommended H1",
                "recommended_h2s": ["recommended H2"],
                "content_sections": ["specific section to add"]
            },
            "next_steps": ["ordered action"],
        },
        "local_summary": local_summary,
        "rows": _compact_rows(rows),
        "target_domain": "myassuredhomenursing.com",
    }

    payload = {
        "contents": [{
            "parts": [{
                "text": json.dumps(prompt, ensure_ascii=False)
            }]
        }],
        "generationConfig": {
            "temperature": 0.2,
            "responseMimeType": "application/json",
        },
    }

    try:
        response = requests.post(
            _get_endpoint(config.model),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
            },
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        analysis = _extract_json(text)
        analysis["source"] = "gemini"
        analysis["summary"] = local_summary
        analysis["model"] = config.model
        return analysis
    except Exception as exc:
        fallback["executive_summary"] = f"Gemini analysis failed: {exc}"
        fallback["error"] = str(exc)
        return fallback
