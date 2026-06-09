#!/usr/bin/env python3
"""Provider-based SERP runner coordinated by a local Ollama model.

This module deliberately avoids browser automation. Python owns the tools:
search provider calls, SERP parsing, matching, retries, and row creation.
Ollama is used as the coordinator/analysis layer when available.
"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

import requests


DEFAULT_OLLAMA_MODEL = "gemma4:e4b"
DEFAULT_OLLAMA_URL = "http://100.69.27.37:11434"
DEFAULT_SEARCH_BACKEND = "ollama"
_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def _config_value(key: str) -> str:
    """Read a value from config.json (fallback when the env var is unset)."""
    try:
        with open(_CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return str(data.get(key, "")).strip() if isinstance(data, dict) else ""
    except Exception:
        return ""
# Ollama hosted web-search API (cloud) — requires an ollama.com API key.
# This is NOT the local Ollama server; it is the hosted search endpoint.
OLLAMA_WEB_SEARCH_URL = os.getenv(
    "OLLAMA_WEB_SEARCH_URL", "https://ollama.com/api/web_search"
).rstrip("/")
MAX_RESULTS = int(os.getenv("SERP_MAX_RESULTS", "100"))
RETRY_COUNT = int(os.getenv("SERP_RETRY_COUNT", "2"))
RETRY_DELAY_SECONDS = float(os.getenv("SERP_RETRY_DELAY_SECONDS", "4"))
COMPETITOR_LIMIT = int(os.getenv("COMPETITOR_LIMIT", "5"))
REQUEST_TIMEOUT = int(os.getenv("SEARCH_REQUEST_TIMEOUT", "30"))
# Pacing: minimum seconds between search-provider requests, including retries.
# Ollama free tier allows a short burst (~16) then rate-limits, recovering after
# a quiet period. 10s (~6 req/min) stays under the sustained limit. Lower it for
# paid tiers, raise it if you still see 429s. Set 0 to disable pacing.
MIN_REQUEST_INTERVAL = float(os.getenv("SERP_MIN_REQUEST_INTERVAL", "10"))
# When a request is rate-limited (HTTP 429), wait this long before retrying so the
# provider's rate window can reset, instead of hammering with short retries.
RATE_LIMIT_COOLDOWN = float(os.getenv("SERP_RATE_LIMIT_COOLDOWN", "60"))
# Stop the batch early once this many keywords in a row all fail with 429 — the
# provider's session/quota is exhausted and continuing just wastes time.
RATE_LIMIT_GIVEUP = int(os.getenv("SERP_RATE_LIMIT_GIVEUP", "3"))


@dataclass
class SearchResult:
    position: int
    title: str
    url: str
    snippet: str = ""


def _ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL).strip() or DEFAULT_OLLAMA_MODEL


def _ollama_url() -> str:
    return (os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_URL).strip() or DEFAULT_OLLAMA_URL).rstrip("/")


def _search_backend() -> str:
    configured = os.getenv("SEARCH_BACKEND", "").strip().lower()
    if configured:
        return configured
    return DEFAULT_SEARCH_BACKEND


def _normalize_domain(value: str) -> str:
    value = value.strip().lower()
    if not value:
        return ""
    if "://" not in value:
        value = "https://" + value
    host = urlparse(value).netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    return host


def _domain_matches(url: str, target_domain: str) -> bool:
    found = _normalize_domain(url)
    target = _normalize_domain(target_domain)
    return bool(found and target and (found == target or found.endswith("." + target)))


def _position_label(position: int) -> str:
    page = (position - 1) // 10 + 1
    pos = (position - 1) % 10 + 1
    return f"{page}.{pos}"


def _call_ollama(prompt: dict[str, Any], timeout: int = 45,
                 max_tokens: int | None = None) -> dict[str, Any] | None:
    options: dict[str, Any] = {"temperature": 0.2}
    if max_tokens:
        options["num_predict"] = max_tokens
    payload = {
        "model": _ollama_model(),
        "prompt": json.dumps(prompt, ensure_ascii=False),
        "stream": False,
        "format": "json",
        "options": options,
        # Keep the model resident between turns so we don't pay cold-load latency
        # on every chat message.
        "keep_alive": "30m",
    }
    try:
        response = requests.post(f"{_ollama_url()}/api/generate", json=payload, timeout=timeout)
        response.raise_for_status()
        raw = response.json().get("response", "")
        return json.loads(raw) if raw else None
    except Exception:
        return None


def _reasoning_backend() -> str:
    """Which LLM does the 'thinking' (plan/route/synthesize/analyze)."""
    configured = os.getenv("REASONING_BACKEND", "").strip().lower()
    return configured or "gemini"


def _call_gemini_json(prompt: dict[str, Any], timeout: int = 45,
                      max_tokens: int | None = None) -> dict[str, Any] | None:
    """Reasoning call to Gemini (JSON mode, NO web grounding). Returns dict or None."""
    import gemini_agent

    api_key = gemini_agent._get_api_key()
    if not gemini_agent._is_configured_api_key(api_key):
        return None
    gen_cfg: dict[str, Any] = {"temperature": 0.2, "responseMimeType": "application/json"}
    if max_tokens:
        gen_cfg["maxOutputTokens"] = max_tokens
    payload = {
        "contents": [{"parts": [{"text": json.dumps(prompt, ensure_ascii=False)}]}],
        "generationConfig": gen_cfg,
    }
    try:
        response = requests.post(
            gemini_agent._get_endpoint(gemini_agent._get_model()),
            headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        text = response.json()["candidates"][0]["content"]["parts"][0]["text"]
        result = gemini_agent._extract_json(text)
        return result if isinstance(result, dict) else None
    except Exception:
        return None


def _call_llm(prompt: dict[str, Any], timeout: int = 45,
              max_tokens: int | None = None) -> dict[str, Any] | None:
    """Reasoning dispatcher: primary backend with automatic fallback to the other.

    Default primary is Gemini (JSON mode); if it is unavailable/quota-limited (returns
    None), fall back to the local Ollama model so the agent keeps working offline.

    `max_tokens` caps the generated output so short replies (chat synthesis) return
    quickly instead of letting the model ramble up to its default ceiling.
    """
    if _reasoning_backend() == "gemini":
        return (_call_gemini_json(prompt, timeout, max_tokens)
                or _call_ollama(prompt, timeout, max_tokens))
    return (_call_ollama(prompt, timeout, max_tokens)
            or _call_gemini_json(prompt, timeout, max_tokens))


def build_agent_plan(keywords: list[tuple[str, str]], target_domain: str) -> dict[str, Any]:
    """Ask Ollama for a lightweight execution plan, with a deterministic fallback."""
    prompt = {
        "role": "Autonomous SEO SERP Agent",
        "task": "Plan a rank-checking run. Python tools will execute search and parsing.",
        "target_domain": target_domain,
        "total_keywords": len(keywords),
        "backend": _search_backend(),
        "required_json": {
            "batch_size": "integer",
            "rate_limit_seconds": "number",
            "retry_failed_keywords": "boolean",
            "notes": ["short operational note"],
        },
    }
    plan = _call_llm(prompt, timeout=20)
    if isinstance(plan, dict):
        return plan
    return {
        "batch_size": 1,
        "rate_limit_seconds": RETRY_DELAY_SECONDS,
        "retry_failed_keywords": True,
        "notes": ["Ollama unavailable; using deterministic local execution plan."],
    }


def build_local_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    ranked_rows = [row for row in rows if row.get("Position") != "Not Found"]
    page1_rows = [
        row for row in ranked_rows
        if str(row.get("Position", "")).startswith("1.")
    ]
    review_rows = [row for row in rows if row.get("Reviews") == "Yes"]
    locations = Counter(row.get("Location", "Unknown") for row in rows)

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


def analyze_with_ollama(rows: list[dict[str, Any]], target_domain: str) -> dict[str, Any] | None:
    compact_rows = [
        {
            "keyword": row.get("Keyword"),
            "location": row.get("Location"),
            "position": row.get("Position"),
            "url_found": row.get("URL Found"),
            "competitors": row.get("Competitors", [])[:5],
        }
        for row in rows[:80]
    ]
    prompt = {
        "role": "SEO rank report analyst",
        "task": "Analyze completed SERP rank-check results and return only JSON.",
        "target_domain": target_domain,
        "rows": compact_rows,
        "required_schema": {
            "executive_summary": "2-3 sentence summary",
            "recommendations": ["specific SEO action"],
            "risks": ["ranking risk"],
            "competitor_insights": [
                {
                    "competitor": "domain or title",
                    "why_they_rank": "SERP-based reason",
                    "what_to_copy_ethically": "pattern to learn from",
                }
            ],
            "page_changes": [
                {
                    "area": "title | meta | H1 | content | local signals",
                    "current_issue": "issue from SERP data",
                    "recommended_change": "specific change",
                }
            ],
        },
    }
    return _call_llm(prompt, timeout=40, max_tokens=900)


def _serpapi_results(keyword: str) -> list[SearchResult]:
    api_key = os.getenv("SERPAPI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SERPAPI_API_KEY is required for SEARCH_BACKEND=serpapi")

    params = {
        "engine": "google",
        "q": keyword,
        "num": min(MAX_RESULTS, 100),
        "hl": os.getenv("GOOGLE_HL", "en"),
        "gl": os.getenv("GOOGLE_GL", "us"),
        "api_key": api_key,
    }
    if os.getenv("GOOGLE_LOCATION"):
        params["location"] = os.getenv("GOOGLE_LOCATION")

    response = requests.get("https://serpapi.com/search.json", params=params, timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    data = response.json()
    results: list[SearchResult] = []
    for idx, item in enumerate(data.get("organic_results", []), 1):
        link = item.get("link") or item.get("redirect_link") or ""
        if not link:
            continue
        results.append(SearchResult(
            position=int(item.get("position") or idx),
            title=item.get("title", ""),
            url=link,
            snippet=item.get("snippet", ""),
        ))
    return results[:MAX_RESULTS]


def _clean_google_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.netloc and "google." not in parsed.netloc:
        return url
    if parsed.path == "/url":
        q = parse_qs(parsed.query).get("q", [""])[0]
        return unquote(q)
    if parsed.path.startswith("/url"):
        q = parse_qs(parsed.query).get("q", [""])[0]
        return unquote(q)
    return ""


def _is_search_result_url(url: str) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return False
    blocked_hosts = (
        "google.",
        "webcache.googleusercontent.com",
        "policies.google.com",
        "support.google.com",
        "accounts.google.com",
    )
    return not any(host in parsed.netloc.lower() for host in blocked_hosts)


class _GoogleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._href_stack: list[str] = []
        self._in_h3 = False
        self._current_href = ""
        self._current_title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name: value or "" for name, value in attrs}
        if tag == "a":
            cleaned = _clean_google_url(attr.get("href", ""))
            self._href_stack.append(cleaned)
        elif tag == "h3" and self._href_stack and _is_search_result_url(self._href_stack[-1]):
            self._in_h3 = True
            self._current_href = self._href_stack[-1]
            self._current_title = []

    def handle_data(self, data: str) -> None:
        if self._in_h3:
            self._current_title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "h3" and self._in_h3:
            title = " ".join("".join(self._current_title).split())
            if title and self._current_href:
                self.results.append({"title": title, "url": self._current_href})
            self._in_h3 = False
            self._current_href = ""
            self._current_title = []
        elif tag == "a" and self._href_stack:
            self._href_stack.pop()


def _google_results(keyword: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }
    for start in range(0, MAX_RESULTS, 10):
        response = requests.get(
            "https://www.google.com/search",
            params={
                "q": keyword,
                "num": 10,
                "start": start,
                "hl": os.getenv("GOOGLE_HL", "en"),
                "gl": os.getenv("GOOGLE_GL", "us"),
                "pws": "0",
            },
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        lower_text = response.text.lower()
        if (
            "/sorry/" in response.url
            or "unusual traffic" in lower_text
            or "/httpservice/retry/enablejs" in lower_text
            or "sg_rel" in lower_text
        ):
            raise RuntimeError("Google returned an anti-bot or JavaScript challenge page")

        parser = _GoogleParser()
        parser.feed(response.text)
        if not parser.results:
            raise RuntimeError("Google returned no parseable organic links in static HTML")

        for parsed in parser.results:
            if not parsed["url"] or any(existing.url == parsed["url"] for existing in results):
                continue
            results.append(SearchResult(
                position=len(results) + 1,
                title=parsed["title"],
                url=parsed["url"],
            ))
            if len(results) >= MAX_RESULTS:
                break
        if len(results) >= MAX_RESULTS:
            break
        time.sleep(1.5)
    return results


class _DuckDuckGoParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result_link = False
        self._current_href = ""
        self._current_title: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {name: value or "" for name, value in attrs}
        classes = attr.get("class", "")
        if tag == "a" and "result__a" in classes:
            self._in_result_link = True
            self._current_href = attr.get("href", "")
            self._current_title = []

    def handle_data(self, data: str) -> None:
        if self._in_result_link:
            self._current_title.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_result_link:
            self.results.append({
                "title": " ".join("".join(self._current_title).split()),
                "url": _clean_duckduckgo_url(self._current_href),
            })
            self._in_result_link = False
            self._current_href = ""
            self._current_title = []


def _clean_duckduckgo_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        uddg = parse_qs(parsed.query).get("uddg", [""])[0]
        return unquote(uddg)
    return url


def _duckduckgo_results(keyword: str) -> list[SearchResult]:
    results: list[SearchResult] = []
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136 Safari/537.36"
        )
    }
    for offset in range(0, MAX_RESULTS, 30):
        response = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": keyword, "s": str(offset)},
            headers=headers,
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        parser = _DuckDuckGoParser()
        parser.feed(response.text)
        if not parser.results:
            break
        for parsed in parser.results:
            if not parsed["url"]:
                continue
            if any(existing.url == parsed["url"] for existing in results):
                continue
            results.append(SearchResult(
                position=len(results) + 1,
                title=parsed["title"],
                url=parsed["url"],
            ))
            if len(results) >= MAX_RESULTS:
                break
        if len(results) >= MAX_RESULTS:
            break
        time.sleep(1.0)
    return results


def _ollama_web_search_results(keyword: str) -> list[SearchResult]:
    """Query Ollama's hosted web-search API (cloud).

    Requires OLLAMA_API_KEY from an ollama.com account. Note: results are
    relevance-ranked by Ollama's search provider, NOT Google's exact organic
    SERP order — so positions are an approximation of true Google rank.
    """
    api_key = os.getenv("OLLAMA_API_KEY", "").strip() or _config_value("OLLAMA_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OLLAMA_API_KEY is required for SEARCH_BACKEND=ollama. "
            "Create a free key at https://ollama.com/settings/keys and set it in "
            'config.json or the environment: $env:OLLAMA_API_KEY="<your-key>"'
        )

    count = min(MAX_RESULTS, int(os.getenv("OLLAMA_WEBSEARCH_COUNT", "10")))
    response = requests.post(
        OLLAMA_WEB_SEARCH_URL,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={"query": keyword, "max_results": count},
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()

    results: list[SearchResult] = []
    for item in data.get("results", []):
        url = (item.get("url") or "").strip()
        if not _is_search_result_url(url):
            continue
        if any(existing.url == url for existing in results):
            continue
        results.append(SearchResult(
            position=len(results) + 1,
            title=(item.get("title") or "").strip(),
            url=url,
            snippet=(item.get("content") or "").strip()[:300],
        ))
        if len(results) >= MAX_RESULTS:
            break
    return results


def _serper_results(keyword: str, stop_domain: str = "") -> list[SearchResult]:
    """Use Serper.dev (Google Search API) for REAL Google rankings, paging to depth so
    it sees page 4, 5, 10, etc.

    Serper returns ~10 organic results per call (its `num` param is not honored beyond
    one page on most accounts), so reaching the full depth means paging. To keep rank
    checks fast we EARLY-EXIT as soon as `stop_domain` is found — a site that ranks well
    returns in one page (~3s); only a deep/absent site pays for the full pagination.

    Positions are Google's true organic order. One Serper credit per page fetched.
    """
    api_key = os.getenv("SERPER_API_KEY", "").strip() or _config_value("SERPER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "SERPER_API_KEY is required for SEARCH_BACKEND=serper. Create a free key at "
            "https://serper.dev (2,500 free searches) and put it in config.json."
        )

    # Depth from SERPER_DEPTH (env or config.json); default 100 = pages 1-10.
    depth_cfg = os.getenv("SERPER_DEPTH", "").strip() or _config_value("SERPER_DEPTH") or "100"
    depth = min(MAX_RESULTS, int(depth_cfg))
    results: list[SearchResult] = []

    def _collect(organic: list[dict]) -> bool:
        """Append organic items as absolute-ranked results. Returns True to stop paging:
        once depth is hit, OR once the target domain is found (early-exit)."""
        for item in organic:
            link = (item.get("link") or "").strip()
            if not _is_search_result_url(link):
                continue
            if any(existing.url == link for existing in results):
                continue
            results.append(SearchResult(
                position=len(results) + 1,
                title=(item.get("title") or "").strip(),
                url=link,
                snippet=(item.get("snippet") or "").strip()[:300],
            ))
            if stop_domain and _domain_matches(link, stop_domain):
                return True  # found the site we're checking — no need to page deeper
            if len(results) >= depth:
                return True
        return False

    def _fetch(page: int) -> list[dict]:
        response = requests.post(
            "https://google.serper.dev/search",
            headers={"X-API-KEY": api_key, "Content-Type": "application/json"},
            json={"q": keyword, "page": page, "num": 10,
                  "gl": os.getenv("GOOGLE_GL", "us"), "hl": os.getenv("GOOGLE_HL", "en")},
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.json().get("organic", [])

    for page in range(1, (depth + 9) // 10 + 1):
        organic = _fetch(page)
        if not organic or _collect(organic):
            break
    return results


def _google_cse_results(keyword: str) -> list[SearchResult]:
    """Use Google's Programmable Search (Custom Search JSON API) for REAL Google
    rankings, paginated up to MAX_RESULTS (default depth 50 = pages 1-5).

    Returns true organic ranking order (10 results per request, start=1,11,21,...),
    so positions are exact — unlike Gemini grounding. Free tier: 100 queries/day,
    and each page of 10 counts as one query.

    Requires a Google API key with the "Custom Search API" enabled (GOOGLE_CSE_API_KEY)
    and a Programmable Search Engine ID set to search the entire web (GOOGLE_CSE_ID).
    """
    api_key = os.getenv("GOOGLE_CSE_API_KEY", "").strip() or _config_value("GOOGLE_CSE_API_KEY")
    cx = os.getenv("GOOGLE_CSE_ID", "").strip() or _config_value("GOOGLE_CSE_ID")
    if not api_key or not cx:
        raise RuntimeError(
            "GOOGLE_CSE_API_KEY and GOOGLE_CSE_ID are required for SEARCH_BACKEND=google_cse. "
            "1) Enable 'Custom Search API' in Google Cloud and create an API key. "
            "2) Create a Programmable Search Engine (search the entire web) and copy its ID (cx). "
            "Put both in config.json."
        )

    # Depth in results; each 10 is one billable query. 50 => pages 1-5 (covers page 4).
    depth = min(MAX_RESULTS, int(os.getenv("GOOGLE_CSE_DEPTH", "50")))
    results: list[SearchResult] = []
    for start in range(1, depth + 1, 10):
        response = requests.get(
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": cx,
                "q": keyword,
                "num": 10,
                "start": start,
                "hl": os.getenv("GOOGLE_HL", "en"),
                "gl": os.getenv("GOOGLE_GL", "us"),
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        items = data.get("items", [])
        if not items:
            break
        for item in items:
            link = (item.get("link") or "").strip()
            if not _is_search_result_url(link):
                continue
            if any(existing.url == link for existing in results):
                continue
            results.append(SearchResult(
                position=len(results) + 1,
                title=(item.get("title") or "").strip(),
                url=link,
                snippet=(item.get("snippet") or "").strip()[:300],
            ))
            if len(results) >= depth:
                break
        if len(results) >= depth:
            break
    return results


def _gemini_results(keyword: str) -> list[SearchResult]:
    """Use Gemini's Google Search grounding to discover ranking domains.

    NOTE: grounding returns the sources Gemini consulted (as domain names, in
    citation order) — NOT Google's true organic SERP order. Positions are
    therefore an approximation of real rank, not exact.
    """
    import gemini_agent

    api_key = gemini_agent._get_api_key()
    if not gemini_agent._is_configured_api_key(api_key):
        raise RuntimeError(
            "GEMINI_API_KEY is required for SEARCH_BACKEND=gemini. "
            "Set a valid key (starts with AIza) in config.json or the environment."
        )

    endpoint = gemini_agent._get_endpoint(gemini_agent._get_model())
    prompt = (
        f"Search Google for: {keyword}\n"
        f"List as many organically ranking websites as you can find for this exact "
        f"query (aim for the top {MAX_RESULTS}), in ranking order with the best first. "
        "Give the domain of each ranking page. Do not include ads or map-pack listings."
    )
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        # google_search grounding is incompatible with responseMimeType=json,
        # so we intentionally do not set a JSON response format here.
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.0},
    }
    response = requests.post(
        endpoint,
        headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
        json=payload,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    data = response.json()

    try:
        chunks = data["candidates"][0]["groundingMetadata"]["groundingChunks"]
    except (KeyError, IndexError, TypeError):
        chunks = []

    results: list[SearchResult] = []
    for chunk in chunks:
        web = chunk.get("web") or {}
        domain = (web.get("title") or "").strip()
        if not domain:
            continue
        url = domain if "://" in domain else f"https://{domain}"
        if not _is_search_result_url(url):
            continue
        if any(_normalize_domain(existing.url) == _normalize_domain(url) for existing in results):
            continue
        results.append(SearchResult(
            position=len(results) + 1,
            title=domain,
            url=url,
            snippet=(web.get("uri") or "")[:300],
        ))
        if len(results) >= MAX_RESULTS:
            break
    return results


_last_request_ts = 0.0


# Paid/direct search APIs handle their own rate limiting at high volume, so we add NO
# artificial pacing between calls. Only HTML-scraping backends need a gap to avoid
# being IP-blocked by Google/DuckDuckGo.
_DIRECT_API_BACKENDS = {
    "serper", "serper_dev", "serperdev", "serpapi",
    "google_cse", "cse", "programmable", "google_programmable",
    "gemini", "gemini_grounding", "google_gemini",
    "ollama", "ollama_web", "ollama_websearch",
}


def _min_request_interval() -> float:
    """Seconds to wait between provider calls. Direct APIs need none; scraping
    backends keep MIN_REQUEST_INTERVAL so we don't get blocked."""
    if _search_backend() in _DIRECT_API_BACKENDS:
        return 0.0
    return MIN_REQUEST_INTERVAL


def _respect_rate_limit(logger: Any = None) -> None:
    """Block until at least the per-backend interval has passed since the last request.

    Gates every search-provider call (including retries) so scraping backends never
    exceed a safe rate. Direct APIs (Serper etc.) are not throttled.
    """
    global _last_request_ts
    interval = _min_request_interval()
    if interval <= 0:
        return
    wait = interval - (time.time() - _last_request_ts)
    if wait > 0:
        if logger:
            logger.info("         Rate-limit pacing: waiting %.0fs (%.1f req/min cap)",
                        wait, 60.0 / interval)
        time.sleep(wait)
    _last_request_ts = time.time()


def search_keyword(keyword: str, stop_domain: str = "") -> list[SearchResult]:
    """Run one keyword through the active backend. `stop_domain`, when given, lets
    paginating backends early-exit as soon as that domain is found (fast rank checks)."""
    backend = _search_backend()
    if backend in {"serper", "serper_dev", "serperdev"}:
        return _serper_results(keyword, stop_domain=stop_domain)
    if backend in {"google_cse", "cse", "programmable", "google_programmable"}:
        return _google_cse_results(keyword)
    if backend in {"gemini", "gemini_grounding", "google_gemini"}:
        return _gemini_results(keyword)
    if backend in {"ollama", "ollama_web", "ollama_websearch"}:
        return _ollama_web_search_results(keyword)
    if backend in {"google", "google_html"}:
        return _google_results(keyword)
    if backend == "serpapi":
        return _serpapi_results(keyword)
    if backend in {"duckduckgo", "ddg", "duckduckgo_html"}:
        return _duckduckgo_results(keyword)
    raise RuntimeError(f"Unsupported SEARCH_BACKEND: {backend}")


def parse_ranking(results: list[SearchResult], target_domain: str) -> tuple[str | None, str, list[dict[str, Any]]]:
    competitors: list[dict[str, Any]] = []
    for result in results:
        if _domain_matches(result.url, target_domain):
            return _position_label(result.position), result.url, competitors
        if len(competitors) < COMPETITOR_LIMIT:
            competitors.append({
                "position": result.position,
                "title": result.title,
                "url": result.url,
                "snippet": result.snippet,
            })
    return None, "", competitors


def run_websearch_agent(
    keywords: list[tuple[str, str]],
    target_domain: str,
    logger: Any,
) -> list[dict[str, Any]]:
    backend = _search_backend()
    plan = build_agent_plan(keywords, target_domain)
    logger.info("Agent coordinator: Ollama model=%s", _ollama_model())
    logger.info("Search backend: %s", backend)
    logger.info("Agent plan: batch_size=%s retry=%s", plan.get("batch_size"), plan.get("retry_failed_keywords"))
    interval = _min_request_interval()
    if interval > 0:
        logger.info("Rate limit: %.0fs between requests (~%.1f req/min)",
                    interval, 60.0 / interval)
    else:
        logger.info("Rate limit: none (%s is a direct API — full speed)", backend)

    rows: list[dict[str, Any]] = []
    consecutive_rate_limited = 0
    for idx, (location, keyword) in enumerate(keywords, 1):
        logger.info("[%3d/%d]  %s", idx, len(keywords), keyword)
        pos_str, found_url, competitors = None, "", []
        search_ok = False        # True only if a search call actually returned
        rate_limited = False     # True if every attempt failed with HTTP 429

        for attempt in range(1, RETRY_COUNT + 2):
            try:
                _respect_rate_limit(logger)
                # Early-exit once the client's domain is found: parse_ranking only uses
                # results up to the match, so fetching deeper pages is pure waste.
                results = search_keyword(keyword, stop_domain=target_domain)
                search_ok = True
                rate_limited = False
                logger.info("         Provider returned %d organic results", len(results))
                pos_str, found_url, competitors = parse_ranking(results, target_domain)
                if pos_str:
                    logger.info("         *** MATCH position %s  ->  %s", pos_str, found_url)
                else:
                    logger.info("         %s not found in first %d results", target_domain, MAX_RESULTS)
                break
            except Exception as exc:
                msg = str(exc)
                rate_limited = "429" in msg or "Too Many Requests" in msg
                logger.warning("         Search failed attempt %d: %s", attempt, msg[:120])
                if attempt <= RETRY_COUNT:
                    if rate_limited:
                        logger.info("         Rate limited (429) — cooling down %ds for window reset",
                                    int(RATE_LIMIT_COOLDOWN))
                        time.sleep(RATE_LIMIT_COOLDOWN)
                    else:
                        time.sleep(RETRY_DELAY_SECONDS * attempt)

        rows.append({
            "Location": location,
            "Keyword": keyword,
            "Position": pos_str if pos_str else "Not Found",
            "Reviews": "No",
            "URL Found": found_url,
            "Competitors": competitors,
            "Checked At": datetime.now().strftime("%d-%m-%Y %H:%M"),
            # _ok marks a genuine result (search succeeded). Rate-limited rows are
            # NOT ok, so batch checkpointing can re-queue them on the next run.
            "_ok": search_ok,
        })

        # Detect an exhausted session/quota: several keywords in a row that all
        # failed with 429 means continuing is pointless — stop the batch early.
        if rate_limited and not search_ok:
            consecutive_rate_limited += 1
        else:
            consecutive_rate_limited = 0
        if consecutive_rate_limited >= RATE_LIMIT_GIVEUP:
            logger.warning(
                "         %d keywords in a row hit the rate limit — provider quota looks "
                "exhausted. Stopping this batch; resume after the limit resets.",
                consecutive_rate_limited,
            )
            break

    return rows
