import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
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
        app.state.usage = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "total_tokens": 0, "thinking_tokens": 0, "cached_tokens": 0}
        yield


app = FastAPI(lifespan=lifespan)

app.include_router(chat_router)

# Stessa origine per UI e API: niente CORS, niente Live Server.
# Il mount va per ultimo, altrimenti ruba le route all'API.
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "ui", html=True), name="ui")