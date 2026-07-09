"""HTTP routes. Pure HTTP traffic cop — never imports agno, aiosqlite, or any DB logic."""
import uuid

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse, JSONResponse

from app.schemas import SendMessageRequest, SendMessageResponse

router = APIRouter(tags=["messages"])


@router.post("/messages", response_model=SendMessageResponse)
async def send_message(body: SendMessageRequest, request: Request):
    """
    Accept user text, delegate to agent service, return message_id for streaming.
    """
    agent_svc = request.app.state.agent_svc
    message_id = str(uuid.uuid4())

    await agent_svc.handle_incoming_message(message_id, body.user_id, body.content, body.session_id)

    return SendMessageResponse(message_id=message_id, status="queued")


@router.get("/messages/{message_id}/stream")
async def stream_reply(message_id: str, request: Request):
    """
    SSE stream of agent events: tokens, tool calls, completion.
    """
    agent_svc = request.app.state.agent_svc

    async def event_generator():
        async for event in agent_svc.stream_events(message_id):
            yield f"event: {event.event}\ndata: {event.data}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ── Sessions ──────────────────────────────────────────────────────────────

@router.post("/sessions")
async def create_session(request: Request):
    """Create a new chat session for the given user."""
    body = await request.json()
    user_id = body.get("user_id", "default")
    title = body.get("title", "新会话")
    agent_svc = request.app.state.agent_svc
    sess = await agent_svc.create_session(user_id, title)
    return JSONResponse(sess)


@router.get("/sessions/{user_id}")
async def list_sessions(user_id: str, request: Request):
    """List all chat sessions for a user."""
    agent_svc = request.app.state.agent_svc
    sessions = await agent_svc.list_sessions(user_id)
    return JSONResponse({"user_id": user_id, "sessions": sessions})
