#!/usr/bin/env python3
"""Verify Phase 1: no generate_creative_brief, default subscriptions, fallback."""
import asyncio
import json
import os
import subprocess
import sys

import httpx

USER_ID = "phase1_test_user"
PORT = 19999
BASE = f"http://127.0.0.1:{PORT}"
API = f"{BASE}/api/v1"
DB = os.path.abspath("app.db")


def kill_port(port):
    result = subprocess.run(f"netstat -ano | findstr :{port}", shell=True, capture_output=True, text=True)
    for line in result.stdout.strip().split("\n"):
        if "LISTENING" in line:
            pid = line.strip().split()[-1]
            subprocess.run(f"taskkill /F /PID {pid}", shell=True, capture_output=True)


async def send_and_stream(client, msg):
    r = await client.post(f"{API}/messages", json={"user_id": USER_ID, "content": msg})
    mid = r.json()["message_id"]
    result = {"tokens": [], "tool_calls": [], "error": None}
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
                        result["tokens"].append(json.loads(data_buf).get("content", ""))
                    except json.JSONDecodeError:
                        pass
                elif event_type == "tool_call":
                    try:
                        tc = json.loads(data_buf)
                        result["tool_calls"].append(tc.get("tool_name", ""))
                    except json.JSONDecodeError:
                        pass
                elif event_type == "done":
                    return result
                elif event_type == "error":
                    result["error"] = data_buf
                    return result
                event_type = ""
                data_buf = ""
    return result


async def main():
    # Clean
    for f in [DB, DB + "-wal", DB + "-shm"]:
        try:
            os.remove(f)
        except (FileNotFoundError, PermissionError):
            pass
    kill_port(PORT)
    await asyncio.sleep(1)

    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(PORT), "--log-level", "warning"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    passed = 0
    failed = 0

    async with httpx.AsyncClient(timeout=120.0) as c:
        # Wait
        for _ in range(30):
            try:
                if (await c.get(f"{BASE}/", timeout=2.0)).status_code == 200:
                    break
            except Exception:
                pass
            await asyncio.sleep(1)

        try:
            # ── Test 1: New user with no subs should still get content ──
            print("Test 1: New user fetch_subscribed_feeds (should fall back to default)")
            r = await send_and_stream(c, "帮我看看今天有什么科技新闻，用fetch_subscribed_feeds获取内容")
            print(f"  tools called: {r['tool_calls']}")
            print(f"  tokens ({len(''.join(r['tokens']))} chars)")
            if "fetch_subscribed_feeds" in r["tool_calls"]:
                print("  ✅ fetch_subscribed_feeds was called")
                passed += 1
            else:
                print("  ❌ fetch_subscribed_feeds NOT called")
                failed += 1

            if len("".join(r["tokens"])) > 50:
                print("  ✅ Agent returned content")
                passed += 1
            else:
                print("  ❌ Agent returned little or no content")
                failed += 1

            # ── Test 2: Check DB for default subscriptions ──
            print("\nTest 2: Default subscriptions in DB")
            subprocess.run(["sqlite3", DB, "PRAGMA wal_checkpoint(TRUNCATE);"], capture_output=True)
            subs_result = subprocess.run(
                ["sqlite3", DB, "SELECT name, url FROM rss_subscriptions WHERE user_id='default_user' ORDER BY name;"],
                capture_output=True, text=True,
            )
            if subs_result.stdout.strip():
                print(f"  subscribed:\n{subs_result.stdout}")
                passed += 1
            else:
                print("  ❌ No default subscriptions found")
                failed += 1

            # ── Test 3: Verify generate_creative_brief is NOT in agent tools ──
            print("\nTest 3: generate_creative_brief should NOT exist")
            # Use the agent a few times to collect tools it tries to use
            r3 = await send_and_stream(c, "你有哪些工具可以用？列出名称即可。")
            reply = "".join(r3["tokens"])
            if "generate_creative_brief" in reply.lower():
                print("  ❌ Agent still mentions generate_creative_brief")
                failed += 1
            else:
                print("  ✅ Agent does NOT mention generate_creative_brief")
                passed += 1

        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()

    total = passed + failed
    print(f"\n{'=' * 50}")
    print(f"Phase 1 RESULTS: {passed}/{total} passed, {failed} failed")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
