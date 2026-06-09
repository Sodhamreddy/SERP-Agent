#!/usr/bin/env python3
"""Capture screenshots/scan.png — a keyword scan running inside the chat."""
import os
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
os.makedirs("screenshots", exist_ok=True)


def run():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 820})

        pg.goto(f"{BASE}/signup", wait_until="networkidle")
        pg.fill('input[name="name"]', "Demo Admin")
        pg.fill('input[name="email"]', "demo@kleza.io")
        pg.fill('input[name="password"]', "secret123")
        pg.fill('input[name="company"]', "Kleza Solutions")
        pg.fill('input[name="code"]', "ahns-admin")
        pg.click('button[type="submit"]')
        pg.wait_for_selector("#chatInput", timeout=20000)
        pg.wait_for_timeout(1500)

        # limit the run to a few keywords, then start it (progress streams in chat)
        pg.evaluate("document.getElementById('runCount').dataset.value = '10'")
        pg.click("#sbRunAll")
        try:
            pg.wait_for_selector(".scan-box", timeout=15000)
            # let a little progress accumulate so the bar + status look alive
            pg.wait_for_timeout(9000)
            pg.screenshot(path="screenshots/scan.png")
            print("scan.png")
        except Exception as e:
            print("scan skipped:", e)

        b.close()


if __name__ == "__main__":
    run()
