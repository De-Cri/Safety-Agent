"""
Import data/Estrazione1.csv into PostgreSQL.

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
from db.models import SafetyEvent, EventDetection
from db.writes import create_tables, insert_events

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

CSV_PATH = "data/Estrazione1.csv"
DELIMITER = ";"


def parse_row(row: dict) -> SafetyEvent:
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
    event.detections = [
        EventDetection(event_id=event_id, violation_type=vtype, confidence=conf)
        for vtype, conf in parse_trigger(row["Trigger"])
    ]
    return event


def event_stream():
    with open(CSV_PATH, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f, delimiter=DELIMITER)
        for row in reader:
            yield parse_row(row)


def main():
    create_tables()
    print("Tabelle create / verificate.")
    total = insert_events(event_stream())
    print(f"Importazione completata: {total} eventi.")


if __name__ == "__main__":
    main()