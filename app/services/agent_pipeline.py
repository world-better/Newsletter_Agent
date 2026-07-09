"""Agent pipeline — orchestrates: context assembly → agent execution → persistence.
Framework-specific: replace this entire file when swapping agent frameworks.
Part of the agent layer (not protocol / not HTTP)."""

import json
import uuid
from typing import Any, AsyncIterator, Dict, List

from agno.agent import Agent

from app.schemas import EventType, StreamEvent
from app.data.db_service import DBService
from app.services.agent_context import assemble_context


async def process_and_stream(
    db: DBService,
    agent: Agent,
    message_id: str,
) -> AsyncIterator[StreamEvent]:
    """
    Full lifecycle for one agent turn:
      1. assemble context from DB
      2. run agent via agno's arun(), translating events to StreamEvent
      3. capture reply content + tool calls
      4. persist to DB after stream completes

    Replace this function entirely when swapping agent frameworks.
    """
    context = await assemble_context(db, message_id)
    if context is None:
        yield StreamEvent(event=EventType.ERROR, data=json.dumps({"error": "Message not found"}))
        return

    reply_content = ""
    tool_call_logs: list[dict[str, str]] = []

    try:
        final_content = ""
        async for event in agent.arun(
            input=context,
            stream=True,
            stream_events=True,
        ):
            event_name = getattr(event, "event", "")

            if event_name == "RunContent":
                # Reasoning tokens (chain-of-thought) → REASONING events
                reasoning = getattr(event, "reasoning_content", None)
                if reasoning:
                    yield StreamEvent(event=EventType.REASONING, data=json.dumps({"content": reasoning}))

                # Response content → TOKEN events
                content = getattr(event, "content", "")
                if content:
                    final_content = content
                    yield StreamEvent(event=EventType.TOKEN, data=json.dumps({"content": content}))

            elif event_name == "ToolCallCompleted":
                tool = getattr(event, "tool", None)
                if tool is not None:
                    tool_name = getattr(tool, "tool_name", "") or getattr(tool, "name", "")
                    raw_args = getattr(tool, "arguments", "")
                    raw_result = getattr(tool, "content", "") or getattr(tool, "result", "")

                    arguments = json.dumps(raw_args, ensure_ascii=False) if not isinstance(raw_args, str) else raw_args
                    result = json.dumps(raw_result, ensure_ascii=False) if not isinstance(raw_result, str) else raw_result

                    # Capture for DB persistence
                    if tool_name:
                        tool_call_logs.append({
                            "tool_name": str(tool_name),
                            "arguments": arguments,
                            "result": result,
                        })

                    yield StreamEvent(
                        event=EventType.TOOL_CALL,
                        data=json.dumps({
                            "tool_name": str(tool_name),
                            "arguments": arguments,
                            "result": result,
                        }),
                    )

            elif event_name == "RunCompleted":
                content = getattr(event, "content", "")
                if content:
                    final_content = content
                reply_content = final_content
                # Persist BEFORE yielding DONE — normal async loop context, no generator cleanup trap
                await _persist_reply(db, message_id, reply_content, tool_call_logs)
                yield StreamEvent(event=EventType.DONE, data=json.dumps({"content": final_content}))
                return

            elif event_name == "RunError":
                error = getattr(event, "content", str(event))
                yield StreamEvent(event=EventType.ERROR, data=json.dumps({"error": error}))
                return

        # Fallback: events ended without a terminal event
        reply_content = final_content
        await _persist_reply(db, message_id, reply_content, tool_call_logs)
        yield StreamEvent(event=EventType.DONE, data=json.dumps({"content": final_content}))

    except Exception as e:
        yield StreamEvent(event=EventType.ERROR, data=json.dumps({"error": str(e)}))


# ── Persistence helper (stable across framework swaps) ──────────────────────

async def _persist_reply(
    db: DBService,
    message_id: str,
    reply_content: str,
    tool_call_logs: list[dict[str, str]],
):
    """Save assistant reply and tool calls to DB after streaming completes."""
    if not (reply_content or tool_call_logs):
        return
    try:
        message = await db.get_message_by_id(message_id)
        if not message:
            return
        user_id = message["user_id"]
        session_id = message["session_id"] if "session_id" in message.keys() else None
        reply_id = str(uuid.uuid4())
        await db.insert_message(reply_id, user_id, "assistant", reply_content or "", session_id)

        for tc in tool_call_logs:
            if tc["tool_name"]:
                await db.log_tool_call(
                    message_id=reply_id,
                    tool_name=tc["tool_name"],
                    arguments=tc["arguments"],
                    result=tc["result"],
                )
    except Exception as e:
        print(f"[PERSIST ERROR] {type(e).__name__}: {e}")
