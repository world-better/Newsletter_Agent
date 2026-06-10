"""Agent core — all agno imports, tool definitions, and agent factory.
Swap this file when changing frameworks."""

import os
import json
import httpx
from typing import Any, Callable, Dict, List

from dotenv import load_dotenv

from agno.agent import Agent
from agno.tools import tool
from agno.models.openai import OpenAILike
from pydantic import BaseModel, Field

load_dotenv()


# ── Tool schemas ───────────────────────────────────────────────────────────

class OutputFormat(BaseModel):
    include_brief: bool = Field(description="Whether to include the editorial brief.")
    target_word_count: int = Field(description="Desired word count for the brief.")


def logger_hook(function_name: str, function_call: Callable, arguments: Dict[str, Any]):
    print(f"[HOOK] Executing {function_name} with: {arguments}")
    return function_call(**arguments)


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
            "persona": writer_persona,
            "focus": key_insights_focus,
            "word_target": output_format.target_word_count,
        },
        "content": f"Brief ({output_format.target_word_count} words): " + ", ".join(titles),
    }


# ── Agent factory ──────────────────────────────────────────────────────────

def create_agent() -> Agent:
    """Build the agent with tools. Called once at startup."""
    return Agent(
        model=OpenAILike(
            id=os.getenv("OPENROUTER_MODEL_ID", "openrouter/free"),
            api_key=os.getenv("OPENROUTER_API_KEY"),
            base_url="https://openrouter.ai/api/v1",
        ),
        tools=[generate_creative_brief],
    )
