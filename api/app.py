import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from api.routes.chat import router as chat_router
from agent.core import Agent

agent = Agent()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with agent.connect() as (mcp_session, system_instruction):
        app.state.mcp_session = mcp_session
        app.state.system_instruction = system_instruction
        app.state.agent = agent
        app.state.chat_session = agent.new_session(mcp_session, system_instruction)
        app.state.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0, "thinking_tokens": 0}
        yield


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500"],
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type", "X-API-Key"],
)

app.include_router(chat_router)