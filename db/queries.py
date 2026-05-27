from db.models import SafetyEvent, EventDetection, SessionLocal


def _event_to_dict(event: SafetyEvent) -> dict:
    return {
        "event_id":       event.event_id,
        "event_datetime": event.event_datetime.isoformat(),
        "camera_name":    event.camera_name,
        "event_type":     event.event_type,
        "severity":       event.severity,
        "reviewed":       event.reviewed,
        "detections": [
            {
                "violation_type": d.violation_type,
                "confidence":     float(d.confidence) if d.confidence is not None else None,
            }
            for d in event.detections
        ],
    }


def get_event_by_id(event_id: int) -> dict | None:
    with SessionLocal() as session:
        event = session.get(SafetyEvent, event_id)
        return _event_to_dict(event) if event else None


def get_events_filtered(column: str, value: str) -> list[dict]:
    allowed = {"camera_name", "event_type", "severity", "reviewed"}
    if column not in allowed:
        raise ValueError(f"Column '{column}' is not filterable. Choose from: {allowed}")

    with SessionLocal() as session:
        col = getattr(SafetyEvent, column)
        events = session.query(SafetyEvent).filter(col == value).all()
        return [_event_to_dict(e) for e in events]


def get_events_limited(limit: int) -> list[dict]:
    with SessionLocal() as session:
        events = session.query(SafetyEvent).order_by(SafetyEvent.event_datetime).limit(limit).all()
        return [_event_to_dict(e) for e in events]
