#!/usr/bin/env python3
"""Capture app screenshots into screenshots/ by driving the local app with Playwright."""
import os
from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:5000"
os.makedirs("screenshots", exist_ok=True)


def run():
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1280, "height": 820})

        # 1) Auth page (sign-up form) -> login.png
        pg.goto(f"{BASE}/signup", wait_until="networkidle")
        pg.screenshot(path="screenshots/login.png")
        print("login.png")

        # sign up an admin so we can see the app
        pg.fill('input[name="name"]', "Demo Admin")
        pg.fill('input[name="email"]', "demo@kleza.io")
        pg.fill('input[name="password"]', "secret123")
        pg.fill('input[name="company"]', "Kleza Solutions")
        pg.fill('input[name="code"]', "ahns-admin")
        pg.click('button[type="submit"]')
        pg.wait_for_selector("#chatInput", timeout=20000)
        pg.wait_for_timeout(1200)

        # 2) Chat home (sidebar + welcome) -> chat.png + sidebar.png
        pg.screenshot(path="screenshots/chat.png")
        print("chat.png")
        pg.screenshot(path="screenshots/sidebar.png", clip={"x": 0, "y": 0, "width": 290, "height": 820})
        print("sidebar.png")

        # 3) Clarify (no search cost): ask about a website without naming it
        pg.fill("#chatInput", "best pharmacy in Independence MO check a specific website")
        pg.click("#chatSend")
        try:
            pg.wait_for_selector(".clarify-q", timeout=60000)
            pg.wait_for_timeout(800)
            pg.screenshot(path="screenshots/clarify.png")
            print("clarify.png")
        except Exception as e:
            print("clarify skipped:", e)

        # 4) A ranking result card
        pg.evaluate("newChat && newChat()")
        pg.fill("#chatInput", 'check ranking for "home care services in Detroit, MI"')
        pg.click("#chatSend")
        try:
            pg.wait_for_selector(".res-card", timeout=120000)
            pg.wait_for_timeout(1000)
            pg.screenshot(path="screenshots/result.png")
            print("result.png")
        except Exception as e:
            print("result skipped:", e)

        b.close()


if __name__ == "__main__":
    run()
