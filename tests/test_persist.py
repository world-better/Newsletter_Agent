#!/usr/bin/env python3
"""End-to-end verification: start server → simulate conversation → verify DB records.

Usage:
    python tests/test_persist.py

Requires: httpx  (pip install httpx)
"""
import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

# Configuration
PORT = 18888  # Different from dev to avoid conflicts
BASE = f"http://127.0.0.1:{PORT}"
API = f"{BASE}/api/v1"
PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "app.db"
DB_WAL = PROJECT_DIR / "app.db-wal"
DB_SHM = PROJECT_DIR / "app.db-shm"
USER_ID = "test_user_01"
PASS = 0
FAIL = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}  {detail}")


async def send_and_stream(content: str) -> dict:
    """Send a message and consume the full SSE stream. Return gathered data."""
    async with httpx.AsyncClient(timeout=60.0) as c:
        # ── Send message ──
        resp = await c.post(f"{API}/messages", json={"user_id": USER_ID, "content": content})
        resp.raise_for_status()
        msg_id = resp.json()["message_id"]

        # ── Stream events ──
        reply_parts = []
        has_done = False
        has_tool = False
        has_reasoning = False

        async with c.stream("GET", f"{API}/messages/{msg_id}/stream") as stream:
            stream.raise_for_status()
            event_type = ""
            data_buf = ""
            async for line in stream.aiter_lines():
                if line.startswith("event:"):
                    event_type = line.split(":", 1)[1].strip()
                elif line.startswith("data:"):
                    data_buf = line.split(":", 1)[1].strip()
                elif line == "" and event_type:
                    if event_type == "token":
                        try:
                            reply_parts.append(json.loads(data_buf).get("content", data_buf))
                        except json.JSONDecodeError:
                            reply_parts.append(data_buf)
                    elif event_type == "reasoning":
                        has_reasoning = True
                    elif event_type == "tool_call":
                        has_tool = True
                    elif event_type == "done":
                        has_done = True
                    elif event_type == "error":
                        return {"error": data_buf, "msg_id": msg_id}
                    event_type = ""
                    data_buf = ""

        return {
            "msg_id": msg_id,
            "reply": "".join(reply_parts),
            "has_done": has_done,
            "has_tool": has_tool,
            "has_reasoning": has_reasoning,
        }


async def check_db() -> dict:
    """Fetch conversation history directly from sqlite3."""
    # Give SQLite time to flush WAL
    await asyncio.sleep(0.5)
    # Force checkpoint so CLI sees all data
    subprocess.run(
        ["sqlite3", str(DB_PATH), "PRAGMA wal_checkpoint(TRUNCATE);"],
        capture_output=True, timeout=5,
    )
    result = subprocess.run(
        ["sqlite3", str(DB_PATH),
         "SELECT role FROM messages ORDER BY created_at ASC;"],
        capture_output=True, text=True, timeout=5,
    )
    roles = [r.strip() for r in result.stdout.strip().split("\n") if r.strip()]
    return {
        "count": len(roles),
        "roles": roles,
    }


async def main():
    global PASS, FAIL

    print("=" * 60)
    print("PERSISTENCE VERIFICATION")
    print("=" * 60)

    # ── Clean DB ──
    for f in [DB_PATH, DB_WAL, DB_SHM]:
        if f.exists():
            f.unlink()
    print(f"\n[setup] Cleaned DB at {DB_PATH}")

    # ── Kill anything on our port ──
    subprocess.run(
        f"taskkill //F //PID $(netstat -ano | grep ':{PORT} ' | awk '{{print $5}}' | tail -1) 2>nul || true",
        shell=True,
    )
    await asyncio.sleep(1)

    # ── Start server ──
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        cwd=PROJECT_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    print(f"[setup] Server PID {server.pid} starting on port {PORT}...")

    # ── Wait for server ──
    started = False
    for i in range(60):
        try:
            async with httpx.AsyncClient(timeout=2.0) as c:
                r = await c.get(f"{BASE}/", timeout=2.0)
                if r.status_code == 200:
                    print(f"[setup] Server ready after ~{i}s\n")
                    started = True
                    break
        except (httpx.ConnectError, httpx.TimeoutException):
            pass
        await asyncio.sleep(0.5)
    if not started:
        stderr = server.stderr.read().decode(errors="replace")[:500] if server.stderr else "?"
        print(f"[FATAL] Server didn't start. stderr: {stderr}")
        server.kill()
        sys.exit(1)

    try:
        # ════════════════════════════════════════════════
        # TEST 1: Simple greeting (no tool call)
        # ════════════════════════════════════════════════
        print("── Test 1: Simple greeting (no tool call) ──")
        r1 = await send_and_stream("你好，请介绍一下你自己，不要调用工具")
        check("message sent and streamed", "error" not in r1)
        check("DONE event received", r1.get("has_done", False))
        check("has non-empty reply", len(r1.get("reply", "")) > 20)

        await asyncio.sleep(0.5)
        db1 = await check_db()
        check("DB has 2 messages (user+assistant)", db1["count"] >= 2,
              f"got {db1['count']}: {db1['roles']}")
        check("role 'assistant' present", "assistant" in db1["roles"],
              f"roles: {db1['roles']}")

        # ════════════════════════════════════════════════
        # TEST 2: Tool-calling request
        # ════════════════════════════════════════════════
        print("\n── Test 2: Tool-calling request ──")
        r2 = await send_and_stream("请调用工具 generate_creative_brief 生成3篇故事的简报，技术记者视角")
        check("message sent and streamed", "error" not in r2)
        check("DONE event received", r2.get("has_done", False))
        check("TOOL_CALL event received", r2.get("has_tool", False),
              "model may have chosen not to call a tool")

        await asyncio.sleep(0.5)
        db2 = await check_db()
        check("DB has 4+ messages", db2["count"] >= 4,
              f"got {db2['count']}: {db2['roles']}")
        check("roles include user+assistant+assistant",
              db2["roles"].count("user") >= 2 and db2["roles"].count("assistant") >= 2,
              f"roles: {db2['roles']}")

        # ════════════════════════════════════════════════
        # TEST 3: Check tool_calls table
        # ════════════════════════════════════════════════
        print("\n── Test 3: tool_calls table ──")
        subprocess.run(
            ["sqlite3", str(DB_PATH), "PRAGMA wal_checkpoint(TRUNCATE);"],
            capture_output=True, timeout=5,
        )
        tc_result = subprocess.run(
            ["sqlite3", str(DB_PATH), "SELECT tool_name, substr(result,1,50) FROM tool_calls;"],
            capture_output=True, text=True, timeout=5,
        )
        tc_output = tc_result.stdout.strip()
        has_tool = len(tc_output) > 0
        check("tool_calls table has records", has_tool, f"got: {repr(tc_output[:100])}")

        # ════════════════════════════════════════════════
        # RESULTS
        # ════════════════════════════════════════════════
        total = PASS + FAIL
        print(f"\n{'=' * 60}")
        print(f"RESULTS: {PASS}/{total} passed, {FAIL} failed")
        print(f"{'=' * 60}")

        if FAIL > 0:
            print("\n⚠️  Some checks failed. See ❌ above for details.")
            sys.exit(1)
        else:
            print("\n🎉 ALL CHECKS PASSED — persistence works correctly!\n")
            print("DB now has:")
            print(f"  - {db2['count']} messages (user + assistant roles)")
            print(f"  - roles: {db2['roles']}")
            if r2.get("has_tool"):
                print("  - tool_calls logged")
            sys.exit(0)

    finally:
        # ── Cleanup ──
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()
        # Remove test DB
        for f in [DB_PATH, DB_WAL, DB_SHM]:
            if f.exists():
                f.unlink()


if __name__ == "__main__":
    asyncio.run(main())
