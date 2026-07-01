---
name: audit_website
description: Audit a web page for SEO basics (title, meta, H1, reviews, word count). Defaults to our own site.
label: Auditing website
order: 3
deterministic_answer: true
args:
  url: optional page URL; defaults to our website
triggers:
  - audit
  - my website
  - my site
  - homepage
  - page seo
  - site seo
---

# audit_website

A fast, static on-page SEO check: fetch the page HTML and report the fundamentals.

## When to use
- "Audit my website", "check my homepage SEO", "audit https://…".

## Behaviour
- Fetches the URL (defaults to the active client's domain) with a browser-like
  User-Agent, parses static HTML only (no JS rendering).
- Reports: `<title>` + length, meta description + length, first `<h1>`, rough word
  count, reviews/testimonials signal, a US-style phone match, and HTTPS.

## Answer note
`deterministic_answer` is **true** — `render()` already lists the flagged issues
clearly, so the agent skips the LLM rewording round-trip.
