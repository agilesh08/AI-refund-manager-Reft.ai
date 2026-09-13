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


class VerificationEventType(str, enum.Enum):
    """Audit event types for tracking verification session transitions."""
    SESSION_CREATED = "SESSION_CREATED"
    SESSION_STARTED = "SESSION_STARTED"
    SESSION_COMPLETED = "SESSION_COMPLETED"
    SESSION_CANCELLED = "SESSION_CANCELLED"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    AI_REASONING_COMPLETED = "AI_REASONING_COMPLETED"
    AI_REASONING_FAILED = "AI_REASONING_FAILED"
    EVIDENCE_REQUEST_CREATED = "EVIDENCE_REQUEST_CREATED"
    EVIDENCE_REQUEST_FULFILLED = "EVIDENCE_REQUEST_FULFILLED"
    EVIDENCE_REQUEST_CANCELLED = "EVIDENCE_REQUEST_CANCELLED"
    SIGNAL_CREATED = "SIGNAL_CREATED"
    SIGNAL_VALIDATED = "SIGNAL_VALIDATED"
    SIGNAL_REJECTED = "SIGNAL_REJECTED"
    SIGNAL_UPDATED = "SIGNAL_UPDATED"
    FUSION_STARTED = "FUSION_STARTED"
    FUSION_COMPLETED = "FUSION_COMPLETED"
    FUSION_FAILED = "FUSION_FAILED"
    FUSION_STATE_CHANGED = "FUSION_STATE_CHANGED"
    MERCHANT_DECISION_MADE = "MERCHANT_DECISION_MADE"
    SESSION_HELD = "SESSION_HELD"
    SESSION_RESUMED = "SESSION_RESUMED"
    SESSION_DELETED = "SESSION_DELETED"



class VerificationEvent(Base):
    """Immutable audit trail log event for a verification session."""
    __tablename__ = "verification_events"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    verification_id: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(
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
    session = relationship("VerificationSession", back_populates="events")

    def __repr__(self) -> str:
        return f"<VerificationEvent id={self.id} type={self.event_type} session={self.verification_id}>"
