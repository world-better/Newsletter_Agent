#!/usr/bin/env python3
"""Interactive CLI client for the Agent API.

Connects to the running FastAPI server, manages multi-user sessions,
and streams agent responses token-by-token via SSE.

Usage:
    python client.py              # interactive persona selection
    python client.py --user 1     # skip selection, use persona #1
    python client.py --user 2     # skip selection, use persona #2

Requires: httpx  (pip install httpx)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

import httpx

BASE_URL = "http://127.0.0.1:8001"
API_PREFIX = "/api/v1"

PERSONAS: dict[str, dict[str, str]] = {
    "1": {"id": "editor_chief_01", "name": "Editor-in-Chief (Kee)"},
    "2": {"id": "tech_analyst_02", "name": "Tech Analyst (Beta)"},
    "3": {"id": "design_critic_03", "name": "Design Critic (Gamma)"},
    "4": {"id": "guest_reviewer_04", "name": "Guest Reviewer (Delta)"},
    "5": {"id": "billing_admin_05", "name": "System Admin (Omega)"},
}


# ── Argument parsing ─────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Agent API interactive CLI")
    parser.add_argument(
        "--user", "-u",
        choices=list(PERSONAS.keys()),
        help="Persona number (1–5). Omit for interactive selection.",
    )
    parser.add_argument(
        "--host", default="127.0.0.1",
        help="Server host (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port", default=8001, type=int,
        help="Server port (default: 8001)",
    )
    return parser.parse_args()


# ── Persona selection ────────────────────────────────────────────────────────

def select_persona(key: str | None) -> tuple[str, str, str]:
    """Return (user_id, display_name, selection_key)."""
    if key and key in PERSONAS:
        p = PERSONAS[key]
        return p["id"], p["name"], key

    print("=" * 50)
    print("  AGENT API — Interactive CLI")
    print("=" * 50)
    for k, profile in PERSONAS.items():
        print(f"  [{k}] {profile['name']}  ({profile['id']})")

    while True:
        c = input("\nSelect persona [1-5]: ").strip()
        if c in PERSONAS:
            p = PERSONAS[c]
            return p["id"], p["name"], c
        print(f"  Invalid: {c!r}")


# ── ANSI display helpers ──────────────────────────────────────────────────

_STYLES = {
    "reasoning": "\033[90m",   # gray/dim for model thinking
    "token":     "\033[92m",   # green for answer content
    "tool_call": "\033[94m",   # blue for tool calls
    "error":     "\033[91m",   # red for errors
    "reset":     "\033[0m",
}


# ── SSE stream consumer ──────────────────────────────────────────────────────

async def _stream_events(client: httpx.AsyncClient, url: str):
    """Read SSE stream line-by-line, yield (event_type, content) tuples."""
    async with client.stream("GET", url) as resp:
        resp.raise_for_status()
        event_type = ""
        data_buffer = ""

        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                event_type = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_buffer = line.split(":", 1)[1].strip()
            elif line == "" and event_type:
                if event_type in ("token", "reasoning"):
                    try:
                        payload = json.loads(data_buffer)
                        content = payload.get("content", data_buffer)
                    except json.JSONDecodeError:
                        content = data_buffer
                    yield event_type, content
                elif event_type == "tool_call":
                    yield event_type, data_buffer
                elif event_type == "error":
                    yield event_type, data_buffer
                elif event_type == "done":
                    return
                event_type = ""
                data_buffer = ""


# ── Main CLI loop ────────────────────────────────────────────────────────────

async def launch_cli(host: str, port: int, user_key: str | None):
    base_url = f"http://{host}:{port}{API_PREFIX}"
    user_id, user_name, choice = select_persona(user_key)

    print(f"\n  [MOUNTED] {user_name}  (ID: {user_id})")
    print("  Type 'exit' or 'quit' to disconnect.\n")

    async with httpx.AsyncClient(timeout=120.0) as client:
        # ── Connection check ──
        try:
            await client.get(f"http://{host}:{port}/", timeout=3.0)
        except httpx.ConnectError:
            print(f"  [FATAL] Cannot connect to {host}:{port}")
            print(f"          Start the server with:  uvicorn app.main:app --reload")
            sys.exit(1)
        except httpx.HTTPError:
            pass  # server is up, route might not exist yet

        # ── REPL loop ──
        while True:
            try:
                raw = input(f"  user: {choice} | ")
            except (EOFError, KeyboardInterrupt):
                print("\n  [EXIT] Interrupted.")
                break

            text = raw.strip()
            if text.lower() in ("exit", "quit"):
                print("  [EXIT] Disconnecting...")
                break
            if not text:
                continue

            # Send message
            try:
                resp = await client.post(
                    f"{base_url}/messages",
                    json={"user_id": user_id, "content": text},
                )
                resp.raise_for_status()
                message_id = resp.json()["message_id"]
            except httpx.HTTPError as exc:
                print(f"  [HTTP ERROR] {exc}")
                continue

            # Stream reply with styled output
            sys.stdout.write("  agent          | ")
            sys.stdout.flush()

            try:
                async for ev_type, content in _stream_events(client, f"{base_url}/messages/{message_id}/stream"):
                    style = _STYLES.get(ev_type, "")
                    reset = _STYLES["reset"]
                    if ev_type == "error":
                        sys.stdout.write(f"{style}{content}{reset}")
                    elif ev_type == "tool_call":
                        # Show tool calls in blue, then continue on same line
                        sys.stdout.write(f"{style}[tool] {content[:60]}{reset}")
                    elif ev_type == "reasoning":
                        sys.stdout.write(f"{style}{content}{reset}")
                    elif ev_type == "token":
                        sys.stdout.write(f"{style}{content}{reset}")
                    sys.stdout.flush()
            except httpx.HTTPError as exc:
                sys.stdout.write(f"[STREAM ERROR] {exc}")

            sys.stdout.write("\n")
            sys.stdout.flush()


def main():
    args = parse_args()
    try:
        asyncio.run(launch_cli(args.host, args.port, args.user))
    except KeyboardInterrupt:
        print("\n  [EXIT] Interrupted.")


if __name__ == "__main__":
    main()
