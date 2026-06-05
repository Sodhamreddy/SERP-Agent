# Deploying SERP Agent on a VPS (port 7030)

The app runs as **one Waitress process** (multi-threaded) on **port 7030**. It keeps
in-memory state (one scan at a time + the live log queue), so **do not run multiple
workers/instances** — threads handle concurrency.

Two ways to expose it:
- **A. Direct** — open port 7030, access `http://YOUR_SERVER_IP:7030` (no HTTPS).
- **B. Behind nginx + HTTPS** — recommended for real use (needed for `COOKIE_SECURE`).

---

## 0. Server
Ubuntu 22.04/24.04 VPS, Python 3.12. SSH in as a sudo user.

```bash
sudo apt update && sudo apt install -y python3 python3-venv python3-pip nginx
sudo useradd -r -m -d /opt/serp-agent -s /bin/bash serp   # service user
```

## 1. Get the code onto the server
Copy the project to `/opt/serp-agent` (git clone or scp). Then:

```bash
cd /opt/serp-agent
sudo chown -R serp:serp /opt/serp-agent
sudo -u serp python3 -m venv venv
sudo -u serp venv/bin/pip install -r requirements.txt
```

## 2. Configure `config.json`
This file holds your keys + codes (it is gitignored — create/upload it):

```json
{
  "GEMINI_API_KEY": "AIza...",
  "GEMINI_MODEL": "gemini-2.5-flash",
  "SERPER_API_KEY": "your-serper-key",
  "SEARCH_BACKEND": "serper",
  "REASONING_BACKEND": "gemini",
  "OLLAMA_API_KEY": "",
  "SERPER_DEPTH": "100",
  "SIGNUP_CODE": "CHANGE-ME-team",
  "ADMIN_CODE": "CHANGE-ME-admin",
  "COOKIE_SECURE": false
}
```
- **Change `SIGNUP_CODE` and `ADMIN_CODE`** to private values before going live.
- Set **`COOKIE_SECURE: true`** only when serving over HTTPS (Option B). Leave `false` for Option A.
- `SECRET_KEY` is auto-generated and saved on first run.

## 3. Quick test
```bash
cd /opt/serp-agent && sudo -u serp venv/bin/python serve.py
# -> "SERP Agent (production) — http://0.0.0.0:7030"
```
Visit `http://YOUR_SERVER_IP:7030/login`. Ctrl-C to stop.

## 4. Run it as a service (auto-restart, starts on boot)
```bash
sudo cp deploy/serp-agent.service /etc/systemd/system/serp-agent.service
sudo systemctl daemon-reload
sudo systemctl enable --now serp-agent
sudo systemctl status serp-agent      # check it's running
sudo journalctl -u serp-agent -f      # live logs
```
The service runs Waitress bound to `127.0.0.1:7030` (change to `0.0.0.0` in the unit's
`HOST` env for Option A direct access).

---

## Option A — direct on :7030 (no HTTPS)
1. In `serp-agent.service` set `Environment=HOST=0.0.0.0`, then
   `sudo systemctl daemon-reload && sudo systemctl restart serp-agent`.
2. Open the firewall: `sudo ufw allow 7030/tcp`.
3. Visit `http://YOUR_SERVER_IP:7030`. Keep `COOKIE_SECURE: false`.

## Option B — nginx + HTTPS (recommended)
Keep `HOST=127.0.0.1` (default). Then:
```bash
sudo cp deploy/nginx-serp-agent.conf /etc/nginx/sites-available/serp-agent
sudo ln -s /etc/nginx/sites-available/serp-agent /etc/nginx/sites-enabled/
# edit the file: set your real server_name (domain)
sudo nginx -t && sudo systemctl reload nginx

# free HTTPS cert:
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.com
```
Then set `"COOKIE_SECURE": true` in `config.json` and
`sudo systemctl restart serp-agent`. Visit `https://your-domain.com`.

> nginx is configured with `proxy_buffering off` + long timeouts so the **live chat and
> scan-progress streaming (SSE)** work correctly.

---

## First login
Open the site → **Create one** → sign up with your name, email, password, organization
name, and the **admin code** you set. That account becomes the admin (sees all projects).
Share the **team code** with staff (they sign up as members).

## Updating later
```bash
cd /opt/serp-agent && sudo -u serp git pull        # or re-upload files
sudo -u serp venv/bin/pip install -r requirements.txt
sudo systemctl restart serp-agent
```
`config.json`, `users.json`, `clients.json`, `keywords.json`, `tickets.json`, and
`results/` persist on disk across updates (they're gitignored).

## Notes / limits
- **One process only** — never scale to multiple workers (would break the shared
  in-memory scan state). More `WAITRESS_THREADS` is fine for concurrency.
- A full 120-keyword scan at depth 100 takes ~30–40 min and ~1,200 Serper credits.
- Back up the JSON data files + `results/` periodically.
