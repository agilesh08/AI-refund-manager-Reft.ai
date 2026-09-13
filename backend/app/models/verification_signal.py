"""VerificationSignal database model and enums for multi-source deterministic signal ingestion."""
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import String, DateTime, ForeignKey, JSON, Float
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class SignalType(str, enum.Enum):
    """Supported deterministic signal categories."""
    PAYMENT = "PAYMENT"
    ORDER = "ORDER"
    DELIVERY = "DELIVERY"
    LOCATION = "LOCATION"


class SourceType(str, enum.Enum):
    """Provenance origin categories for ingested signals."""
    MERCHANT_PROVIDED = "MERCHANT_PROVIDED"
    SYSTEM_GENERATED = "SYSTEM_GENERATED"
    INTEGRATION = "INTEGRATION"
    CUSTOMER_PROVIDED = "CUSTOMER_PROVIDED"


class SignalStatus(str, enum.Enum):
    """Validation and lifecycle states of an ingested signal."""
    VALID = "VALID"
    INVALID = "INVALID"
    UNAVAILABLE = "UNAVAILABLE"
    PENDING = "PENDING"


class VerificationSignal(Base):
    """Normalized deterministic signal record associated with a verification session."""
    __tablename__ = "verification_signals"

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
    signal_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=SignalStatus.VALID.value,
        nullable=False,
        index=True,
    )
    data_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    source_reference: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        index=True,
    )
    confidence: Mapped[Optional[float]] = mapped_column(
        Float,
        nullable=True,
        default=None,
    )
    observed_at: Mapped[datetime] = mapped_column(
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
    session = relationship("VerificationSession", back_populates="signals")

    def __repr__(self) -> str:
        return (
            f"<VerificationSignal id={self.id} session={self.verification_session_id} "
            f"type={self.signal_type} source={self.source_type} status={self.status}>"
        )
