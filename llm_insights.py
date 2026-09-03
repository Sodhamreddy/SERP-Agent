#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shared aggregation for the Competitor Analysis and LLM Overview dashboards.

Both dashboards read the most recent scan for a target domain (the active client)
and reshape it — no new searches for the aggregate views.

The active search backend is Gemini grounding, so a scan's "Position" is the
target's position among the sources the AI answer cited — i.e. its AI-Overview
citation rank. That is exactly what the LLM Overview wants, so the same scan data
powers both the competitor footprint and the LLM-visibility summary.

Two entry points:
    competitor_report(domain)     who dominates the SERPs we compete in
    llm_visibility_report(domain) whether/where AI answers cite the target

`latest_report_for(domain)` scopes to the active client by matching the `domain`
field saved in each scan's `.analysis.json` sidecar; it falls back to the newest
scan when no sidecar matches (older runs, or a brand-new client).
"""
from __future__ import annotations

import ast
import glob
import os
import re
from collections import defaultdict
from datetime import datetime
from typing import Any
from urllib.parse import urlparse

import pandas as pd

_REPORT_GLOB = "results/* SERP *.csv"
_TOP_COMPETITORS = 15

# A backend whose positions are citations, not exact Google rank.
_APPROX_BACKENDS = {"gemini", "gemini_grounding", "google_gemini", "ollama"}


# ── parsing helpers ───────────────────────────────────────────────

def _position_value(pos: Any) -> int | None:
    """'1.4' (page.slot) → absolute 4; '2.3' → 13; 'Not Found'/blank → None."""
    s = str(pos if pos is not None else "").strip()
    if not s or s.lower() in ("not found", "nan", "none"):
        return None
    m = re.match(r"^(\d+)(?:\.(\d+))?$", s)
    if not m:
        return None
    page, slot = int(m.group(1)), int(m.group(2) or 1)
    return (page - 1) * 10 + slot


def _domain_of(url: str) -> str:
    """Bare registrable host, lower-cased, no leading www."""
    try:
        host = urlparse(url if "//" in url else "//" + url).netloc.lower()
    except Exception:  # noqa: BLE001
        host = ""
    return host[4:] if host.startswith("www.") else host


def _parse_competitors(cell: Any) -> list[dict[str, Any]]:
    """The CSV stores the competitor list as a Python-repr string; in-memory rows
    keep the real list. Accept either and never raise on a malformed cell."""
    if isinstance(cell, list):
        return [c for c in cell if isinstance(c, dict)]
    s = str(cell or "").strip()
    if not s or s.lower() in ("nan", "none", "[]"):
        return []
    try:
        val = ast.literal_eval(s)
        return [c for c in val if isinstance(c, dict)] if isinstance(val, list) else []
    except Exception:  # noqa: BLE001
        return []


# ── report discovery (scope to the active client) ────────────────

def _analysis_domain(csv_path: str) -> str:
    """The target domain saved in the scan's .analysis.json sidecar ('' if none)."""
    sidecar = csv_path[:-4] + ".analysis.json"
    try:
        import json
        with open(sidecar, encoding="utf-8") as fh:
            return str((json.load(fh) or {}).get("domain", "")).lower()
    except Exception:  # noqa: BLE001
        return ""


def _normalize(domain: str) -> str:
    d = (domain or "").strip().lower()
    d = re.sub(r"^https?://", "", d).split("/")[0]
    return d[4:] if d.startswith("www.") else d


def latest_report_for(domain: str) -> dict[str, Any] | None:
    """Most recent scan whose sidecar domain matches `domain`; else the newest
    scan overall (flagged matched=False so the UI can say it may be another client)."""
    files = sorted(glob.glob(_REPORT_GLOB), key=os.path.getmtime, reverse=True)
    if not files:
        return None
    target = _normalize(domain)
    fallback = files[0]
    for csv_path in files:
        if target and _normalize(_analysis_domain(csv_path)) == target:
            return _report_meta(csv_path, matched=True)
    return _report_meta(fallback, matched=False)


def _report_meta(csv_path: str, matched: bool) -> dict[str, Any]:
    base = os.path.basename(csv_path)
    m = re.search(r"(\d{2}-\d{2}-\d{4}) (\d{2})-(\d{2})", base)
    when = f"{m.group(1)} {m.group(2)}:{m.group(3)}" if m else base
    return {"csv_path": csv_path, "report": base, "generated_at": when,
            "matched": matched}


def _load_rows(csv_path: str) -> list[dict[str, Any]]:
    try:
        return pd.read_csv(csv_path).to_dict("records")
    except Exception:  # noqa: BLE001
        return []


def _backend() -> str:
    try:
        import websearch_agent as wa
        return wa._search_backend()
    except Exception:  # noqa: BLE001
        return "gemini"


# ── competitor footprint ──────────────────────────────────────────

def _aggregate_competitors(rows: list[dict[str, Any]], target: str) -> list[dict[str, Any]]:
    """Roll the per-keyword competitor lists up into a per-domain footprint."""
    agg: dict[str, dict[str, Any]] = defaultdict(
        lambda: {"appearances": 0, "positions": [], "beats_us": 0, "keywords": []})
    for r in rows:
        our_pos = _position_value(r.get("Position"))
        keyword = str(r.get("Keyword", ""))
        seen: set[str] = set()
        for c in _parse_competitors(r.get("Competitors")):
            dom = _domain_of(str(c.get("url", "")))
            if not dom or dom == target or dom in seen:
                continue
            seen.add(dom)
            e = agg[dom]
            e["appearances"] += 1
            cpos = _position_value(c.get("position"))
            if cpos is not None:
                e["positions"].append(cpos)
            if our_pos is None or (cpos is not None and cpos < our_pos):
                e["beats_us"] += 1
            if keyword and keyword not in e["keywords"]:
                e["keywords"].append(keyword)

    out = []
    for dom, e in agg.items():
        positions = e["positions"]
        out.append({
            "domain": dom,
            "appearances": e["appearances"],
            "beats_us": e["beats_us"],
            "best_position": min(positions) if positions else None,
            "avg_position": round(sum(positions) / len(positions), 1) if positions else None,
            "keywords": e["keywords"][:5],
        })
    out.sort(key=lambda x: (-x["appearances"], -x["beats_us"]))
    return out


def competitor_report(domain: str) -> dict[str, Any]:
    """Aggregate competitor footprint across the target's most recent scan."""
    meta = latest_report_for(domain)
    if not meta:
        return {"ok": False, "error": "No scan reports found yet. Run a full scan first."}
    rows = _load_rows(meta["csv_path"])
    if not rows:
        return {"ok": False, "error": "The most recent scan report could not be read."}

    target = _normalize(domain)
    competitors = _aggregate_competitors(rows, target)
    our_positions = [p for p in (_position_value(r.get("Position")) for r in rows) if p is not None]
    total = len(rows)
    return {
        "ok": True,
        "mode": "aggregate",
        "domain": domain,
        "report": meta["report"],
        "generated_at": meta["generated_at"],
        "matched_client": meta["matched"],
        "total_keywords": total,
        "ranked": len(our_positions),
        "not_found": total - len(our_positions),
        "our_avg_position": round(sum(our_positions) / len(our_positions), 1) if our_positions else None,
        "unique_competitors": len(competitors),
        "competitors": competitors[:_TOP_COMPETITORS],
    }


# ── LLM / AI-search visibility ────────────────────────────────────

_PLATFORM = {
    "gemini": "Google AI Overview (Gemini)",
    "gemini_grounding": "Google AI Overview (Gemini)",
    "google_gemini": "Google AI Overview (Gemini)",
    "ollama": "Local LLM (Ollama)",
    "serper": "Google (Serper)",
    "google_cse": "Google (CSE)",
    "serpapi": "Google (SerpAPI)",
}


def llm_visibility_report(domain: str) -> dict[str, Any]:
    """Reframe the most recent scan as AI-platform citation visibility for `domain`."""
    meta = latest_report_for(domain)
    if not meta:
        return {"ok": False, "error": "No scan reports found yet. Run a full scan first."}
    rows = _load_rows(meta["csv_path"])
    if not rows:
        return {"ok": False, "error": "The most recent scan report could not be read."}

    backend = _backend()
    target = _normalize(domain)
    top3 = mid = deeper = not_cited = 0
    cited_positions: list[int] = []
    per_keyword: list[dict[str, Any]] = []

    for r in rows:
        abs_pos = _position_value(r.get("Position"))
        per_keyword.append({
            "location": str(r.get("Location", "") or ""),
            "keyword": str(r.get("Keyword", "")),
            "position": str(r.get("Position", "")) if abs_pos is not None else "Not cited",
            "abs": abs_pos,
            "cited": abs_pos is not None,
            "url": str(r.get("URL Found", "") or ""),
        })
        if abs_pos is None:
            not_cited += 1
        else:
            cited_positions.append(abs_pos)
            if abs_pos <= 3:
                top3 += 1
            elif abs_pos <= 10:
                mid += 1
            else:
                deeper += 1

    total = len(rows)
    cited = len(cited_positions)
    per_keyword.sort(key=lambda x: (x["abs"] is None, x["abs"] or 0))
    competitors = _aggregate_competitors(rows, target)
    return {
        "ok": True,
        "mode": "aggregate",
        "domain": domain,
        "platform": _PLATFORM.get(backend, backend),
        "backend": backend,
        "approximate": backend in _APPROX_BACKENDS,
        "report": meta["report"],
        "generated_at": meta["generated_at"],
        "matched_client": meta["matched"],
        "total_keywords": total,
        "cited": cited,
        "citation_rate": round(cited / total * 100, 1) if total else 0.0,
        "avg_cited_position": round(sum(cited_positions) / cited, 1) if cited else None,
        "buckets": {"top3": top3, "top10": mid, "deeper": deeper, "not_cited": not_cited},
        "also_cited": competitors[:8],
        "keywords": per_keyword,
    }
