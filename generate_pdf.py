#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Generate a professional, plain-English PDF guide to the SERP Agent agentic workflow.

    pip install fpdf2
    python generate_pdf.py   ->  SERP_Agent_Agentic_Workflow.pdf

Screenshots (optional): drop PNG/JPG files into a 'screenshots/' folder using the
names listed in SHOTS below and they get embedded automatically; otherwise a clean
labelled placeholder is drawn in their place.
"""
import os
from fpdf import FPDF
try:
    from PIL import Image
except Exception:
    Image = None

NAVY  = (23, 42, 86)      # deep navy header
BLUE  = (37, 99, 235)     # accent
LBLUE = (226, 235, 252)
PILL  = (47, 92, 196)
GREY  = (90, 100, 115)
LGREY = (238, 242, 249)
DARK  = (17, 24, 39)
MUTED = (120, 130, 145)

MARGIN = 16
PAGE_W = 210
CONTENT_W = PAGE_W - 2 * MARGIN

# screenshot file -> caption (drop these into ./screenshots/)
SHOTS = {
    "login":   "The sign-in / sign-up screen (team access)",
    "chat":    "Chat home - quick actions and example prompts",
    "result":  "A live ranking result card (real Google position)",
    "clarify": "The agent asking which website to check",
    "scan":    "A keyword scan running inside the chat",
    "sidebar": "Sidebar - active client, reports and tickets",
}


class Doc(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_fill_color(*NAVY)
        self.rect(0, 0, PAGE_W, 12, "F")
        self.set_xy(MARGIN, 3.5)
        self.set_font("Helvetica", "B", 8.5)
        self.set_text_color(255, 255, 255)
        self.cell(0, 5, "SERP AGENT - AGENTIC AI WORKFLOW", align="L")
        self.set_xy(MARGIN, 3.5)
        self.cell(CONTENT_W, 5, "Kleza Solutions", align="R")
        self.set_text_color(*DARK)
        self.set_y(20)

    def footer(self):
        if self.page_no() == 1:
            return
        self.set_y(-12)
        self.set_font("Helvetica", "", 8)
        self.set_text_color(*MUTED)
        self.cell(0, 8, f"serpagent.kleza.io          {self.page_no()}", align="C")


def rrect(pdf, x, y, w, h, r, fill, style="F"):
    pdf.set_fill_color(*fill)
    try:
        pdf.rect(x, y, w, h, style=style, round_corners=True, corner_radius=r)
    except Exception:
        pdf.rect(x, y, w, h, style)


def banner(pdf, title_lines, subtitle, pills):
    """Big rounded navy header card with title, subtitle and pill tags."""
    x, y, w = MARGIN, pdf.get_y(), CONTENT_W
    h = 16 + 11 * len(title_lines) + 9 + 14
    rrect(pdf, x, y, w, h, 5, NAVY)
    cy = y + 11
    pdf.set_text_color(255, 255, 255)
    pdf.set_font("Helvetica", "B", 23)
    for ln in title_lines:
        pdf.set_xy(x + 9, cy)
        pdf.cell(w - 18, 10, ln)
        cy += 10.5
    cy += 2
    pdf.set_xy(x + 9, cy)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(180, 200, 240)
    pdf.cell(w - 18, 6, subtitle)
    cy += 11
    px = x + 9
    pdf.set_font("Helvetica", "B", 8.5)
    for p in pills:
        pw = pdf.get_string_width(p) + 8
        if px + pw > x + w - 9:
            break
        rrect(pdf, px, cy, pw, 7, 3.5, PILL)
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(px, cy)
        pdf.cell(pw, 7, p, align="C")
        px += pw + 4
    pdf.set_text_color(*DARK)
    pdf.set_y(y + h + 6)


def h1(pdf, text):
    if pdf.get_y() > 250:
        pdf.add_page()
    pdf.ln(2)
    y = pdf.get_y()
    pdf.set_fill_color(*BLUE)
    pdf.rect(MARGIN, y + 1, 3, 7, "F")          # accent left bar
    pdf.set_xy(MARGIN + 6, y)
    pdf.set_font("Helvetica", "B", 14)
    pdf.set_text_color(*NAVY)
    pdf.cell(0, 9, text, new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*DARK)
    pdf.ln(2.5)


def h2(pdf, text):
    pdf.ln(1)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*BLUE)
    pdf.multi_cell(0, 6.5, text)
    pdf.set_text_color(*DARK)


def body(pdf, text):
    pdf.set_font("Helvetica", "", 10.5)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(0, 5.8, text)
    pdf.ln(1)


def bullet(pdf, label, text=""):
    pdf.set_x(MARGIN)
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(*BLUE)
    pdf.cell(6, 5.8, chr(149))
    pdf.set_text_color(*DARK)
    if label and text:
        pdf.set_font("Helvetica", "B", 10.5)
        pdf.cell(0, 5.8, label, new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(MARGIN + 6)
        pdf.set_font("Helvetica", "", 10.5)
        pdf.multi_cell(CONTENT_W - 6, 5.5, text)
    else:
        pdf.set_font("Helvetica", "", 10.5)
        pdf.multi_cell(CONTENT_W - 6, 5.8, label or text)
    pdf.ln(0.5)


def note(pdf, text):
    pdf.ln(1)
    pdf.set_font("Helvetica", "", 10)
    tw, lh = CONTENT_W - 12, 5.4
    # measure height WITHOUT rendering (page-break-safe)
    lines = pdf.multi_cell(tw, lh, text, dry_run=True, output="LINES")
    h = len(lines) * lh + 6
    # keep the whole callout on one page
    if pdf.get_y() + h + 4 > 285:
        pdf.add_page()
    x, y = MARGIN, pdf.get_y()
    pdf.set_fill_color(*LBLUE)
    pdf.rect(x, y, CONTENT_W, h, "F")
    pdf.set_fill_color(*BLUE)
    pdf.rect(x, y, 3, h, "F")
    pdf.set_xy(x + 8, y + 3)
    pdf.set_text_color(*DARK)
    pdf.multi_cell(tw, lh, text)
    pdf.set_text_color(*DARK)
    pdf.set_y(y + h + 3)


def screenshot(pdf, key, max_h=104):
    """Embed screenshots/<key>.(png|jpg): the frame is sized to the image so it fills
    the page width (capped by max_h), leaving no empty padding. Placeholder if absent."""
    caption = SHOTS.get(key, key)
    path = None
    for ext in (".png", ".jpg", ".jpeg", ".PNG", ".JPG"):
        p = os.path.join("screenshots", key + ext)
        if os.path.exists(p):
            path = p
            break
    pdf.set_draw_color(*BLUE)
    pdf.set_line_width(0.4)
    if path and Image is not None:
        try:
            iw, ih = Image.open(path).size
            dw = CONTENT_W - 4                      # display the image near full width
            dh = dw * ih / iw
            if dh > max_h:                          # tall/narrow shots: cap by height
                dh = max_h
                dw = dh * iw / ih
            fw, fh = dw + 4, dh + 4                 # frame = image + 2mm padding
            if pdf.get_y() + fh + 12 > 285:
                pdf.add_page()
            x = MARGIN + (CONTENT_W - fw) / 2       # centre the framed image
            y = pdf.get_y()
            pdf.image(path, x=x + 2, y=y + 2, w=dw, h=dh)
            pdf.rect(x, y, fw, fh, "D")
            pdf.set_y(y + fh + 1)
        except Exception:
            path = None
    elif path and Image is None:
        # PIL missing: fall back to a fixed box, fit by aspect ratio
        h = 100
        if pdf.get_y() + h + 12 > 285:
            pdf.add_page()
        x, y, w = MARGIN, pdf.get_y(), CONTENT_W
        try:
            pdf.image(path, x=x + 2, y=y + 2, w=w - 4, h=h - 4, keep_aspect_ratio=True)
            pdf.rect(x, y, w, h, "D")
            pdf.set_y(y + h + 1)
        except Exception:
            path = None
    if not path:
        h = 70
        if pdf.get_y() + h + 12 > 285:
            pdf.add_page()
        x, y, w = MARGIN, pdf.get_y(), CONTENT_W
        rrect(pdf, x, y, w, h, 4, LGREY)
        pdf.rect(x, y, w, h, "D")
        pdf.set_xy(x, y + h / 2 - 6)
        pdf.set_font("Helvetica", "B", 10)
        pdf.set_text_color(*BLUE)
        pdf.cell(w, 6, "[ screenshot ]", align="C", new_x="LMARGIN", new_y="NEXT")
        pdf.set_x(x)
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*MUTED)
        pdf.cell(w, 5, f"add  screenshots/{key}.png", align="C")
        pdf.set_y(y + h + 1)
    pdf.set_font("Helvetica", "I", 9)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 5, "Fig. " + caption)
    pdf.set_text_color(*DARK)
    pdf.ln(3)


pdf = Doc()
pdf.set_auto_page_break(True, margin=16)
pdf.set_margins(MARGIN, 20, MARGIN)

# ===================== COVER =====================
pdf.add_page()
pdf.set_y(34)
banner(pdf,
       ["SERP Agent", "Agentic AI Workflow"],
       "How the AI agent works - a plain-English guide for everyone",
       ["Chat Agent", "Gemini AI", "Serper Search", "Multi-Client", "Reports", "Roles"])
body(pdf, "This guide explains, in simple terms, how SERP Agent works: how you ask it questions in "
          "plain language, how the AI plans and carries out the steps, how it checks real Google "
          "rankings, and how the same system can be reused for any client or website. No technical "
          "background needed.")
h1(pdf, "What this guide covers")
for t in ["What SERP Agent is, in plain words",
          "What 'Agentic AI' means and why it matters",
          "The end-to-end flow: how a request becomes an answer",
          "A real, step-by-step example of the agent thinking",
          "The agent's toolbox and how it stays accurate",
          "How it is built generically to reuse for any client"]:
    bullet(pdf, t)
screenshot(pdf, "chat", max_h=80)   # smaller so it fits on the cover page (no blank gap)

# ===================== 1 =====================
h1(pdf, "1.  What is SERP Agent?")
body(pdf, "SERP Agent is a smart assistant for tracking where a website appears on Google. Instead of "
          "running reports and reading spreadsheets, you simply chat with it in plain language - like "
          "talking to a colleague - and it does the work for you.")
body(pdf, '"SERP" just means a Google search results page. So you can ask things like:')
bullet(pdf, '"Where does my website rank for \'home care services in Detroit\'?"')
bullet(pdf, '"Who are my top competitors for this keyword?"')
bullet(pdf, '"Audit my website" or "Give me ideas to improve my ranking."')
body(pdf, "It supports many clients at once, and several team members - each sees only their own "
          "projects, while an admin sees everything.")
screenshot(pdf, "login")

# ===================== 2 =====================
h1(pdf, "2.  What does 'Agentic AI' mean?")
body(pdf, "A normal program does one fixed thing. An AGENT is different: you give it a goal in your "
          "own words, and it figures out the steps itself, does them, and explains the result. Think "
          "of a helpful assistant who, when asked 'how do we rank and how can we improve?', knows to:")
bullet(pdf, "PLAN", "decide the steps (first check the rank, then suggest improvements).")
bullet(pdf, "ACT", "do each step (search Google, read the results).")
bullet(pdf, "OBSERVE", "look at what came back.")
bullet(pdf, "ANSWER", "explain it clearly in plain language.")
note(pdf, "In one line: you ask in plain English  ->  the AI plans the steps  ->  it uses the right "
          "tools  ->  it reads the results  ->  it replies in plain English.")

# ===================== 3 =====================
h1(pdf, "3.  The end-to-end flow")
body(pdf, "Every request moves through four stages. The AI 'brain' is used at the start (to plan) and "
          "at the end (to write the answer). The 'tools' do the real-world work in the middle.")
pdf.ln(1)
bw, bh, gap = 39, 30, 7           # 4*39 + 3*7 = 177mm -> fits the 178mm content width
if pdf.get_y() + bh + 14 > 285:   # keep the whole diagram on one page
    pdf.add_page()
y = pdf.get_y() + 2
steps = [("1. INPUT", "you type a request"),
         ("2. AI BRAIN", "Gemini PLANS the steps"),
         ("3. TOOLS", "search Google / read site"),
         ("4. AI BRAIN", "Gemini writes the ANSWER")]
fills = [LGREY, LBLUE, LGREY, LBLUE]
for i, (t, s) in enumerate(steps):
    x = MARGIN + i * (bw + gap)
    rrect(pdf, x, y, bw, bh, 4, fills[i])
    pdf.set_xy(x, y + 5)
    pdf.set_font("Helvetica", "B", 9.5)
    pdf.set_text_color(*NAVY)
    pdf.multi_cell(bw, 4.6, t, align="C")
    pdf.set_xy(x, y + 15)
    pdf.set_font("Helvetica", "", 7.6)
    pdf.set_text_color(*GREY)
    pdf.multi_cell(bw, 3.5, s, align="C")
    if i < 3:
        ax = x + bw
        pdf.set_draw_color(*BLUE)
        pdf.set_line_width(0.6)
        pdf.line(ax, y + bh / 2, ax + gap, y + bh / 2)
        pdf.line(ax + gap, y + bh / 2, ax + gap - 2, y + bh / 2 - 1.8)
        pdf.line(ax + gap, y + bh / 2, ax + gap - 2, y + bh / 2 + 1.8)
pdf.set_text_color(*DARK)
pdf.set_y(y + bh + 7)
body(pdf, "Whatever the tools collect (a real Google results page, or a page's content) is handed back "
          "to the AI brain, which turns the raw data into a clear, useful reply.")
h2(pdf, "What powers each stage")
bullet(pdf, "The brain:", "Google Gemini plans and writes. If it is ever unavailable, a free backup "
        "model takes over automatically.")
bullet(pdf, "The search:", "Serper returns the REAL Google top-100 results, so positions are accurate "
        "even deep ones (page 4, 5...).")
bullet(pdf, "The tools:", "small single-purpose helpers - check a rank, compare competitors, audit a "
        "site, recommend fixes, run a full scan.")

# ===================== 4 =====================
h1(pdf, "4.  How the agent thinks (a real example)")
body(pdf, "You see each step appear live in the chat as the agent works.")
h2(pdf, "Example:  \"Check rank for 'home care in Troy' and how to improve\"")
bullet(pdf, "Plan:", "Gemini decides two steps are needed - check the ranking, then suggest tips.")
bullet(pdf, "Act (check rank):", "searches Google via Serper and finds the position, e.g. 4.6 "
        "(page 4, result 6).")
bullet(pdf, "Act (recommend):", "uses the ranking + competitors to ask Gemini for specific SEO ideas.")
bullet(pdf, "Answer:", "combines both into one clear reply, shows a result card, and saves a report.")
note(pdf, "Smart safety check: if a request is missing a detail - e.g. you ask about a website but "
          "don't say which - the agent does NOT guess. It pauses and asks you (\"Which website?\") "
          "with clickable options and a box to type the address.")
screenshot(pdf, "clarify")
screenshot(pdf, "result")

# ===================== 5 =====================
h1(pdf, "5.  The agent's toolbox")
body(pdf, "The agent chooses the right tool automatically - you never pick one manually.")
for name, desc in [
    ("Check a keyword's rank", "your exact Google position for one keyword (real top-100)."),
    ("Compare competitors", "which websites outrank you for a keyword, and why."),
    ("Audit my website", "SEO basics: title, H1, meta description, reviews, word count."),
    ("SEO recommendations", "concrete, practical ideas to improve a keyword's ranking."),
    ("List keywords", "all keywords and locations tracked for the client."),
    ("Run full scan", "checks many keywords at once and builds an Excel + CSV report."),
    ("Ask to clarify", "requests a missing detail (which website / which keyword)."),
]:
    bullet(pdf, name + ":", desc)
screenshot(pdf, "scan")

# ===================== 6 =====================
h1(pdf, "6.  Built generically (reusable for any client)")
body(pdf, "The tool is not locked to one company - the same system works for ANY client or website.")
bullet(pdf, "Multiple clients:", "each client has its own website + keyword list; switch the active "
        "client from a dropdown and everything retargets instantly.")
bullet(pdf, "Any website on the fly:", "in chat you can check ANY site for ANY keyword, even one that "
        "isn't a saved client.")
bullet(pdf, "Editable keywords:", "add or upload keywords (CSV) per client - no code changes.")
bullet(pdf, "Pluggable search:", "the search engine is swappable without touching the rest.")
note(pdf, "The generic recipe: (1) define small tools, (2) let an AI PLAN which tools to use from a "
          "plain request, (3) run the tools, (4) let the AI SUMMARISE the results. Swap the tools and "
          "you have a brand-new agent for a different job.")
screenshot(pdf, "sidebar")

# ===================== 7 =====================
h1(pdf, "7.  Accounts, roles and reports")
bullet(pdf, "Sign in / sign up:", "team members register with a private organization code; passwords "
        "are stored securely (never in plain text).")
bullet(pdf, "Roles:", "a MEMBER sees only their own projects; an ADMIN sees and manages all of them.")
bullet(pdf, "Reports:", "every scan produces a downloadable Excel + CSV, listed in the sidebar.")
bullet(pdf, "Support tickets:", "any user can raise an issue; the admin is alerted and can resolve it.")

h1(pdf, "8.  Reading the results")
body(pdf, "Rankings come from real Google data, so positions are accurate.")
bullet(pdf, "A position like 4.6", "means page 4, result 6 in Google.")
bullet(pdf, "'Not in top 100'", "means the site was not found in the first 100 results checked - the "
        "agent is honest rather than guessing.")
bullet(pdf, "Every answer states the website + keyword it used", "so a result is never ambiguous.")

h2(pdf, "In short, with SERP Agent you can:")
bullet(pdf, "Ask in plain English", "no reports, dashboards or training needed - just chat.")
bullet(pdf, "Trust the numbers", "real Google top-100 positions, never guessed or estimated.")
bullet(pdf, "Reuse it for anyone", "any client, any website, any keyword - the same agent adapts.")
bullet(pdf, "Work as a team", "members manage their own projects; an admin oversees everything.")
note(pdf, "In summary: you ask in plain English, an AI agent plans and runs the right tools, checks "
          "real Google rankings, and replies clearly - for any client, any keyword, any website.")
pdf.ln(2)
pdf.set_font("Helvetica", "I", 9.5)
pdf.set_text_color(*MUTED)
pdf.multi_cell(0, 5, "SERP Agent  -  Kleza Solutions  -  serpagent.kleza.io", align="C")
pdf.set_text_color(*DARK)

pdf.output("SERP_Agent_Agentic_Workflow.pdf")
print("Created SERP_Agent_Agentic_Workflow.pdf")
print("Screenshots folder:", "screenshots/ (drop", ", ".join(SHOTS) + " as .png to embed)")
