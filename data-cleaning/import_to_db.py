"""
Import data/Estrazione1.csv into PostgreSQL using SQLAlchemy.

Schema:
  safety_events     — one row per event
  event_detections  — one row per AI detection inside an event (can be multiple)

Usage:
  1. Set DATABASE_URL below (or export as environment variable)
  2. pip install sqlalchemy psycopg2-binary
  3. python data-cleaning/import_to_db.py
"""

import sys
import csv
import os
import re
from datetime import datetime
from analyze import parse_trigger, parse_name

from sqlalchemy import (
    create_engine, text,
    Column, Integer, SmallInteger, Boolean, String,
    Numeric, DateTime, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, Session, relationship

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:password@localhost:5432/safety_db",
)

CSV_PATH = "data/Estrazione1.csv"
DELIMITER = ";"
BATCH_SIZE = 500

class Base(DeclarativeBase):
    pass


class SafetyEvent(Base):
    __tablename__ = "safety_events"

    event_id       = Column(Integer, primary_key=True, autoincrement=False)
    event_datetime = Column(DateTime, nullable=False, index=True)
    camera_name    = Column(String(100), nullable=False, index=True)
    event_type     = Column(String(150), nullable=False)
    severity       = Column(SmallInteger, nullable=False)
    reviewed       = Column(Boolean, nullable=False, default=False)

    detections = relationship(
        "EventDetection",
        back_populates="event",
        cascade="all, delete-orphan",
    )


class EventDetection(Base):
    __tablename__ = "event_detections"

    id             = Column(Integer, primary_key=True, autoincrement=True)
    event_id       = Column(Integer, ForeignKey("safety_events.event_id"), nullable=False, index=True)
    violation_type = Column(String(60), nullable=False)
    confidence     = Column(Numeric(5, 2), nullable=True)

    event = relationship("SafetyEvent", back_populates="detections")


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
    engine = create_engine(DATABASE_URL, echo=False)
    print(f"Connessione a: {DATABASE_URL.split('@')[-1]}")

    Base.metadata.create_all(engine)
    print("Tabelle create / verificate.")


if __name__ == "__main__":
    main()
