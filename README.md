# AHNS SERP Tracker

Current implementation note: the app now runs through `run_serp_agent()` in
agentic web-search mode. The default backend does not use Playwright or a
browser.

```text
Ollama (Gemma4)
      ↓
Agent
      ↓
Search Provider / Web Search Tool
      ↓
SERP Parser
      ↓
Report
```

No SERP API key is required for the default flow. The built-in web-search tool
uses Google HTML search without Playwright. DuckDuckGo is available as a fallback.

---

## Agent Chat Mode (primary UI)

The web UI opens on an **agent chat window**. Instead of only running the whole
120-keyword batch, the client can ask for one thing at a time in plain language. A
local Ollama model reads each message, picks **one tool**, and Python runs only that
tool — streaming the agent's progress back into the chat.

**Try:**
- *"Check ranking for `home care services in Detroit, MI`"* → checks that one keyword
- *"Audit my website"* → fetches the site and reports title / H1 / meta / reviews
- *"Who outranks us for `Senior In home care in Troy, MI`?"* → competitor list
- *"List the keywords you track"* → keyword/location catalog
- *"Run the full 120-keyword scan"* → the original batch run

**Tools** (each reuses existing functions; see [`agent_chat.py`](agent_chat.py)):
`check_rank` · `compare_competitors` · `audit_website` · `recommend` ·
`list_keywords` · `full_scan` · `help`.

**Routing**: Ollama tool-calling picks the tool. If Ollama is unavailable, a
deterministic keyword-matching fallback keeps the chat working offline.

The classic **Dashboard** (stats, live run log, reports, AI recommendations) is still
available via the **Dashboard** toggle in the top-right nav.

> Automated Google SERP position monitor for **myassuredhomenursing.com**  
> 120 keywords · 30 Michigan cities · CAPTCHA-free via [valentin.app](https://valentin.app/)

---

## What It Does

Checks Google search rankings for `myassuredhomenursing.com` across **120 keywords** (30 Michigan cities × 4 keyword types) without any API key or CAPTCHA issues.

Instead of hitting Google directly, it drives [valentin.app](https://valentin.app/) — a public SERP checker that handles Google interaction — reducing per-keyword time from 30–60 s down to **3–6 s**.

Results are saved as a color-coded Excel report and displayed live in a web dashboard.

---

## Keyword Types (× 30 cities)

| # | Keyword Template |
|---|---|
| 1 | `Senior In home care in <City>, Mi` |
| 2 | `home care services in <City>, Mi` |
| 3 | `In home care services in <City>, Mi` |
| 4 | `24 hour home care in <City>, Mi` |

**Cities covered:** Birmingham · Beverly Hills · Ann Arbor · Bloomfield Hills · Clinton Township · Dearborn · Detroit · Farmington Hills · Flint · Grand Rapids · Kalamazoo · Lansing · Livonia · Madison Heights · Midland · Monroe · Mount Clemens · Northville · Novi · Oakland County · Pontiac · Rochester · Royal Oak · Saginaw · Shelby Township · Sterling Heights · Taylor · Troy · West Bloomfield · Warren · Milford Charter Township · South Lyon · Plymouth

---

## Features

- **CAPTCHA-free** — routes searches through valentin.app
- **Fast** — ~3–6 s per keyword, full run in ~10–20 min
- **Reviews detection** — detects Google star ratings per result
- **Professional Excel** — Summary sheet + per-location grouped data, color-coded rows
- **Web UI** — live log, stats cards, download & cleanup — at `http://localhost:5000`
- **Security hardened** — rate limiting, path-traversal prevention, security headers

---

## Installation

```bash
# 1. Install Python dependencies
pip install -r requirements.txt

# 2. Pull the local Ollama model
ollama pull gemma4
```

> Requires **Python 3.12+**. Python path on this machine:  
> `C:\Users\Sodham\AppData\Local\Programs\Python\Python312\python.exe`

---

## Ollama Agent Analysis

The dashboard uses Ollama as the local agent layer after each SERP run.

Default:

```powershell
$env:OLLAMA_MODEL="gemma4:e4b"
$env:OLLAMA_BASE_URL="http://100.69.27.37:11434"
python app.py
```

Default web-search backend:

```powershell
$env:SEARCH_BACKEND="google"
```

Fallback web-search backend:

```powershell
$env:SEARCH_BACKEND="duckduckgo"
```

Optional paid Google SERP provider:

```powershell
$env:SEARCH_BACKEND="serpapi"
$env:SERPAPI_API_KEY="your-serpapi-key"
```

Without Ollama running, the dashboard still works and shows local SERP metrics.

---

## Usage

### Web UI (recommended)

```bat
start_ui.bat
```

Opens `http://localhost:5000` automatically. Click **Run Now** to start.

### Command Line

```bat
run.bat
```

---

## Time Estimates

| Mode | Keywords | Time |
|---|---|---|
| Test (Birmingham only — edit KEYWORDS) | 4 | ~1 min |
| Full run (all 30 cities) | 120 | ~10–20 min |
| Per keyword | 1 | ~3–6 s |

---

## Output

Files are saved to `results/`:

```
AHNS SERP DD-MM-YYYY HH-MM-SS.xlsx
AHNS SERP DD-MM-YYYY HH-MM-SS.csv
```

### Excel Structure

| Sheet | Contents |
|---|---|
| `Summary` | Totals per city: ranked, page-1 count, has-reviews count |
| `SERP Report` | Full data grouped by city, color-coded |

### Column Reference

| Column | Example | Notes |
|---|---|---|
| S.No | `1` | Row index within city group |
| Keyword | `Senior In home care in Troy, Mi` | Full search query |
| Position | `1.3` | Page 1, result 3 |
| Reviews | `Yes` | Google star rating detected |
| Checked At | `15-04-2026 14:32` | Local timestamp |

**Row colors:** Green = has reviews · Red = no reviews

---

## Security

| Feature | Detail |
|---|---|
| Rate limiting | `/run` blocked for 60 s after each run |
| Path traversal | `/download` validates filename with strict regex |
| Security headers | `X-Content-Type-Options`, `X-Frame-Options`, `X-XSS-Protection` |
| Local only | Server binds to `127.0.0.1` — not exposed externally |

---

## File Structure

```
SERP-Agent/
├── serp_agent.py        # Core agent — keyword catalog, Excel output
├── websearch_agent.py   # Search providers, SERP parsing, Ollama analysis
├── agent_chat.py        # Agent chat layer — tool registry, router, turn runner
├── app.py               # Flask web server (chat + dashboard routes)
├── templates/
│   └── index.html       # Web UI (chat-first, dashboard secondary)
├── start_ui.bat         # Launch web UI
├── run.bat              # Launch CLI
├── requirements.txt     # Python dependencies
├── generate_docs.py     # Generates PDF documentation
├── README.md            # This file
└── results/             # Auto-created, stores .xlsx and .csv reports
```

---

## Generate PDF Documentation

```bash
pip install fpdf2
python generate_docs.py
```

Outputs `AHNS_SERP_Agent_Documentation.pdf` in the project folder.

---

## Troubleshooting

**valentin.app form not found** — The site may have updated its layout. Check that `https://valentin.app/` loads in your browser, then re-run.

**0 results extracted** — The page may not have fully loaded. The agent retries automatically; if persistent, increase `DELAY_MIN`/`DELAY_MAX` in `serp_agent.py`.

**Port 5000 in use** — Change `port=5000` to `port=5001` in `app.py`.

**Excel file locked** — Close the file in Excel before running again.
# SERP-Agent
