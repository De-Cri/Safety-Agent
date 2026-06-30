# Safety Agent

Experimental LLM agent for analyzing workplace safety events detected by a computer vision system (CCTV cameras). The user asks in natural language, the agent queries the database through MCP tools and answers the request.

## Goal

Computer vision systems produce thousands of events (PPE violations, severity, per-frame detections) that no human wants to scroll through by hand. The goal is to give an overview of everything that puts employees and facilities at risk, in real time, just by asking: counts, filters by camera/type/severity/date, time trends, and chart generation to visualize the distribution of events at a glance.

The key point: the model **never receives a dump of the database**. It only receives tools to query it. This guarantees data-grounded answers, token costs under control, and privacy (the model only sees what the question needs).

## Architecture

```
UI (web chat)  →  FastAPI  →  Agent (Gemini 2.5 Flash)  →  MCP server  →  PostgreSQL
```

Four pieces, each with a single job:

- **MCP server** ([mcp/servers/safety-server/server.py](mcp/servers/safety-server/server.py)) — exposes the database as tools via the Model Context Protocol (FastMCP). Primitive tools (`get_event_by_id`, `list_events`), aggregations (`count_events`, `group_by_count`, `average_severity`, `events_per_day`, `events_by_hour`) and a `db://schema` resource that describes the *live* DB schema to the model: real cameras and event types, not made-up ones.
- **Agent** ([src/core.py](src/core.py)) — connects Gemini to the MCP server over stdio. At startup it reads `db://schema` and injects it into the system prompt, so the model knows what it can ask before it even calls a tool. The prompt rules live in [prompts/system.py](prompts/system.py).
- **API** ([api/app.py](api/app.py), [api/routes/chat.py](api/routes/chat.py)) — FastAPI with `/chat`, `/stats`, and `/chat/reset` endpoints. The MCP server lives in the app lifespan: a single process, shared across requests. Charts are rendered by [mcp/plot-creator/generate_histograms.py](mcp/plot-creator/generate_histograms.py).
- **Database** ([db/models.py](db/models.py)) — PostgreSQL via SQLAlchemy. Two tables: `safety_events` (camera, type, severity 1-10, reviewed) and `event_detections` (one row per person/vehicle in the frame, with confidence). Data comes from the CSV in `data/` through [data-cleaning/import_to_db.py](data-cleaning/import_to_db.py).

### Token control

By default the tools return only the essential fields (*lean* mode) and never more than 20 rows — if details are needed, the model asks for them explicitly. The chat history is pruned to the last 2 user turns. These look like small details, but they are the difference between a cheap agent and one that burns the budget just to say "hi".

## Results

### Exploratory data analysis

The charts below are **examples generated from synthetic data** ([data-cleaning/generate_demo_plots.py](data-cleaning/generate_demo_plots.py)): camera names and numbers are made up, they only serve to show the kind of analysis produced. The same visualizations run on the real dataset (private, not included in the repo) through [data-cleaning/visualize.py](data-cleaning/visualize.py):

| | |
|---|---|
| ![Violations by camera](data-cleaning/plots/plot_1_violations_by_camera.png) | ![Events by hour](data-cleaning/plots/plot_2_events_by_hour.png) |
| ![Daily trend](data-cleaning/plots/plot_3_daily_trend.png) | ![Severity heatmap](data-cleaning/plots/plot_4_severity_heatmap.png) |

![Multiple detections](data-cleaning/plots/plot_5_multi_detections.png)

### Agent evaluation (T-Eval)

The agent is evaluated against a test set anchored to a real DB snapshot ([tests/evaluations/run_t_eval.py](tests/evaluations/run_t_eval.py)), scoring three dimensions per question:

- **R — Retrieve:** was the correct tool selected?
- **U — Understand:** are the passed parameters correct?
- **V — Review:** is the final answer correct? (programmatic checks first, then an LLM-as-judge fallback)

Chart coverage — that every supported chart type is produced by a natural question — is checked separately by [tests/evaluations/test_chart_coverage.py](tests/evaluations/test_chart_coverage.py). Both runners are resume-safe: they save after each question and pick up where they stopped.

## Quick start

```bash
# 1. Environment variables (GEMINI_API_KEY_CREDIT, PASSWORD_SAFETY_AGENT_DB, API_KEY)
cp .env.local.example .env.local

# 2. Import the data into the DB
python data-cleaning/import_to_db.py

# 3. Configure the UI (config.js is gitignored, it holds the API key)
cp ui/config.example.js ui/config.js

# 4. Start the API (also launches the MCP server and serves the UI)
uvicorn api.app:app

# 5. Open http://127.0.0.1:8000
```

Alternatively, `python cli.py` to chat from the terminal without the UI.

## Tests

```bash
python tests/evaluations/run_t_eval.py            # R/U/V evaluation against the live agent
python tests/evaluations/rescore.py               # re-score from saved transcripts (no agent calls)
python tests/evaluations/test_chart_coverage.py   # chart type coverage
```
