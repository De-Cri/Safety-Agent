import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from mcp.server.fastmcp import FastMCP
from datetime import datetime
from db.queries import EventFilters
from db.queries import get_event_by_id as _get_event_by_id
from db.queries import list_events as _list_events
from db.queries import get_db_summary as _get_db_summary
from db.queries import count_events as _count_events
from db.queries import group_by_count as _group_by_count
from db.queries import average_severity as _average_severity
from db.queries import events_per_day as _events_per_day
from db.queries import events_by_hour as _events_by_hour
from db.queries import average_events_per_period as _average_events_per_period
from typing import Literal

mcp = FastMCP("safety-agent")


_LEAN_FIELDS = {"event_id", "event_datetime", "camera_name", "event_type", "severity"}
_ALL_FIELDS  = {"event_id", "event_datetime", "camera_name", "event_type", "severity", "reviewed", "detections"}

_MAX_LIMIT = 20  # hard ceiling for all list tools — never return more than this

def _cap(n: int) -> int:
    if n < 1:
        raise ValueError("limit must be greater than zero")
    return min(n, _MAX_LIMIT)


def _requested_fields(fields: list[str] | None, default: set[str]) -> set[str]:
    keep = _ALL_FIELDS if fields == ["*"] else (set(fields) if fields else default)
    unknown = keep - _ALL_FIELDS
    if unknown:
        raise ValueError(f"Unknown fields: {sorted(unknown)}")
    return keep


def _filters(
    camera_name: str | None = None,
    event_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> EventFilters:
    return EventFilters(
        camera_name=camera_name,
        event_type=event_type,
        severity=severity,
        reviewed=reviewed,
        date_start=date_start,
        date_end=date_end,
        min_severity=min_severity,
        max_severity=max_severity,
    )

# RESOURCE

@mcp.resource("db://schema")
def db_schema() -> str:
    """Live DB schema: distinct cameras, event types, date range, total events."""
    s = _get_db_summary()
    cameras    = ", ".join(s["cameras"])    or "N/A"
    evt_types  = ", ".join(s["event_types"]) or "N/A"
    return (
        f"## Schema del database (live)\n"
        f"Totale eventi: {s['total']}\n"
        f"Intervallo date: {s['date_min']} → {s['date_max']}\n\n"
        f"Campi di ogni evento:\n"
        f"- event_id: ID numerico univoco\n"
        f"- event_datetime: data e ora della rilevazione (ISO 8601)\n"
        f"- camera_name: nome dell'area/telecamera. Valori presenti nel DB: {cameras}\n"
        f"- event_type: tipo di violazione DPI. Valori presenti nel DB: {evt_types}\n"
        f"- severity: gravità da 1 a 10 (1-3 bassa, 4-6 media, 7-10 critica)\n"
        f"- reviewed: se l'evento è stato revisionato manualmente (booleano)\n"
        f"- detections: lista di rilevazioni CV, ognuna con violation_type e confidence (0-100%)\n"
    )


#PRIMITIVE TOOLS


@mcp.tool()
def get_event_by_id(event_id: int, fields: list[str] | None = ["*"]) -> dict:
    """Retrieve a single safety event by its numeric ID.
    fields: list of columns to return. Default ["*"] = all fields including detections
    (violation_type, confidence). Pass a subset like ["event_id","severity"] to reduce output."""

    result = _get_event_by_id(event_id, fields=_requested_fields(fields, _ALL_FIELDS))
    if result is None:
        raise ValueError(f"Event {event_id} not found")
    return result


@mcp.tool()
def list_events(
    limit: int = 10,
    descending_search_order: bool = True,
    camera_name: str | None = None,
    event_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
    fields: list[str] | None = None,
) -> list[dict]:
    """List raw safety events, newest first by default, with optional filters.
    limit: number of events to return (default 10, hard max 20).
    descending_search_order: true = newest first (default), false = oldest first.
    camera_name / event_type / severity / reviewed: optional exact-match filters.
    date_start / date_end: optional ISO 8601 datetime bounds.
    min_severity / max_severity: filter by severity range (e.g. min_severity=7 for critical events).
    fields: columns to return. Default (None) = lean set [event_id, event_datetime,
    camera_name, event_type, severity]. Pass ["*"] to include reviewed and detections."""

    return _list_events(
        limit=_cap(limit),
        descending_search_order=descending_search_order,
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            severity=severity,
            reviewed=reviewed,
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
        fields=_requested_fields(fields, _LEAN_FIELDS),
    )

# MATH / AGGREGATION TOOLS

@mcp.tool()
def count_events(
    camera_name: str | None = None,
    event_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> int:
    """Count safety events, with optional filters.
    camera_name / event_type / severity / reviewed: optional exact-match filters.
    date_start / date_end: ISO 8601 datetime bounds (both optional).
    min_severity / max_severity: severity range (e.g. min_severity=7 counts only critical events).
    Use this instead of fetching events and counting manually."""

    return _count_events(
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            severity=severity,
            reviewed=reviewed,
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
    )

@mcp.tool()
def group_by_count(
    column: Literal["camera_name", "event_type", "severity"],
    camera_name: str | None = None,
    event_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> list[dict]:
    """Count events grouped by a column, sorted by count descending.
    Returns a list of {"value": ..., "count": ...} showing every distinct value actually present.
    camera_name / event_type / severity / reviewed: optional exact-match filters.
    date_start / date_end: ISO 8601 bounds to restrict the ranking to a time window.
    min_severity / max_severity: optional severity range filters.
    Use for: ranking (which camera had the most events, most common violation type), and also
    to find the highest or lowest severity value actually present in the data for a given period —
    call with column='severity' and inspect the values returned; do not assume the scale extremes."""

    return _group_by_count(
        column=column,
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            severity=severity,
            reviewed=reviewed,
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
    )

@mcp.tool()
def average_severity(
    camera_name: str | None = None,
    event_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> float | None:
    """Compute the average severity (1-10) across events, with optional filters.
    camera_name / event_type / severity / reviewed: optional exact-match filters.
    date_start / date_end: ISO 8601 datetime bounds (both optional).
    min_severity / max_severity: restrict the average to a severity band.
    Returns a float rounded to 2 decimals, or null if no events match."""

    return _average_severity(
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            severity=severity,
            reviewed=reviewed,
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
    )

@mcp.tool()
def events_per_day(
    camera_name: str | None = None,
    event_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> list[dict]:
    """Return the number of safety events per calendar day, ordered by date ascending.
    Returns a list of {"date": "YYYY-MM-DD", "count": N} dicts.
    date_start / date_end: ISO 8601 bounds (both optional — omit for the full dataset).
    Use for trend questions: how many violations per day this week, busiest days, etc."""

    return _events_per_day(
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            severity=severity,
            reviewed=reviewed,
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
    )


@mcp.tool()
def average_events_per_period(
    period: Literal["day", "hour"],
    camera_name: str | None = None,
    event_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> float:
    """Return the average number of events per day or per hour.
    period='day': average daily event count (total / distinct days).
    period='hour': average event count per hour slot (total / distinct hours observed).
    All standard filters apply. Use to answer 'on average how many events per day/hour?'"""

    return _average_events_per_period(
        period=period,
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            severity=severity,
            reviewed=reviewed,
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
    )


@mcp.tool()
def events_by_hour(
    camera_name: str | None = None,
    event_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> list[dict]:
    """Return the number of safety events grouped by hour of the day (0-23), ordered ascending.
    Returns a list of {"hour": H, "count": N} dicts.
    Use for time-of-day pattern questions: busiest hours, peak violation times, night vs day comparison."""

    return _events_by_hour(
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            severity=severity,
            reviewed=reviewed,
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
    )


# BASIC MATH TOOLS

@mcp.tool()
def add(a: float, b: float) -> float:
    """Return the sum of a and b."""
    return a + b


@mcp.tool()
def subtract(a: float, b: float) -> float:
    """Return the difference a - b."""
    return a - b


@mcp.tool()
def multiply(a: float, b: float) -> float:
    """Return the product of a and b."""
    return a * b


@mcp.tool()
def divide(a: float, b: float) -> float:
    """Return a divided by b. Raises an error if b is zero."""
    if b == 0:
        raise ValueError("Division by zero is not allowed")
    return a / b


@mcp.tool()
def percentage(value: float, total: float) -> float:
    """Return what percentage `value` is of `total` (0-100 scale).
    Raises an error if total is zero — even percentages have standards."""
    if total == 0:
        raise ValueError("Cannot compute percentage of zero total")
    return round((value / total) * 100, 4)


if __name__ == "__main__":
    mcp.run()