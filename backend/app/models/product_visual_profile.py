"""Database model for Llama-consolidated canonical Product Visual Profile."""
import enum
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from sqlalchemy import String, Text, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class ProductVisualProfileStatus(str, enum.Enum):
    """Lifecycle states of a consolidated product visual profile."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    READY = "READY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class ProductVisualProfile(Base):
    """Consolidated canonical product visual profile synthesized by Llama 3.2 1B from reference analyses."""
    __tablename__ = "product_visual_profiles"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    product_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("products.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
        index=True,
    )
    qwen_model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    llama_model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    profile_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    reference_hashes_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=ProductVisualProfileStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    profile_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
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
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
        nullable=False,
    )

    # Relationship
    product = relationship("Product", backref="visual_profile", uselist=False)

    def __repr__(self) -> str:
        return f"<ProductVisualProfile id={self.id} product_id={self.product_id} status={self.status}>"
