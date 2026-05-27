"""
Import data/Estrazione1.csv into PostgreSQL using SQLAlchemy.

Schema:
  safety_events     — one row per event
  event_detections  — one row per AI detection inside an event (can be multiple)

Usage:
  1. Fill .env.local with PASSWORD_SAFETY_AGENT_DB
  2. pip install sqlalchemy psycopg2-binary python-dotenv
  3. python data-cleaning/import_to_db.py
"""

import sys
import csv
from pathlib import Path
from datetime import datetime
from analyze import parse_trigger, parse_name

sys.path.insert(0, str(Path(__file__).parent.parent))
from db.models import Base, SafetyEvent, EventDetection, engine, SessionLocal

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

CSV_PATH = "data/Estrazione1.csv"
DELIMITER = ";"
BATCH_SIZE = 500


def parse_row(row: dict) -> tuple[SafetyEvent, list[EventDetection]]:
    event_id       = int(row["Event ID"])
    event_datetime = datetime.strptime(row["Date and Time"], "%d/%m/%Y, %H:%M:%S")
    camera_name, event_type = parse_name(row["Name"])
    severity       = int(row["Severity"])
    reviewed       = row["Reviewed"].strip().lower() == "yes"

    event = SafetyEvent(
        event_id=event_id,
        event_datetime=event_datetime,
        camera_name=camera_name.strip(),
        event_type=event_type.strip(),
        severity=severity,
        reviewed=reviewed,
    )

    detections = [
        EventDetection(event_id=event_id, violation_type=vtype, confidence=conf)
        for vtype, conf in parse_trigger(row["Trigger"])
    ]

    return event, detections


def main():
    print(f"Connessione al DB...")
    Base.metadata.create_all(engine)
    print("Tabelle create / verificate.")

    with SessionLocal() as session:
        batch: list[SafetyEvent] = []
        with open(CSV_PATH, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter=DELIMITER)
            for row in reader:
                event, detections = parse_row(row)
                event.detections = detections
                batch.append(event)
                if len(batch) >= BATCH_SIZE:
                    session.add_all(batch)
                    session.flush()
                    batch = []
        if batch:
            session.add_all(batch)
        session.commit()
        print("Importazione completata.")


if __name__ == "__main__":
    main()
