import uuid
from datetime import datetime, timezone
from sqlalchemy import String, Boolean, DateTime
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime with timezone awareness."""
    return datetime.now(timezone.utc)


class Merchant(Base):
    """Merchant account database model."""
    __tablename__ = "merchants"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    business_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(
        String(255),
        unique=True,
        index=True,
        nullable=False,
    )
    phone: Mapped[str | None] = mapped_column(
        String(50),
        nullable=True,
        default=None,
    )
    password_hash: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
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
    products = relationship(
        "Product",
        back_populates="merchant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    workflows = relationship(
        "Workflow",
        back_populates="merchant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    verification_sessions = relationship(
        "VerificationSession",
        back_populates="merchant",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )



    def __repr__(self) -> str:
        return f"<Merchant id={self.id} email={self.email} business_name={self.business_name}>"
