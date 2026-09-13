"""Evidence fusion result model for Milestone 11.

Stores immutable historical multi-source evidence fusion assessments combining
claims, merchant reference baselines, customer evidence, visual analyses,
and deterministic signals (payment, order, delivery, location).
"""
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import String, Float, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class VerificationAssessmentState(str, enum.Enum):
    """Final assessment state resulting from multi-source evidence fusion."""
    EVIDENCE_CONSISTENT = "EVIDENCE_CONSISTENT"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    INCONSISTENCY_DETECTED = "INCONSISTENCY_DETECTED"


class EvidenceFusionResult(Base):
    """Immutable record of an evidence fusion assessment for a verification session.

    The assessment state, dimensions, and contradictions are calculated 100%
    deterministically. An optional human-readable explanation is produced by Llama 3.2
    without modifying the state or confidence.
    """
    __tablename__ = "verification_fusion_results"

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
    assessment_state: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        index=True,
    )
    overall_confidence: Mapped[float] = mapped_column(
        Float,
        nullable=False,
    )
    fusion_version: Mapped[str] = mapped_column(
        String(20),
        default="v1",
        nullable=False,
    )
    input_context_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    result_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    explanation_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(
        JSON,
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

    # Relationships
    session = relationship(
        "VerificationSession",
        back_populates="fusion_results",
    )

    def __repr__(self) -> str:
        return (
            f"<EvidenceFusionResult id={self.id} "
            f"session_id={self.verification_session_id} "
            f"state={self.assessment_state} "
            f"confidence={self.overall_confidence:.2f}>"
        )
