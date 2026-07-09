#!/usr/bin/env python3
"""Streamlit web frontend — AI chat format + subscription sidebar.

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

DEFAULT_SUBS = [
    ("Hacker News 头条", "hnrss.org/frontpage"),
    ("NYT Technology", "rss.nytimes.com/services/xml/rss/nyt/Technology.xml"),
    ("BBC Technology", "feeds.bbci.co.uk/news/technology/rss.xml"),
    ("知乎日报", "rsshub.rssforever.com/zhihu/daily"),
    ("V2EX 最新", "rsshub.rssforever.com/v2ex/topics/latest"),
]

SUGGESTIONS = [
    "看看HackerNews今天有什么",
    "知乎日报今天聊了什么",
    "帮我聚合科技新闻做简报",
]

# ── Page setup ──────────────────────────────────────────────────────────────

st.set_page_config(page_title="任意门聚合简报", page_icon="🔍", layout="wide")

# Hide default Streamlit chrome
st.markdown("""
<style>
    header[data-testid="stHeader"] {display: none;}
    .stApp {margin-top: -40px;}
</style>
""", unsafe_allow_html=True)

if "user_id" not in st.session_state:
    st.session_state.user_id = str(uuid.uuid4())[:8]
if "messages" not in st.session_state:
    st.session_state.messages = []
if "session_id" not in st.session_state:
    st.session_state.session_id = None
if "session_title" not in st.session_state:
    st.session_state.session_title = "新会话"


# ── Streaming SSE consumer (threaded — yields tokens in real-time) ──────────

import queue
import threading


def stream_events(user_id: str, prompt: str, session_id: str | None = None):
    """Generator that yields (event_type, content) tuples in real-time via background thread."""
    q: queue.Queue = queue.Queue()

    async def _fetch():
        try:
            async with httpx.AsyncClient(timeout=180.0) as c:
                body: dict = {"user_id": user_id, "content": prompt}
                if session_id:
                    body["session_id"] = session_id
                r = await c.post(f"{API}/messages", json=body)
                r.raise_for_status()
                mid = r.json()["message_id"]
                async with c.stream("GET", f"{API}/messages/{mid}/stream") as s:
                    event_type, dbuf = "", ""
                    async for line in s.aiter_lines():
                        if line.startswith("event:"): event_type = line.split(":", 1)[1].strip()
                        elif line.startswith("data:"): dbuf = line.split(":", 1)[1].strip()
                        elif line == "" and event_type:
                            content = ""
                            try:
                                payload = json.loads(dbuf)
                                if event_type in ("token", "reasoning"):
                                    content = payload.get("content", dbuf)
                                elif event_type == "tool_call":
                                    content = payload.get("tool_name", dbuf)
                                elif event_type == "error":
                                    content = dbuf
                            except json.JSONDecodeError:
                                content = dbuf
                            q.put((event_type, content))
                            if event_type in ("done", "error"):
                                return
                            event_type, dbuf = "", ""
        except Exception as e:
            q.put(("error", str(e)))

    def _run():
        asyncio.run(_fetch())

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    while True:
        item = q.get()
        yield item
        if item[0] in ("done", "error"):
            break


def _list_sessions() -> list[dict]:
    """Fetch session list from API."""
    try:
        r = httpx.get(f"{API}/sessions/{st.session_state.user_id}", timeout=5)
        r.raise_for_status()
        return r.json().get("sessions", [])
    except Exception:
        return []


def _load_session_messages(session_id: str) -> list[dict]:
    """Load message history for a session."""
    try:
        r = httpx.get(f"{API}/sessions/{session_id}/messages", timeout=5)
        r.raise_for_status()
        msgs = r.json().get("messages", [])
        result = []
        for m in msgs:
            result.append({"role": m["role"], "content": m["content"]})
        return result
    except Exception:
        return []


def _rename_session(session_id: str, title: str):
    """Rename a session via API."""
    try:
        httpx.patch(f"{API}/sessions/{session_id}", json={"title": title}, timeout=5)
    except Exception:
        pass


# ── Sidebar ─────────────────────────────────────────────────────────────────

def render_sidebar():
    # ── Session list ──
    st.sidebar.markdown("### 💬 会话")
    if st.sidebar.button("＋ 新会话", use_container_width=True):
        st.session_state.messages = []
        st.session_state.session_id = None
        st.session_state.session_title = ""
        st.rerun()

    user_sessions = _list_sessions()
    for s in (user_sessions or []):
        sid = s["id"]
        is_active = (st.session_state.session_id == sid)
        label = s.get("title", "")[:25]
        prefix = "▸ " if is_active else "  "

        col1, col2 = st.sidebar.columns([5, 1])
        if col1.button(f"{prefix}{label}", key=f"sess_{sid}", use_container_width=True):
            st.session_state.session_id = sid
            st.session_state.session_title = s.get("title", "")
            st.session_state.messages = _load_session_messages(sid)
            st.rerun()

        # Rename button (pencil)
        rename_key = f"renaming_{sid}"
        if col2.button("✏️", key=f"edit_{sid}", help="重命名"):
            st.session_state[rename_key] = True

        if st.session_state.get(rename_key):
            new_name = st.sidebar.text_input("新名称", value=label, key=f"name_{sid}")
            c1, c2 = st.sidebar.columns(2)
            if c1.button("保存", key=f"save_{sid}"):
                if new_name.strip():
                    _rename_session(sid, new_name.strip())
                    st.session_state[rename_key] = False
                    st.rerun()
            if c2.button("取消", key=f"cancel_{sid}"):
                st.session_state[rename_key] = False
                st.rerun()

    st.sidebar.markdown("---")
    st.sidebar.title("📡 订阅管理")

    # ── Default subscriptions (prominent) ──
    st.sidebar.markdown("### 默认订阅源")
    for name, url in DEFAULT_SUBS:
        st.sidebar.markdown(
            f'<div style="padding:4px 0;border-bottom:1px solid #333;margin-bottom:2px">'
            f'<span style="font-weight:600;font-size:15px">{name}</span><br>'
            f'<span style="font-size:11px;color:#999">{url}</span></div>',
            unsafe_allow_html=True,
        )

    # ── Add subscription (same visual weight) ──
    st.sidebar.markdown("---")
    st.sidebar.markdown("### + 添加订阅")
    sub_name = st.sidebar.text_input("名称", key="add_name", placeholder="例如: GitHub Trending")
    sub_url = st.sidebar.text_input("URL", key="add_url", placeholder="例如: https://hnrss.org/frontpage")
    if st.sidebar.button("添加订阅源", use_container_width=True):
        if sub_name and sub_url:
            with st.sidebar:
                with st.spinner("添加中..."):
                    list(stream_events(
                        st.session_state.user_id,
                        f"请添加RSS订阅源，名称叫 {sub_name}，地址是 {sub_url}，user_id是 {st.session_state.user_id}",
                        st.session_state.session_id,
                    ))
                st.success(f"已添加: {sub_name}")
                st.rerun()
        else:
            st.sidebar.warning("名称和 URL 不能为空")


# ── Main ─────────────────────────────────────────────────────────────────────

def _process_user_message(prompt: str):
    """Send prompt to agent, stream reply in real-time, append to history."""
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        reasoning_buf = []
        content_buf = []
        tools_buf = []
        error_msg = None

        # Streaming containers
        reasoning_expander = st.expander("💭 思考过程", expanded=False)
        reasoning_placeholder = reasoning_expander.empty()
        tools_placeholder = st.empty()
        content_placeholder = st.empty()

        for ev_type, ev_content in stream_events(st.session_state.user_id, prompt, st.session_state.session_id):
            if ev_type == "reasoning":
                reasoning_buf.append(ev_content)
                reasoning_placeholder.markdown(
                    f'<span style="color:#999;font-size:13px">{"".join(reasoning_buf)}</span>',
                    unsafe_allow_html=True,
                )
            elif ev_type == "token":
                content_buf.append(ev_content)
                content_placeholder.markdown("".join(content_buf))
            elif ev_type == "tool_call":
                tools_buf.append(ev_content)
                tools_placeholder.caption(f"🔧 调用工具：{', '.join(tools_buf)}")
            elif ev_type == "error":
                error_msg = ev_content

        # Clean up empty containers
        if not reasoning_buf:
            reasoning_expander.empty()
        if not tools_buf:
            tools_placeholder.empty()

        if error_msg:
            st.error(f"出错了：{error_msg}")
            st.session_state.messages.append({
                "role": "assistant", "content": f"❌ {error_msg}",
                "reasoning": "", "tool_calls": [],
            })
        else:
            final_content = "".join(content_buf) or "Agent 没有返回内容。"
            st.session_state.messages.append({
                "role": "assistant",
                "content": final_content,
                "reasoning": "".join(reasoning_buf),
                "tool_calls": tools_buf,
            })


def main():
    render_sidebar()

    # ── Chat history (if any) ──
    for msg in st.session_state.messages:
        role = msg["role"]
        with st.chat_message(role):
            if role == "assistant" and msg.get("reasoning"):
                with st.expander("💭 思考过程", expanded=False):
                    st.markdown(f'<span style="color:#777;font-size:13px">{msg["reasoning"]}</span>',
                               unsafe_allow_html=True)
            if msg.get("tool_calls"):
                st.caption(f"🔧 {', '.join(msg['tool_calls'])}")
            st.markdown(msg["content"])

    # ── Welcome state (empty chat) ──
    if not st.session_state.messages:
        st.markdown(
            '<div style="text-align:center;padding:40px 0 4px 0">'
            '<h2 style="margin:0">🔍 任意门聚合简报</h2>'
            '<p style="color:#888;font-size:13px;margin:4px 0 0 0">AI 多源聚合 · 输入主题即可获得结构化简报</p>'
            '</div>',
            unsafe_allow_html=True,
        )

    # ── Suggestion chips (compact, above chat_input) ──
    st.markdown(
        '<p style="color:#888;font-size:12px;margin:12px 0 2px 8px">💡 试试</p>',
        unsafe_allow_html=True,
    )
    cols = st.columns(len(SUGGESTIONS))
    for i, sug in enumerate(SUGGESTIONS):
        if cols[i].button(sug, key=f"sug_{i}", use_container_width=True):
            st.session_state.messages.append({"role": "user", "content": sug})
            _process_user_message(sug)
            st.rerun()

    # ── Chat input ──
    if prompt := st.chat_input("输入你想了解的内容，Enter 发送..."):
        st.session_state.messages.append({"role": "user", "content": prompt})
        _process_user_message(prompt)
        st.rerun()


if __name__ == "__main__":
    main()
