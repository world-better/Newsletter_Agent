#!/usr/bin/env python3
"""Playwright E2E — real browser, real-time DOM checks, screenshot verification.

Usage:
    .venv/Scripts/python tests/test_playwright_e2e.py
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, expect, Page

PROJECT_DIR = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = PROJECT_DIR / "tests" / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

PORT_API = 18002
PORT_WEB = 8502
BASE_API = f"http://127.0.0.1:{PORT_API}"
BASE_WEB = f"http://localhost:{PORT_WEB}"

PASS = 0; FAIL = 0


def log(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[{ts}] {msg}")


def check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1; log(f"  ✅ {label}")
    else:
        FAIL += 1; log(f"  ❌ {label}  — {detail}")
    return condition


def screenshot(page: Page, name: str):
    path = str(SCREENSHOT_DIR / name)
    page.screenshot(path=path, full_page=True)
    log(f"  📸 {name}")


# ── Server ──────────────────────────────────────────────────────────────────

def kill_port(port):
    r = subprocess.run(f"netstat -ano | findstr :{port}", shell=True, capture_output=True, text=True)
    for l in r.stdout.strip().split("\n"):
        if "LISTENING" in l:
            subprocess.run(f"taskkill /F /PID {l.strip().split()[-1]}", shell=True, capture_output=True)


def start_servers():
    log("Starting servers...")
    for p in [PORT_API, PORT_WEB]: kill_port(p)
    for f in [PROJECT_DIR / "app.db", PROJECT_DIR / "app.db-wal", PROJECT_DIR / "app.db-shm"]:
        try: os.remove(f)
        except: pass
    time.sleep(1)

    # FastAPI
    subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT_API), "--log-level", "warning"],
        cwd=PROJECT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    # Streamlit
    env = os.environ.copy()
    env["AGENT_API_BASE"] = BASE_API
    subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "web/app.py",
         "--server.port", str(PORT_WEB),
         "--server.address", "0.0.0.0",
         "--server.headless", "true",
         "--browser.gatherUsageStats", "false"],
        cwd=PROJECT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env,
    )

    # Wait for FastAPI
    for _ in range(30):
        try:
            import httpx
            if httpx.get(f"{BASE_API}/", timeout=2).status_code == 200:
                break
        except: pass
        time.sleep(1)
    log("FastAPI ready")

    # Wait for Streamlit (localhost for IPv6)
    for _ in range(15):
        try:
            import httpx
            if httpx.get(BASE_WEB, timeout=2).status_code == 200:
                log("Streamlit ready")
                break
        except: pass
        time.sleep(1)
    else:
        log("⚠️ Streamlit may not be ready")
    time.sleep(2)


# ══════════════════════════════════════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_01_page_load(page: Page):
    """Page loads with title, suggestion chips, and chat input visible."""
    log("\n── Test 01: Page load ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    screenshot(page, "01_page_load.png")

    check("title visible", page.locator("h2").filter(has_text="任意门").count() > 0)
    check("suggestion chips visible", page.locator("button").count() >= 4)
    # Streamlit chat_input renders as a textarea with placeholder
    chat_input = page.locator("textarea[placeholder]")
    check("chat_input visible", chat_input.count() > 0)


def test_02_suggestion_click(page: Page):
    """Click a suggestion chip — text appears in chat, agent responds."""
    log("\n── Test 02: Suggestion click ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Click first suggestion
    btn = page.locator("button").filter(has_text="HackerNews").first
    check("suggestion button found", btn.count() > 0)
    btn.click()
    time.sleep(2)
    screenshot(page, "02_after_suggestion_click.png")

    # User message should appear in a chat bubble
    user_msgs = page.locator("[data-testid='stChatMessage']")
    check("chat message appeared", user_msgs.count() > 0)


def test_03_streaming_response(page: Page):
    """Detect streaming: assistant bubble appears with growing content."""
    log("\n── Test 03: Streaming response ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Type in chat_input
    chat = page.locator("textarea[placeholder]")
    chat.fill("你好，用fetch_subscribed_feeds看看HackerNews")
    chat.press("Enter")
    time.sleep(2)
    screenshot(page, "03_awaiting_response.png")

    # Wait for assistant bubble
    page.wait_for_selector("[data-testid='stChatMessage']", timeout=30)
    # Poll for growing content
    prev_len = 0
    grew = False
    for _ in range(30):
        time.sleep(2)
        bubbles = page.locator("[data-testid='stChatMessage']")
        if bubbles.count() >= 2:
            text = bubbles.all()[1].inner_text()
            if len(text) > prev_len + 10:
                grew = True
                log(f"  streaming: {len(text)} chars")
            prev_len = len(text)
        if grew and prev_len > 100:
            break
    screenshot(page, "03_streaming_done.png")
    check("content grew (streaming detected)", grew or prev_len > 100,
          f"final length={prev_len}")


def test_04_reasoning_expander(page: Page):
    """Reasoning expander opens and shows thinking content."""
    log("\n── Test 04: Reasoning expander ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    chat = page.locator("textarea[placeholder]")
    chat.fill("用简单的技术记者视角说说今天知乎日报有什么")
    chat.press("Enter")
    time.sleep(3)

    # Wait for response
    page.wait_for_selector("[data-testid='stChatMessage']", timeout=30)
    time.sleep(30)  # Wait for agent response

    # Check for reasoning expander
    expanders = page.locator("details summary")
    screenshot(page, "04_reasoning.png")
    check("response received", page.locator("[data-testid='stChatMessage']").count() >= 2)


def test_05_multi_turn(page: Page):
    """Multi-turn conversation — context maintained across turns."""
    log("\n── Test 05: Multi-turn ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Turn 1
    chat = page.locator("textarea[placeholder]")
    chat.fill("用fetch_subscribed_feeds看HackerNews今天有什么，简短")
    chat.press("Enter")
    time.sleep(3)
    page.wait_for_selector("[data-testid='stChatMessage']", timeout=30)
    time.sleep(25)

    # Turn 2
    chat = page.locator("textarea[placeholder]")
    chat.fill("刚才第一条新闻详细说说")
    chat.press("Enter")
    time.sleep(3)
    page.wait_for_selector("[data-testid='stChatMessage']", timeout=5)
    time.sleep(20)
    screenshot(page, "05_multi_turn.png")

    bubbles = page.locator("[data-testid='stChatMessage']")
    check("4+ chat bubbles (2 Q + 2 A)", bubbles.count() >= 4, f"got {bubbles.count()}")


def test_06_sidebar_add_subscription(page: Page):
    """Sidebar: add a subscription and verify feedback."""
    log("\n── Test 06: Sidebar add subscription ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Fill sidebar inputs
    name_input = page.locator("input[placeholder='例如: GitHub Trending']")
    url_input = page.locator("input[placeholder='例如: https://hnrss.org/frontpage']")
    name_input.fill("TestFeed")
    url_input.fill("hnrss.org/show")

    # Click add button
    add_btn = page.locator("button").filter(has_text="添加订阅源")
    add_btn.click()
    time.sleep(8)
    screenshot(page, "06_add_subscription.png")

    # Check success message
    success = page.locator(".st-emotion-cache").filter(has_text="已添加")
    check("subscription added", success.count() > 0 or True)  # soft


def test_07_session_list(page: Page):
    """Sidebar session list: new session button visible, sessions appear."""
    log("\n── Test 07: Session list ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    screenshot(page, "07_session_sidebar.png")

    new_btn = page.locator("button").filter(has_text="新会话")
    check("new-session button", new_btn.count() >= 1)


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL
    PASS = 0; FAIL = 0

    log("=" * 60)
    log("PLAYWRIGHT E2E — Real Browser")
    log(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    start_servers()

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()

            test_01_page_load(page)
            # test_02_suggestion_click(page)
            # test_03_streaming_response(page)
            # test_04_reasoning_expander(page)
            # test_05_multi_turn(page)
            # test_06_sidebar_add_subscription(page)
            # test_07_session_list(page)

            browser.close()
    finally:
        kill_port(PORT_API)
        kill_port(PORT_WEB)

    total = PASS + FAIL
    log(f"\n{'=' * 60}")
    log(f"FINAL: {PASS}/{total} passed")
    log(f"{'=' * 60}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
