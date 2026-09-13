"""Merchant verification session management business logic."""
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import (
    generate_verification_id,
    generate_verification_token,
    hash_verification_token,
)
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.workflow import WorkflowStatus
from app.schemas.verification import VerificationCreateRequest
from app.services.product_service import get_merchant_product, get_product_completeness
from app.services.workflow_service import get_merchant_workflow

logger = logging.getLogger(__name__)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure a datetime object is timezone-aware in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


def create_verification_session(
    db: Session,
    merchant_id: str,
    data: VerificationCreateRequest,
) -> VerificationSession:
    """Create a new verification session for a customer refund claim.
    
    Validates:
    - Product exists, belongs to merchant, and has all 4 reference angles uploaded.
    - Workflow exists, belongs to merchant, has status == ACTIVE, and contains steps.
    
    Generates:
    - Unique human-readable verification_id (VR-YYYY-XXXXXXXX).
    - Cryptographically secure 32-byte URL-safe raw token.
    - SHA-256 hash of the token for database storage.
    - Ephemeral customer_link returned only once on creation.
    - Frozen snapshot of the active workflow graph and step configurations.
    - Audit event recording SESSION_CREATED.
    """
    # 1. Product validation & reference completeness check
    product = get_merchant_product(db, merchant_id, data.product_id)
    completeness = get_product_completeness(db, merchant_id, product.id)
    if not completeness.complete:
        missing = [
            angle.upper()
            for angle, present in completeness.reference_status.items()
            if not present
        ]
        logger.warning(
            "Session creation rejected: product %s missing reference angles: %s",
            product.id,
            missing,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Product '{product.name}' is incomplete. All 4 reference angles "
                f"(FRONT, BACK, LEFT, RIGHT) are required before creating verification sessions. "
                f"Missing: {', '.join(missing)}"
            ),
        )

    # 1b. Check AI visual reference analysis readiness (Strict Product Verification Gating)
    from app.models.product_visual_profile import ProductVisualProfile, ProductVisualProfileStatus
    profile = db.execute(
        select(ProductVisualProfile).where(ProductVisualProfile.product_id == product.id)
    ).scalar_one_or_none()

    current_status = getattr(product, "reference_processing_status", "NOT_READY")

    if current_status == "PROCESSING" or (profile and profile.status == ProductVisualProfileStatus.PROCESSING.value):
        logger.warning("Session creation rejected: product %s reference analysis is in progress", product.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REFERENCE_ANALYSIS_IN_PROGRESS",
                "message": f"This product is still being prepared for visual verification. Please wait until reference analysis is complete."
            },
        )
    elif current_status == "FAILED" or (profile and profile.status == ProductVisualProfileStatus.FAILED.value):
        logger.warning("Session creation rejected: product %s reference analysis failed", product.id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REFERENCE_ANALYSIS_FAILED",
                "message": f"Trusted reference analysis for '{product.name}' failed. Please re-upload reference images."
            },
        )
    elif current_status != "READY" or not profile or profile.status != ProductVisualProfileStatus.READY.value:
        logger.warning("Session creation rejected: product %s profile is not ready (status: %s)", product.id, current_status)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "REFERENCE_ANALYSIS_NOT_READY",
                "message": f"Product '{product.name}' trusted visual profile is not ready. Please complete reference analysis."
            },
        )

    # 2. Workflow validation & ACTIVE status check
    workflow = get_merchant_workflow(db, merchant_id, data.workflow_id)
    if workflow.status != WorkflowStatus.ACTIVE.value:
        logger.warning(
            "Session creation rejected: workflow %s is in state '%s'",
            workflow.id,
            workflow.status,
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Workflow '{workflow.name}' is in '{workflow.status}' state. "
                f"Only ACTIVE workflows can be used to initiate customer verification sessions."
            ),
        )

    if not workflow.steps or len(workflow.steps) == 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Workflow '{workflow.name}' contains no steps. Cannot create verification session.",
        )

    # 3. Generate verification ID, raw token, and hash
    verification_id = generate_verification_id()
    while db.execute(
        select(VerificationSession).where(VerificationSession.verification_id == verification_id)
    ).scalar_one_or_none() is not None:
        verification_id = generate_verification_id()

    raw_token = generate_verification_token(32)
    token_hash = hash_verification_token(raw_token)
    customer_link = f"{settings.CUSTOMER_VERIFICATION_BASE_URL.rstrip('/')}/{raw_token}"

    # 4. Freeze workflow definition snapshot (include only enabled steps)
    active_steps = [
        s for s in sorted(workflow.steps, key=lambda x: x.step_order)
        if (s.config_json or {}).get("enabled", True) is not False
    ]
    if not active_steps:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Workflow '{workflow.name}' contains no enabled steps. Cannot create verification session.",
        )

    workflow_snapshot = {
        "workflow_id": workflow.id,
        "workflow_name": workflow.name,
        "workflow_version": workflow.version,
        "steps": [
            {
                "id": s.id,
                "step_key": s.step_key,
                "step_type": s.step_type,
                "title": s.title,
                "description": s.description,
                "step_order": s.step_order,
                "required": s.required,
                "config_json": s.config_json or {},
            }
            for s in active_steps
        ],
    }

    # 5. Expiration timestamp
    expires_at = utc_now() + timedelta(hours=settings.VERIFICATION_SESSION_EXPIRY_HOURS)

    # 6. Instantiate session
    session = VerificationSession(
        verification_id=verification_id,
        merchant_id=merchant_id,
        product_id=product.id,
        workflow_id=workflow.id,
        workflow_version=workflow.version,
        workflow_snapshot_json=workflow_snapshot,
        order_id=data.order_id,
        customer_name=data.customer_name,
        customer_contact=data.customer_contact,
        refund_reason=data.refund_reason,
        refund_amount=data.refund_amount,
        status=SessionStatus.CREATED.value,
        max_attempts=data.max_attempts or 1,
        attempts_count=0,
        customer_token_hash=token_hash,
        expires_at=expires_at,
    )
    db.add(session)
    db.flush()

    # 7. Record creation audit event
    event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.SESSION_CREATED.value,
        metadata_json={
            "order_id": data.order_id,
            "product_id": product.id,
            "workflow_id": workflow.id,
            "workflow_version": workflow.version,
            "expires_at": expires_at.isoformat(),
        },
    )
    db.add(event)
    db.commit()
    db.refresh(session)

    # Attach ephemeral customer_link for one-time return to the merchant
    setattr(session, "customer_link", customer_link)

    logger.info(
        "Created verification session %s (%s) for merchant %s (Order: %s)",
        session.id,
        session.verification_id,
        merchant_id,
        session.order_id,
    )
    return session


def list_merchant_sessions(
    db: Session,
    merchant_id: str,
    status_filter: Optional[str] = None,
) -> List[VerificationSession]:
    """Retrieve all verification sessions owned by the merchant.
    
    Lazily checks and transitions expired sessions to EXPIRED status.
    Customer links are NOT returned here as raw tokens are never persisted.
    """
    stmt = (
        select(VerificationSession)
        .where(VerificationSession.merchant_id == merchant_id)
        .order_by(VerificationSession.created_at.desc())
    )
    if status_filter:
        stmt = stmt.where(VerificationSession.status == status_filter)

    sessions = list(db.execute(stmt).scalars().all())

    # Check for expired sessions
    now = utc_now()
    modified = False
    for s in sessions:
        if (
            s.status in (SessionStatus.CREATED.value, SessionStatus.IN_PROGRESS.value)
            and ensure_utc(s.expires_at) <= now
        ):
            s.status = SessionStatus.EXPIRED.value
            event = VerificationEvent(
                session_id=s.id,
                verification_id=s.verification_id,
                event_type=VerificationEventType.SESSION_EXPIRED.value,
                metadata_json={"detected_at": now.isoformat()},
            )
            db.add(event)
            modified = True

    if modified:
        db.commit()

    return sessions


def get_merchant_session(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> VerificationSession:
    """Retrieve a single verification session by verification_id or internal ID.
    
    Enforces merchant isolation and lazily checks expiration.
    """
    session = db.execute(
        select(VerificationSession).where(
            VerificationSession.merchant_id == merchant_id,
            or_(
                VerificationSession.verification_id == verification_identifier,
                VerificationSession.id == verification_identifier,
            ),
        )
    ).scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found",
        )

    # Check expiration
    now = utc_now()
    if (
        session.status in (SessionStatus.CREATED.value, SessionStatus.IN_PROGRESS.value)
        and ensure_utc(session.expires_at) <= now
    ):
        session.status = SessionStatus.EXPIRED.value
        event = VerificationEvent(
            session_id=session.id,
            verification_id=session.verification_id,
            event_type=VerificationEventType.SESSION_EXPIRED.value,
            metadata_json={"detected_at": now.isoformat()},
        )
        db.add(event)
        db.commit()
        db.refresh(session)
    elif (
        session.status == SessionStatus.HELD.value
        and session.hold_until is not None
        and ensure_utc(session.hold_until) <= now
    ):
        restored = (
            SessionStatus.COMPLETED.value
            if session.completed_at
            else (SessionStatus.IN_PROGRESS.value if session.started_at else SessionStatus.CREATED.value)
        )
        session.status = restored
        session.held_at = None
        session.hold_until = None
        session.held_by = None
        event = VerificationEvent(
            session_id=session.id,
            verification_id=session.verification_id,
            event_type=VerificationEventType.SESSION_RESUMED.value,
            metadata_json={"auto_resumed": True, "resumed_at": now.isoformat(), "restored_status": restored},
        )
        db.add(event)
        db.commit()
        db.refresh(session)

    return session


def cancel_merchant_session(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> VerificationSession:
    """Cancel a verification session.
    
    Disallows cancelling completed, expired, or already cancelled sessions.
    """
    session = get_merchant_session(db, merchant_id, verification_identifier)

    if session.status == SessionStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Completed verification sessions cannot be cancelled",
        )

    if session.status == SessionStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification session is already cancelled",
        )

    if session.status == SessionStatus.EXPIRED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expired verification sessions cannot be cancelled",
        )

    session.status = SessionStatus.CANCELLED.value

    event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.SESSION_CANCELLED.value,
        metadata_json={"cancelled_by": "merchant", "merchant_id": merchant_id},
    )
    db.add(event)
    db.commit()
    db.refresh(session)

    logger.info(
        "Cancelled verification session %s (%s) by merchant %s",
        session.id,
        session.verification_id,
        merchant_id,
    )
    return session


def hold_verification_session(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    duration_seconds: Optional[int] = None,
) -> VerificationSession:
    """Hold a verification session, temporarily blocking customer access.
    
    Validates merchant isolation and preserves existing customer evidence.
    """
    session = get_merchant_session(db, merchant_id, verification_identifier)

    if session.status == SessionStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cancelled verification sessions cannot be held",
        )
    if session.status == SessionStatus.EXPIRED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Expired verification sessions cannot be held",
        )

    now = utc_now()
    session.status = SessionStatus.HELD.value
    session.held_at = now
    session.held_by = merchant_id
    if duration_seconds and duration_seconds > 0:
        session.hold_until = now + timedelta(seconds=duration_seconds)
    else:
        session.hold_until = None

    event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.SESSION_HELD.value,
        metadata_json={
            "held_by": merchant_id,
            "held_at": now.isoformat(),
            "hold_until": session.hold_until.isoformat() if session.hold_until else None,
            "duration_seconds": duration_seconds,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(session)

    logger.info(
        "Held verification session %s by merchant %s (hold_until: %s)",
        session.verification_id,
        merchant_id,
        session.hold_until,
    )
    return session


def resume_verification_session(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> VerificationSession:
    """Resume a previously held verification session."""
    session = get_merchant_session(db, merchant_id, verification_identifier)

    if session.status != SessionStatus.HELD.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Verification session is in '{session.status}' state; only HELD sessions can be resumed",
        )

    now = utc_now()
    restored_status = (
        SessionStatus.COMPLETED.value
        if session.completed_at
        else (SessionStatus.IN_PROGRESS.value if session.started_at else SessionStatus.CREATED.value)
    )
    session.status = restored_status
    session.held_at = None
    session.hold_until = None
    session.held_by = None

    event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.SESSION_RESUMED.value,
        metadata_json={
            "resumed_by": merchant_id,
            "resumed_at": now.isoformat(),
            "restored_status": restored_status,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(session)

    logger.info(
        "Resumed verification session %s by merchant %s (status restored to %s)",
        session.verification_id,
        merchant_id,
        restored_status,
    )
    return session


def delete_verification_session(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> None:
    """Safely delete a verification session and cascade cleanup of all child records and disk files."""
    from pathlib import Path
    session = db.execute(
        select(VerificationSession).where(
            VerificationSession.merchant_id == merchant_id,
            or_(
                VerificationSession.verification_id == verification_identifier,
                VerificationSession.id == verification_identifier,
            ),
        )
    ).scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found",
        )

    # 1. Clean up physical evidence files from disk
    for ev in (session.evidence_items or []):
        if ev.storage_path:
            try:
                p = Path(ev.storage_path)
                if p.is_file():
                    p.unlink(missing_ok=True)
            except Exception as exc:
                logger.warning("Error deleting evidence file %s: %s", ev.storage_path, exc)

    # 2. Record audit event before deleting session
    event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.SESSION_DELETED.value,
        metadata_json={
            "deleted_by": merchant_id,
            "deleted_at": utc_now().isoformat(),
            "verification_id": session.verification_id,
        },
    )
    db.add(event)
    db.flush()

    # 3. Delete parent session (SQLAlchemy cascades all child records)
    v_id = session.verification_id
    db.delete(session)
    db.commit()
    logger.info(
        "Deleted verification session %s and associated child records/files by merchant %s",
        v_id,
        merchant_id,
    )

