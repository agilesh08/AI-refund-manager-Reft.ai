"""ReasoningRun database model and lifecycle enums for Ollama Llama 3.2 3B reasoning executions."""
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


class ReasoningRunStatus(str, enum.Enum):
    """Lifecycle states of a reasoning execution run."""
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ReasoningRun(Base):
    """Immutable audit record of a local AI reasoning execution on verification evidence."""
    __tablename__ = "reasoning_runs"

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
    model_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )
    prompt_version: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
    )
    input_context_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        index=True,
    )
    result_json: Mapped[Dict[str, Any]] = mapped_column(
        JSON,
        default=dict,
        nullable=False,
    )
    status: Mapped[str] = mapped_column(
        String(50),
        default=ReasoningRunStatus.PENDING.value,
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

    # Relationships
    session = relationship("VerificationSession", back_populates="reasoning_runs")

    @property
    def result(self) -> Optional[Dict[str, Any]]:
        """Access result dictionary for schema validation."""
        return self.result_json if self.result_json else None

    def __repr__(self) -> str:
        return f"<ReasoningRun id={self.id} session_id={self.verification_session_id} status={self.status}>"
