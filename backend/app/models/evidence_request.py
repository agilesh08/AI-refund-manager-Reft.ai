"""EvidenceRequest database model and lifecycle enums for adaptive evidence follow-ups."""
import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, Any
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class EvidenceRequestStatus(str, enum.Enum):
    """Lifecycle states of an adaptive evidence follow-up request."""
    PENDING = "PENDING"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class EvidenceRequest(Base):
    """Immutable/auditable targeted follow-up evidence request for a verification session."""
    __tablename__ = "evidence_requests"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    verification_session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_step_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        index=True,
    )
    requested_evidence_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    reason: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    options_json: Mapped[Optional[Any]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=EvidenceRequestStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    fulfilled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Relationship
    session = relationship("VerificationSession", back_populates="evidence_requests")

    @property
    def step_key(self) -> str:
        """Alias for workflow_step_key for backward compatibility."""
        return self.workflow_step_key

    def __repr__(self) -> str:
        return (
            f"<EvidenceRequest id={self.id} session={self.verification_session_id} "
            f"step={self.workflow_step_key} type={self.requested_evidence_type} status={self.status}>"
        )
