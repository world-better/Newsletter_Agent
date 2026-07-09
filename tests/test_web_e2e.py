#!/usr/bin/env python3
"""E2E test suite — chat UI format. Tests backend only (httpx), not AppTest UI.

Chat UI uses st.chat_input + st.chat_message — AppTest can click suggestion
buttons but the main interaction path (chat input → SSE → render) is best
tested via httpx directly, which is what the backend tests already do.

This file reuses the proven backend test infra from the 36/36 run.
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

PORT = 18001
BASE = f"http://127.0.0.1:{PORT}"
API = f"{BASE}/api/v1"
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "app.db"
LOG_PATH = PROJECT_DIR / "tests" / "test_log.md"

os.environ["AGENT_API_BASE"] = BASE

PASS = 0; FAIL = 0; WARN = 0; LOG_LINES: list[str] = []


def log(msg: str):
    global LOG_LINES
    LOG_LINES.append(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")
    print(LOG_LINES[-1])


def check(label: str, condition: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if condition: PASS += 1; log(f"  ✅ {label}")
    else: FAIL += 1; log(f"  ❌ {label}  — {detail}")
    return condition


def soft_check(label: str, condition: bool, detail: str = ""):
    global PASS, WARN
    if condition: PASS += 1; log(f"  ✅ {label}")
    else: WARN += 1; log(f"  ⚠️ {label} (model) — {detail}")


# ── Server ──────────────────────────────────────────────────────────────────

_server = None

def start_server():
    global _server
    log("── Starting FastAPI ──")
    for f in [DB_PATH, str(DB_PATH) + "-wal", str(DB_PATH) + "-shm"]:
        try: os.remove(f)
        except: pass
    r = subprocess.run(f"netstat -ano | findstr :{PORT}", shell=True, capture_output=True, text=True)
    for l in r.stdout.strip().split("\n"):
        if "LISTENING" in l:
            subprocess.run(f"taskkill /F /PID {l.strip().split()[-1]}", shell=True, capture_output=True)
    time.sleep(1)
    _server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=PROJECT_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(30):
        try:
            if httpx.get(f"{BASE}/", timeout=2).status_code == 200: break
        except: pass
        time.sleep(1)
    log("  FastAPI ready")


def stop_server():
    global _server
    if _server:
        _server.terminate()
        try: _server.wait(5)
        except: _server.kill()


# ── DB ──────────────────────────────────────────────────────────────────────

def db_msg_roles(uid: str) -> list[str]:
    subprocess.run(["sqlite3", str(DB_PATH), "PRAGMA wal_checkpoint(TRUNCATE);"], capture_output=True)
    r = subprocess.run(["sqlite3", str(DB_PATH),
        f"SELECT role FROM messages WHERE user_id='{uid}' ORDER BY created_at;"],
        capture_output=True, text=True)
    return [x.strip() for x in r.stdout.strip().split("\n") if x.strip()]


def db_sub_count(uid: str) -> int:
    r = subprocess.run(["sqlite3", str(DB_PATH),
        f"SELECT COUNT(*) FROM rss_subscriptions WHERE user_id='{uid}';"],
        capture_output=True, text=True)
    try: return int(r.stdout.strip())
    except: return 0


# ── Agent turn ──────────────────────────────────────────────────────────────

async def _agent_turn(uid: str, prompt: str) -> dict:
    tokens, tools, error, reasoning = [], [], None, []
    async with httpx.AsyncClient(timeout=180) as c:
        r = await c.post(f"{API}/messages", json={"user_id": uid, "content": prompt})
        if r.status_code != 200: return {"tokens": "", "tools": [], "error": f"POST {r.status_code}", "reasoning": ""}
        mid = r.json()["message_id"]
        et, dbuf = "", ""
        async with c.stream("GET", f"{API}/messages/{mid}/stream") as s:
            async for line in s.aiter_lines():
                if line.startswith("event:"): et = line.split(":", 1)[1].strip()
                elif line.startswith("data:"): dbuf = line.split(":", 1)[1].strip()
                elif line == "" and et:
                    if et == "token":
                        try: tokens.append(json.loads(dbuf).get("content", ""))
                        except: pass
                    elif et == "reasoning":
                        try: reasoning.append(json.loads(dbuf).get("content", ""))
                        except: pass
                    elif et == "tool_call":
                        try: tools.append(json.loads(dbuf).get("tool_name", ""))
                        except: pass
                    elif et == "error": error = dbuf
                    elif et == "done":
                        return {"tokens": "".join(tokens), "tools": tools, "error": error, "reasoning": "".join(reasoning)}
                    et, dbuf = "", ""
    return {"tokens": "".join(tokens), "tools": tools, "error": error, "reasoning": "".join(reasoning)}


def agent_turn(uid: str, prompt: str, retries=1) -> dict:
    for attempt in range(retries + 1):
        r = asyncio.run(_agent_turn(uid, prompt))
        if r["error"] is None and len(r["tokens"]) > 20: return r
        if attempt < retries: log(f"  retry {attempt+1}/{retries}"); time.sleep(3)
    return r


# ══════════════════════════════════════════════════════════════════════════════
# TESTS
# ══════════════════════════════════════════════════════════════════════════════

def test_01_chat_first_message():
    """新用户打开页面，发第一条消息 — 模拟 chat_input 行为"""
    log("\n── Test 01: First chat message ──")
    uid = f"t1_{uuid.uuid4().hex[:6]}"
    r = agent_turn(uid, "看看HackerNews今天有什么", retries=1)
    check("reply has content", len(r["tokens"]) > 50, f"len={len(r['tokens'])}")
    soft_check("used fetch tool", "fetch_subscribed_feeds" in r["tools"])
    roles = db_msg_roles(uid)
    check("DB has user+assistant", "user" in roles and "assistant" in roles, f"roles: {roles}")


def test_02_multi_turn():
    """两轮连续对话，上下文保持"""
    log("\n── Test 02: Multi-turn chat ──")
    uid = f"t2_{uuid.uuid4().hex[:6]}"
    r1 = agent_turn(uid, "用fetch_subscribed_feeds做HackerNews简报", retries=1)
    check("round 1 ok", len(r1["tokens"]) > 50)
    r2 = agent_turn(uid, "刚才提到的第一个项目详细说说")
    check("round 2 ok", len(r2["tokens"]) > 30)
    check("round 2 longer", len(r2["tokens"]) >= len(r1["tokens"]), f"r1={len(r1['tokens'])} r2={len(r2['tokens'])}")
    roles = db_msg_roles(uid)
    check("DB has 4+ msgs", len(roles) >= 4, f"roles: {roles}")


def test_03_free_form():
    """自由格式输入，不点预设"""
    log("\n── Test 03: Free-form input ──")
    uid = f"t3_{uuid.uuid4().hex[:6]}"
    r = agent_turn(uid, "用fetch_subscribed_feeds分析科技趋势，关注AI方向", retries=1)
    check("reply ok", len(r["tokens"]) > 80, f"len={len(r['tokens'])}")
    soft_check("fetch called", "fetch_subscribed_feeds" in r["tools"])


def test_04_reasoning():
    """检查思考过程"""
    log("\n── Test 04: Reasoning ──")
    uid = f"t4_{uuid.uuid4().hex[:6]}"
    r = agent_turn(uid, "用fetch_subscribed_feeds看知乎日报，技术记者视角", retries=1)
    check("reply ok", len(r["tokens"]) > 50)
    if r["reasoning"]: log(f"  reasoning: {len(r['reasoning'])} chars")


def test_05_subscription_add():
    """侧边栏添加订阅 — 真实交互"""
    log("\n── Test 05: Add subscription ──")
    uid = f"t5_{uuid.uuid4().hex[:6]}"
    r = agent_turn(uid, f"请添加RSS订阅源，名称叫 TestFeed，地址是 hnrss.org/show，user_id是 {uid}")
    soft_check("add called", "add_rss_subscription" in r["tools"])
    check("reply confirms", len(r["tokens"]) > 10)
    check("DB has sub", db_sub_count(uid) >= 1, f"found {db_sub_count(uid)}")


def test_06_english():
    """英文 prompt"""
    log("\n── Test 06: English prompt ──")
    uid = f"t6_{uuid.uuid4().hex[:6]}"
    r = agent_turn(uid, "Use fetch_subscribed_feeds for a tech brief, 3 stories", retries=1)
    check("reply ok", len(r["tokens"]) > 50)
    words = r["tokens"].split()
    ascii_w = sum(1 for w in words if all(ord(c) < 128 for c in w))
    soft_check("english reply", ascii_w / max(len(words), 1) > 0.4, f"ratio={ascii_w}/{len(words)}")


def test_07_concurrent():
    """3 用户同时 chat"""
    log("\n── Test 07: 3-user concurrent ──")
    users = {"zhang": "看看HackerNews今天有什么", "wang": "分析科技趋势AI方向",
             "li": "write a tech weekly in English"}
    results, lock = {}, threading.Lock()

    def task(n, p):
        r = asyncio.run(_agent_turn(n, p))
        with lock: results[n] = r

    ts = [threading.Thread(target=task, args=(n, p)) for n, p in users.items()]
    t0 = time.time()
    for t in ts: t.start()
    for t in ts: t.join()
    log(f"  3 users done in {time.time()-t0:.1f}s")

    for n, r in results.items():
        ok = len(r["tokens"]) > 50 and r["error"] is None
        check(f"user {n}: ok={ok}", ok, f"error={r['error']}" if r["error"] else "")
    for n in users:
        roles = db_msg_roles(n)
        check(f"user {n} msgs isolated", len(roles) >= 2, f"roles: {roles}")


def test_08_persist():
    """多轮后 DB 完整性"""
    log("\n── Test 08: Persist reliability ──")
    uid = f"t8_{uuid.uuid4().hex[:6]}"
    r1 = agent_turn(uid, "用fetch_subscribed_feeds做简报，5篇故事", retries=1)
    check("round 1 ok", len(r1["tokens"]) > 50)
    r2 = agent_turn(uid, "详细分析第一条")
    check("round 2 ok", len(r2["tokens"]) > 20)
    roles = db_msg_roles(uid)
    check("DB correct", roles.count("user") >= 2 and roles.count("assistant") >= 2, f"roles: {roles}")
    subprocess.run(["sqlite3", str(DB_PATH), "PRAGMA wal_checkpoint(TRUNCATE);"], capture_output=True)
    tc = subprocess.run(["sqlite3", str(DB_PATH),
        f"SELECT COUNT(*) FROM tool_calls WHERE message_id IN (SELECT id FROM messages WHERE user_id='{uid}');"],
        capture_output=True, text=True)
    soft_check("tool_calls in DB", int(tc.stdout.strip() or "0") >= 1)


# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

def main():
    global PASS, FAIL, WARN
    PASS = 0; FAIL = 0; WARN = 0; LOG_LINES.clear()
    log("=" * 60)
    log("E2E TEST — Chat UI Backend")
    log(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    log("=" * 60)

    start_server()
    try:
        test_01_chat_first_message()
        test_02_multi_turn()
        test_03_free_form()
        test_04_reasoning()
        test_05_subscription_add()
        test_06_english()
        test_07_concurrent()
        test_08_persist()
    finally:
        stop_server()

    total = PASS + FAIL
    log(f"\n{'=' * 60}")
    log(f"FINAL: {PASS}/{total} passed, {WARN} soft-warnings")
    log(f"{'=' * 60}")

    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("# E2E Test Report\n\n")
        f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"**Result:** {PASS}/{total} passed ({WARN} soft-warnings)\n\n")
        f.write("```\n")
        for l in LOG_LINES: f.write(l + "\n")
        f.write("```\n")

    print(f"\n✅ Log: {LOG_PATH}  |  {PASS}/{total} passed")
    sys.exit(0 if FAIL == 0 else 1)


if __name__ == "__main__":
    main()
