import enum
import uuid
from datetime import datetime, timezone
from typing import Optional, Any, Dict
from sqlalchemy import String, Text, Boolean, Integer, DateTime, ForeignKey, UniqueConstraint, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


class WorkflowStepType(str, enum.Enum):
    """The 7 canonical verification workflow step types."""
    MCQ = "MCQ"
    TEXT = "TEXT"
    IMAGE = "IMAGE"
    CAMERA = "CAMERA"
    PAYMENT = "PAYMENT"
    ORDER = "ORDER"
    DELIVERY = "DELIVERY"


class WorkflowStep(Base):
    """Individual verification step within a workflow."""
    __tablename__ = "workflow_steps"

    __table_args__ = (
        UniqueConstraint("workflow_id", "step_key", name="uq_workflow_step_key"),
    )

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
        index=True,
    )
    workflow_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    step_key: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    step_type: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    description: Mapped[Optional[str]] = mapped_column(
        Text,
        nullable=True,
        default=None,
    )
    step_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
    )
    required: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    config_json: Mapped[Dict[str, Any]] = mapped_column(
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
    workflow = relationship("Workflow", back_populates="steps")

    def __repr__(self) -> str:
        return f"<WorkflowStep id={self.id} key={self.step_key} type={self.step_type} order={self.step_order}>"
