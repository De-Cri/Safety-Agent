#!/usr/bin/env python3
"""
test_chart_coverage.py

For each supported chart type:
  - sends a natural question to the agent (without explicitly asking for a chart)
  - captures Gemini's text response
  - generates the corresponding chart
  - saves everything to test_chart_coverage.html (question + answer + image)

Fixed 2s retry on 503 errors.
"""

import sys
import asyncio
import time
from pathlib import Path
from unittest.mock import patch
from datetime import datetime

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env.local")

import api.routes.chat as _chat_module
from src.core import Agent
from api.routes.chat import _to_chart, _CHARTABLE

OUTPUT_HTML = Path(__file__).parent / "test_chart_coverage.html"

# ── Test cases ──────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "id":            "C01",
        "chart_type":    "line",
        "expected_tool": "events_per_day",
        "question":      "How did the number of safety events go day by day in the dataset?",
    },
    {
        "id":            "C02",
        "chart_type":    "bar",
        "expected_tool": "events_by_hour",
        "question":      "At what time of day do incidents cluster the most?",
    },
    {
        "id":            "C03",
        "chart_type":    "pie",
        "expected_tool": "group_by_violation_type",
        "question":      "Which type of PPE violation is most common in the dataset?",
    },
    {
        "id":            "C04",
        "chart_type":    "treemap",
        "expected_tool": "group_by_count",
        "question":      "How many events did each camera record over the whole period?",
    },
    {
        "id":            "C05",
        "chart_type":    "heatmap_grid (weekday×hour)",
        "expected_tool": "events_by_weekday_hour",
        "question":      "Are there patterns in the day of week and time when more events happen?",
    },
    {
        "id":            "C06",
        "chart_type":    "heatmap_grid (violation×date)",
        "expected_tool": "events_per_day_by_violation_type",
        "question":      "How does the number of violations per PPE violation type vary day by day?",
    },
    {
        "id":            "C07",
        "chart_type":    "calendar_heatmap",
        "expected_tool": "events_per_day",
        "question":      "Give me an overall view of events day by day across the whole available period.",
        "known_limitation": "Dataset covers only 29 days (< 60) → the code produces 'line', not 'calendar_heatmap'.",
    },
    {
        "id":            "C08",
        "chart_type":    "pie (explicit request)",
        "expected_tool": "group_by_violation_type",
        "question":      "Make me a pie chart showing how PPE violations break down across the various types.",
    },
    {
        "id":            "C09",
        "chart_type":    "treemap (explicit request)",
        "expected_tool": "group_by_count",
        "question":      "Make me a treemap with the number of events per camera.",
    },
]


# ── Agent with 503 retry ──────────────────────────────────────────────────────

async def send_with_retry(agent, chat_session_factory, question: str):
    while True:
        chat_session = chat_session_factory()
        try:
            return await agent.send(chat_session, question)
        except Exception as e:
            err = str(e)
            if "503" in err or "unavailable" in err.lower():
                print("  [503 — retry in 2s]")
                await asyncio.sleep(2)
                continue
            raise


# ── HTML builder ──────────────────────────────────────────────────────────────

def _html_row(tc: dict, response_text: str, tool_names: list, actual_chart_type: str | None, chart_b64: str | None) -> str:
    known = tc.get("known_limitation", "")
    status_label = "KNOWN LIMITATION" if known else ("PASS" if chart_b64 else "NO CHART")
    status_color = "#f0ad4e" if known else ("#5cb85c" if chart_b64 else "#d9534f")

    tool_str = ", ".join(tool_names) if tool_names else "(none)"
    chart_img_html = (
        f'<img src="data:image/png;base64,{chart_b64}" style="max-width:100%;border-radius:6px;margin-top:12px">'
        if chart_b64 else
        '<p style="color:#d9534f;font-style:italic">No chart generated.</p>'
    )
    limitation_note = (
        f'<p style="background:#fff3cd;border-left:4px solid #f0ad4e;padding:8px;border-radius:4px;margin-top:8px">'
        f'<strong>Known limitation:</strong> {known}</p>'
    ) if known else ""

    return f"""
  <div style="background:#fff;border-radius:8px;box-shadow:0 1px 4px rgba(0,0,0,.12);padding:24px;margin-bottom:28px">
    <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px">
      <span style="font-weight:700;font-size:1.1em;color:#333">{tc['id']}</span>
      <span style="background:{status_color};color:#fff;border-radius:4px;padding:2px 10px;font-size:.85em">{status_label}</span>
      <span style="background:#e9ecef;color:#495057;border-radius:4px;padding:2px 10px;font-size:.85em">
        expected: <strong>{tc['chart_type']}</strong>
        {f'&nbsp;|&nbsp;got: <strong>{actual_chart_type}</strong>' if actual_chart_type and actual_chart_type != tc['chart_type'].split(' ')[0] else ''}
      </span>
    </div>

    <p style="margin:0 0 4px 0;font-size:.78em;color:#888;text-transform:uppercase;letter-spacing:.05em">Question</p>
    <p style="background:#f8f9fa;padding:10px 14px;border-radius:6px;font-style:italic;margin:0 0 14px 0">"{tc['question']}"</p>

    <p style="margin:0 0 4px 0;font-size:.78em;color:#888;text-transform:uppercase;letter-spacing:.05em">Tools called</p>
    <p style="font-family:monospace;background:#f1f3f5;padding:6px 12px;border-radius:4px;margin:0 0 14px 0">{tool_str}</p>

    <p style="margin:0 0 4px 0;font-size:.78em;color:#888;text-transform:uppercase;letter-spacing:.05em">Gemini response</p>
    <p style="margin:0 0 14px 0;line-height:1.6">{response_text.replace('<','&lt;').replace('>','&gt;')}</p>

    {limitation_note}
    {chart_img_html}
  </div>
"""


def build_html(rows: list[str]) -> str:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Chart Coverage Test — SafetyAgent</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #f4f6f8; margin: 0; padding: 24px; color: #333; }}
    h1 {{ font-size: 1.5em; margin-bottom: 4px; }}
    .meta {{ color: #888; font-size: .85em; margin-bottom: 28px; }}
  </style>
</head>
<body>
  <h1>Chart Coverage Test — SafetyAgent</h1>
  <p class="meta">Generated on {ts} &nbsp;|&nbsp; {len(rows)} chart types tested</p>
  {body}
</body>
</html>"""


# ── Main runner ─────────────────────────────────────────────────────────

async def run() -> None:
    agent = Agent()
    html_rows: list[str] = []

    # If the HTML already exists, extract the completed cases so we don't repeat them
    done_ids: set[str] = set()
    existing_content = ""
    if OUTPUT_HTML.exists():
        existing_content = OUTPUT_HTML.read_text(encoding="utf-8")
        import re as _re
        done_ids = set(_re.findall(r'<strong>(C\d+)</strong>', existing_content))
        if done_ids:
            print(f"[resume] skipped {sorted(done_ids)} (already in the HTML)")

    print("=" * 60)
    print("CHART COVERAGE TEST")
    print("=" * 60)

    async with agent.connect() as (mcp_session, system_instruction):
        for i, tc in enumerate(TEST_CASES):
            if tc["id"] in done_ids:
                print(f"  [{tc['id']}] skip")
                continue
            print(f"\n[{i+1}/{len(TEST_CASES)}] {tc['id']} | expected: {tc['chart_type']}")
            print(f"  Q: {tc['question']}")

            # Agent call with 503 retry
            response_text, tool_calls, usage = await send_with_retry(
                agent,
                lambda: agent.new_session(mcp_session, system_instruction),
                tc["question"],
            )

            tool_names = [t["tool"] for t in tool_calls]
            print(f"  Tool: {tool_names or '(none)'}")

            # Generate chart and capture the actual chart_type
            chartable_hits = [t for t in tool_calls if t["tool"] in _CHARTABLE]
            chart_b64 = None
            actual_chart_type = None

            if chartable_hits:
                captured: dict = {}
                original = _chat_module.render_chart

                def _cap(chart_data, _c=captured, _o=original):
                    _c["chart_type"] = chart_data.chart_type
                    return _o(chart_data)

                with patch.object(_chat_module, "render_chart", _cap):
                    chart_b64 = await _to_chart(chartable_hits)

                actual_chart_type = captured.get("chart_type")

            status = "KNOWN LIMITATION" if tc.get("known_limitation") else ("PASS" if chart_b64 else "NO CHART")
            print(f"  chart_type obtained: {actual_chart_type or '-'}  |  status: {status}")

            html_rows.append(_html_row(tc, response_text, tool_names, actual_chart_type, chart_b64))

            # Save after each test: append the new blocks to the existing HTML
            all_rows_html = html_rows
            if existing_content:
                # Extract the already-existing blocks and add the new ones
                import re as _re2
                old_body = _re2.findall(r'(<div style="background:#fff.*?</div>\s*)', existing_content, _re2.DOTALL)
                all_rows_html = old_body + html_rows
            OUTPUT_HTML.write_text(build_html(all_rows_html), encoding="utf-8")

    print(f"\nOutput saved to: {OUTPUT_HTML}")
    _print_summary(html_rows)


def _print_summary(rows: list) -> None:
    # Rebuilds the results from TEST_CASES (already printed during the run)
    print("\n" + "=" * 60)
    print("DONE")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run())
