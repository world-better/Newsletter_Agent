#!/usr/bin/env python3
"""Simulate real conversation: add RSS subscriptions, fetch feeds, verify DB."""
import asyncio
import json
import os
import subprocess
import sys

import httpx

USER_ID = "editor_chief_01"
PORT = 18999
BASE = f"http://127.0.0.1:{PORT}"
API = f"{BASE}/api/v1"
DB = os.path.abspath("app.db")


def kill_port(port: int):
    """Kill any process listening on the given port (Windows)."""
    result = subprocess.run(f"netstat -ano | findstr :{port}", shell=True, capture_output=True, text=True)
    for line in result.stdout.strip().split("\n"):
        parts = line.strip().split()
        if len(parts) >= 5 and "LISTENING" in line:
            pid = parts[-1]
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)


async def send_and_show(client, msg: str):
    """Send message and stream reply to stdout."""
    r = await client.post(f"{API}/messages", json={"user_id": USER_ID, "content": msg})
    mid = r.json()["message_id"]

    async with client.stream("GET", f"{API}/messages/{mid}/stream") as s:
        event_type = ""
        data_buf = ""
        async for line in s.aiter_lines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_buf = line.split(":", 1)[1].strip()
            elif line == "" and event_type:
                if event_type == "token":
                    try:
                        print(json.loads(data_buf).get("content", ""), end="", flush=True)
                    except json.JSONDecodeError:
                        pass
                elif event_type == "tool_call":
                    try:
                        tc = json.loads(data_buf)
                        args_preview = tc.get("arguments", "")[:80]
                        print(f"\n🔧 [TOOL] {tc.get('tool_name', '')}  args={args_preview}", flush=True)
                    except json.JSONDecodeError:
                        pass
                elif event_type == "done":
                    print()
                    return
                elif event_type == "error":
                    print(f"\n❌ ERROR: {data_buf}")
                    return
                event_type = ""
                data_buf = ""


def db_check(label: str):
    subprocess.run(["sqlite3", DB, "PRAGMA wal_checkpoint(TRUNCATE);"], capture_output=True)
    r = subprocess.run(
        ["sqlite3", DB, "SELECT name, url FROM rss_subscriptions;"],
        capture_output=True, text=True,
    )
    print(f"  [db:{label}] subscriptions: {r.stdout.strip() or '(empty)'}")


async def main():
    # Clean DB
    for f in [DB, DB + "-wal", DB + "-shm"]:
        try:
            os.remove(f)
        except FileNotFoundError:
            pass
        except PermissionError:
            pass  # will be handled later

    # Kill only the test port (not our own PID)
    kill_port(PORT)
    await asyncio.sleep(1)

    # Start server
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "info"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    # Async reader for server stdout (prints relevant lines)
    async def log_reader():
        while True:
            line = await asyncio.get_event_loop().run_in_executor(None, server.stdout.readline)
            if not line:
                break
            decoded = line.decode(errors="replace").rstrip()
            if any(kw in decoded.lower() for kw in ["error", "hook", "tool", "warning", "persist", "traceback", "exception"]):
                print(f"  ⚙️ {decoded}", flush=True)
    asyncio.create_task(log_reader())

    async with httpx.AsyncClient(timeout=120.0) as c:
        # Wait for server
        for i in range(30):
            try:
                r = await c.get(f"{BASE}/", timeout=2.0)
                if r.status_code == 200:
                    print(f"[setup] Server ready after ~{i}s")
                    break
            except Exception:
                pass
            await asyncio.sleep(1)
        else:
            print("[FATAL] Server didn't start")
            server.kill()
            sys.exit(1)

        try:
            # ── Conversation 1: Add Hacker News RSS ──
            print("=" * 60)
            print("ROUND 1: 添加订阅 hnrss.org/frontpage → Hacker News")
            print("=" * 60)
            await send_and_show(c, "请添加RSS订阅源，地址是 hnrss.org/frontpage，订阅名称叫 Hacker News")
            db_check("after round 1")

            # ── Conversation 2: Add Elon Musk RSS ──
            print()
            print("=" * 60)
            print("ROUND 2: 添加订阅 nitter.net/elonmusk/rss → Elon Musk")
            print("=" * 60)
            await send_and_show(c, "再添加一个订阅，地址是 nitter.net/elonmusk/rss，名称叫 Elon Musk")
            db_check("after round 2")

            # ── Conversation 3: Fetch and brief ──
            print()
            print("=" * 60)
            print("ROUND 3: 抓取所有订阅源，生成简报")
            print("=" * 60)
            await send_and_show(
                c,
                "请帮我抓取我所有订阅源的最新内容，整合成简报，每个源取3篇，技术记者视角，关注AI和科技趋势",
            )
            db_check("after round 3")

            # ── Conversation 4: Direct HackerNews tool ──
            print()
            print("=" * 60)
            print("ROUND 4: 直接调用 generate_creative_brief 获取 HackerNews")
            print("=" * 60)
            await send_and_show(
                c,
                "请使用 generate_creative_brief 生成 HackerNews 简报，5篇，技术记者视角，关注 AI 和创业公司",
            )

            # ── Verify DB ──
            print()
            print("=" * 60)
            print("DB VERIFICATION")
            print("=" * 60)
            subprocess.run(["sqlite3", DB, "PRAGMA wal_checkpoint(TRUNCATE);"], capture_output=True)
            r = subprocess.run(
                ["sqlite3", DB, "SELECT role, substr(content,1,60) FROM messages;"],
                capture_output=True, text=True,
            )
            print("【messages】")
            print(r.stdout)
            r2 = subprocess.run(
                ["sqlite3", DB, "SELECT tool_name, substr(arguments,1,60) FROM tool_calls;"],
                capture_output=True, text=True,
            )
            print("【tool_calls】")
            print(r2.stdout)
            r3 = subprocess.run(
                ["sqlite3", DB, "SELECT name, url FROM rss_subscriptions;"],
                capture_output=True, text=True,
            )
            print("【subscriptions】")
            print(r3.stdout)

        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()


if __name__ == "__main__":
    asyncio.run(main())
