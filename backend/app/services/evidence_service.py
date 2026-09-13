"""Customer evidence collection and multi-source signal ingestion service.

Handles:
- Evidence source abstraction (Customer, Payment, Order, Delivery, Location).
- Session state validation (must be IN_PROGRESS).
- Frozen workflow snapshot validation (step existence and type compatibility).
- Image, video, and text evidence creation with SHA-256 integrity calculation.
- Exact duplicate detection with metadata preservation.
- Secure filesystem storage under storage/evidence/ (ignoring client filenames).
- Immutable audit event trail (EvidenceEvent).
- Customer and merchant isolated evidence retrieval.
"""
import enum
import io
import logging
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, UploadFile, status
from PIL import Image
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import generate_evidence_id
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.evidence_event import EvidenceEvent, EvidenceEventType
from app.models.verification import VerificationSession, SessionStatus
from app.schemas.evidence import EvidenceTextCreateRequest
from app.services import public_verification_service, verification_service
from app.utils.file_storage import (
    calculate_sha256,
    generate_safe_evidence_filename,
    save_evidence_file,
    validate_and_read_image,
    validate_and_read_video,
)

logger = logging.getLogger(__name__)


class EvidenceSource(str, enum.Enum):
    """Architectural abstraction for multi-source evidence signal origin."""
    CUSTOMER = "CUSTOMER"
    PAYMENT = "PAYMENT"
    ORDER = "ORDER"
    DELIVERY = "DELIVERY"
    LOCATION = "LOCATION"


def validate_session_for_evidence(session: VerificationSession) -> None:
    """Validate that the session is in IN_PROGRESS state to accept customer evidence."""
    if session.status == SessionStatus.CREATED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification session has not been started. Please start the session before submitting evidence.",
        )
    if session.status == SessionStatus.COMPLETED.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification session is already completed.",
        )
    if session.status == SessionStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This verification session has been cancelled by the merchant",
        )
    if session.status == SessionStatus.EXPIRED.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="This verification session link has expired",
        )
    if session.status != SessionStatus.IN_PROGRESS.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot submit evidence for session in '{session.status}' state",
        )


def validate_workflow_step_for_evidence(
    snapshot: Dict[str, Any],
    workflow_step_key: Optional[str],
    evidence_type: EvidenceType,
) -> None:
    """Validate submitted evidence against the frozen workflow snapshot.
    
    CRITICAL: Validates against snapshot only, never querying mutable live workflow tables.
    """
    steps = snapshot.get("steps", [])

    if workflow_step_key is not None:
        step = next((s for s in steps if s.get("step_key") == workflow_step_key), None)
        if not step:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"Workflow step '{workflow_step_key}' not found in verification session workflow snapshot",
            )

        step_type = step.get("step_type", "")
        config = step.get("config_json", {}) or {}

        if evidence_type == EvidenceType.CUSTOMER_IMAGE:
            if step_type not in ("IMAGE", "CAMERA", "PAYMENT"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Workflow step '{workflow_step_key}' of type '{step_type}' does not accept image evidence. Expected IMAGE, CAMERA, or PAYMENT.",
                )

        elif evidence_type == EvidenceType.CUSTOMER_TEXT:
            if step_type not in ("TEXT", "MCQ"):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Workflow step '{workflow_step_key}' of type '{step_type}' does not accept text evidence. Expected TEXT or MCQ.",
                )

        elif evidence_type == EvidenceType.CUSTOMER_VIDEO:
            video_permitted = (
                config.get("allow_video") is True
                or config.get("video_allowed") is True
                or step_type == "VIDEO"
            )
            if not video_permitted:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail=f"Workflow step '{workflow_step_key}' does not permit video uploads",
                )
    else:
        # If no workflow_step_key is supplied for video, verify that at least one step permits video
        if evidence_type == EvidenceType.CUSTOMER_VIDEO:
            has_video_step = any(
                (s.get("config_json", {}) or {}).get("allow_video") is True
                or (s.get("config_json", {}) or {}).get("video_allowed") is True
                or s.get("step_type") == "VIDEO"
                for s in steps
            )
            if not has_video_step:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                    detail="Verification workflow does not permit video evidence",
                )


def log_evidence_event(
    db: Session,
    evidence_id: str,
    session_id: str,
    event_type: str,
    event_data: Optional[Dict[str, Any]] = None,
) -> EvidenceEvent:
    """Record an append-only audit event for submitted evidence."""
    event = EvidenceEvent(
        evidence_id=evidence_id,
        verification_session_id=session_id,
        event_type=event_type,
        event_data_json=event_data or {},
    )
    db.add(event)
    return event


async def create_customer_image_evidence(
    db: Session,
    raw_token: str,
    file: UploadFile,
    workflow_step_key: Optional[str] = None,
) -> Evidence:
    """Process, validate, store, and record customer image evidence."""
    session = public_verification_service.get_session_by_token(db, raw_token)
    validate_session_for_evidence(session)
    validate_workflow_step_for_evidence(
        session.workflow_snapshot_json,
        workflow_step_key,
        EvidenceType.CUSTOMER_IMAGE,
    )

    # 1. Image validation & reading
    file_bytes, ext = await validate_and_read_image(file, settings.MAX_IMAGE_SIZE_MB)
    sha256 = calculate_sha256(file_bytes)

    # 2. Extract dimensions without executing full image processing
    image_width, image_height, img_format = None, None, None
    try:
        with Image.open(io.BytesIO(file_bytes)) as img:
            image_width, image_height = img.size
            img_format = img.format
    except Exception:
        pass

    # 3. Duplicate detection
    existing_dup = db.execute(
        select(Evidence).where(
            Evidence.verification_session_id == session.id,
            Evidence.sha256_hash == sha256,
        )
    ).scalars().first()

    metadata: Dict[str, Any] = {
        "capture_source": "customer_upload",
        "client_filename": file.filename,
        "image_width": image_width,
        "image_height": image_height,
        "format": img_format,
    }
    if existing_dup:
        metadata["duplicate_of"] = existing_dup.evidence_id
        logger.info(
            "Identical image evidence detected for session %s (duplicate of %s)",
            session.verification_id,
            existing_dup.evidence_id,
        )

    # 4. Save file safely under storage/evidence/
    stored_filename = generate_safe_evidence_filename(session.verification_id, "image", ext)
    relative_path = save_evidence_file(file_bytes, stored_filename)

    # 5. Generate human-safe public evidence ID
    evidence_id = generate_evidence_id()

    # 6. Instantiate Evidence record
    mime_type = "image/jpeg" if ext in (".jpg", ".jpeg") else f"image/{ext.lstrip('.')}"
    evidence = Evidence(
        evidence_id=evidence_id,
        verification_session_id=session.id,
        workflow_step_key=workflow_step_key,
        evidence_type=EvidenceType.CUSTOMER_IMAGE.value,
        status=EvidenceStatus.READY_FOR_ANALYSIS.value,
        original_filename=file.filename,
        stored_filename=stored_filename,
        storage_path=relative_path,
        mime_type=mime_type,
        file_size_bytes=len(file_bytes),
        sha256_hash=sha256,
        metadata_json=metadata,
    )
    db.add(evidence)
    db.flush()

    # 7. Record immutable audit events: UPLOADED -> VALIDATED -> READY_FOR_ANALYSIS
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_UPLOADED.value,
        {"filename": file.filename, "size_bytes": len(file_bytes), "evidence_type": evidence.evidence_type},
    )
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_VALIDATED.value,
        {"sha256_hash": sha256, "mime_type": mime_type},
    )
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_READY_FOR_ANALYSIS.value,
        {"status": EvidenceStatus.READY_FOR_ANALYSIS.value},
    )

    db.commit()
    db.refresh(evidence)

    logger.info(
        "Persisted customer image evidence %s (%s) for session %s",
        evidence.id,
        evidence.evidence_id,
        session.verification_id,
    )
    return evidence


async def create_customer_video_evidence(
    db: Session,
    raw_token: str,
    file: UploadFile,
    workflow_step_key: Optional[str] = None,
) -> Evidence:
    """Process, validate, store, and record customer video evidence."""
    session = public_verification_service.get_session_by_token(db, raw_token)
    validate_session_for_evidence(session)
    validate_workflow_step_for_evidence(
        session.workflow_snapshot_json,
        workflow_step_key,
        EvidenceType.CUSTOMER_VIDEO,
    )

    # 1. Video validation & reading
    file_bytes, ext, mime_type = await validate_and_read_video(file, settings.MAX_VIDEO_SIZE_MB)
    sha256 = calculate_sha256(file_bytes)

    # 2. Duplicate detection
    existing_dup = db.execute(
        select(Evidence).where(
            Evidence.verification_session_id == session.id,
            Evidence.sha256_hash == sha256,
        )
    ).scalars().first()

    metadata: Dict[str, Any] = {
        "capture_source": "customer_upload",
        "client_filename": file.filename,
        "duration_seconds": None,
        "width": None,
        "height": None,
    }
    if existing_dup:
        metadata["duplicate_of"] = existing_dup.evidence_id
        logger.info(
            "Identical video evidence detected for session %s (duplicate of %s)",
            session.verification_id,
            existing_dup.evidence_id,
        )

    # 3. Save file safely under storage/evidence/
    stored_filename = generate_safe_evidence_filename(session.verification_id, "video", ext)
    relative_path = save_evidence_file(file_bytes, stored_filename)

    # 4. Generate human-safe public evidence ID
    evidence_id = generate_evidence_id()

    # 5. Instantiate Evidence record
    evidence = Evidence(
        evidence_id=evidence_id,
        verification_session_id=session.id,
        workflow_step_key=workflow_step_key,
        evidence_type=EvidenceType.CUSTOMER_VIDEO.value,
        status=EvidenceStatus.READY_FOR_ANALYSIS.value,
        original_filename=file.filename,
        stored_filename=stored_filename,
        storage_path=relative_path,
        mime_type=mime_type,
        file_size_bytes=len(file_bytes),
        sha256_hash=sha256,
        metadata_json=metadata,
    )
    db.add(evidence)
    db.flush()

    # 6. Record immutable audit events: UPLOADED -> VALIDATED -> READY_FOR_ANALYSIS
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_UPLOADED.value,
        {"filename": file.filename, "size_bytes": len(file_bytes), "evidence_type": evidence.evidence_type},
    )
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_VALIDATED.value,
        {"sha256_hash": sha256, "mime_type": mime_type},
    )
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_READY_FOR_ANALYSIS.value,
        {"status": EvidenceStatus.READY_FOR_ANALYSIS.value},
    )

    db.commit()
    db.refresh(evidence)

    logger.info(
        "Persisted customer video evidence %s (%s) for session %s",
        evidence.id,
        evidence.evidence_id,
        session.verification_id,
    )
    return evidence


def create_customer_text_evidence(
    db: Session,
    raw_token: str,
    data: EvidenceTextCreateRequest,
) -> Evidence:
    """Validate, record, and persist customer text evidence.
    
    Text evidence is kept strictly in the database; no filesystem files are created.
    """
    session = public_verification_service.get_session_by_token(db, raw_token)
    validate_session_for_evidence(session)
    validate_workflow_step_for_evidence(
        session.workflow_snapshot_json,
        data.workflow_step_key,
        EvidenceType.CUSTOMER_TEXT,
    )

    clean_text = data.text.strip()
    text_bytes = clean_text.encode("utf-8")
    sha256 = calculate_sha256(text_bytes)

    # Duplicate detection
    existing_dup = db.execute(
        select(Evidence).where(
            Evidence.verification_session_id == session.id,
            Evidence.sha256_hash == sha256,
        )
    ).scalars().first()

    metadata: Dict[str, Any] = {
        "capture_source": "customer_text",
        "char_length": len(clean_text),
    }
    if existing_dup:
        metadata["duplicate_of"] = existing_dup.evidence_id

    evidence_id = generate_evidence_id()

    evidence = Evidence(
        evidence_id=evidence_id,
        verification_session_id=session.id,
        workflow_step_key=data.workflow_step_key,
        evidence_type=EvidenceType.CUSTOMER_TEXT.value,
        status=EvidenceStatus.READY_FOR_ANALYSIS.value,
        original_filename=None,
        stored_filename=None,
        storage_path=None,
        mime_type="text/plain",
        file_size_bytes=len(text_bytes),
        sha256_hash=sha256,
        text_content=clean_text,
        metadata_json=metadata,
    )
    db.add(evidence)
    db.flush()

    # Record audit events
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_UPLOADED.value,
        {"evidence_type": evidence.evidence_type, "char_length": len(clean_text)},
    )
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_VALIDATED.value,
        {"sha256_hash": sha256},
    )
    log_evidence_event(
        db,
        evidence.id,
        session.id,
        EvidenceEventType.EVIDENCE_READY_FOR_ANALYSIS.value,
        {"status": EvidenceStatus.READY_FOR_ANALYSIS.value},
    )

    db.commit()
    db.refresh(evidence)

    logger.info(
        "Persisted customer text evidence %s (%s) for session %s",
        evidence.id,
        evidence.evidence_id,
        session.verification_id,
    )
    return evidence


def list_customer_evidence(
    db: Session,
    raw_token: str,
    workflow_step_key: Optional[str] = None,
) -> List[Evidence]:
    """Retrieve all evidence items for a customer verification session."""
    session = public_verification_service.get_session_by_token(db, raw_token)

    stmt = (
        select(Evidence)
        .where(Evidence.verification_session_id == session.id)
        .order_by(Evidence.created_at.asc())
    )
    if workflow_step_key:
        stmt = stmt.where(Evidence.workflow_step_key == workflow_step_key)

    return list(db.execute(stmt).scalars().all())


def get_customer_evidence_item(
    db: Session,
    raw_token: str,
    evidence_identifier: str,
) -> Evidence:
    """Retrieve a single evidence item for customer viewing or download."""
    session = public_verification_service.get_session_by_token(db, raw_token)

    evidence = db.execute(
        select(Evidence).where(
            Evidence.verification_session_id == session.id,
            or_(
                Evidence.evidence_id == evidence_identifier,
                Evidence.id == evidence_identifier,
            ),
        )
    ).scalar_one_or_none()

    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found",
        )

    return evidence


def list_merchant_evidence(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    workflow_step_key: Optional[str] = None,
) -> List[Evidence]:
    """Retrieve evidence items for a merchant's owned verification session."""
    session = verification_service.get_merchant_session(db, merchant_id, verification_identifier)

    stmt = (
        select(Evidence)
        .where(Evidence.verification_session_id == session.id)
        .order_by(Evidence.created_at.asc())
    )
    if workflow_step_key:
        stmt = stmt.where(Evidence.workflow_step_key == workflow_step_key)

    return list(db.execute(stmt).scalars().all())


def get_merchant_evidence_item(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    evidence_identifier: str,
) -> Evidence:
    """Retrieve single evidence item for merchant dashboard or evidence inspection."""
    session = verification_service.get_merchant_session(db, merchant_id, verification_identifier)

    evidence = db.execute(
        select(Evidence).where(
            Evidence.verification_session_id == session.id,
            or_(
                Evidence.evidence_id == evidence_identifier,
                Evidence.id == evidence_identifier,
            ),
        )
    ).scalar_one_or_none()

    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found",
        )

    return evidence
