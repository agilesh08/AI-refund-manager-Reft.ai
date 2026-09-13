"""Customer-facing public verification service.

Strictly isolates customer endpoints from sensitive merchant data and guarantees:
- Unauthenticated customer access via URL token only.
- Cryptographic SHA-256 token verification.
- HTTP 410 Gone for expired or cancelled sessions.
- Zero exposure of internal IDs, hashes, merchant emails, or passwords.
"""
import logging
from datetime import datetime, timezone
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.security import hash_verification_token
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.schemas.verification import (
    CustomerMerchantInfo,
    CustomerProductInfo,
    CustomerWorkflowInfo,
    CustomerVerificationResponse,
    CustomerWorkflowResponse,
    VerificationStartResponse,
)

logger = logging.getLogger(__name__)


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is timezone-aware in UTC."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


def utc_now() -> datetime:
    """Current UTC datetime."""
    return datetime.now(timezone.utc)


def get_session_by_token(db: Session, raw_token: str) -> VerificationSession:
    """Look up a verification session by customer raw token.
    
    Validates token presence, checks expiration and cancellation status.
    Raises:
    - 404 NOT FOUND if token does not match any session.
    - 410 GONE if session was cancelled by merchant.
    - 410 GONE if session link has expired.
    """
    clean_token = raw_token.strip() if raw_token else ""
    if not clean_token:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found",
        )

    session = None
    if clean_token.upper().startswith("VR-"):
        stmt = (
            select(VerificationSession)
            .options(
                joinedload(VerificationSession.merchant),
                joinedload(VerificationSession.product),
                joinedload(VerificationSession.workflow),
            )
            .where(VerificationSession.verification_id == clean_token.upper())
        )
        session = db.execute(stmt).scalar_one_or_none()

    if not session:
        token_hash = hash_verification_token(clean_token)
        stmt = (
            select(VerificationSession)
            .options(
                joinedload(VerificationSession.merchant),
                joinedload(VerificationSession.product),
                joinedload(VerificationSession.workflow),
            )
            .where(VerificationSession.customer_token_hash == token_hash)
        )
        session = db.execute(stmt).scalar_one_or_none()

    if not session:
        logger.warning("Invalid customer verification token attempted")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found",
        )

    # Check cancelled status -> 410 Gone
    if session.status == SessionStatus.CANCELLED.value:
        logger.info("Customer accessed cancelled verification session %s", session.verification_id)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This verification session has been cancelled by the merchant",
        )

    now = utc_now()

    # Check hold status & auto-expiration -> 423 Locked
    if session.status == SessionStatus.HELD.value:
        if session.hold_until is not None and ensure_utc(session.hold_until) <= now:
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
        else:
            logger.info("Customer accessed held verification session %s", session.verification_id)
            raise HTTPException(
                status_code=status.HTTP_423_LOCKED,
                detail="Verification temporarily paused",
            )

    # Check expiration -> 410 Gone
    if session.status == SessionStatus.EXPIRED.value or ensure_utc(session.expires_at) <= now:
        if session.status != SessionStatus.EXPIRED.value:
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

        logger.info("Customer accessed expired verification session %s", session.verification_id)
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This verification session link has expired",
        )

    return session


def get_customer_session_overview(db: Session, raw_token: str) -> CustomerVerificationResponse:
    """Retrieve sanitized verification session overview for customer landing page."""
    session = get_session_by_token(db, raw_token)

    workflow_name = session.workflow_snapshot_json.get(
        "workflow_name",
        session.workflow.name if session.workflow else "Verification Workflow",
    )

    return CustomerVerificationResponse(
        verification_id=session.verification_id,
        merchant=CustomerMerchantInfo(business_name=session.merchant.business_name),
        product=CustomerProductInfo(name=session.product.name),
        status=session.status,
        max_attempts=getattr(session, "max_attempts", 1) or 1,
        attempts_count=getattr(session, "attempts_count", 0) or 0,
        expires_at=session.expires_at,
        workflow=CustomerWorkflowInfo(name=workflow_name),
    )


def start_customer_session(db: Session, raw_token: str) -> VerificationStartResponse:
    """Transition verification session to IN_PROGRESS when customer starts the workflow.
    
    Idempotent if already IN_PROGRESS.
    Rejects if already COMPLETED or max attempts reached.
    """
    session = get_session_by_token(db, raw_token)

    max_att = getattr(session, "max_attempts", 1) or 1
    att_count = getattr(session, "attempts_count", 0) or 0
    if session.status == SessionStatus.COMPLETED.value or att_count >= max_att:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification already completed",
        )

    if session.status == SessionStatus.CREATED.value:
        session.status = SessionStatus.IN_PROGRESS.value
        session.started_at = utc_now()

        event = VerificationEvent(
            session_id=session.id,
            verification_id=session.verification_id,
            event_type=VerificationEventType.SESSION_STARTED.value,
            metadata_json={"started_at": session.started_at.isoformat()},
        )
        db.add(event)
        db.commit()
        db.refresh(session)
        logger.info(
            "Customer started session %s (started_at: %s)",
            session.verification_id,
            session.started_at,
        )

    return VerificationStartResponse(
        verification_id=session.verification_id,
        status=session.status,
        started_at=session.started_at or utc_now(),
        message="Verification session started successfully",
    )


def get_customer_workflow(db: Session, raw_token: str) -> CustomerWorkflowResponse:
    """Retrieve the frozen workflow snapshot for the customer verification flow."""
    session = get_session_by_token(db, raw_token)
    max_att = getattr(session, "max_attempts", 1) or 1
    att_count = getattr(session, "attempts_count", 0) or 0
    if session.status == SessionStatus.COMPLETED.value or att_count >= max_att:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification already completed",
        )
    snapshot = session.workflow_snapshot_json or {}

    return CustomerWorkflowResponse(
        verification_id=session.verification_id,
        workflow_name=snapshot.get("workflow_name", "Verification Workflow"),
        workflow_version=snapshot.get("workflow_version", session.workflow_version),
        steps=snapshot.get("steps", []),
    )


def complete_customer_session(db: Session, raw_token: str) -> VerificationStartResponse:
    """Mark verification session as COMPLETED when customer finishes submitting evidence."""
    session = get_session_by_token(db, raw_token)
    if session.status != SessionStatus.COMPLETED.value:
        session.status = SessionStatus.COMPLETED.value
        session.completed_at = utc_now()
        session.attempts_count = (getattr(session, "attempts_count", 0) or 0) + 1
        event = VerificationEvent(
            session_id=session.id,
            verification_id=session.verification_id,
            event_type=VerificationEventType.SESSION_COMPLETED.value,
            metadata_json={"completed_by": "customer", "completed_at": utc_now().isoformat()},
        )
        db.add(event)
        db.commit()
        db.refresh(session)
        logger.info("Customer completed verification session %s", session.verification_id)

        # Trigger deterministic session fusion to establish assessment state
        try:
            from app.services import evidence_fusion_service
            evidence_fusion_service.run_session_fusion(
                db=db,
                merchant_id=session.merchant_id,
                verification_identifier=session.id,
            )
            logger.info("Session fusion evaluated for completed session %s", session.verification_id)
        except Exception as exc:
            logger.warning("Session fusion on customer completion failed gracefully: %s", exc)

    return VerificationStartResponse(
        verification_id=session.verification_id,
        status=session.status,
        started_at=session.started_at or utc_now(),
        message="Verification session completed successfully",
    )


def analyze_customer_session(db: Session, raw_token: str) -> dict:
    """Execute automated visual analysis and adaptive reasoning cycle for submitted customer evidence."""
    session = get_session_by_token(db, raw_token)
    if session.status == SessionStatus.COMPLETED.value:
        return {"status": "ALREADY_COMPLETED", "message": "Verification is already completed"}

    from app.models.evidence import Evidence, EvidenceType
    from app.models.evidence_request import EvidenceRequestStatus
    from app.services import evidence_request_service, evidence_processing_service, adaptive_verification_service
    from sqlalchemy import select

    # Check for pending evidence request first
    existing_requests = evidence_request_service.list_session_requests(db, session.id)
    pending_req = next((r for r in existing_requests if r.status == EvidenceRequestStatus.PENDING.value), None)
    if pending_req:
        return {
            "status": "FOLLOWUP_REQUIRED",
            "request": {
                "id": pending_req.id,
                "workflow_step_key": pending_req.workflow_step_key,
                "requested_evidence_type": pending_req.requested_evidence_type,
                "reason": pending_req.reason,
                "status": pending_req.status,
            },
            "message": pending_req.reason,
        }

    # Find latest image evidence
    latest_img = db.execute(
        select(Evidence)
        .where(
            Evidence.verification_session_id == session.id,
            Evidence.evidence_type == EvidenceType.CUSTOMER_IMAGE.value,
        )
        .order_by(Evidence.created_at.desc())
    ).scalars().first()

    if latest_img:
        try:
            evidence_processing_service.analyze_evidence_image(
                db=db,
                merchant_id=session.merchant_id,
                verification_identifier=session.id,
                evidence_identifier=latest_img.id,
                force_reanalyze=False,
            )
        except Exception as exc:
            logger.warning("Visual analysis in customer analyze failed gracefully: %s", exc)

        try:
            run, req = adaptive_verification_service.run_adaptive_reasoning_cycle(
                db=db,
                merchant_id=session.merchant_id,
                verification_identifier=session.id,
            )
            if req and req.status == EvidenceRequestStatus.PENDING.value:
                return {
                    "status": "FOLLOWUP_REQUIRED",
                    "request": {
                        "id": req.id,
                        "workflow_step_key": req.workflow_step_key,
                        "requested_evidence_type": req.requested_evidence_type,
                        "reason": req.reason,
                        "status": req.status,
                    },
                    "message": req.reason,
                }
        except Exception as exc:
            logger.warning("Adaptive reasoning in customer analyze failed gracefully: %s", exc)

    return {
        "status": "READY_FOR_REVIEW",
        "message": "Evidence successfully analyzed and verified",
    }

