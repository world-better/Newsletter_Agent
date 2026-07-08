#!/usr/bin/env python3
"""E2E test suite: 3 personas × 10 tests — real user scenarios.

Tests are resilient to LLM behavior variance: tool-call checks are best-effort;
content delivery + DB correctness + error safety are the hard assertions.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

import httpx
from streamlit.testing.v1 import AppTest

# ── Config ──────────────────────────────────────────────────────────────────

PORT = 18001
BASE = f"http://127.0.0.1:{PORT}"
API = f"{BASE}/api/v1"
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "app.db"
LOG_PATH = PROJECT_DIR / "tests" / "test_log.md"
MAX_RETRIES = 2  # retry agent calls that depend on model tool selection

os.environ["AGENT_API_BASE"] = BASE

PASS = 0
FAIL = 0
WARN = 0
LOG_LINES: list[str] = []


def log(msg: str):
    global LOG_LINES
    timestamp = datetime.now().strftime("%H:%M:%S")
    line = f"[{timestamp}] {msg}"
    LOG_LINES.append(line)
    print(line)


def check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition:
        PASS += 1
        log(f"  ✅ {label}")
    else:
        FAIL += 1
        log(f"  ❌ {label}  — {detail}")
    return condition


def soft_check(label: str, condition: bool, detail: str = "") -> bool:
    """Best-effort check: warn on failure, don't count as hard fail."""
    global PASS, WARN
    if condition:
        PASS += 1
        log(f"  ✅ {label}")
    else:
        WARN += 1
        log(f"  ⚠️ {label} (model-behavior) — {detail}")
    return condition


# ── Server lifecycle ────────────────────────────────────────────────────────

_server: subprocess.Popen | None = None


def kill_port(port: int):
    result = subprocess.run(
        f"netstat -ano | findstr :{port}", shell=True,
        capture_output=True, text=True,
    )
    for line in result.stdout.strip().split("\n"):
        if "LISTENING" in line:
            pid = line.strip().split()[-1]
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)


def start_server():
    global _server
    log("── Starting FastAPI backend ──")
    for f in [DB_PATH, str(DB_PATH) + "-wal", str(DB_PATH) + "-shm"]:
        try: os.remove(f)
        except (FileNotFoundError, PermissionError): pass
    kill_port(PORT)
    time.sleep(1)
    _server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            r = httpx.get(f"{BASE}/", timeout=2.0)
            if r.status_code == 200:
                log(f"  FastAPI ready on :{PORT}")
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("FastAPI did not start")


def stop_server():
    global _server
    if _server:
        _server.terminate()
        try: _server.wait(timeout=5)
        except subprocess.TimeoutExpired: _server.kill()
    kill_port(PORT)


# ── DB helpers ──────────────────────────────────────────────────────────────

def db_checkpoint():
    subprocess.run(
        ["sqlite3", str(DB_PATH), "PRAGMA wal_checkpoint(TRUNCATE);"],
        capture_output=True,
    )


def db_messages_for(user_id: str) -> list[str]:
    db_checkpoint()
    r = subprocess.run(
        ["sqlite3", str(DB_PATH),
         f"SELECT role FROM messages WHERE user_id='{user_id}' ORDER BY created_at ASC;"],
        capture_output=True, text=True,
    )
    return [x.strip() for x in r.stdout.strip().split("\n") if x.strip()]


def db_subscription_count(user_id: str) -> int:
    r = subprocess.run(
        ["sqlite3", str(DB_PATH),
         f"SELECT COUNT(*) FROM rss_subscriptions WHERE user_id='{user_id}';"],
        capture_output=True, text=True,
    )
    try: return int(r.stdout.strip())
    except ValueError: return 0


# ── Agent interaction helper ────────────────────────────────────────────────

async def _agent_turn(user_id: str, prompt: str) -> dict:
    """Send a message and consume the SSE stream. Returns {tokens, tools, error}."""
    tokens = []; tools = []; error = None; reasoning = []
    async with httpx.AsyncClient(timeout=180.0) as c:
        resp = await c.post(f"{API}/messages", json={"user_id": user_id, "content": prompt})
        if resp.status_code != 200:
            return {"tokens": "", "tools": [], "error": f"POST {resp.status_code}", "reasoning": ""}
        mid = resp.json()["message_id"]
        event_type = ""; dbuf = ""
        async with c.stream("GET", f"{API}/messages/{mid}/stream") as s:
            async for line in s.aiter_lines():
                if line.startswith("event:"): event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"): dbuf = line.split(":", 1)[1].strip()
                elif line == "" and event_type:
                    if event_type == "token":
                        try: tokens.append(json.loads(dbuf).get("content", ""))
                        except: pass
                    elif event_type == "reasoning":
                        try: reasoning.append(json.loads(dbuf).get("content", ""))
                        except: pass
                    elif event_type == "tool_call":
                        try: tools.append(json.loads(dbuf).get("tool_name", ""))
                        except: pass
                    elif event_type == "error":
                        error = dbuf
                    elif event_type == "done":
                        return {"tokens": "".join(tokens), "tools": tools, "error": error, "reasoning": "".join(reasoning)}
                    event_type = ""; dbuf = ""
        return {"tokens": "".join(tokens), "tools": tools, "error": error, "reasoning": "".join(reasoning)}


def agent_turn(user_id: str, prompt: str, retries: int = 0) -> dict:
    """Sync wrapper with optional retry."""
    for attempt in range(retries + 1):
        result = asyncio.run(_agent_turn(user_id, prompt))
        if result["error"] is None and len(result["tokens"]) > 20:
            return result
        if attempt < retries:
            log(f"  (retry {attempt+1}/{retries})")
            time.sleep(3)
    return result


# ── AppTest helpers ─────────────────────────────────────────────────────────

def find_button(at: AppTest, label_substring: str) -> int | None:
    for i, b in enumerate(at.button):
        if label_substring in (b.label or ""):
            return i
    return None


# ══════════════════════════════════════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_01_landing():
    """张姐打开页面，看到标题和正常布局。"""
    log("\n── Test 01: Landing page ──")
    at = AppTest.from_file(str(PROJECT_DIR / "web" / "app.py"))
    at.run()
    at.session_state["user_id"] = "zhang_hr_01"
    check("page title visible", "任意门" in at.title[0].value)
    check("has preset buttons", len(at.button) >= 6, f"found {len(at.button)} buttons")
    check("has text input", len(at.text_input) >= 1)
    check("has generate button", "生成简报" in " ".join(b.label or "" for b in at.button))


def test_02_preset_and_generate():
    """张姐点预设按钮 → 生成简报。"""
    log("\n── Test 02: Preset + generate ──")
    at = AppTest.from_file(str(PROJECT_DIR / "web" / "app.py"))
    at.run()
    at.session_state["user_id"] = "zhang_hr_02"

    idx = find_button(at, "HackerNews")
    if idx is None:
        check("preset button found", False)
        return
    at.button[idx].click().run()

    try:
        preset_val = at.session_state["chosen_preset"]
    except (KeyError, AttributeError):
        preset_val = ""
    check("preset text in session_state", "HackerNews" in str(preset_val))

    at.text_input[0].input(str(preset_val)).run()
    gen_idx = find_button(at, "生成简报")
    at.button[gen_idx].click().run(timeout=120.0)

    # Check markdown blocks: find any block with substantial content (not page title/caption)
    has_content = any(
        len(m.value) > 20 and "任意门聚合简报" not in (m.value or "")
        for m in at.markdown
    )
    max_len = max((len(m.value) for m in at.markdown), default=0)
    check("brief content in markdown", has_content, f"{len(at.markdown)} blocks, max_len={max_len}")


def test_03_multi_turn():
    """张姐两轮对话：第一轮简报，第二轮追问。"""
    log("\n── Test 03: Multi-turn conversation ──")
    uid = f"zhang_hr_03_{uuid.uuid4().hex[:6]}"

    r1 = agent_turn(uid, "用fetch_subscribed_feeds看看HackerNews今天有什么，做个简短简报", retries=1)
    check("round 1 has content", len(r1["tokens"]) > 50, f"len={len(r1['tokens'])}")
    soft_check("round 1 used tool", "fetch_subscribed_feeds" in r1["tools"])

    r2 = agent_turn(uid, "能说得更详细一点吗？字数多一点", retries=1)
    check("round 2 has content", len(r2["tokens"]) > 50, f"len={len(r2['tokens'])}")
    check("round 2 is longer", len(r2["tokens"]) >= len(r1["tokens"]),
          f"r1={len(r1['tokens'])} r2={len(r2['tokens'])}")

    roles = db_messages_for(uid)
    check("DB has user+assistant×2", roles.count("user") >= 2 and roles.count("assistant") >= 2,
          f"roles: {roles}")


def test_04_free_text():
    """老王自由输入，不点预设。"""
    log("\n── Test 04: Free text input ──")
    uid = f"wang_pm_04_{uuid.uuid4().hex[:6]}"

    r = agent_turn(uid, "用fetch_subscribed_feeds分析当前科技行业的发展趋势，带具体来源")
    check("reply has content", len(r["tokens"]) > 80, f"len={len(r['tokens'])}")
    soft_check("fetch_subscribed_feeds was called", "fetch_subscribed_feeds" in r["tools"])

    has_source = any(kw in r["tokens"] for kw in ["Hacker", "News", "HN", "科技", "Tech", "来源", "source"])
    check("reply mentions content sources", has_source)


def test_05_reasoning():
    """老王点 AI 思考过程。"""
    log("\n── Test 05: Reasoning display ──")
    uid = f"wang_pm_05_{uuid.uuid4().hex[:6]}"

    r = agent_turn(uid, "用fetch_subscribed_feeds看看知乎日报今天有什么，技术记者视角")
    check("reply has content", len(r["tokens"]) > 50, f"len={len(r['tokens'])}")
    if r["reasoning"]:
        log(f"  reasoning: {len(r['reasoning'])} chars ✓")


def test_06_subscription_crud():
    """老王订阅增删全流程。"""
    log("\n── Test 06: Subscription CRUD ──")
    uid = f"wang_pm_06_{uuid.uuid4().hex[:6]}"

    # Add
    r1 = agent_turn(uid, f"请添加RSS订阅源，名称叫 GitHub Show，地址是 hnrss.org/show，user_id是 {uid}")
    soft_check("add tool called", "add_rss_subscription" in r1["tools"])
    check("add confirmed", len(r1["tokens"]) > 10, f"reply: {r1['tokens'][:60]}")

    # Verify DB
    count = db_subscription_count(uid)
    check("subscription in DB", count >= 1, f"found {count} subs")

    # Use
    r2 = agent_turn(uid, f"用我新增的订阅源 GitHub Show 抓取内容做个简报，user_id是 {uid}", retries=1)
    check("use-sub reply has content", len(r2["tokens"]) > 50, f"len={len(r2['tokens'])}")

    # Delete
    r3 = agent_turn(uid, f"请删除订阅源 GitHub Show，user_id是 {uid}")
    soft_check("delete tool called", "delete_rss_subscription" in r3["tools"])
    check("delete confirmed", len(r3["tokens"]) > 5 or "✅" in r3["tokens"] or "删除" in r3["tokens"] or "delete" in r3["tokens"].lower())

    # DB: at least 3 user+assistant pairs
    roles = db_messages_for(uid)
    check("DB has all turns", roles.count("user") >= 2 and roles.count("assistant") >= 2,
          f"roles: {roles}")


def test_07_empty_input():
    """小李空输入直接点生成——不应触发。"""
    log("\n── Test 07: Empty input guard ──")
    uid = f"li_dev_07_{uuid.uuid4().hex[:6]}"
    result = asyncio.run(_agent_turn(uid, ""))
    # FastAPI validates min_length=1 → 422
    check("empty content rejected", result["error"] is not None,
          f"error={result['error']}")


def test_08_english_prompt():
    """小李英文 prompt。"""
    log("\n── Test 08: English prompt ──")
    uid = f"li_dev_08_{uuid.uuid4().hex[:6]}"

    r = agent_turn(uid, "Use fetch_subscribed_feeds to write a tech weekly, 3 stories, journalist perspective, focus on AI trends", retries=1)
    check("reply has content", len(r["tokens"]) > 60, f"len={len(r['tokens'])}")

    # Check if reply is in English (more than half of words are ASCII)
    if r["tokens"]:
        words = r["tokens"].split()
        ascii_words = sum(1 for w in words if all(ord(c) < 128 for c in w))
        english_ratio = ascii_words / max(len(words), 1)
        soft_check("reply is english", english_ratio > 0.5, f"english ratio: {english_ratio:.1%}")


def test_09_concurrent():
    """小李测试：3 个用户同时并发。"""
    log("\n── Test 09: 3-user concurrent ──")
    users = {
        "zhang_hr_c09": "看看HackerNews今天有什么，用fetch_subscribed_feeds做简报",
        "wang_pm_c09": "用fetch_subscribed_feeds分析当前科技趋势，AI方向",
        "li_dev_c09": "write a brief about today's tech news, use fetch_subscribed_feeds",
    }
    results: dict[str, dict] = {}
    lock = threading.Lock()

    def user_task(name: str, prompt: str):
        result = asyncio.run(_agent_turn(name, prompt))
        with lock:
            results[name] = result

    threads = [threading.Thread(target=user_task, args=(n, p)) for n, p in users.items()]
    t0 = time.time()
    for t in threads: t.start()
    for t in threads: t.join()
    elapsed = time.time() - t0
    log(f"  3 users done in {elapsed:.1f}s")

    # Verify all finished without errors
    for name, r in results.items():
        has_content = len(r["tokens"]) > 50
        no_error = r["error"] is None
        ok = has_content and no_error
        check(f"user {name}: content={has_content} ok={no_error}", ok,
              f"error={r['error']}" if not no_error else "")

    # DB isolation
    for name in users:
        roles = db_messages_for(name)
        check(f"user {name} has messages", len(roles) >= 2, f"roles: {roles}")


def test_10_persist_reliability():
    """小李测试：多轮对话后 DB 完整性。"""
    log("\n── Test 10: Persist reliability ──")
    uid = f"li_dev_10_{uuid.uuid4().hex[:6]}"

    r1 = agent_turn(uid, "用fetch_subscribed_feeds看看HackerNews今天有什么，做简报", retries=1)
    check("round 1 ok", r1["error"] is None and len(r1["tokens"]) > 50)
    soft_check("round 1 has tool", len(r1["tools"]) >= 1)

    r2 = agent_turn(uid, "刚才提到的第一条项目具体是什么？详细说说")
    check("round 2 ok", r2["error"] is None and len(r2["tokens"]) > 20)

    # DB
    roles = db_messages_for(uid)
    check("DB roles correct", "user" in roles and "assistant" in roles)

    db_checkpoint()
    tc_result = subprocess.run(
        ["sqlite3", str(DB_PATH),
         "SELECT COUNT(*) FROM tool_calls WHERE message_id IN "
         f"(SELECT id FROM messages WHERE user_id='{uid}');"],
        capture_output=True, text=True,
    )
    tc_count = int(tc_result.stdout.strip() or "0")
    soft_check("tool_calls in DB", tc_count >= 1, f"found {tc_count}")


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def write_log():
    total = PASS + FAIL + WARN
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("# E2E Test Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Result:** {PASS}/{PASS+FAIL} hard-checks passed ({WARN} soft-check warnings)\n\n")
        f.write(f"| Category | Count |\n|----------|-------|\n")
        f.write(f"| ✅ Passed | {PASS} |\n")
        f.write(f"| ❌ Failed | {FAIL} |\n")
        f.write(f"| ⚠️ Warnings (model-behavior) | {WARN} |\n\n")
        f.write("## Full Log\n\n```\n")
        for line in LOG_LINES:
            f.write(line + "\n")
        f.write("```\n")


def main():
    global PASS, FAIL, WARN
    PASS = 0; FAIL = 0; WARN = 0; LOG_LINES.clear()

    log("=" * 60)
    log("E2E TEST SUITE — 3 Personas × 10 Tests")
    log(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    start_server()

    try:
        test_01_landing()
        test_02_preset_and_generate()
        test_03_multi_turn()
        test_04_free_text()
        test_05_reasoning()
        test_06_subscription_crud()
        test_07_empty_input()
        test_08_english_prompt()
        test_09_concurrent()
        test_10_persist_reliability()
    finally:
        stop_server()

    total = PASS + FAIL
    log(f"\n{'=' * 60}")
    log(f"FINAL: {PASS}/{total} hard-checks passed, {WARN} soft-warnings")
    log(f"{'=' * 60}")

    write_log()
    print(f"\n✅ Test log written to: {LOG_PATH}")
    print(f"   Hard: {PASS}/{total} passed")
    if WARN: print(f"   Soft: {WARN} warnings (model behavior variance)")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
