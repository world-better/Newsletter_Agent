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

    async def handle_incoming_message(self, message_id: str, user_id: str, content: str):
        """Persist user message to DB."""
        await self._db.insert_message(message_id, user_id, "user", content)

    async def stream_events(self, message_id: str) -> AsyncIterator[StreamEvent]:
        """Delegate all lifecycle orchestration to the pipeline."""
        async for event in process_and_stream(self._db, self._agent, message_id):
            yield event
