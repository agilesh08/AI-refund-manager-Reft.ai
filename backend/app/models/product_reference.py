import enum
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class ReferenceAngle(str, enum.Enum):
    """The four canonical reference evidence angles."""
    FRONT = "FRONT"
    BACK = "BACK"
    LEFT = "LEFT"
    RIGHT = "RIGHT"


class ProductReference(Base):
    """Trusted merchant baseline product reference image."""
    __tablename__ = "product_references"

    __table_args__ = (
        UniqueConstraint("product_id", "angle", name="uq_product_reference_angle"),
    )

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
    angle: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
    )
    image_path: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
    )
    image_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        nullable=False,
    )

    # Relationships
    product = relationship("Product", back_populates="references")

    def __repr__(self) -> str:
        return f"<ProductReference id={self.id} product_id={self.product_id} angle={self.angle}>"
