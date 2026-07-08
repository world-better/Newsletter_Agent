#!/usr/bin/env python3
"""Streamlit web frontend for 任意门聚合简报.

Connects to the FastAPI agent backend via HTTP (same protocol as client.py).
Does NOT import agno/aiosqlite — keeps hot-plugin separation clean.
"""
from __future__ import annotations

import asyncio
import json
import os
import uuid

import httpx
import streamlit as st

# ── Config ──────────────────────────────────────────────────────────────────

FASTAPI_BASE = os.environ.get("AGENT_API_BASE", "http://127.0.0.1:8001")
API = f"{FASTAPI_BASE}/api/v1"

PRESETS = [
    "看看HackerNews今天最新有什么",
    "Show HN有什么有意思的新项目",
    "知乎日报今天聊了什么话题",
    "V2EX社区今天有什么技术讨论",
    "帮我聚合HackerNews和NYT的科技新闻",
    "BBC和NYT本周科技趋势",
]

# ── Page setup ──────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="任意门聚合简报",
    page_icon="🔍",
    layout="wide",
)
st.title("🔍 任意门聚合简报")
st.caption("基于 RSS 多源聚合 · AI 自动生成结构化简报")


# ── Session ─────────────────────────────────────────────────────────────────

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]


# ── SSE stream consumer ─────────────────────────────────────────────────────

async def _consume_sse(url: str) -> dict:
    """Read SSE stream, return dict with reasoning / content / tools / errors."""
    result = {"reasoning": [], "tokens": [], "tool_calls": [], "error": None}
    async with httpx.AsyncClient(timeout=120.0) as c:
        async with c.stream("GET", url) as resp:
            resp.raise_for_status()
            event_type = ""
            data_buf = ""
            async for line in resp.aiter_lines():
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
                    elif event_type == "reasoning":
                        try:
                            result["reasoning"].append(json.loads(data_buf).get("content", ""))
                        except json.JSONDecodeError:
                            pass
                    elif event_type == "tool_call":
                        try:
                            tc = json.loads(data_buf)
                            result["tool_calls"].append(tc.get("tool_name", ""))
                        except json.JSONDecodeError:
                            pass
                    elif event_type == "error":
                        result["error"] = data_buf
                    elif event_type == "done":
                        return result
                    event_type = ""
                    data_buf = ""
    return result


def stream_reply(user_id: str, prompt: str) -> dict:
    """Send prompt → consume SSE → return structured result."""
    return asyncio.run(_stream_reply_async(user_id, prompt))


async def _stream_reply_async(user_id: str, prompt: str) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as c:
        # Post message
        resp = await c.post(f"{API}/messages", json={"user_id": user_id, "content": prompt})
        resp.raise_for_status()
        msg_id = resp.json()["message_id"]
        # Consume SSE
        return await _consume_sse(f"{API}/messages/{msg_id}/stream")


# ── Sidebar: Subscription management ────────────────────────────────────────

async def _load_subs(user_id: str) -> list[dict]:
    async with httpx.AsyncClient(timeout=10.0) as c:
        r = await c.get(f"{API}/debug/history/{user_id}")
        r.raise_for_status()
        return r.json().get("messages", [])


def add_sub(user_id: str, name: str, url: str) -> str:
    """Send an add-subscription prompt to the agent."""
    return stream_reply(user_id, f"请添加一个RSS订阅订阅源，名称叫 {name}，地址是 {url}，user_id是 {user_id}")["tokens"]


def del_sub(user_id: str, name: str) -> str:
    """Send a delete-subscription prompt to the agent."""
    return stream_reply(user_id, f"请删除订阅源 {name}，user_id是 {user_id}")["tokens"]


def render_sidebar():
    st.sidebar.header("📡 管理订阅")
    st.sidebar.caption(f"会话 ID: `{st.session_state.user_id}`")

    # Add subscription
    st.sidebar.subheader("+ 添加订阅")
    sub_name = st.sidebar.text_input("名称", key="add_name", placeholder="例如: GitHub Trending")
    sub_url = st.sidebar.text_input("URL", key="add_url", placeholder="例如: https://hnrss.org/frontpage")
    if st.sidebar.button("添加订阅源"):
        if sub_name and sub_url:
            with st.sidebar:
                with st.spinner("添加中..."):
                    stream_reply(
                        st.session_state.user_id,
                        f"请添加RSS订阅源，名称叫 {sub_name}，地址是 {sub_url}，user_id是 {st.session_state.user_id}",
                    )
                st.success(f"已添加: {sub_name}")
                st.rerun()
        else:
            st.sidebar.warning("名称和URL不能为空")

    # Delete subscription
    st.sidebar.subheader("× 删除订阅")
    del_name = st.sidebar.text_input("要删除的订阅名称", key="del_name", placeholder="输入名称后点击删除")
    if st.sidebar.button("删除订阅源"):
        if del_name:
            with st.sidebar:
                with st.spinner("删除中..."):
                    stream_reply(
                        st.session_state.user_id,
                        f"请删除订阅源 {del_name}，user_id是 {st.session_state.user_id}",
                    )
                st.info(f"已删除: {del_name}")
                st.rerun()
        else:
            st.sidebar.warning("请输入要删除的订阅名称")

    # Current subscriptions (blurb)
    st.sidebar.divider()
    st.sidebar.caption(
        "默认订阅源：HackerNews · Show HN · NYT Tech · BBC Tech · 知乎日报 · V2EX\n\n"
        "你可以添加自己的 RSS 订阅源覆盖默认列表。"
    )


# ── Main UI ─────────────────────────────────────────────────────────────────

def main():
    render_sidebar()

    # Preset buttons
    st.subheader("💡 试试")
    cols = st.columns(3)
    if "chosen_preset" not in st.session_state:
        st.session_state.chosen_preset = ""
    for i, text in enumerate(PRESETS):
        col = cols[i % 3]
        if col.button(text, key=f"preset_{i}", use_container_width=True):
            st.session_state.chosen_preset = text

    # Input area
    st.subheader("📝 主题 / 任务")
    prompted = st.text_input(
        "输入你想了解的内容，或点上面的预设按钮",
        value=st.session_state.chosen_preset,
        key="prompt_input",
        placeholder="例如：帮我看看最近HackerNews和知乎有什么新东西...",
    )

    generate_btn = st.button("🚀 生成简报", type="primary", use_container_width=True)

    if generate_btn and prompted:
        st.session_state.chosen_preset = ""  # clear after use
        process_prompt(prompted)


def process_prompt(prompt: str):
    """Send prompt, show streaming results."""
    user_id = st.session_state.user_id

    # Progress containers
    status_area = st.empty()
    reasoning_expander = st.expander("💭 AI 思考过程", expanded=False)
    output_area = st.empty()
    tool_area = st.empty()
    source_area = st.empty()

    status_area.info("⏳ Agent 正在聚合信息...")

    result = stream_reply(user_id, prompt)

    if result.get("error"):
        status_area.error(f"❌ 出错了：{result['error']}")
        return

    # Reasoning
    reasoning_text = "".join(result.get("reasoning", []))
    if reasoning_text:
        reasoning_expander.markdown(
            f'<span style="color:#888;">{reasoning_text}</span>',
            unsafe_allow_html=True,
        )

    # Tool calls
    tools = result.get("tool_calls", [])
    if tools:
        tool_area.caption(f"🔧 调用工具：{' · '.join(tools)}")

    # Main output
    content = "".join(result.get("tokens", []))
    if content:
        status_area.empty()
        output_area.markdown(content)
    else:
        status_area.warning("Agent 没有返回内容。")

    # Sources
    source_area.divider()
    source_area.caption(
        "📡 信息来源：RSS 多源聚合 (HackerNews · Show HN · NYT Technology · BBC Technology · 知乎日报 · V2EX)"
    )


if __name__ == "__main__":
    main()
