#!/usr/bin/env python3
"""One-click launcher: FastAPI backend + Streamlit frontend.

Usage:
    python web/start.py
    python web/start.py --api-port 8001 --web-port 8501
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent

parser = argparse.ArgumentParser(description="Start 任意门聚合简报")
parser.add_argument("--api-port", default=8001, type=int, help="FastAPI backend port")
parser.add_argument("--web-port", default=8501, type=int, help="Streamlit frontend port")
args = parser.parse_args()

print("=" * 50)
print("  任意门聚合简报")
print(f"  API:  http://127.0.0.1:{args.api_port}")
print(f"  Web:  http://127.0.0.1:{args.web_port}")
print("=" * 50)

# ── Start FastAPI ──
backend = subprocess.Popen(
    [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(args.api_port), "--log-level", "info"],
    cwd=PROJECT_DIR,
)
print(f"\n[backend] FastAPI PID {backend.pid} on :{args.api_port}")

# ── Wait for FastAPI ──
print("[backend] Waiting for startup...")
for _ in range(15):
    try:
        import httpx
        r = httpx.get(f"http://127.0.0.1:{args.api_port}/", timeout=1.0)
        if r.status_code == 200:
            print(f"[backend] Ready ✓")
            break
    except Exception:
        pass
    time.sleep(1)
else:
    print("[backend] ⚠️  Startup taking longer than expected, proceeding anyway...")

# ── Start Streamlit ──
frontend = subprocess.Popen(
    [sys.executable, "-m", "streamlit", "run", "web/app.py", "--server.port", str(args.web_port)],
    cwd=PROJECT_DIR,
)
print(f"[web] Streamlit PID {frontend.pid} on :{args.web_port}")

print(f"\n🔍 在浏览器中打开: http://127.0.0.1:{args.web_port}")
print("按 Ctrl+C 停止所有服务。\n")

try:
    frontend.wait()
except KeyboardInterrupt:
    print("\n[shutdown] 正在停止...")
    frontend.terminate()
    backend.terminate()
    frontend.wait()
    backend.wait()
    print("[shutdown] 已停止。")
