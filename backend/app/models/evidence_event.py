"""Evidence audit event database model and event types."""
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict
from sqlalchemy import String, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class EvidenceEventType(str, enum.Enum):
    """Audit event types for tracking evidence lifecycle states."""
    EVIDENCE_UPLOADED = "EVIDENCE_UPLOADED"
    EVIDENCE_VALIDATED = "EVIDENCE_VALIDATED"
    EVIDENCE_REJECTED = "EVIDENCE_REJECTED"
    EVIDENCE_READY_FOR_ANALYSIS = "EVIDENCE_READY_FOR_ANALYSIS"
    EVIDENCE_FAILED = "EVIDENCE_FAILED"


class EvidenceEvent(Base):
    """Immutable audit trail log event for submitted evidence."""
    __tablename__ = "evidence_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("evidence.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verification_session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    event_data_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    evidence = relationship("Evidence", back_populates="events")

    def __repr__(self) -> str:
        return f"<EvidenceEvent id={self.id} type={self.event_type} evidence_id={self.evidence_id}>"
