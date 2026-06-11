import sys
import asyncio
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "plot-creator"))
from generate_histograms import render_chart, ChartData
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from api.auth import require_api_key

router = APIRouter(dependencies=[Depends(require_api_key)])


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    response: str
    chart_image: str | None = None
    usage: dict | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(req: Request, body: ChatRequest) -> ChatResponse:
    text, tool_results, call_usage = await req.app.state.agent.send(
        chat_session=req.app.state.chat_session,
        user_input=body.message,
    )
    for k, v in call_usage.items():
        req.app.state.usage[k] = req.app.state.usage.get(k, 0) + v
    req.app.state.usage["calls"] += 1

    chart = await _to_chart(tool_results)
    return ChatResponse(response=text, chart_image=chart, usage=call_usage)


@router.get("/stats")
async def get_stats(req: Request):
    return req.app.state.usage


@router.post("/chat/reset")
async def reset_chat(req: Request):
    req.app.state.chat_session = req.app.state.agent.new_session(
        req.app.state.mcp_session,
        req.app.state.system_instruction,
    )
    return {"ok": True}


_CHARTABLE = {"events_per_day", "group_by_count", "events_by_hour"}

def _build_chart_data(tool: str, data: list[dict]) -> ChartData | None:
    if tool == "events_per_day":
        return ChartData(
            labels=[r["date"] for r in data],
            values=[r["count"] for r in data],
            title="Eventi per giorno",
        )
    if tool == "group_by_count":
        return ChartData(
            labels=[r["value"] for r in data],
            values=[r["count"] for r in data],
            title="Distribuzione eventi",
        )
    if tool == "events_by_hour":
        return ChartData(
            labels=[f"{r['hour']:02d}:00" for r in data],
            values=[r["count"] for r in data],
            title="Eventi per ora del giorno",
        )
    return None


async def _to_chart(tool_results: list[dict]) -> str | None:
    hit = next((r for r in tool_results if r["tool"] in _CHARTABLE), None)
    if not hit:
        return None

    try:
        tool = hit["tool"]
        # MCP wraps the return value; navigate defensively
        raw = hit["data"]
        data = raw.get("result", raw)
        if hasattr(data, "structuredContent"):
            data = data.structuredContent.get("result", data)

        chart_data = _build_chart_data(tool, data)
        if not chart_data or not chart_data.labels:
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, render_chart, chart_data)
    except Exception:
        return None
