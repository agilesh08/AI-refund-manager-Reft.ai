"""Evidence analysis service for AI visual consistency analysis.

Handles Gemini Vision multimodal analysis comparing customer evidence images
against merchant trusted product reference angles (FRONT, BACK, LEFT, RIGHT).
"""
import logging
from typing import Any, Dict, List, Optional
from fastapi import HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence, EvidenceStatus, EvidenceType
from app.models.evidence_event import EvidenceEvent
from app.models.verification import VerificationSession
from app.models.product_reference import ProductReference, ReferenceAngle
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus, utc_now
from app.schemas.evidence import EvidenceProcessPlaceholderResponse
from app.schemas.visual_analysis import VisualAnalysisResult
from app.ai.qwen_vision import qwen_vision_service
from app.utils.file_storage import get_evidence_file_path, get_reference_file_path

logger = logging.getLogger(__name__)

REQUIRED_REFERENCE_ANGLES = {
    ReferenceAngle.FRONT.value,
    ReferenceAngle.BACK.value,
    ReferenceAngle.LEFT.value,
    ReferenceAngle.RIGHT.value,
}


def guess_image_mime(path: str) -> str:
    """Guess MIME type from file extension."""
    ext = path.lower().rsplit(".", 1)[-1] if "." in path else ""
    if ext in ("jpg", "jpeg"):
        return "image/jpeg"
    elif ext == "png":
        return "image/png"
    elif ext == "webp":
        return "image/webp"
    return "image/jpeg"


def process_evidence(db: Session, evidence_identifier: str) -> EvidenceProcessPlaceholderResponse:
    """Pre-analysis queue boundary function preserved from Milestone 6."""
    evidence = db.execute(
        select(Evidence).where(
            or_(
                Evidence.evidence_id == evidence_identifier,
                Evidence.id == evidence_identifier,
            )
        )
    ).scalar_one_or_none()

    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence not found",
        )

    if evidence.status != EvidenceStatus.READY_FOR_ANALYSIS.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Evidence is in '{evidence.status}' state, expected READY_FOR_ANALYSIS",
        )

    logger.info("Evidence %s verified and ready for downstream analysis queue", evidence.evidence_id)

    return EvidenceProcessPlaceholderResponse(
        evidence_id=evidence.evidence_id,
        status=evidence.status,
        message="Evidence verified and queued for future AI analysis pipeline",
        placeholder=True,
    )


def analyze_evidence_image(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    evidence_identifier: str,
    force_reanalyze: bool = False,
) -> VisualAnalysis:
    """Run Gemini Vision visual consistency analysis on customer image evidence.

    Args:
        db: Active database session.
        merchant_id: ID of the authenticated merchant.
        verification_identifier: VerificationSession id or human verification_id.
        evidence_identifier: Evidence id or evidence_id.
        force_reanalyze: If True, bypass cached COMPLETED results and re-run analysis.

    Returns:
        VisualAnalysis record (COMPLETED or FAILED).
    """
    # 1. Fetch verification session enforcing merchant isolation
    session = db.execute(
        select(VerificationSession).where(
            or_(
                VerificationSession.id == verification_identifier,
                VerificationSession.verification_id == verification_identifier,
            ),
            VerificationSession.merchant_id == merchant_id,
        )
    ).scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found",
        )

    # 2. Fetch evidence item belonging to this session
    evidence = db.execute(
        select(Evidence).where(
            or_(
                Evidence.id == evidence_identifier,
                Evidence.evidence_id == evidence_identifier,
            ),
            Evidence.verification_session_id == session.id,
        )
    ).scalar_one_or_none()

    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence item not found for this verification session",
        )

    # 3. Validate evidence type (only CUSTOMER_IMAGE is eligible for visual analysis)
    if evidence.evidence_type != EvidenceType.CUSTOMER_IMAGE.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Visual analysis is only applicable to image evidence (CUSTOMER_IMAGE), got {evidence.evidence_type}",
        )

    if not evidence.storage_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Evidence does not have an associated file path on disk",
        )

    # 4. Check retry safety / caching
    if not force_reanalyze:
        existing_completed = db.execute(
            select(VisualAnalysis)
            .where(
                VisualAnalysis.evidence_id == evidence.id,
                VisualAnalysis.status == VisualAnalysisStatus.COMPLETED.value,
            )
            .order_by(VisualAnalysis.created_at.desc())
        ).scalars().first()

        if existing_completed:
            logger.info(
                "Returning cached visual analysis %s for evidence %s",
                existing_completed.id,
                evidence.evidence_id,
            )
            return existing_completed

    # 5. Read customer evidence file from storage
    evidence_path = get_evidence_file_path(evidence.storage_path)
    evidence_bytes = evidence_path.read_bytes()
    evidence_mime = evidence.mime_type or guess_image_mime(evidence.storage_path)

    # 6. Retrieve stored ProductVisualProfile directly from DB without reconsolidating
    from app.models.product_visual_profile import ProductVisualProfile, ProductVisualProfileStatus
    profile = db.execute(
        select(ProductVisualProfile).where(ProductVisualProfile.product_id == session.product_id)
    ).scalar_one_or_none()
    profile_dict = profile.profile_json if (profile and profile.status == ProductVisualProfileStatus.READY.value) else None

    # Optionally pass max 1 FRONT reference image if available for fallback visual comparison
    product_refs = db.execute(
        select(ProductReference).where(ProductReference.product_id == session.product_id)
    ).scalars().all()

    reference_images_payload: List[Dict[str, Any]] = []
    if product_refs:
        front_ref = next((r for r in product_refs if r.angle == "FRONT"), product_refs[0])
        try:
            ref_file_path = get_reference_file_path(front_ref.image_path)
            ref_bytes = ref_file_path.read_bytes()
            ref_mime = guess_image_mime(front_ref.image_path)
            reference_images_payload.append({
                "angle": front_ref.angle,
                "bytes": ref_bytes,
                "mime_type": ref_mime,
            })
        except Exception as exc:
            logger.warning("Could not read front reference file: %s", exc)

    # 7. Prepare product info and claim context
    product_info = {}
    if session.product:
        product_info = {
            "name": session.product.name,
            "sku": session.product.sku,
            "description": session.product.description or "",
            "price": str(session.product.price) if session.product.price is not None else "0.00",
        }

    claim_context = {
        "workflow_step_key": evidence.workflow_step_key,
        "customer_notes": session.refund_reason or "",
        "order_id": session.order_id,
        "customer_name": session.customer_name or "",
    }

    # 8. Create VisualAnalysis record in PROCESSING state
    analysis = VisualAnalysis(
        evidence_id=evidence.id,
        model_name=qwen_vision_service.model_name,
        prompt_version=qwen_vision_service.prompt_version,
        status=VisualAnalysisStatus.PROCESSING.value,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)

    # 9. Invoke local Qwen2.5-VL Vision service with 1 customer image + visual profile
    try:
        result: VisualAnalysisResult = qwen_vision_service.analyze_evidence_image(
            evidence_bytes=evidence_bytes,
            evidence_mime_type=evidence_mime,
            reference_images=reference_images_payload,
            product_info=product_info,
            claim_context=claim_context,
            visual_profile=profile_dict,
        )

        analysis.result_json = result.model_dump()
        analysis.overall_confidence = result.overall_visual_confidence
        analysis.status = VisualAnalysisStatus.COMPLETED.value
        analysis.completed_at = utc_now()

        # Update evidence status to ANALYZED
        evidence.status = EvidenceStatus.ANALYZED.value

        # Log audit event
        event = EvidenceEvent(
            evidence_id=evidence.id,
            verification_session_id=session.id,
            event_type="AI_VISUAL_ANALYSIS_COMPLETED",
            event_data_json={
                "actor": "SYSTEM_QWEN_VISION",
                "note": f"Qwen visual analysis completed with confidence {result.overall_visual_confidence}",
                "confidence": result.overall_visual_confidence,
            },
        )
        db.add(event)
        db.commit()
        db.refresh(analysis)

        logger.info(
            "Visual analysis %s completed successfully for evidence %s",
            analysis.id,
            evidence.evidence_id,
        )
        return analysis

    except Exception as exc:
        logger.error(
            "Visual analysis failed for evidence %s: %s",
            evidence.evidence_id,
            exc,
            exc_info=True,
        )
        analysis.status = VisualAnalysisStatus.FAILED.value
        analysis.error_message = str(exc)
        analysis.completed_at = utc_now()

        # Customer evidence remains READY_FOR_ANALYSIS (never accuse customer or fail claim due to AI failure)
        event = EvidenceEvent(
            evidence_id=evidence.id,
            verification_session_id=session.id,
            event_type="AI_VISUAL_ANALYSIS_FAILED",
            event_data_json={
                "actor": "SYSTEM_QWEN_VISION",
                "note": f"Qwen visual analysis failed: {str(exc)[:200]}",
                "error": str(exc)[:500],
            },
        )
        db.add(event)
        db.commit()
        db.refresh(analysis)

        return analysis


def get_evidence_analysis(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    evidence_identifier: str,
) -> VisualAnalysis:
    """Retrieve the latest visual analysis for a merchant-owned evidence item.

    Args:
        db: Active database session.
        merchant_id: ID of the authenticated merchant.
        verification_identifier: VerificationSession id or verification_id.
        evidence_identifier: Evidence id or evidence_id.

    Returns:
        Latest VisualAnalysis record.
    """
    # 1. Fetch verification session enforcing merchant isolation
    session = db.execute(
        select(VerificationSession).where(
            or_(
                VerificationSession.id == verification_identifier,
                VerificationSession.verification_id == verification_identifier,
            ),
            VerificationSession.merchant_id == merchant_id,
        )
    ).scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found",
        )

    # 2. Fetch evidence item
    evidence = db.execute(
        select(Evidence).where(
            or_(
                Evidence.id == evidence_identifier,
                Evidence.evidence_id == evidence_identifier,
            ),
            Evidence.verification_session_id == session.id,
        )
    ).scalar_one_or_none()

    if not evidence:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence item not found for this verification session",
        )

    # 3. Retrieve latest VisualAnalysis
    analysis = db.execute(
        select(VisualAnalysis)
        .where(VisualAnalysis.evidence_id == evidence.id)
        .order_by(VisualAnalysis.created_at.desc())
    ).scalars().first()

    if not analysis:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No visual analysis found for this evidence item",
        )

    return analysis
