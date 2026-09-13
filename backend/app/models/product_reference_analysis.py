"""Database model for individual Qwen visual analysis of merchant product reference images."""
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


class ProductReferenceAnalysisStatus(str, enum.Enum):
    """Lifecycle states of a reference image analysis."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ProductReferenceVisualAnalysis(Base):
    """Stored structured visual observation for a single merchant reference image."""
    __tablename__ = "product_reference_visual_analyses"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    product_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    product_reference_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("product_references.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    angle: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        index=True,
    )
    image_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=ProductReferenceAnalysisStatus.PENDING.value,
        nullable=False,
        index=True,
    )
    result_json: Mapped[Dict[str, Any]] = mapped_column(
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

    # Relationships
    product = relationship("Product", backref="reference_analyses")
    product_reference = relationship("ProductReference", backref="analyses")

    def __repr__(self) -> str:
        return f"<ProductReferenceVisualAnalysis id={self.id} product_id={self.product_id} angle={self.angle} status={self.status}>"
