1. async for route
    This question is about architectural advice (sync/async tradeoffs, WAL coupling, endpoint design) — not Agno documentation. Let me address it using what Agno's docs actually say about the async boundary.

    ---

    **On the sync/async impedance mismatch — it depends on your prototype stage:**

    Agno natively has both `Agent.run()` (sync) and `Agent.arun()` (async). The clean answer is: **use `arun()` throughout** — it's a first-class async path, not a bolted-on wrapper. This eliminates the `run_in_executor` deadlock risk entirely. Your FastAPI route stays in the event loop, tools can be async, and DB calls stay async.

    **On WAL coupling — it depends on how much you care about correctness now:**

    If you're prototyping, skip the event bus. Use Agno's built-in `PostHookCompleted` / `ToolCallCompleted` stream events (via `stream_events=True`) as your "write trigger" — they fire in the same async context, so you can `await db.write(event)` inline without a separate bus. The coupling is real but contained to one seam.

    **On POST + SSE vs. two endpoints — it depends on your client:**

    Agno's own AgentOS uses a single POST that returns resumable SSE (`background=True, stream=True`). Events are buffered with sequential `event_index` values; clients reconnect via `/resume`. This is the pattern to copy — it solves your correlation problem and handles disconnects gracefully.

    **The one seam to pick:** async boundary at the **route layer** (`arun()` in FastAPI), sync nowhere. Let DB writes happen in `ToolCallCompleted` event handlers inline.

    ```suggestions
    (Running Agents - async & streaming)[/agents/running-agents]
    (Background Execution - resumable SSE)[/background-execution/overview]
    ```
    
2. 
    > ## Documentation Index
    > Fetch the complete documentation index at: https://docs.agno.com/llms.txt
    > Use this file to discover all available pages before exploring further.

    # SqliteDb

    `SqliteDb` is a class that implements the Db interface using SQLite as the backend storage system. It provides lightweight, file-based storage for agent sessions with support for JSON data types and schema versioning.

    <Snippet file="db-sqlite-params.mdx" />

    <Snippet file="db-new-bulk-methods.mdx" />

3. agno's database
    Database

    Give your agents persistent storage for sessions, context, memory and knowledge.
    Databases are a foundational part of agent engineering. Add a database to your agent and you get persistent storage for sessions, context, memory, learnings, and evaluation datasets.

        Chat history. Include previous messages in context for multi-turn conversations.
        Session persistence. Store session information and conversation history across requests.
        State management. Store internal agent state across runs. Critical for planning agents.
        Context control. Summarize, compress, enrich, and prune context for better responses.
        Memory and knowledge. Store user-level facts, searchable knowledge, decision traces, and learned insights.
        Tracing and evaluation. Store detailed traces for debugging, monitoring, and building evaluation datasets.
        Data ownership. No third-party dependencies. Query your own database. Build evaluation datasets, extract few-shot examples, flag low-quality responses for review.

    This is how good software is built. Agents are no different.
    ​
    Quick Start

    from agno.agent import Agent
    from agno.db.sqlite import SqliteDb

    agent = Agent(
        db=SqliteDb(db_file="agent.db"),
        add_history_to_context=True,
        num_history_runs=3,
    )

    # First message
    agent.print_response("I'm working on a Python API project", session_id="dev_session")

    # Later — agent remembers the context
    agent.print_response("What testing framework should I use?", session_id="dev_session")

    The agent now persists sessions and includes the last 3 runs in every request. Database storage overview
    ​
    Guides
    Chat History
    Include previous messages in context for multi-turn conversations.
    Session Storage
    Store and retrieve session data from your database.
    Session Summaries
    Condense long conversations to manage token costs.
    Storage Control
    Choose what gets persisted to your database.
    ​
    Works With Teams and Workflows
    Storage works identically across Agents, Teams, and Workflows:

    from agno.team import Team
    from agno.workflow import Workflow
    from agno.db.postgres import PostgresDb

    db = PostgresDb(db_url="postgresql://user:pass@localhost:5432/mydb")

    team = Team(db=db, ...)
    workflow = Workflow(db=db, ...)

    ​
    Supported Databases
    Agno supports 13+ databases for session storage. Use SQLite for development, PostgreSQL for production. View all supported databases.
    ​
    Async Support
    For async applications, use the async database classes:

    from agno.agent import Agent
    from agno.db.postgres import AsyncPostgresDb

    agent = Agent(
        db=AsyncPostgresDb(db_url="postgresql+psycopg_async://..."),
    )

    ​
    Troubleshooting