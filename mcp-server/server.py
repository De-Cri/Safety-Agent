import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp.server.fastmcp import FastMCP
from db.queries import get_events_filtered as _get_events_filtered
from db.queries import get_event_by_id as _get_event_by_id
from db.queries import get_events_limited as _get_events_limited
from typing import Literal

mcp = FastMCP("safety-agent")

@mcp.tool()
def get_event_by_id(event_id: int) -> dict:
    """Retrieve a single safety event by its numeric ID. Returns event datetime, camera location, event type, severity (1-10), reviewed status, and the list of PPE violations detected (e.g. missing hard hat, missing high-vis vest) with confidence scores."""

    result = _get_event_by_id(event_id)
    if result is None:
        raise ValueError(f"Even {event_id} not found")

    return result

@mcp.tool()
def get_events_filtered(
    column: Literal["camera_name","event_type","severity","reviewed"],
    value: str
) -> list[dict]:
    """Filter safety events by a specific column and value. Filterable columns: camera_name (camera location), event_type (type of safety violation), severity (integer 1-10), reviewed (true/false). Each event includes its PPE violations (e.g. missing hard hat, missing high-vis vest) with confidence scores."""

    return _get_events_filtered(column=column,value=value)

@mcp.tool()
def get_events_limited(limit: int) -> list[dict]:
    """Retrieve the first N safety events ordered by datetime ascending. Each event includes camera location, event type, severity (1-10), reviewed status, and PPE violations detected (e.g. missing hard hat, missing high-vis vest) with confidence scores."""

    return _get_events_limited(limit= limit)

if __name__ == "__main__":
    mcp.run()