"""MerchantDecision database model for tracking merchant refund resolutions."""
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, List, Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class DecisionType(str, enum.Enum):
    """Supported merchant decision outcomes for a verification session."""
    REFUND_APPROVED = "REFUND_APPROVED"
    REFUND_REJECTED = "REFUND_REJECTED"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class ActionTaken(str, enum.Enum):
    """Supported merchant action resolutions."""
    FULL_REFUND = "FULL_REFUND"
    PARTIAL_REFUND = "PARTIAL_REFUND"
    NO_REFUND = "NO_REFUND"
    RETURN_REQUESTED = "RETURN_REQUESTED"


class MerchantDecision(Base):
    """Record of a merchant-controlled final decision on a verification session."""
    __tablename__ = "merchant_decisions"

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
    merchant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    decision: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    decision_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    notes: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    rejection_reasons_json: Mapped[Optional[Any]] = mapped_column(
        JSON,
        nullable=True,
        default=None,
    )
    action_taken: Mapped[Optional[str]] = mapped_column(
        String(50),
        nullable=True,
        default=None,
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
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
    session = relationship(
        "VerificationSession",
        back_populates="merchant_decisions",
    )
    merchant = relationship(
        "Merchant",
    )

    @property
    def decision_id(self) -> str:
        return self.id

    @property
    def rejection_reasons(self) -> Optional[List[str]]:
        if isinstance(self.rejection_reasons_json, list):
            return self.rejection_reasons_json
        return None

    def __repr__(self) -> str:
        return f"<MerchantDecision id={self.id} session_id={self.verification_session_id} decision={self.decision}>"
