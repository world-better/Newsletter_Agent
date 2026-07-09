"""Request/response schemas — framework-agnostic, stable across agent swaps."""
from enum import StrEnum

from pydantic import BaseModel, Field


class EventType(StrEnum):
    TOKEN = "token"
    REASONING = "reasoning"
    TOOL_CALL = "tool_call"
    DONE = "done"
    ERROR = "error"


class SendMessageRequest(BaseModel):
    user_id: str = Field(..., description="Identifier for the user session")
    content: str = Field(..., min_length=1, description="User message text")
    session_id: str | None = Field(None, description="Chat session ID; auto-created if omitted")


class SendMessageResponse(BaseModel):
    message_id: str
    status: str = "queued"


class StreamEvent(BaseModel):
    """SSE event payload. Shape stays stable regardless of agent framework."""
    event: EventType
    data: str  # JSON-serialized payload
