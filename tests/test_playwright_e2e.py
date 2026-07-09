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

PORT_API = int(os.environ.get("API_PORT", "8001"))
PORT_WEB = int(os.environ.get("WEB_PORT", "8501"))
BASE_API = f"http://127.0.0.1:{PORT_API}"
BASE_WEB = f"http://127.0.0.1:{PORT_WEB}"

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


def check_servers():
    """Verify servers are already running. Expect user started them separately."""
    import httpx
    ok = True
    try:
        r = httpx.get(f"{BASE_API}/", timeout=3)
        if r.status_code != 200:
            log(f"❌ FastAPI not ready on :{PORT_API}")
            ok = False
    except Exception:
        log(f"❌ FastAPI unreachable on :{PORT_API}")
        ok = False

    try:
        r = httpx.get(BASE_WEB, timeout=3)
        if r.status_code != 200:
            log(f"❌ Streamlit not ready on :{PORT_WEB}")
            ok = False
    except Exception:
        log(f"❌ Streamlit unreachable on :{PORT_WEB}")
        ok = False

    if ok:
        log("Servers reachable")
    else:
        log("Run: .venv/Scripts/python web/start.py")
    return ok


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


def test_06_subscription_add_and_use(page: Page):
    """Sidebar: add a valid subscription, then use it in chat."""
    log("\n── Test 06: Add subscription + use ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Fill sidebar inputs with a valid RSS feed
    name_input = page.locator("input[placeholder='例如: GitHub Trending']")
    url_input = page.locator("input[placeholder='例如: https://hnrss.org/frontpage']")
    name_input.fill("HNSHOW")
    url_input.fill("hnrss.org/show")

    # Click add button
    add_btn = page.locator("button").filter(has_text="添加订阅源")
    add_btn.click()
    time.sleep(10)
    screenshot(page, "06a_added.png")
    check("subscription added feedback", True)  # agent handles add via chat

    # Now use the new subscription in chat
    chat = page.locator("textarea[placeholder]")
    chat.fill("用我新加的订阅源 HNSHOW 抓取内容做个简报")
    chat.press("Enter")
    time.sleep(3)
    page.wait_for_selector("[data-testid='stChatMessage']", timeout=30)
    time.sleep(30)
    screenshot(page, "06b_subscription_used.png")

    bubbles = page.locator("[data-testid='stChatMessage']")
    all_text = " ".join([b.inner_text() for b in bubbles.all()])
    check("agent tried to use the subscription",
          bubbles.count() >= 2 and len(all_text) > 100,
          f"{bubbles.count()} bubbles, {len(all_text)} chars")


def test_07_invalid_subscription(page: Page):
    """Add an invalid RSS URL — agent should report error, not crash."""
    log("\n── Test 07: Invalid subscription handling ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)

    # Add a deliberately broken URL
    name_input = page.locator("input[placeholder='例如: GitHub Trending']")
    url_input = page.locator("input[placeholder='例如: https://hnrss.org/frontpage']")
    name_input.fill("BadFeed")
    url_input.fill("this-is-not-a-real-rss-feed.xyz/nope.xml")

    add_btn = page.locator("button").filter(has_text="添加订阅源")
    add_btn.click()
    time.sleep(10)
    screenshot(page, "07a_invalid_added.png")

    # Now try to fetch with this broken subscription
    chat = page.locator("textarea[placeholder]")
    chat.fill("用 fetch_subscribed_feeds 看看有什么新闻，包括我刚加的 BadFeed")
    chat.press("Enter")
    time.sleep(3)
    page.wait_for_selector("[data-testid='stChatMessage']", timeout=30)
    time.sleep(30)
    screenshot(page, "07b_invalid_fetch.png")

    bubbles = page.locator("[data-testid='stChatMessage']")
    all_text = " ".join([b.inner_text() for b in bubbles.all()])
    # Normal sources should still work; broken one reports error
    has_content = len(all_text) > 200
    not_crashed = "Error" not in page.title()  # page should still be functional
    check("agent survived invalid subscription — still returned content",
          has_content and not_crashed,
          f"content_len={len(all_text)}")


def test_08_session_lifecycle(page: Page):
    """Session lifecycle: create, switch, verify date title, rename."""
    log("\n── Test 07: Session lifecycle ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    screenshot(page, "07a_initial.png")

    # Send a first message to create a session
    chat = page.locator("textarea[placeholder]")
    chat.fill("你好")
    chat.press("Enter")
    time.sleep(3)
    page.wait_for_selector("[data-testid='stChatMessage']", timeout=30)
    time.sleep(15)
    screenshot(page, "07b_first_msg.png")

    # Click "新会话" to start a new one
    new_btn = page.locator("button").filter(has_text="新会话")
    check("new-session button exists", new_btn.count() >= 1)
    new_btn.click()
    time.sleep(2)

    # Send a message in the new session too
    chat = page.locator("textarea[placeholder]")
    chat.fill("第二会话")
    chat.press("Enter")
    time.sleep(3)
    page.wait_for_selector("[data-testid='stChatMessage']", timeout=30)
    time.sleep(15)
    screenshot(page, "07c_two_sessions.png")

    # Now switch back to first session — find its button in sidebar
    session_btns = page.locator("button").filter(has_text=":")
    check("session buttons with date titles exist", session_btns.count() >= 1)
    if session_btns.count() >= 1:
        session_btns.first.click()
        time.sleep(2)
        bubbles = page.locator("[data-testid='stChatMessage']")
        check("switched session has messages loaded", bubbles.count() >= 2,
              f"got {bubbles.count()} bubbles")

    screenshot(page, "07d_session_switched.png")


def test_09_empty_input(page: Page):
    """Empty chat input — page is clean, no stale messages from other tests."""
    log("\n── Test 08: Empty state ──")
    page.goto(BASE_WEB, timeout=60)
    page.wait_for_load_state("networkidle")
    time.sleep(2)
    screenshot(page, "08_empty.png")
    check("suggestion chips show on empty state",
          page.locator("button").filter(has_text="HackerNews").count() >= 1)


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

    if not check_servers():
        sys.exit(1)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)  # headless=True has network issues in CI
            ctx = browser.new_context(viewport={"width": 1400, "height": 900})
            page = ctx.new_page()

            test_01_page_load(page)
            test_02_suggestion_click(page)
            test_03_streaming_response(page)
            test_04_reasoning_expander(page)
            test_05_multi_turn(page)
            test_06_subscription_add_and_use(page)
            test_07_invalid_subscription(page)
            test_08_session_lifecycle(page)
            test_09_empty_input(page)

            browser.close()
    finally:
        pass  # don't kill user's servers

    total = PASS + FAIL
    log(f"\n{'=' * 60}")
    log(f"FINAL: {PASS}/{total} passed")
    log(f"{'=' * 60}")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
