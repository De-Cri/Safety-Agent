import os
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import (
    create_engine,
    Column, Integer, SmallInteger, Boolean, String,
    Numeric, DateTime, ForeignKey,
)
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

load_dotenv(Path(__file__).parent.parent / ".env.local")

DATABASE_URL = os.environ.get("DATABASE_URL") or (
    f"postgresql+psycopg2://postgres:{os.environ['PASSWORD_SAFETY_AGENT_DB']}@localhost:5432/safety_agent_db"
)


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


engine = create_engine(DATABASE_URL, echo=False)
SessionLocal = sessionmaker(bind=engine)
