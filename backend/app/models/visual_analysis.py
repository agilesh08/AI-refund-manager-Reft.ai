"""VisualAnalysis database model and lifecycle enums for Gemini Vision visual analysis."""
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import String, Text, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class VisualAnalysisStatus(str, enum.Enum):
    """Lifecycle states of a visual consistency analysis run."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class VisualAnalysis(Base):
    """Record of an AI visual consistency analysis performed on customer evidence."""
    __tablename__ = "visual_analyses"

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
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    overall_confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        default=None,
    )
    result_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=VisualAnalysisStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    error_message: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # Relationship
    evidence = relationship("Evidence", back_populates="analyses")

    @property
    def public_evidence_id(self) -> str:
        """Return human-readable evidence_id from associated Evidence if loaded."""
        if self.evidence and self.evidence.evidence_id:
            return self.evidence.evidence_id
        return self.evidence_id

    def __repr__(self) -> str:
        return f"<VisualAnalysis id={self.id} evidence_id={self.evidence_id} status={self.status}>"
