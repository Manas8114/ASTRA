import os
import logging
from sqlalchemy import create_engine, Column, Integer, String, JSON, DateTime
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime, timezone

log = logging.getLogger("astra.pg_audit")

Base = declarative_base()

class EventAudit(Base):
    __tablename__ = 'astra_event_audit'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    cell_id = Column(String, index=True)
    event_type = Column(String, index=True)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    payload = Column(JSON)

class PGAuditTrail:
    def __init__(self):
        # Default to a local sqlite if PG not available for easy dev fallback
        db_url = os.getenv("DATABASE_URL", "sqlite:///./data/astra_audit.db")
        # Add connect_args for sqlite
        connect_args = {"check_same_thread": False} if db_url.startswith("sqlite") else {}
        self.engine = create_engine(db_url, connect_args=connect_args)
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        log.info(f"Initialized PG Audit Trail with DB: {db_url}")

    def append_event(self, cell_id: str, event_type: str, payload: dict):
        db = self.SessionLocal()
        try:
            audit_entry = EventAudit(
                cell_id=cell_id,
                event_type=event_type,
                payload=payload
            )
            db.add(audit_entry)
            db.commit()
        except Exception as e:
            log.error(f"Failed to append to PG audit trail: {e}")
            db.rollback()
        finally:
            db.close()

pg_audit_trail = PGAuditTrail()
