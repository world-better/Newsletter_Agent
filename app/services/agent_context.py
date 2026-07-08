"""Context assembly — pure data preparation. Fetches and trims conversation history.
No agno imports, no StreamEvent, no agent execution. Just returns a list of dicts."""

from typing import Dict, List

from app.data.db_service import DBService

DEFAULT_CONTEXT_LIMIT = 10 #默认payload十条


def trim_context(history: List[Dict[str, str]], limit: int = DEFAULT_CONTEXT_LIMIT) -> List[Dict[str, str]]:
    """Keep only the last N messages to fit the agent's context window."""
    return history[-limit:] if len(history) > limit else history


async def assemble_context(db: DBService, message_id: str) -> List[Dict[str, str]] | None:
    """
    Given a message_id, fetch the message + full user history from DB,
    trim to context window, and return as a list of {role, content} dicts.
    Returns None if the message is not found.
    """
    message = await db.get_message_by_id(message_id)
    if message is None:
        return None

    user_id = message["user_id"]
    history_rows = await db.get_history(user_id)
    history = [{"role": r["role"], "content": r["content"]} for r in history_rows]
    result = trim_context(history)

    # Fetch default subscriptions for the system prompt
    default_subs = await db.list_subscriptions("default_user")
    default_list = "\n".join(
        f"  - {s['name']}（{s['url']}）" for s in default_subs
    ) if default_subs else "  （暂无）"

    result.insert(0, {"role": "system", "content": f"""你是「任意门聚合简报」的 AI 助手。你的工具可以聚合多个 RSS 订阅源的内容并生成简报。

## 可用工具
- `fetch_subscribed_feeds(user_id, writer_persona, key_insights_focus, output_format)` — 抓取用户订阅的所有 RSS 源的最新内容，整合成简报。**此工具已内置默认订阅源的兜底逻辑：如果用户自己没有添加任何订阅，会自动使用系统默认的订阅源。**
- `add_rss_subscription(name, url, user_id)` — 添加一个新的 RSS 订阅源。**只在用户明确要求添加订阅时才调用。需要用户明确提供名称和 URL。不要自己编造 URL。**
- `delete_rss_subscription(name, user_id)` — 删除一个已有的 RSS 订阅源。**只在用户明确要求删除时调用。**

## 系统默认订阅源（所有用户共享）
{default_list}

## 行为准则
1. **直接抓取，不要加订阅。** 用户想看内容 → 直接调 `fetch_subscribed_feeds`。默认订阅源已经覆盖了常见的信息渠道，不需要先 add 再用。
2. **不要自己编 URL。** 只有当用户明确说"请添加这个 RSS 源"并提供了具体 URL 时，才能调 `add_rss_subscription`。如果用户只是说"我想看 XXX 的内容"——用 `fetch_subscribed_feeds`，不要自己猜一个 URL。
3. **删除前确认。** 用户说"删除 XXX"时直接删除，不需要额外确认。但不要主动删除用户没提到的订阅。
4. **默认订阅源不能被用户删除。** 用户只能删除自己添加的（user_id={user_id}），删除 default_user 的订阅会失败。
5. **简报结构化。** 用清晰的标题、分段、来源标注来组织简报内容。文字精炼但不失深度。
6. **中文优先。** 除非用户用英文提问，否则用中文回复。

## 当前用户
user_id = "{user_id}"
（调用工具时请使用这个 user_id）"""})
    return result
