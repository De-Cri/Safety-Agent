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


_CHARTABLE = {"events_per_day", "group_by_count", "events_by_hour", "events_by_weekday_hour"}

def _build_chart_data(tool: str, data: list[dict]) -> ChartData | None:
    if tool == "events_per_day":
        labels = [r["date"] for r in data]
        values = [r["count"] for r in data]
        # calendar heatmap for long periods, line for short ones
        chart_type = "calendar_heatmap" if len(labels) > 14 else "line"
        return ChartData(labels=labels, values=values, title="Eventi per giorno", chart_type=chart_type)

    if tool == "group_by_count":
        labels = [str(r["value"]) for r in data]
        values = [r["count"] for r in data]
        chart_type = "pie" if len(labels) <= 6 else "treemap"
        return ChartData(labels=labels, values=values, title="Distribuzione eventi", chart_type=chart_type)

    if tool == "events_by_hour":
        return ChartData(
            labels=[f"{r['hour']:02d}:00" for r in data],
            values=[r["count"] for r in data],
            title="Eventi per ora del giorno",
            chart_type="bar",
        )

    if tool == "events_by_weekday_hour":
        # PostgreSQL dow: 0=Sun..6=Sat → convert to 0=Mon..6=Sun
        matrix = [[0] * 24 for _ in range(7)]
        for r in data:
            mon_dow = (int(r["weekday"]) - 1) % 7
            matrix[mon_dow][int(r["hour"])] = r["count"]
        return ChartData(
            labels=[],
            values=[],
            title="Distribuzione eventi per giorno e ora",
            chart_type="heatmap_grid",
            extra={"matrix": matrix},
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
        if not chart_data:
            return None
        if not chart_data.labels and not chart_data.extra:
            return None

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, render_chart, chart_data)
    except Exception:
        return None
