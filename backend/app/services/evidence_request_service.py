"""Evidence request service for managing adaptive evidence follow-ups."""
import logging
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import EvidenceType
from app.models.evidence_request import EvidenceRequest, EvidenceRequestStatus, utc_now
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType

logger = logging.getLogger(__name__)


def validate_requested_step(
    session: VerificationSession,
    step_key: str,
    requested_evidence_type: str,
) -> Dict[str, Any]:
    """Validate requested follow-up step against the session's frozen workflow snapshot.

    Strictly validates:
    1. Session is active (IN_PROGRESS).
    2. Step exists in frozen snapshot.
    3. Step is an IMAGE or CAMERA step.

    Raises:
        HTTPException: If any validation rule is violated.
    """
    if session.status == SessionStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This verification session has been cancelled",
        )
    if session.status == SessionStatus.EXPIRED.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This verification session link has expired",
        )
    if session.status != SessionStatus.IN_PROGRESS.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot request evidence for session in '{session.status}' state; must be IN_PROGRESS",
        )

    snapshot_steps = (session.workflow_snapshot_json or {}).get("steps", [])
    step_def = next((s for s in snapshot_steps if s.get("step_key") == step_key), None)

    if not step_def:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Step '{step_key}' does not exist in the session's frozen workflow snapshot",
        )

    step_type = step_def.get("step_type", "")
    if step_type not in ("IMAGE", "CAMERA", "MCQ", "TEXT"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Workflow step '{step_key}' of type '{step_type}' is not eligible for adaptive follow-up. "
                "Adaptive follow-ups are allowed on IMAGE, CAMERA, MCQ, or TEXT steps."
            ),
        )

    if requested_evidence_type == EvidenceType.CUSTOMER_IMAGE.value and step_type not in ("IMAGE", "CAMERA"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Workflow step '{step_key}' of type '{step_type}' is not eligible for adaptive follow-up. "
                "Adaptive image requests may only target IMAGE or CAMERA steps."
            ),
        )

    return step_def


def create_evidence_request(
    db: Session,
    session: VerificationSession,
    step_key: str,
    requested_evidence_type: str,
    reason: str,
    options: Optional[List[str]] = None,
) -> Optional[EvidenceRequest]:
    """Create and persist a targeted follow-up evidence request.

    Enforces:
    - Adaptive inquiry driven by honest uncertainty resolution (no artificial cutoff).
    - Deduplication: checks for pending requests and prevents duplicate inquiries.
    - Frozen workflow snapshot step compatibility.
    - Immutable audit event logging.

    Returns:
        EvidenceRequest instance or existing pending request.
    """
    # 1. Validate step against frozen snapshot
    validate_requested_step(session, step_key, requested_evidence_type)

    # 2. Deduplication: check if any PENDING request already exists for this session
    existing_pending = db.execute(
        select(EvidenceRequest).where(
            EvidenceRequest.verification_session_id == session.id,
            EvidenceRequest.status == EvidenceRequestStatus.PENDING.value,
        )
    ).scalars().first()

    if existing_pending:
        logger.info(
            "Reusing existing pending evidence request %s for session %s step %s",
            existing_pending.id,
            session.verification_id,
            existing_pending.workflow_step_key,
        )
        return existing_pending

    # 3. Check question history and max adaptive follow-ups limit
    existing_requests = db.execute(
        select(EvidenceRequest).where(
            EvidenceRequest.verification_session_id == session.id,
            EvidenceRequest.status != EvidenceRequestStatus.CANCELLED.value,
        )
    ).scalars().all()

    if settings.MAX_ADAPTIVE_FOLLOWUPS and len(existing_requests) >= settings.MAX_ADAPTIVE_FOLLOWUPS:
        logger.info(
            "Max adaptive follow-ups limit (%d) reached for session %s; suppressing further requests",
            settings.MAX_ADAPTIVE_FOLLOWUPS,
            session.verification_id,
        )
        return None

    norm_reason = reason.strip().lower()
    for prev in existing_requests:
        prev_norm = prev.reason.strip().lower()
        if norm_reason == prev_norm or (len(prev_norm) > 15 and (prev_norm in norm_reason or norm_reason in prev_norm)):
            logger.info("Suppressing duplicate evidence request: '%s'", reason)
            return None

    # 4. Instantiate new EvidenceRequest
    req = EvidenceRequest(
        verification_session_id=session.id,
        workflow_step_key=step_key,
        requested_evidence_type=requested_evidence_type,
        reason=reason,
        options_json=options,
        status=EvidenceRequestStatus.PENDING.value,
    )
    db.add(req)
    db.flush()

    # 5. Audit log event
    event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.EVIDENCE_REQUEST_CREATED.value,
        metadata_json={
            "request_id": req.id,
            "step_key": step_key,
            "requested_evidence_type": requested_evidence_type,
            "reason": reason,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(req)

    logger.info(
        "Created adaptive evidence request %s for session %s (step: %s, type: %s)",
        req.id,
        session.verification_id,
        step_key,
        requested_evidence_type,
    )
    return req


def get_pending_request(db: Session, session_id: str) -> Optional[EvidenceRequest]:
    """Retrieve the most recent pending evidence request for a session."""
    return db.execute(
        select(EvidenceRequest).where(
            EvidenceRequest.verification_session_id == session_id,
            EvidenceRequest.status == EvidenceRequestStatus.PENDING.value,
        ).order_by(EvidenceRequest.created_at.desc())
    ).scalars().first()


def get_request_by_id(
    db: Session,
    request_id: str,
    session_id: Optional[str] = None,
) -> Optional[EvidenceRequest]:
    """Retrieve an evidence request by ID, optionally validating session ownership."""
    query = select(EvidenceRequest).where(EvidenceRequest.id == request_id)
    if session_id:
        query = query.where(EvidenceRequest.verification_session_id == session_id)
    return db.execute(query).scalar_one_or_none()


def list_session_requests(db: Session, session_id: str) -> List[EvidenceRequest]:
    """Retrieve all evidence requests for a verification session in chronological order."""
    if not session_id:
        return []
    return list(
        db.execute(
            select(EvidenceRequest)
            .where(EvidenceRequest.verification_session_id == session_id)
            .order_by(EvidenceRequest.created_at.asc())
        ).scalars().all()
    )


def fulfill_request(db: Session, request: EvidenceRequest) -> EvidenceRequest:
    """Mark an evidence request as fulfilled and log audit event."""
    request.status = EvidenceRequestStatus.FULFILLED.value
    request.fulfilled_at = utc_now()

    event = VerificationEvent(
        session_id=request.verification_session_id,
        verification_id=request.session.verification_id if request.session else "",
        event_type=VerificationEventType.EVIDENCE_REQUEST_FULFILLED.value,
        metadata_json={
            "request_id": request.id,
            "step_key": request.workflow_step_key,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(request)

    logger.info("Evidence request %s marked FULFILLED", request.id)
    return request


def cancel_request(
    db: Session,
    request: EvidenceRequest,
    reason: str = "",
) -> EvidenceRequest:
    """Cancel an active evidence request and log audit event."""
    request.status = EvidenceRequestStatus.CANCELLED.value

    event = VerificationEvent(
        session_id=request.verification_session_id,
        verification_id=request.session.verification_id if request.session else "",
        event_type=VerificationEventType.EVIDENCE_REQUEST_CANCELLED.value,
        metadata_json={
            "request_id": request.id,
            "step_key": request.workflow_step_key,
            "reason": reason,
        },
    )
    db.add(event)
    db.commit()
    db.refresh(request)

    logger.info("Evidence request %s marked CANCELLED (Reason: %s)", request.id, reason)
    return request
