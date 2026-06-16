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
    # Inject user identity so tools that need user_id can be called properly
    result.insert(0, {"role": "system", "content": f"Current user ID: {user_id}"})
    return result
