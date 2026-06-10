"""FastAPI application entry point — wires dependencies, mounts routers."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.routes.messages import router as messages_router
from app.data.db_service import DBService
from app.services.agent_core import create_agent
from app.services.agent_service import AgentService

db = DBService("app.db")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init()
    agent = create_agent()
    app.state.agent_svc = AgentService(db, agent)
    yield
    await db.close()


app = FastAPI(title="Agent API", lifespan=lifespan)
app.include_router(messages_router, prefix="/api/v1")


@app.get("/")
async def root():
    """Health check — client.py uses this to verify connectivity."""
    return {"status": "ok", "service": "Agent API"}
