"""Evidence database model and lifecycle enums."""
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import String, Text, Integer, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class EvidenceType(str, enum.Enum):
    """Categorization of evidence types collected during verification."""
    CUSTOMER_IMAGE = "CUSTOMER_IMAGE"
    CUSTOMER_VIDEO = "CUSTOMER_VIDEO"
    CUSTOMER_TEXT = "CUSTOMER_TEXT"
    PAYMENT_SIGNAL = "PAYMENT_SIGNAL"
    ORDER_SIGNAL = "ORDER_SIGNAL"
    DELIVERY_SIGNAL = "DELIVERY_SIGNAL"
    LOCATION_SIGNAL = "LOCATION_SIGNAL"


class EvidenceStatus(str, enum.Enum):
    """Lifecycle states of an evidence item."""
    UPLOADING = "UPLOADING"
    STORED = "STORED"
    READY_FOR_ANALYSIS = "READY_FOR_ANALYSIS"
    ANALYZED = "ANALYZED"
    REJECTED = "REJECTED"
    FAILED = "FAILED"


class Evidence(Base):
    """Evidence record submitted for a verification session."""
    __tablename__ = "evidence"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    evidence_id: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    verification_session_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("verification_sessions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_step_key: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        default=None,
    )
    evidence_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=EvidenceStatus.READY_FOR_ANALYSIS.value,
        nullable=False,
        index=True,
    )
    original_filename: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    stored_filename: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    storage_path: Mapped[Optional[str]] = mapped_column(
        String(500),
        nullable=True,
        default=None,
    )
    mime_type: Mapped[Optional[str]] = mapped_column(
        String(100),
        nullable=True,
        default=None,
    )
    file_size_bytes: Mapped[Optional[int]] = mapped_column(
        Integer,
        nullable=True,
        default=None,
    )
    sha256_hash: Mapped[Optional[str]] = mapped_column(
        String(64),
        nullable=True,
        index=True,
        default=None,
    )
    text_content: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # Relationships
    session = relationship("VerificationSession", back_populates="evidence_items")
    events = relationship(
        "EvidenceEvent",
        back_populates="evidence",
        cascade="all, delete-orphan",
        order_by="EvidenceEvent.created_at.asc()",
        passive_deletes=True,
    )
    analyses = relationship(
        "VisualAnalysis",
        back_populates="evidence",
        cascade="all, delete-orphan",
        order_by="VisualAnalysis.created_at.desc()",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        return f"<Evidence id={self.id} evidence_id={self.evidence_id} type={self.evidence_type} status={self.status}>"
