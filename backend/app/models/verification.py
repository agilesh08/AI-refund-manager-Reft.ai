from decimal import Decimal
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy import String, Text, Integer, Numeric, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class SessionStatus(str, enum.Enum):
    """Lifecycle states of a customer refund verification session."""
    CREATED = "CREATED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"
    HELD = "HELD"


class VerificationSession(Base):
    """Merchant-initiated customer verification session with frozen workflow snapshot."""
    __tablename__ = "verification_sessions"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    verification_id: Mapped[str] = mapped_column(
        String(50),
        unique=True,
        index=True,
        nullable=False,
    )
    merchant_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("merchants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    workflow_version: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    workflow_snapshot_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
    )
    order_id: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    customer_name: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    customer_contact: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )
    refund_reason: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    refund_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 2),
        nullable=True,
        default=None,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default=SessionStatus.CREATED.value,
        nullable=False,
        index=True,
    )
    customer_token_hash: Mapped[str] = mapped_column(
        String(64),
        unique=True,
        index=True,
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    max_attempts: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    attempts_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    held_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    hold_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    held_by: Mapped[Optional[str]] = mapped_column(
        String(255),
        nullable=True,
        default=None,
    )

    # Relationships
    merchant = relationship("Merchant", back_populates="verification_sessions")
    product = relationship("Product")
    workflow = relationship("Workflow")
    events = relationship(
        "VerificationEvent",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="VerificationEvent.created_at.asc()",
        passive_deletes=True,
    )
    evidence_items = relationship(
        "Evidence",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="Evidence.created_at.asc()",
        passive_deletes=True,
    )
    evidence_events = relationship(
        "EvidenceEvent",
        cascade="all, delete-orphan",
        order_by="EvidenceEvent.created_at.asc()",
        passive_deletes=True,
    )
    reasoning_runs = relationship(
        "ReasoningRun",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ReasoningRun.created_at.desc()",
        passive_deletes=True,
    )
    evidence_requests = relationship(
        "EvidenceRequest",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="EvidenceRequest.created_at.asc()",
        passive_deletes=True,
    )

    signals = relationship(
        "VerificationSignal",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="VerificationSignal.created_at.asc()",
        passive_deletes=True,
    )

    fusion_results = relationship(
        "EvidenceFusionResult",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="EvidenceFusionResult.created_at.desc()",
        passive_deletes=True,
    )

    merchant_decisions = relationship(
        "MerchantDecision",
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="MerchantDecision.created_at.desc()",
        passive_deletes=True,
    )

    @property
    def customer_email(self) -> Optional[str]:
        return self.customer_contact

    @property
    def customer_id(self) -> Optional[str]:
        return self.customer_contact

    @property
    def claimed_item_condition(self) -> Optional[str]:
        return None

    def __repr__(self) -> str:
        return f"<VerificationSession id={self.id} verification_id={self.verification_id} status={self.status}>"

