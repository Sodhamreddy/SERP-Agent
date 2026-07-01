#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask Web UI for AHNS SERP Tracker
Run  : python app.py  (or double-click start_ui.bat)
Open : http://localhost:5000
"""

import os
import re
import sys
import glob
import json
import queue
import logging
import threading
from datetime import datetime

import pandas as pd
from flask import (
    Flask, render_template, Response,
    jsonify, send_from_directory, abort,
    request, session, redirect, url_for,
)

# Handle PyInstaller bundle path
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")


def _load_local_config() -> dict:
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_local_config(data: dict) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)


_local_config = _load_local_config()
if _local_config.get("OLLAMA_MODEL") and not os.getenv("OLLAMA_MODEL"):
    os.environ["OLLAMA_MODEL"] = str(_local_config["OLLAMA_MODEL"]).strip()
if _local_config.get("OLLAMA_BASE_URL") and not os.getenv("OLLAMA_BASE_URL"):
    os.environ["OLLAMA_BASE_URL"] = str(_local_config["OLLAMA_BASE_URL"]).strip()
# Search backend for rank checks (e.g. "gemini" for Google-Search grounding, which
# returns more than the 10-result cap of the Ollama web-search API).
if _local_config.get("SEARCH_BACKEND") and not os.getenv("SEARCH_BACKEND"):
    os.environ["SEARCH_BACKEND"] = str(_local_config["SEARCH_BACKEND"]).strip()
# Reasoning backend: which LLM plans/answers (default "gemini", Ollama is the fallback).
if _local_config.get("REASONING_BACKEND") and not os.getenv("REASONING_BACKEND"):
    os.environ["REASONING_BACKEND"] = str(_local_config["REASONING_BACKEND"]).strip()
# Auto-upgrade to Google Programmable Search once its credentials are configured.
# It returns REAL Google rankings up to 100 results (sees page 4+), unlike Gemini
# grounding (~5 results). The moment both keys are present in config.json, prefer it.
_cse_key = str(_local_config.get("GOOGLE_CSE_API_KEY", "")).strip()
_cse_id = str(_local_config.get("GOOGLE_CSE_ID", "")).strip()
_serper_key = str(_local_config.get("SERPER_API_KEY", "")).strip()
# Serper.dev needs only one key and returns the real top 100 in one call — prefer it
# first, then Google CSE, otherwise stay on whatever was configured (Gemini).
if _serper_key and os.getenv("SEARCH_BACKEND", "").strip().lower() in ("", "gemini"):
    os.environ["SEARCH_BACKEND"] = "serper"
elif _cse_key and _cse_id and os.getenv("SEARCH_BACKEND", "").strip().lower() in ("", "gemini"):
    os.environ["SEARCH_BACKEND"] = "google_cse"

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))

# ── Auth config ───────────────────────────────────────────────
# Stable SECRET_KEY so sessions survive restarts. Generate + persist on first run.
_secret = str(_local_config.get("SECRET_KEY", "")).strip() or os.getenv("SECRET_KEY", "").strip()
if not _secret:
    _secret = os.urandom(24).hex()
    _local_config["SECRET_KEY"] = _secret
    _save_local_config(_local_config)
app.secret_key = _secret
app.config["TEMPLATES_AUTO_RELOAD"] = True   # pick up template edits without a restart
app.jinja_env.auto_reload = True
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"]   = bool(_local_config.get("COOKIE_SECURE", False))

# Behind a reverse proxy (nginx) honor X-Forwarded-* so HTTPS redirects + secure
# cookies work correctly. Harmless in local dev (no proxy headers present).
try:
    from werkzeug.middleware.proxy_fix import ProxyFix
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)
except Exception:
    pass

# Shared organization code required to sign up (keeps registration internal).
SIGNUP_CODE = str(_local_config.get("SIGNUP_CODE", "ahns-team")).strip()
# Separate admin code: signing up with this grants the admin role (sees all projects).
ADMIN_CODE  = str(_local_config.get("ADMIN_CODE", "ahns-admin")).strip()

# Paths reachable without a session; API prefixes that should get 401 (not redirect).
_PUBLIC_PATHS = {"/login", "/signup", "/favicon.ico"}
_API_PREFIXES = ("/chat", "/clients", "/run", "/status", "/stream", "/keywords",
                 "/config", "/settings", "/cleanup", "/download", "/me", "/tickets",
                 "/reports", "/suggest", "/preview", "/analysis")

# ── Rate-limit state ──────────────────────────────────────────
_last_run_time: float = 0.0
RUN_COOLDOWN_SECONDS  = 60          # minimum gap between /run calls

# ── Global agent state ────────────────────────────────────────
_agent_running = False
_agent_lock    = threading.Lock()
_log_queue: queue.Queue = queue.Queue()
_last_rows: list        = []
_last_excel: str        = ""
_last_agent_report: dict = {}
_progress               = {"current": 0, "total": 0}


# ── SSE log handler ───────────────────────────────────────────
class _SSEHandler(logging.Handler):
    def emit(self, record):
        _log_queue.put(json.dumps({
            "t": datetime.now().strftime("%H:%M:%S"),
            "m": record.getMessage(),
        }))

_sse_handler = _SSEHandler()
_sse_handler.setFormatter(logging.Formatter("%(message)s"))


# ── Security headers ──────────────────────────────────────────
@app.after_request
def add_security_headers(resp):
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"]        = "SAMEORIGIN"
    resp.headers["X-XSS-Protection"]       = "1; mode=block"
    resp.headers["Referrer-Policy"]        = "strict-origin-when-cross-origin"
    # Never cache the HTML page so UI changes always show on a normal refresh.
    if resp.mimetype == "text/html":
        resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        resp.headers["Pragma"]        = "no-cache"
    return resp


# ── Auth guard: everything requires login except the public paths ──
@app.before_request
def _require_login():
    path = request.path
    if path.startswith("/static") or path in _PUBLIC_PATHS:
        return None
    if session.get("user"):
        return None
    # Not authenticated: 401 for API/XHR (UI redirects), redirect for page loads.
    if path.startswith(_API_PREFIXES):
        return jsonify({"ok": False, "auth": False, "msg": "Please sign in."}), 401
    return redirect(url_for("login_page"))


# ── Login throttle (per IP) ──
_login_attempts: dict = {}
LOGIN_MAX_ATTEMPTS = 8
LOGIN_WINDOW_SECONDS = 300


def _throttled(ip: str) -> bool:
    import time
    now = time.time()
    hits = [t for t in _login_attempts.get(ip, []) if now - t < LOGIN_WINDOW_SECONDS]
    _login_attempts[ip] = hits
    return len(hits) >= LOGIN_MAX_ATTEMPTS


def _record_attempt(ip: str) -> None:
    import time
    _login_attempts.setdefault(ip, []).append(time.time())


@app.route("/login", methods=["GET", "POST"])
def login_page():
    import auth
    if request.method == "GET":
        if session.get("user"):
            return redirect(url_for("index"))
        return render_template("login.html")

    ip = request.remote_addr or "?"
    if _throttled(ip):
        return render_template("login.html", error="Too many attempts. Please wait a few minutes.")
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    user = auth.verify_user(email, password)
    if not user:
        _record_attempt(ip)
        return render_template("login.html", error="Invalid email or password.", email=email)
    session["user"] = user
    return redirect(url_for("index"))


@app.route("/signup", methods=["GET", "POST"])
def signup_page():
    import auth
    if request.method == "GET":
        if session.get("user"):
            return redirect(url_for("index"))
        return render_template("signup.html")

    import serp_agent as sa
    name = request.form.get("name", "")
    email = request.form.get("email", "")
    password = request.form.get("password", "")
    company = request.form.get("company", "")
    code = request.form.get("code", "").strip()
    # Admin code → admin role; team code → member; anything else → rejected.
    if code == ADMIN_CODE:
        role = "admin"
    elif code == SIGNUP_CODE:
        role = "member"
    else:
        return render_template("signup.html", error="Invalid organization code.",
                               name=name, email=email, company=company)
    try:
        user = auth.create_user(name, email, password, company, role)
    except ValueError as exc:
        return render_template("signup.html", error=str(exc), name=name, email=email, company=company)
    # The first admin claims any ownerless (legacy) projects, e.g. the seeded AHNS client.
    if role == "admin":
        sa.assign_ownerless_to(user["email"])
    session["user"] = user
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/suggest")
def suggest():
    """Google query autocomplete (server-side proxy to avoid CORS). Returns suggestions."""
    import requests
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify({"suggestions": []})
    try:
        r = requests.get(
            "https://suggestqueries.google.com/complete/search",
            params={"client": "firefox", "q": q, "hl": os.getenv("GOOGLE_HL", "en")},
            timeout=5,
        )
        r.raise_for_status()
        data = r.json()  # ["query", ["suggestion1", "suggestion2", ...]]
        sugg = data[1] if isinstance(data, list) and len(data) > 1 and isinstance(data[1], list) else []
        return jsonify({"suggestions": [str(s) for s in sugg[:8]]})
    except Exception:
        return jsonify({"suggestions": []})


@app.route("/reports")
def list_reports():
    """Filenames of generated reports (newest first) for the sidebar list.
    Also says which reports have a saved AI analysis alongside them."""
    have_analysis = {os.path.basename(f) for f in glob.glob("results/AHNS SERP *.analysis.json")}
    files = sorted([os.path.basename(f) for f in glob.glob("results/AHNS SERP *.xlsx")],
                   reverse=True)
    analyses = [f for f in files if f.replace(".xlsx", ".analysis.json") in have_analysis]
    return jsonify({"reports": files, "analyses": analyses})


@app.route("/competitors")
def competitor_analysis_route():
    """Aggregate competitor footprint across the active client's most recent scan."""
    import llm_insights
    active = _active_client()
    if not active:
        return jsonify({"ok": False, "error": "No active client."}), 400
    return jsonify(llm_insights.competitor_report(active["domain"]))


@app.route("/llm-overview")
def llm_overview_route():
    """AI-search (LLM) visibility for the active client, from the most recent scan."""
    import llm_insights
    active = _active_client()
    if not active:
        return jsonify({"ok": False, "error": "No active client."}), 400
    return jsonify(llm_insights.llm_visibility_report(active["domain"]))


@app.route("/ai-platforms/status")
def ai_platforms_status_route():
    """Which AI platforms are wired up (Google AI Overview live; others need keys)."""
    import ai_platforms
    return jsonify({"platforms": ai_platforms.platform_status()})


@app.route("/ai-platforms/check")
def ai_platforms_check_route():
    """Live, per-platform citation position for one keyword across AI platforms."""
    import ai_platforms
    active = _active_client()
    if not active:
        return jsonify({"ok": False, "error": "No active client."}), 400
    keyword = (request.args.get("keyword") or "").strip()
    return jsonify(ai_platforms.check_keyword(keyword, active["domain"]))


@app.route("/me")
def me():
    import tickets
    user = session.get("user") or {}
    out = dict(user)
    # Admins get the count of open tickets for the in-app alert badge.
    out["open_tickets"] = tickets.open_count() if user.get("role") == "admin" else 0
    return jsonify(out)


@app.route("/tickets", methods=["GET", "POST"])
def tickets_route():
    import tickets
    user = _current_user()
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        active = _active_client()
        try:
            t = tickets.create_ticket(
                user.get("email", ""), user.get("name", ""),
                data.get("subject", ""), data.get("message", ""),
                client_id=(active["id"] if active else ""),
            )
        except ValueError as exc:
            return jsonify({"ok": False, "msg": str(exc)})
        return jsonify({"ok": True, "id": t["id"], "msg": "Ticket submitted — an admin has been notified."})

    # GET → admin sees all, member sees own
    is_admin = user.get("role") == "admin"
    return jsonify({"is_admin": is_admin,
                    "tickets": tickets.tickets_for(user.get("email", ""), is_admin)})


@app.route("/tickets/resolve", methods=["POST"])
def resolve_ticket_route():
    import tickets
    if _current_user().get("role") != "admin":
        return jsonify({"ok": False, "msg": "Admins only."}), 403
    tid = int((request.get_json(silent=True) or {}).get("id", 0))
    ok = tickets.resolve_ticket(tid)
    return jsonify({"ok": ok, "open_tickets": tickets.open_count()})


@app.route("/chats", methods=["GET", "POST"])
def chats_route():
    """Per-user chat history: GET lists the user's saved conversations (newest
    first); POST upserts one conversation {id, title, msgs:[{role, html}]}."""
    import chats
    email = _current_user().get("email", "")
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        saved = chats.save_chat(email, data.get("chat") or data)
        return jsonify({"ok": bool(saved), "chat": saved})
    return jsonify({"chats": chats.chats_for(email)})


@app.route("/chats/delete", methods=["POST"])
def chats_delete_route():
    import chats
    email = _current_user().get("email", "")
    cid = str((request.get_json(silent=True) or {}).get("id", "")).strip()
    return jsonify({"ok": chats.delete_chat(email, cid)})


# ── Filename validation ───────────────────────────────────────
_VALID_REPORT = re.compile(r'^AHNS SERP [\d]{2}-[\d]{2}-[\d]{4} [\d]{2}-[\d]{2}-[\d]{2}\.(xlsx|csv)$')

def _validate_report_filename(filename: str) -> bool:
    """Accept only exact AHNS SERP ... .xlsx filenames — prevents path traversal."""
    safe = os.path.basename(filename)
    return bool(_VALID_REPORT.match(safe))


# ── Routes ────────────────────────────────────────────────────

@app.route("/favicon.ico")
def favicon():
    return "", 204   # No content — suppresses browser 404 noise


@app.route("/")
def index():
    try:
        reports = sorted(
            [os.path.basename(f) for f in glob.glob("results/AHNS SERP *.xlsx")],
            reverse=True
        )
        return render_template("index.html", reports=reports)
    except Exception as e:
        return f"<pre>ERROR: {e}\nBASE_DIR: {BASE_DIR}\nCWD: {os.getcwd()}</pre>", 500


@app.route("/run", methods=["POST"])
def run():
    import time
    # ── Rate limiting ──
    now = time.time()
    if now - _last_run_time < RUN_COOLDOWN_SECONDS:
        remaining = int(RUN_COOLDOWN_SECONDS - (now - _last_run_time))
        return jsonify({"ok": False,
                        "msg": f"Please wait {remaining}s before starting another run."})
    active = _active_client()
    if not active:
        return jsonify({"ok": False, "msg": "No active project to scan. Add a client first."})
    kws = [(l, k) for l, k in active.get("keywords", [])]
    # Optional limit: run only the first N keywords (10/30/50/100…); 0/absent = all.
    limit = int((request.get_json(silent=True) or {}).get("limit") or 0)
    if limit > 0:
        kws = kws[:limit]
    if not kws:
        return jsonify({"ok": False, "msg": "This project has no keywords yet."})
    started = _start_full_scan(kws, active["domain"])
    if not started:
        return jsonify({"ok": False, "msg": "Agent is already running."})
    return jsonify({"ok": True, "count": len(kws)})


@app.route("/stream")
def stream():
    """Server-Sent Events — streams live log lines to the browser."""
    def generate():
        while True:
            try:
                data = _log_queue.get(timeout=25)
                yield f"data: {data}\n\n"
            except queue.Empty:
                yield 'data: {"ping":1}\n\n'
    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/status")
def status():
    ollama_model = os.getenv("OLLAMA_MODEL", "gemma4:e4b").strip() or "gemma4:e4b"
    ollama_url = os.getenv("OLLAMA_BASE_URL", "http://100.69.27.37:11434").strip()
    reasoning = os.getenv("REASONING_BACKEND", "gemini").strip() or "gemini"
    search = os.getenv("SEARCH_BACKEND", "gemini").strip() or "gemini"
    return jsonify({
        "running":    _agent_running,
        "current":    _progress["current"],
        "total":      _progress["total"],
        "last_excel": os.path.basename(_last_excel) if _last_excel else "",
        "rows":       _last_rows,
        "agent_report": _last_agent_report,
        "engine": {
            "reasoning": reasoning,          # plans/answers (Gemini primary)
            "search": search,                # finds rankings (Gemini grounding)
            "fallback_model": ollama_model,  # Ollama model used if Gemini is down
        },
        "ollama": {
            "configured": True,
            "model": ollama_model,
            "base_url": ollama_url,
            "status": "configured",
        },
    })


def _current_user() -> dict:
    return session.get("user") or {}


def _active_client():
    """The session user's active client (validated against their access). None if they have none."""
    import serp_agent as sa
    accessible = sa.clients_for(_current_user())
    if not accessible:
        return None
    cid = session.get("active_client")
    chosen = next((c for c in accessible if c["id"] == cid), None)
    if not chosen:
        chosen = accessible[0]
        session["active_client"] = chosen["id"]
    return chosen


@app.route("/clients")
def list_clients():
    import serp_agent as sa
    import auth
    user = _current_user()
    active = _active_client()
    return jsonify({
        "active": active["id"] if active else None,
        "role": user.get("role", "member"),
        "clients": [
            {"id": c["id"], "name": c["name"], "domain": c["domain"],
             "keyword_count": len(c.get("keywords", [])),
             "keywords": [[l, k] for l, k in c.get("keywords", [])],
             "owner": c.get("owner", ""),
             "owner_name": (auth.display_name(c["owner"]) if c.get("owner") else "Unassigned")}
            for c in sa.clients_for(user)
        ],
    })


@app.route("/clients/active", methods=["POST"])
def set_active_client_route():
    import serp_agent as sa
    cid = str((request.get_json(silent=True) or {}).get("id", "")).strip()
    client = sa.get_client(cid)
    if not sa.can_access(_current_user(), client):
        return jsonify({"ok": False, "msg": "Project not found."}), 404
    session["active_client"] = cid
    return jsonify({"ok": True, "active": cid, "target_domain": client["domain"],
                    "keyword_count": len(client.get("keywords", [])),
                    "msg": f"Switched to {client['domain']}"})


@app.route("/clients", methods=["POST"])
def upsert_client_route():
    """Create or update a client (owned by the caller). JSON {id?,name,domain,text|keywords} or CSV."""
    import csv
    import io
    import serp_agent as sa

    if _agent_running:
        return jsonify({"ok": False, "msg": "Cannot edit clients while a scan is running."})
    user = _current_user()

    if request.files.get("file"):
        name = request.form.get("name", "").strip()
        domain = request.form.get("domain", "").strip()
        cid = request.form.get("id", "").strip() or None
        raw = request.files["file"].read().decode("utf-8-sig", errors="replace")
        pairs = []
        for row in csv.reader(io.StringIO(raw)):
            if not row:
                continue
            loc, kw = ("", row[0]) if len(row) == 1 else (row[0], row[1])
            kw = (kw or "").strip()
            if kw and kw.lower() not in ("keyword", "keywords"):
                pairs.append([(loc or "").strip(), kw])
    else:
        data = request.get_json(silent=True) or {}
        name = str(data.get("name", "")).strip()
        domain = str(data.get("domain", "")).strip()
        cid = str(data.get("id", "")).strip() or None
        pairs = data["keywords"] if isinstance(data.get("keywords"), list) \
            else _parse_keyword_text(str(data.get("text", "")))

    if not domain:
        return jsonify({"ok": False, "msg": "Domain is required."})
    # Editing an existing client requires access to it.
    if cid and not sa.can_access(user, sa.get_client(cid)):
        return jsonify({"ok": False, "msg": "Project not found."}), 404
    try:
        client = sa.upsert_client(user.get("email", ""), name, domain, pairs, client_id=cid)
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "msg": str(exc)})
    session["active_client"] = client["id"]
    return jsonify({"ok": True, "id": client["id"], "name": client["name"],
                    "target_domain": client["domain"], "keyword_count": len(client.get("keywords", [])),
                    "msg": f"Saved {client['name']} ({len(client.get('keywords', []))} keywords)."})


@app.route("/clients/delete", methods=["POST"])
def delete_client_route():
    import serp_agent as sa
    if _agent_running:
        return jsonify({"ok": False, "msg": "Cannot delete a client while a scan is running."})
    cid = str((request.get_json(silent=True) or {}).get("id", "")).strip()
    client = sa.get_client(cid)
    if not sa.can_access(_current_user(), client):
        return jsonify({"ok": False, "msg": "Project not found."}), 404
    sa.delete_client(cid)
    if session.get("active_client") == cid:
        session.pop("active_client", None)
    active = _active_client()
    return jsonify({"ok": True, "active": active["id"] if active else None,
                    "msg": "Project deleted."})


@app.route("/settings")
def get_settings():
    """Active client's target domain + keyword list (for the Settings UI)."""
    active = _active_client()
    if not active:
        return jsonify({"target_domain": "", "keyword_count": 0, "keywords": []})
    return jsonify({
        "target_domain": active["domain"],
        "keyword_count": len(active.get("keywords", [])),
        "keywords": [[loc, kw] for loc, kw in active.get("keywords", [])],
    })


@app.route("/config/target", methods=["POST"])
def configure_target():
    """Set the active client's target domain."""
    import serp_agent as sa
    active = _active_client()
    if not active:
        return jsonify({"ok": False, "msg": "No active client."})
    domain = str((request.get_json(silent=True) or {}).get("domain", "")).strip()
    if not domain:
        return jsonify({"ok": False, "msg": "Please enter a domain."})
    try:
        client = sa.upsert_client(_current_user().get("email", ""), active["name"], domain,
                                  active.get("keywords", []), client_id=active["id"])
    except Exception as exc:  # noqa: BLE001
        return jsonify({"ok": False, "msg": f"Invalid domain: {exc}"})
    return jsonify({"ok": True, "target_domain": client["domain"],
                    "msg": f"Now tracking {client['domain']}"})


def _parse_keyword_text(text: str) -> list[tuple[str, str]]:
    """Parse 'Location | Keyword' lines (keyword-only lines allowed)."""
    pairs: list[tuple[str, str]] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" in line:
            loc, kw = line.split("|", 1)
        else:
            loc, kw = "", line
        kw = kw.strip()
        if kw:
            pairs.append((loc.strip(), kw))
    return pairs


@app.route("/keywords", methods=["POST"])
def set_keywords():
    """Replace the keyword list. Accepts JSON list, raw text, or an uploaded CSV."""
    import csv
    import io
    import serp_agent as sa

    if _agent_running:
        return jsonify({"ok": False, "msg": "Cannot edit keywords while a scan is running."})

    pairs: list[tuple[str, str]] = []
    # 1) Uploaded CSV file (2 columns: Location, Keyword — proper CSV parsing)
    if request.files.get("file"):
        raw = request.files["file"].read().decode("utf-8-sig", errors="replace")
        for row in csv.reader(io.StringIO(raw)):
            if not row:
                continue
            if len(row) == 1:
                loc, kw = "", row[0]
            else:
                loc, kw = row[0], row[1]
            kw = (kw or "").strip()
            # Skip a header row like "Location,Keyword".
            if kw and kw.lower() not in ("keyword", "keywords"):
                pairs.append(((loc or "").strip(), kw))
    else:
        data = request.get_json(silent=True) or {}
        if isinstance(data.get("keywords"), list):
            for item in data["keywords"]:
                if isinstance(item, (list, tuple)) and len(item) >= 2:
                    pairs.append((str(item[0]).strip(), str(item[1]).strip()))
                elif isinstance(item, str) and item.strip():
                    pairs.append(("", item.strip()))
        elif isinstance(data.get("text"), str):
            pairs = _parse_keyword_text(data["text"])

    pairs = [(l, k) for l, k in pairs if k]
    if not pairs:
        return jsonify({"ok": False, "msg": "No valid keywords found."})
    active = _active_client()
    if not active:
        return jsonify({"ok": False, "msg": "No active client."})
    sa.upsert_client(_current_user().get("email", ""), active["name"], active["domain"],
                     pairs, client_id=active["id"])
    return jsonify({"ok": True, "keyword_count": len(pairs),
                    "msg": f"Saved {len(pairs)} keyword(s)."})


@app.route("/chat/tools")
def chat_tools():
    """Tool catalog for the chat UI (used to render suggested-prompt chips)."""
    import agent_chat
    return jsonify({"tools": agent_chat.tool_catalog()})


def _start_full_scan(keywords, domain) -> bool:
    """Kick off the heavy keyword batch for the given client. One scan at a time.

    Returns True if the scan was started, False if one is already running.
    """
    global _agent_running, _last_run_time
    import time
    with _agent_lock:
        if _agent_running:
            return False
        _agent_running = True
        _last_run_time = time.time()
    while not _log_queue.empty():
        try:
            _log_queue.get_nowait()
        except Exception:
            break
    threading.Thread(target=_run_agent, args=(keywords, domain), daemon=True).start()
    return True


_GENERIC_TOKENS = {"the", "and", "for", "inc", "llc", "ltd", "co", "home", "care",
                   "services", "service", "hour", "hours", "in", "of", "group",
                   "agency", "health", "company", "solutions"}


def _detect_client(message: str, user: dict):
    """Confidently match a message to one of the user's clients (by name/domain).

    Conservative: only matches on the full name, the domain, the domain root, or a
    distinctive (non-generic, 4+ char) name token — never on generic words like
    'home care'. Returns the client dict or None.
    """
    import re
    import serp_agent as sa
    msg = (message or "").lower()
    for c in sa.clients_for(user):
        name = (c.get("name") or "").lower().strip()
        dom = (c.get("domain") or "").lower().strip()
        root = dom.split(".")[0] if dom else ""
        if name and name in msg:
            return c
        if dom and dom in msg:
            return c
        if root and len(root) >= 4 and root in msg:
            return c
        toks = [t for t in re.split(r"[^a-z0-9]+", name) if len(t) >= 4 and t not in _GENERIC_TOKENS]
        if any(t in msg for t in toks):
            return c
    return None


@app.route("/chat", methods=["POST"])
def chat():
    """Agent-mode chat. Streams step events (SSE) as the agent picks and runs a tool."""
    import agent_chat

    data = request.get_json(silent=True) or {}
    message = str(data.get("message", "")).strip()
    # Per-question targeting: if the message names a project, answer for THAT project
    # (without changing the active client); otherwise use the active client.
    active = _active_client()
    detected = _detect_client(message, _current_user())
    used = detected or active
    if not used:
        def no_client():
            yield f"data: {json.dumps({'step': 'answer', 'text': 'You have no projects yet. Click “+ New” to onboard your first client.'})}\n\n"
            yield f"data: {json.dumps({'step': 'done'})}\n\n"
        return Response(no_client(), mimetype="text/event-stream",
                        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
    ctx = agent_chat.make_ctx(used["domain"], used.get("keywords", []))
    scan_kw = [(l, k) for l, k in used.get("keywords", [])]
    scan_domain = used["domain"]
    # Flag when the question targeted a different project than the active one.
    other = bool(detected and (not active or detected["id"] != active["id"]))
    client_evt = {"step": "client", "name": used["name"], "domain": used["domain"], "other": other}

    def generate():
        try:
            yield f"data: {json.dumps(client_evt, ensure_ascii=False)}\n\n"
            for event in agent_chat.run_turn(message, ctx):
                # The full_scan tool only signals intent — actually launch the batch here.
                if event.get("step") == "action" and event.get("action") == "full_scan":
                    started = _start_full_scan(scan_kw, scan_domain)
                    event = {"step": "action", "action": "full_scan", "started": started}
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as exc:  # noqa: BLE001
            yield f"data: {json.dumps({'step': 'error', 'text': str(exc)})}\n\n"
            yield f"data: {json.dumps({'step': 'done'})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/download/<path:filename>")
def download(filename):
    safe = os.path.basename(filename)
    if not _validate_report_filename(safe):
        abort(400, "Invalid filename.")
    results_dir = os.path.abspath("results")
    target      = os.path.abspath(os.path.join(results_dir, safe))
    if not target.startswith(results_dir):
        abort(400, "Invalid path.")
    return send_from_directory("results", safe, as_attachment=True)


@app.route("/analysis/<path:filename>")
def get_analysis(filename):
    """Return the saved AI analysis for a report (same name as the .xlsx)."""
    safe = os.path.basename(filename)
    if not _validate_report_filename(safe):
        abort(400, "Invalid filename.")
    results_dir = os.path.abspath("results")
    target = os.path.abspath(os.path.join(results_dir, safe.replace(".xlsx", ".analysis.json")))
    if not target.startswith(results_dir) or not os.path.isfile(target):
        abort(404, "No analysis saved for this report.")
    with open(target, encoding="utf-8") as fh:
        return jsonify(json.load(fh))


@app.route("/preview/<path:filename>")
def preview_report(filename):
    """Return a report's sheets as JSON so the UI can show an in-app preview
    (read-only — /download still serves the actual .xlsx file)."""
    safe = os.path.basename(filename)
    if not _validate_report_filename(safe):
        abort(400, "Invalid filename.")
    results_dir = os.path.abspath("results")
    target      = os.path.abspath(os.path.join(results_dir, safe))
    if not target.startswith(results_dir) or not os.path.isfile(target):
        abort(404, "Report not found.")

    from openpyxl import load_workbook
    MAX_ROWS, MAX_COLS = 400, 20   # keep the JSON payload light
    wb = load_workbook(target, read_only=True, data_only=True)
    sheets = []
    try:
        for ws in wb.worksheets:
            rows, truncated = [], False
            for r_idx, row in enumerate(ws.iter_rows(values_only=True)):
                if r_idx >= MAX_ROWS:
                    truncated = True
                    break
                cells = []
                for v in row[:MAX_COLS]:
                    if v is None:
                        cells.append("")
                    elif isinstance(v, float):
                        cells.append(int(v) if v == int(v) else round(v, 2))
                    elif isinstance(v, (int, bool)):
                        cells.append(v)
                    else:
                        cells.append(str(v))
                rows.append(cells)
            sheets.append({"name": ws.title, "rows": rows, "truncated": truncated})
    finally:
        wb.close()
    return jsonify({"filename": safe, "sheets": sheets})


# ── Background agent runner ───────────────────────────────────

def _log(msg: str, done=False, excel=""):
    _log_queue.put(json.dumps({
        "t":     datetime.now().strftime("%H:%M:%S"),
        "m":     msg,
        "done":  done,
        "excel": excel,
    }))


def _position_value(pos) -> int | None:
    """'1.4' (page.slot) → absolute 4; '2.3' → 13; 'Not Found'/blank → None."""
    s = str(pos if pos is not None else "").strip()
    if not s or s.lower() in ("not found", "nan", "none"):
        return None
    m = re.match(r"^(\d+)(?:\.(\d+))?$", s)
    if not m:
        return None
    page, slot = int(m.group(1)), int(m.group(2) or 1)
    return (page - 1) * 10 + slot


def _build_run_comparison(rows: list, prev_csv_path: str) -> dict | None:
    """Per-city comparison of this run vs the previous run's CSV.

    Matches keywords by (Location, Keyword) so a previous run for a different
    client simply yields no matches (returns None instead of a bogus diff)."""
    try:
        prev_df = pd.read_csv(prev_csv_path)
        prev = {(str(r.get("Location", "")), str(r.get("Keyword", ""))):
                (str(r.get("Position", "")), _position_value(r.get("Position")))
                for r in prev_df.to_dict("records")}
    except Exception:  # noqa: BLE001
        return None
    if not prev:
        return None

    locations, by_loc, compared_total = [], {}, 0
    for r in rows:
        loc = str(r.get("Location", "") or "—")
        e = by_loc.get(loc)
        if e is None:
            e = by_loc[loc] = {"location": loc, "checked": 0, "compared": 0,
                               "ranked_prev": 0, "ranked_now": 0, "improved": 0,
                               "declined": 0, "unchanged": 0, "new_ranked": 0,
                               "lost": 0, "changes": []}
            locations.append(e)
        e["checked"] += 1
        cur_raw = str(r.get("Position", ""))
        cur = _position_value(cur_raw)
        if cur is not None:
            e["ranked_now"] += 1
        key = (loc, str(r.get("Keyword", "")))
        if key not in prev:
            continue  # keyword wasn't in the last run — nothing to compare
        old_raw, old = prev[key]
        e["compared"] += 1
        compared_total += 1
        if old is not None:
            e["ranked_prev"] += 1
        if old is None and cur is None:
            e["unchanged"] += 1
        elif old is None:
            e["new_ranked"] += 1
            e["changes"].append({"keyword": key[1], "last": "Not Found", "now": cur_raw, "delta": "new"})
        elif cur is None:
            e["lost"] += 1
            e["changes"].append({"keyword": key[1], "last": old_raw, "now": "Not Found", "delta": "lost"})
        elif cur < old:
            e["improved"] += 1
            e["changes"].append({"keyword": key[1], "last": old_raw, "now": cur_raw, "delta": f"+{old - cur}"})
        elif cur > old:
            e["declined"] += 1
            e["changes"].append({"keyword": key[1], "last": old_raw, "now": cur_raw, "delta": f"-{cur - old}"})
        else:
            e["unchanged"] += 1
    if not compared_total:
        return None  # previous run was for different keywords/client
    for e in by_loc.values():
        e["changes"] = e["changes"][:10]
    return {"previous_run": os.path.basename(prev_csv_path), "locations": locations}


def _run_agent(keywords=None, domain=None):
    global _agent_running, _last_rows, _last_excel, _last_agent_report, _progress

    import serp_agent as sa
    import websearch_agent

    sa.log.addHandler(_sse_handler)
    sa.log.setLevel(logging.INFO)

    try:
        # Use the caller's active client (passed in); fall back to the CLI default.
        keywords = list(keywords) if keywords else (sa.KEYWORDS[:sa.KEYWORD_LIMIT] if sa.KEYWORD_LIMIT else sa.KEYWORDS)
        domain = domain or sa.TARGET_DOMAIN
        _progress["total"]   = len(keywords)
        _progress["current"] = 0

        _log(f"Agent started - {len(keywords)} keywords for {domain}")

        rows = sa.run_serp_agent(keywords, domain)
        _last_rows = rows
        _progress["current"] = len(rows)

        os.makedirs("results", exist_ok=True)
        ts         = datetime.now().strftime("%d-%m-%Y %H-%M-%S")
        excel_path = f"results/AHNS SERP {ts}.xlsx"
        csv_path   = f"results/AHNS SERP {ts}.csv"
        run_date   = datetime.now().strftime("%d/%m/%Y")

        # Compare against the most recent previous run (before this run's CSV exists).
        prev_csvs  = glob.glob("results/AHNS SERP *.csv")
        comparison = (_build_run_comparison(rows, max(prev_csvs, key=os.path.getmtime))
                      if prev_csvs else None)

        df = pd.DataFrame(rows)
        sa.save_excel(df, excel_path, run_date, domain, comparison=comparison)
        df.to_csv(csv_path, index=False)
        _last_excel = excel_path

        _log("Agent analysis started - preparing SEO recommendations")
        ollama_report = websearch_agent.analyze_with_ollama(rows, domain)
        if isinstance(ollama_report, dict):
            _last_agent_report = ollama_report
            _last_agent_report["source"] = "ollama"
            _last_agent_report["model"] = os.getenv("OLLAMA_MODEL", "gemma4:e4b")
            _last_agent_report["summary"] = websearch_agent.build_local_summary(rows)
        else:
            _last_agent_report = {
                "source": "local",
                "summary": websearch_agent.build_local_summary(rows),
                "executive_summary": (
                    "Ollama was unavailable, so the dashboard is showing local SERP metrics. "
                    "Start Ollama and pull the configured model to enable AI recommendations."
                ),
                "recommendations": [
                    "Review keywords marked Not Found first because they are the biggest visibility gap.",
                    "Prioritize ranked keywords that are close to page one.",
                    "Study repeated competitor domains and titles to identify content patterns to improve.",
                ],
                "risks": [],
                "competitor_insights": [],
                "page_changes": [],
                "content_brief": {},
            }
        source = _last_agent_report.get("source", "local")

        # Persist the analysis next to the Excel so it survives restarts and can
        # be reopened later from the sidebar / chat links.
        _last_agent_report["domain"]   = domain
        _last_agent_report["run_date"] = run_date
        if comparison:
            _last_agent_report["comparison"] = comparison
        try:
            with open(f"results/AHNS SERP {ts}.analysis.json", "w", encoding="utf-8") as fh:
                json.dump(_last_agent_report, fh, ensure_ascii=False, indent=1)
        except Exception as exc:  # noqa: BLE001
            _log(f"Could not save the analysis file: {exc}")
        _log(f"Agent analysis ready - source: {source}")

        reviewed = sum(1 for r in rows if r["Reviews"] == "Yes")
        ranked   = sum(1 for r in rows if r["Position"] != "Not Found")
        _log(
            f"COMPLETED — {ranked}/{len(rows)} ranked, {reviewed} with reviews. "
            f"Excel: {os.path.basename(excel_path)}",
            done=True,
            excel=os.path.basename(excel_path),
        )

    except Exception as exc:
        _log(f"ERROR: {exc}", done=True)

    finally:
        sa.log.removeHandler(_sse_handler)
        _agent_running = False


# ── Entry point ───────────────────────────────────────────────

if __name__ == "__main__":
    import webbrowser
    import threading
    print("\n" + "=" * 55)
    print("  AHNS SERP Tracker — Web UI")
    print("  Open: http://localhost:5000")
    print("=" * 55 + "\n")
    # Open browser 2 s after Flask starts (not before)
    threading.Timer(2.0, webbrowser.open, args=["http://localhost:5000"]).start()
    app.run(host="127.0.0.1", port=5000, debug=False, threaded=True)
