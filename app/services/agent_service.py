"""Agent service facade — ultra-thin protocol layer between routes and agent runtime.
Delegates all orchestration to agent_pipeline. Routes depend on this class only."""
from typing import Any, AsyncIterator

from app.schemas import StreamEvent
from app.data.db_service import DBService
from app.services.agent_pipeline import process_and_stream


class AgentService:
    """Wraps the agent behind a plain async interface.
    Routes depend on this class — never on agno, DB, or context logic directly."""

    def __init__(self, db: DBService, agent: Any):
        self._db = db
        self._agent = agent

    async def handle_incoming_message(self, message_id: str, user_id: str, content: str,
                                       session_id: str | None = None):
        """Persist user message to DB. Auto-create session if needed."""
        if session_id is None:
            # Create a new default session
            sess = await self._db.create_session(user_id)
            session_id = sess["id"]
        await self._db.insert_message(message_id, user_id, "user", content, session_id)

    async def stream_events(self, message_id: str) -> AsyncIterator[StreamEvent]:
        """Delegate all lifecycle orchestration to the pipeline."""
        async for event in process_and_stream(self._db, self._agent, message_id):
            yield event

    async def create_session(self, user_id: str, title: str = "新会话") -> dict:
        return await self._db.create_session(user_id, title)

    async def list_sessions(self, user_id: str) -> list[dict]:
        return await self._db.list_sessions(user_id)

    async def rename_session(self, session_id: str, title: str) -> bool:
        return await self._db.rename_session(session_id, title)

    async def get_session_messages(self, session_id: str) -> list[dict]:
        return await self._db.get_session_messages(session_id)
