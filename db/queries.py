from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, cast, exists as sa_exists
from sqlalchemy.orm import Query, selectinload
from sqlalchemy.types import Date
from db.models import SafetyEvent, EventDetection, SessionLocal


EVENT_FIELDS = {"event_id", "event_datetime", "camera_name", "event_type", "severity", "reviewed", "detections"}


@dataclass(frozen=True)
class EventFilters:
    camera_name: str | None = None
    event_type: str | None = None
    violation_type: str | None = None  # filters by detection.violation_type (e.g. "No Hard Hat")
    severity: int | None = None
    reviewed: bool | None = None
    date_start: datetime | None = None
    date_end: datetime | None = None
    min_severity: int | None = None
    max_severity: int | None = None


def _event_to_dict(event: SafetyEvent, fields: set[str] | None = None) -> dict:
    keep = fields or EVENT_FIELDS
    result = {}
    if "event_id" in keep:
        result["event_id"] = event.event_id
    if "event_datetime" in keep:
        result["event_datetime"] = event.event_datetime.isoformat()
    if "camera_name" in keep:
        result["camera_name"] = event.camera_name
    if "event_type" in keep:
        result["event_type"] = event.event_type
    if "severity" in keep:
        result["severity"] = event.severity
    if "reviewed" in keep:
        result["reviewed"] = event.reviewed
    if "detections" in keep:
        result["detections"] = [
            {
                "violation_type": d.violation_type,
                "confidence":     float(d.confidence) if d.confidence is not None else None,
            }
            for d in event.detections
        ]
    return result


def _validate_fields(fields: set[str] | None) -> set[str] | None:
    if fields is None:
        return None
    unknown = fields - EVENT_FIELDS
    if unknown:
        raise ValueError(f"Unknown event fields: {sorted(unknown)}")
    return fields


def _with_detection_loading(q: Query, fields: set[str] | None) -> Query:
    if fields is None or "detections" in fields:
        return q.options(selectinload(SafetyEvent.detections))
    return q


def _apply_event_filters(
    q: Query,
    filters: EventFilters | None = None,
) -> Query:
    if filters is None:
        return q
    if filters.camera_name is not None:
        q = q.filter(SafetyEvent.camera_name == filters.camera_name)
    if filters.event_type is not None:
        q = q.filter(SafetyEvent.event_type == filters.event_type)
    if filters.severity is not None:
        q = q.filter(SafetyEvent.severity == filters.severity)
    if filters.reviewed is not None:
        q = q.filter(SafetyEvent.reviewed == filters.reviewed)
    if filters.date_start:
        q = q.filter(SafetyEvent.event_datetime >= filters.date_start)
    if filters.date_end:
        q = q.filter(SafetyEvent.event_datetime <= filters.date_end)
    if filters.min_severity is not None:
        q = q.filter(SafetyEvent.severity >= filters.min_severity)
    if filters.max_severity is not None:
        q = q.filter(SafetyEvent.severity <= filters.max_severity)
    if filters.violation_type is not None:
        q = q.filter(
            sa_exists().where(
                (EventDetection.event_id == SafetyEvent.event_id) &
                (EventDetection.violation_type == filters.violation_type)
            )
        )
    return q


def get_event_fields() -> set[str]:
    """Returns all fields exposed by _event_to_dict. Used at startup to detect schema drift."""
    return set(EVENT_FIELDS)


def get_event_by_id(event_id: int, fields: set[str] | None = None) -> dict | None:
    fields = _validate_fields(fields)
    with SessionLocal() as session:
        q = _with_detection_loading(session.query(SafetyEvent), fields)
        event = q.filter(SafetyEvent.event_id == event_id).one_or_none()
        return _event_to_dict(event, fields) if event else None



def list_events(
    limit: int,
    descending_search_order: bool = True,
    filters: EventFilters | None = None,
    fields: set[str] | None = None,
) -> list[dict]:
    fields = _validate_fields(fields)
    with SessionLocal() as session:
        order = SafetyEvent.event_datetime.desc() if descending_search_order else SafetyEvent.event_datetime.asc()
        q = _with_detection_loading(session.query(SafetyEvent), fields)
        q = _apply_event_filters(q, filters)
        events = q.order_by(order).limit(limit).all()
        return [_event_to_dict(e, fields) for e in events]


def get_events_limited(
    limit: int,
    descending_search_order: bool = True,
    filters: EventFilters | None = None,
    fields: set[str] | None = None,
) -> list[dict]:
    return list_events(
        limit=limit,
        descending_search_order=descending_search_order,
        filters=filters,
        fields=fields,
    )

def get_db_summary() -> dict:
    """Returns distinct values and date range for dynamic prompt injection."""
    with SessionLocal() as session:
        cameras         = [r[0] for r in session.query(SafetyEvent.camera_name).distinct().all() if r[0]]
        evt_types       = [r[0] for r in session.query(SafetyEvent.event_type).distinct().all() if r[0]]
        violation_types = [r[0] for r in session.query(EventDetection.violation_type).distinct().all() if r[0]]
        date_min   = session.query(SafetyEvent.event_datetime).order_by(SafetyEvent.event_datetime.asc()).limit(1).scalar()
        date_max   = session.query(SafetyEvent.event_datetime).order_by(SafetyEvent.event_datetime.desc()).limit(1).scalar()
        total      = session.query(SafetyEvent).count()
    return {
        "cameras":         sorted(cameras),
        "event_types":     sorted(evt_types),
        "violation_types": sorted(violation_types),
        "date_min":        date_min.isoformat() if date_min else None,
        "date_max":        date_max.isoformat() if date_max else None,
        "total":           total,
    }


def count_events(
    filters: EventFilters | None = None,
) -> int:
    with SessionLocal() as session:
        q = session.query(func.count(SafetyEvent.event_id))
        q = _apply_event_filters(q, filters)
        return q.scalar() or 0


def group_by_count(
    column: str,
    filters: EventFilters | None = None,
) -> list[dict]:
    allowed = {"camera_name", "event_type", "severity"}
    if column not in allowed:
        raise ValueError(f"Cannot group by '{column}'. Choose from: {allowed}")
    with SessionLocal() as session:
        col = getattr(SafetyEvent, column)
        q = session.query(col, func.count(SafetyEvent.event_id))
        q = _apply_event_filters(q, filters)
        rows = q.group_by(col).order_by(func.count(SafetyEvent.event_id).desc()).all()
        return [{"value": str(r[0]), "count": r[1]} for r in rows]


def average_severity(
    filters: EventFilters | None = None,
) -> float | None:
    with SessionLocal() as session:
        q = session.query(func.avg(SafetyEvent.severity))
        q = _apply_event_filters(q, filters)
        result = q.scalar()
        return round(float(result), 2) if result is not None else None


def get_events_by_date(
    date_start: datetime | None = None,
    date_end: datetime | None = None,
    limit: int = 100,
    min_severity: int | None = None,
    max_severity: int | None = None,
    fields: set[str] | None = None,
) -> list[dict]:
    return list_events(
        limit=limit,
        filters=EventFilters(
            date_start=date_start,
            date_end=date_end,
            min_severity=min_severity,
            max_severity=max_severity,
        ),
        fields=fields,
    )


def average_events_per_period(
    period: str,
    filters: EventFilters | None = None,
) -> float:
    allowed = {"day", "hour"}
    if period not in allowed:
        raise ValueError(f"period must be one of {allowed}")
    with SessionLocal() as session:
        period_expr = (
            func.date(SafetyEvent.event_datetime)
            if period == "day"
            else func.extract("hour", SafetyEvent.event_datetime)
        )
        subq = (
            _apply_event_filters(
                session.query(func.count(SafetyEvent.event_id).label("cnt")),
                filters,
            )
            .group_by(period_expr)
            .subquery()
        )
        result = session.query(func.avg(subq.c.cnt)).scalar()
        return round(float(result), 2) if result is not None else 0.0


def events_by_hour(
    filters: EventFilters | None = None,
) -> list[dict]:
    with SessionLocal() as session:
        hour_expr = func.extract("hour", SafetyEvent.event_datetime)
        q = session.query(
            hour_expr.label("hour"),
            func.count(SafetyEvent.event_id).label("count"),
        )
        q = _apply_event_filters(q, filters)
        rows = q.group_by(hour_expr).order_by(hour_expr).all()
        return [{"hour": int(r[0]), "count": r[1]} for r in rows]


def events_by_weekday_hour(
    filters: EventFilters | None = None,
) -> list[dict]:
    """Counts grouped by weekday (PostgreSQL dow: 0=Sun..6=Sat) and hour (0-23)."""
    with SessionLocal() as session:
        dow_expr  = func.extract("dow",  SafetyEvent.event_datetime)
        hour_expr = func.extract("hour", SafetyEvent.event_datetime)
        q = session.query(
            dow_expr.label("weekday"),
            hour_expr.label("hour"),
            func.count(SafetyEvent.event_id).label("count"),
        )
        q = _apply_event_filters(q, filters)
        rows = q.group_by(dow_expr, hour_expr).all()
        return [{"weekday": int(r[0]), "hour": int(r[1]), "count": r[2]} for r in rows]


def events_per_day_by_type(
    filters: EventFilters | None = None,
) -> list[dict]:
    """Counts grouped by (date, event_type): [{"date": "YYYY-MM-DD", "event_type": "...", "count": N}]."""
    with SessionLocal() as session:
        date_col = cast(SafetyEvent.event_datetime, Date)
        q = session.query(
            date_col.label("date"),
            SafetyEvent.event_type,
            func.count(SafetyEvent.event_id).label("count"),
        )
        q = _apply_event_filters(q, filters)
        rows = q.group_by(date_col, SafetyEvent.event_type).order_by(date_col).all()
        return [{"date": str(r[0]), "event_type": r[1], "count": r[2]} for r in rows]


def events_per_day(
    filters: EventFilters | None = None,
) -> list[dict]:
    with SessionLocal() as session:
        date_col = cast(SafetyEvent.event_datetime, Date)
        q = session.query(date_col, func.count(SafetyEvent.event_id))
        q = _apply_event_filters(q, filters)
        rows = q.group_by(date_col).order_by(date_col).all()
        return [{"date": str(r[0]), "count": r[1]} for r in rows]


def group_by_violation_type(
    filters: EventFilters | None = None,
) -> list[dict]:
    """Counts distinct events grouped by violation_type from EventDetection."""
    with SessionLocal() as session:
        cnt = func.count(func.distinct(EventDetection.event_id))
        q = (
            session.query(EventDetection.violation_type, cnt)
            .join(SafetyEvent, EventDetection.event_id == SafetyEvent.event_id)
        )
        q = _apply_event_filters(q, filters)
        rows = q.group_by(EventDetection.violation_type).order_by(cnt.desc()).all()
        return [{"value": r[0], "count": r[1]} for r in rows]


def events_per_day_by_violation_type(
    filters: EventFilters | None = None,
) -> list[dict]:
    """Counts distinct events grouped by (date, violation_type)."""
    with SessionLocal() as session:
        date_col = cast(SafetyEvent.event_datetime, Date)
        cnt = func.count(func.distinct(SafetyEvent.event_id))
        q = (
            session.query(date_col.label("date"), EventDetection.violation_type, cnt)
            .join(EventDetection, SafetyEvent.event_id == EventDetection.event_id)
        )
        q = _apply_event_filters(q, filters)
        rows = (
            q.group_by(date_col, EventDetection.violation_type)
             .order_by(date_col)
             .all()
        )
        return [{"date": str(r[0]), "violation_type": r[1], "count": r[2]} for r in rows]


