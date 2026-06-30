import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
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
from db.queries import events_by_weekday_hour as _events_by_weekday_hour
from db.queries import events_per_day_by_type as _events_per_day_by_type
from db.queries import group_by_violation_type as _group_by_violation_type
from db.queries import events_per_day_by_violation_type as _events_per_day_by_violation_type
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
    violation_type: str | None = None,
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
        violation_type=violation_type,
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
    cameras         = ", ".join(s["cameras"])          or "N/A"
    evt_types       = ", ".join(s["event_types"])       or "N/A"
    violation_types = ", ".join(s["violation_types"])   or "N/A"
    return (
        f"## Database schema (live)\n"
        f"Total events: {s['total']}\n"
        f"Date range: {s['date_min']} → {s['date_max']}\n\n"
        f"Fields of each event:\n"
        f"- event_id: unique numeric ID\n"
        f"- event_datetime: date and time of the detection (ISO 8601)\n"
        f"- camera_name: name of the area/camera. Values present in the DB: {cameras}\n"
        f"- event_type: commercial name of the event (camera-specific, not descriptive of the violation). Values: {evt_types}\n"
        f"- severity: severity from 1 to 10 (1-3 low, 4-6 medium, 7-10 critical)\n"
        f"- reviewed: whether the event has been manually reviewed (boolean)\n"
        f"- detections: list of CV detections, each with violation_type and confidence (0-100%)\n\n"
        f"## Real violation types (violation_type in the detections)\n"
        f"Values present in the DB: {violation_types}\n"
        f"IMPORTANT: to filter or group by PPE violation type ALWAYS use violation_type, "
        f"not event_type. event_type is the generic camera event name and does not identify "
        f"the specific violation.\n\n"
        f"Common filters: the tools accept — camera_name, violation_type, severity, reviewed (exact match), "
        f"date_start/date_end (ISO 8601), min_severity/max_severity (range).\n"
        f"event_type is available but use it only if you want to filter by a camera-specific event name.\n"
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
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
    fields: list[str] | None = None,
) -> list[dict]:
    """List raw safety events, newest first by default (descending_search_order=false for oldest first).
    limit: default 10, hard max 20. Standard optional filters apply.
    violation_type: filters by the real violation type (e.g. "No Hard Hat", "No High Vis vest").
    fields: columns to return. Default (None) = lean set [event_id, event_datetime,
    camera_name, event_type, severity]. Pass ["*"] to include reviewed and detections."""

    return _list_events(
        limit=_cap(limit),
        descending_search_order=descending_search_order,
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            violation_type=violation_type,
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
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> int:
    """Count safety events matching the standard optional filters.
    Use this instead of fetching events and counting manually."""

    return _count_events(
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            violation_type=violation_type,
            severity=severity,
            reviewed=reviewed,
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
    )

@mcp.tool()
def rank_by_count(
    column: Literal["camera_name", "event_type", "severity"],
    camera_name: str | None = None,
    event_type: str | None = None,
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> list[dict]:
    """DEFAULT for TEXT questions about ranking/distribution by camera, event_type, or severity:
    full ranking, 'how many per value/level', 'which most or least'. Returns the
    COMPLETE ordered list (all entries). Does NOT generate charts.
    Use group_by_count ONLY if the user explicitly asks for a chart."""

    return _group_by_count(
        column=column,
        filters=_filters(
            camera_name=camera_name, event_type=event_type, violation_type=violation_type,
            severity=severity, reviewed=reviewed, date_start=date_start, date_end=date_end,
            min_severity=min_severity, max_severity=max_severity,
        ),
    )


@mcp.tool()
def group_by_count(
    column: Literal["camera_name", "severity"],
    camera_name: str | None = None,
    event_type: str | None = None,
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> dict:
    """Use ONLY when the user explicitly asks for a CHART or visual view ('chart',
    'show me visually', 'pie') of the distribution by camera or severity: generates the chart.
    Returns only a summary (top and bottom), NOT the full list: for textual rankings or breakdowns
    use rank_by_count. For PPE violations use group_by_violation_type. Standard filters apply."""

    data = _group_by_count(column=column, filters=_filters(
        camera_name=camera_name, event_type=event_type, violation_type=violation_type,
        severity=severity, reviewed=reviewed, date_start=date_start, date_end=date_end,
        min_severity=min_severity, max_severity=max_severity,
    ))
    if not data:
        return {"categories": 0}
    return {
        "categories": len(data),
        "top_value": str(data[0]["value"]),
        "top_count": data[0]["count"],
        "bottom_value": str(data[-1]["value"]),
        "bottom_count": data[-1]["count"],
    }

@mcp.tool()
def average_severity(
    camera_name: str | None = None,
    event_type: str | None = None,
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> float | None:
    """Average severity (1-10) across events. Standard filters apply.
    Returns a float rounded to 2 decimals, or null if no events match."""

    return _average_severity(
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            violation_type=violation_type,
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
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> dict:
    """Summary of events per calendar day + automatic chart. Standard filters apply.
    Use for trend questions: violations per day this week, busiest days, etc.
    violation_type filters by the real violation type (e.g. "No Hard Hat")."""

    data = _events_per_day(filters=_filters(
        camera_name=camera_name, event_type=event_type, violation_type=violation_type,
        severity=severity, reviewed=reviewed, date_start=date_start, date_end=date_end,
        min_severity=min_severity, max_severity=max_severity,
    ))
    if not data:
        return {"total_events": 0, "days": 0}
    total = sum(r["count"] for r in data)
    peak = max(data, key=lambda r: r["count"])
    return {"total_events": total, "days": len(data), "peak_date": peak["date"], "peak_count": peak["count"]}


@mcp.tool()
def average_events_per_period(
    period: Literal["day", "hour"],
    camera_name: str | None = None,
    event_type: str | None = None,
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> float:
    """Average number of events per day or per hour (total / distinct periods observed).
    Standard filters apply. Use for 'on average how many events per day/hour?'"""

    return _average_events_per_period(
        period=period,
        filters=_filters(
            camera_name=camera_name,
            event_type=event_type,
            violation_type=violation_type,
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
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> dict:
    """Summary of events by hour of day + automatic chart. Standard filters apply.
    Use for time-of-day patterns: busiest hours, peak times, night vs day."""

    data = _events_by_hour(filters=_filters(
        camera_name=camera_name, event_type=event_type, violation_type=violation_type,
        severity=severity, reviewed=reviewed, date_start=date_start, date_end=date_end,
        min_severity=min_severity, max_severity=max_severity,
    ))
    if not data:
        return {"total_events": 0}
    total = sum(r["count"] for r in data)
    peak = max(data, key=lambda r: r["count"])
    quiet = min(data, key=lambda r: r["count"])
    return {"total_events": total, "peak_hour": peak["hour"], "peak_count": peak["count"],
            "quiet_hour": quiet["hour"], "quiet_count": quiet["count"]}


_DOW_EN = {0: "Sunday", 1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday", 6: "Saturday"}

@mcp.tool()
def events_by_weekday_hour(
    camera_name: str | None = None,
    event_type: str | None = None,
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> dict:
    """Summary of events by day-of-week × hour-of-day + automatic heatmap chart. Standard filters apply.
    Use for pattern questions: which day+hour combination has the most violations?"""

    data = _events_by_weekday_hour(filters=_filters(
        camera_name=camera_name, event_type=event_type, violation_type=violation_type,
        severity=severity, reviewed=reviewed, date_start=date_start, date_end=date_end,
        min_severity=min_severity, max_severity=max_severity,
    ))
    if not data:
        return {"total_events": 0}
    total = sum(r["count"] for r in data)
    peak = max(data, key=lambda r: r["count"])
    return {
        "total_events": total,
        "peak_weekday": _DOW_EN.get(peak["weekday"], str(peak["weekday"])),
        "peak_hour": peak["hour"],
        "peak_count": peak["count"],
    }


_VIOLATION_EN = {
    "No Hard Hat":     "no hard hat",
    "No High Vis vest": "no hi-vis vest",
    "No Face cover":   "no face cover",
    "person":          "person detected (vehicle distance)",
}

@mcp.tool()
def rank_by_violation_type(
    camera_name: str | None = None,
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> list[dict]:
    """DEFAULT for TEXT questions about PPE violations: full ranking, 'how do they break down
    by type', 'how many per type', 'which violation most or least frequent'. Returns the COMPLETE list
    ordered by violation_type. Does NOT generate charts.
    Use group_by_violation_type ONLY if the user explicitly asks for a chart."""

    return _group_by_violation_type(filters=_filters(
        camera_name=camera_name, violation_type=violation_type,
        severity=severity, reviewed=reviewed, date_start=date_start, date_end=date_end,
        min_severity=min_severity, max_severity=max_severity,
    ))


@mcp.tool()
def group_by_violation_type(
    camera_name: str | None = None,
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> dict:
    """Use ONLY when the user explicitly asks for a CHART or visual view ('chart',
    'show me visually', 'pie') of the PPE violation distribution: generates the chart.
    Returns only a summary (top and bottom), NOT the full list: for textual rankings or breakdowns
    by type use rank_by_violation_type. Standard filters apply."""

    data = _group_by_violation_type(filters=_filters(
        camera_name=camera_name, violation_type=violation_type,
        severity=severity, reviewed=reviewed, date_start=date_start, date_end=date_end,
        min_severity=min_severity, max_severity=max_severity,
    ))
    if not data:
        return {"categories": 0}
    return {
        "categories": len(data),
        "top_value": data[0]["value"],
        "top_count": data[0]["count"],
        "bottom_value": data[-1]["value"],
        "bottom_count": data[-1]["count"],
    }


@mcp.tool()
def events_per_day_by_violation_type(
    camera_name: str | None = None,
    violation_type: str | None = None,
    severity: int | None = None,
    reviewed: bool | None = None,
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    min_severity: int | None = None,
    max_severity: int | None = None,
) -> dict:
    """Counts events per (day × real PPE violation type) + automatic heatmap.
    Use when the user asks for per-day data broken down by violation type.
    More precise than events_per_day_by_type because it uses violation_type from the detections."""

    data = _events_per_day_by_violation_type(filters=_filters(
        camera_name=camera_name, violation_type=violation_type,
        severity=severity, reviewed=reviewed, date_start=date_start, date_end=date_end,
        min_severity=min_severity, max_severity=max_severity,
    ))
    if not data:
        return {"total_events": 0, "violation_types": 0}
    total = sum(r["count"] for r in data)
    types = len({r["violation_type"] for r in data})
    peak = max(data, key=lambda r: r["count"])
    return {
        "total_events": total,
        "violation_types": types,
        "peak_date": peak["date"],
        "peak_type": _VIOLATION_EN.get(peak["violation_type"], peak["violation_type"]),
        "peak_count": peak["count"],
    }


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