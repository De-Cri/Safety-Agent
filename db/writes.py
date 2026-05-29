from typing import Iterable
from db.models import Base, SafetyEvent, engine, SessionLocal


def create_tables() -> None:
    Base.metadata.create_all(engine)


def insert_events(events: Iterable[SafetyEvent], batch_size: int = 500) -> int:
    with SessionLocal() as session:
        batch = []
        total = 0
        for event in events:
            batch.append(event)
            if len(batch) >= batch_size:
                session.add_all(batch)
                session.flush()
                total += len(batch)
                batch = []
        if batch:
            session.add_all(batch)
            total += len(batch)
        session.commit()
    return total
