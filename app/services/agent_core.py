"""Agent core — all agno imports, tool definitions, and agent factory.
Swap this file when changing frameworks."""

import os
import json
import xml.etree.ElementTree as ET
from typing import Any, Callable, Dict, List

import httpx
from datetime import datetime
from dotenv import load_dotenv

from agno.agent import Agent
from agno.tools import tool
from agno.models.openai import OpenAILike
from pydantic import BaseModel, Field

load_dotenv()


# ── DB bridge for tools that need persistence ──────────────────────────────
# Set via init_db() from main.py lifespan. Module-level so create_agent()
# stays parameterless (hot-plugin requirement).

_db = None  # DBService instance


async def init_db(db):
    """Inject DB reference for tools that need persistence."""
    global _db
    _db = db


def _run_async(coro):
    """Run an async coroutine from a sync tool context.

    agno < 2.7 doesn't support async tool functions natively,
    so sync tools use this helper to call aiosqlite coroutines.
    """
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    # Already in an event loop — use a one-shot thread
    with asyncio.Runner() as runner:
        return runner.run(coro)


# ── Tool schemas ───────────────────────────────────────────────────────────

class OutputFormat(BaseModel):
    include_brief: bool = Field(description="Whether to include the editorial brief.")
    target_word_count: int = Field(description="Desired word count for the brief.")


def logger_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    print(f"[HOOK] Executing {function_name} with: {arguments}")
    return function_call(**arguments)


# ── Existing: HackerNews brief ─────────────────────────────────────────────

@tool(
    name="generate_creative_brief",
    description="Synthesizes HackerNews data into a structured magazine brief.",
    tool_hooks=[logger_hook],
)
def generate_creative_brief(
    num_stories: int,
    writer_persona: str,
    key_insights_focus: List[str],
    output_format: OutputFormat,
) -> Dict[str, Any]:
    """Fetch top stories and format them based on editorial constraints."""
    response = httpx.get("https://hacker-news.firebaseio.com/v0/topstories.json")
    story_ids = response.json()[:num_stories]

    titles = []
    for s_id in story_ids:
        s_data = httpx.get(f"https://hacker-news.firebaseio.com/v0/item/{s_id}.json").json()
        titles.append(s_data.get("title", "No Title"))

    return {
        "metadata": {
            "source": "HackerNews",
            "persona": writer_persona,
            "focus": key_insights_focus,
            "word_target": output_format.target_word_count,
        },
        "content": f"Brief ({output_format.target_word_count} words): " + ", ".join(titles),
    }


# ── RSS subscription tools ─────────────────────────────────────────────────

@tool(
    name="add_rss_subscription",
    description="添加一个RSS订阅源。只在你非常确定用户意图时才调用此工具。需要用户明确提供订阅名称和URL。",
)
def add_rss_subscription(
    name: str,
    url: str,
    user_id: str,
) -> str:
    """Register a new RSS feed subscription for the user."""
    if not name or not url or not user_id:
        return "缺少必填参数：name, url, user_id"
    _run_async(_db.insert_subscription(user_id, name, url))
    return f"✅ 已添加订阅：{name}（{url}）。你可以使用 fetch_subscribed_feeds 获取内容。"


@tool(
    name="delete_rss_subscription",
    description="删除一个RSS订阅源。只在你非常确定用户意图时才调用此工具。需要用户明确指定订阅名称。",
)
def delete_rss_subscription(
    name: str,
    user_id: str,
) -> str:
    """Remove an RSS feed subscription for the user."""
    if not name or not user_id:
        return "缺少必填参数：name, user_id"
    deleted = _run_async(_db.delete_subscription(user_id, name))
    if deleted:
        return f"✅ 已删除订阅：{name}"
    return f"未找到订阅：{name}"


@tool(
    name="fetch_subscribed_feeds",
    description="获取用户所有订阅的RSS源的最新内容，并整合成结构化简报。与 generate_creative_brief 不同，此工具基于用户的自定义订阅源。",
)
def fetch_subscribed_feeds(
    user_id: str,
    writer_persona: str,
    key_insights_focus: List[str],
    output_format: OutputFormat,
) -> Dict[str, Any]:
    """Fetch latest items from all user's subscribed RSS feeds and format as brief."""
    if not _db:
        return {"error": "Database not initialized"}

    subs = _run_async(_db.list_subscriptions(user_id))
    if not subs:
        return {
            "metadata": {"source": "RSS Subscriptions", "count": 0},
            "content": "你还没有添加任何订阅源。请使用 add_rss_subscription 添加。",
        }

    all_items = []
    errors = []

    for sub in subs:
        try:
            url = sub["url"]
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url
            resp = httpx.get(url, timeout=15.0, follow_redirects=True)
            resp.raise_for_status()
            items = _parse_feed(resp.text, max_items=5)
            for item in items:
                item["_source_name"] = sub["name"]
                item["_source_url"] = sub["url"]
            all_items.extend(items)
        except Exception as e:
            errors.append(f"{sub['name']}: {type(e).__name__}")

    # Sort by date descending (newest first), take top items
    all_items.sort(key=lambda x: x.get("_parsed_date", ""), reverse=True)
    top_items = all_items[:20]

    lines = [f"简报 ({output_format.target_word_count} 字，{writer_persona})"]
    lines.append(f"来源数: {len(subs)} | 总条目: {len(all_items)}")
    lines.append("")
    for item in top_items:
        src = item.get("_source_name", "?")
        title = item.get("title", "无标题")
        link = item.get("link", "")
        summary = item.get("summary", "")[:120]
        lines.append(f"[{src}] {title}")
        if summary:
            lines.append(f"  {summary}")
        lines.append("")

    if errors:
        lines.append(f"获取失败的源: {'; '.join(errors)}")

    return {
        "metadata": {
            "source": "RSS Subscriptions",
            "subscription_count": len(subs),
            "source_list": [s["name"] for s in subs],
            "persona": writer_persona,
            "focus": key_insights_focus,
            "word_target": output_format.target_word_count,
            "errors": errors if errors else None,
        },
        "content": "\n".join(lines),
    }


def _parse_feed(xml_text: str, max_items: int = 5) -> List[Dict[str, str]]:
    """Parse RSS 2.0 or Atom feed, return up to max_items entries."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    items = []

    if root.tag == "rss":
        # RSS 2.0
        channel = root.find("channel")
        if channel is None:
            return []
        for entry in list(channel.findall("item"))[:max_items]:
            item = {
                "title": _get_text(entry, "title"),
                "link": _get_text(entry, "link"),
                "summary": _get_text(entry, "description"),
                "published": _get_text(entry, "pubDate"),
            }
            item["_parsed_date"] = item["published"]
            items.append(item)

    elif root.tag == "feed":
        # Atom
        for entry in list(root.findall("{http://www.w3.org/2005/Atom}entry"))[:max_items]:
            link_el = entry.find("{http://www.w3.org/2005/Atom}link")
            item = {
                "title": _get_text(entry, "{http://www.w3.org/2005/Atom}title"),
                "link": link_el.attrib.get("href", "") if link_el is not None else "",
                "summary": _get_text(entry, "{http://www.w3.org/2005/Atom}summary") or _get_text(entry, "{http://www.w3.org/2005/Atom}content"),
                "published": _get_text(entry, "{http://www.w3.org/2005/Atom}published") or _get_text(entry, "{http://www.w3.org/2005/Atom}updated"),
            }
            item["_parsed_date"] = item["published"]
            items.append(item)

    return items


def _get_text(parent: ET.Element, tag: str) -> str:
    el = parent.find(tag)
    return (el.text or "").strip() if el is not None else ""


# ── Agent factory ──────────────────────────────────────────────────────────

def create_agent() -> Agent:
    """Build the agent with tools. Called once at startup."""
    return Agent(
        model=OpenAILike(
            id=os.getenv("OPENROUTER_MODEL_ID", "openrouter/free"),
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        ),
        tools=[generate_creative_brief, add_rss_subscription, delete_rss_subscription, fetch_subscribed_feeds],
    )
