"""Adaptive verification orchestration service.

Binds the closed-loop adaptive cycle:
Customer Evidence Fulfillment -> Gemini Vision Re-Analysis -> Llama Re-Reasoning -> Terminal Action or Request Follow-Up.
"""
import logging
from typing import Optional, Tuple
from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence
from app.models.evidence_request import EvidenceRequest, EvidenceRequestStatus
from app.models.reasoning_run import ReasoningRun, ReasoningRunStatus
from app.models.verification import VerificationSession, SessionStatus
from app.schemas.reasoning import ReasoningAction
from app.services import (
    evidence_request_service,
    evidence_service,
    public_verification_service,
    reasoning_service,
)

logger = logging.getLogger(__name__)


def run_adaptive_reasoning_cycle(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> Tuple[ReasoningRun, Optional[EvidenceRequest]]:
    """Execute reasoning run and automatically manage follow-up EvidenceRequest creation.

    Enforces:
    - AI actions bounded to closed vocabulary.
    - Max adaptive follow-ups cutoff (settings.MAX_ADAPTIVE_FOLLOWUPS).
    - If Llama selects REQUEST_MORE_EVIDENCE, safely validates step and creates request.
    - If max follow-ups reached, suppresses request creation and returns run.

    Returns:
        Tuple of (ReasoningRun, Optional[EvidenceRequest]).
    """
    run = reasoning_service.run_reasoning(
        db=db,
        merchant_id=merchant_id,
        verification_identifier=verification_identifier,
    )

    if run.status != ReasoningRunStatus.COMPLETED.value or not run.result_json:
        return run, None

    action = run.result_json.get("action")
    if action != ReasoningAction.REQUEST_MORE_EVIDENCE.value:
        return run, None

    # Llama requested more evidence
    step_key = run.result_json.get("next_step_key")
    if not step_key:
        logger.warning(
            "Reasoning run %s requested more evidence but provided no next_step_key",
            run.id,
        )
        return run, None

    session = db.get(VerificationSession, run.verification_session_id)
    if not session:
        return run, None

    raw_type = str(run.result_json.get("requested_evidence_type") or "CUSTOMER_IMAGE").upper()
    if "MCQ" in raw_type or "CHOICE" in raw_type:
        requested_type = "MCQ"
    elif "TEXT" in raw_type:
        requested_type = "CUSTOMER_TEXT"
    else:
        requested_type = "CUSTOMER_IMAGE"

    options = run.result_json.get("options") or run.result_json.get("choices")
    if isinstance(options, list):
        options = [str(o).strip() for o in options if str(o).strip()]
    else:
        options = None

    question = run.result_json.get("question")
    reason = (
        question
        or run.result_json.get("reason")
        or run.result_json.get("reasoning_summary")
        or "Please provide follow-up evidence for this item."
    )

    # Consolidate customer claim and visual AI observation gap into targeted follow-up reason
    customer_claim = (session.refund_reason or "").strip()
    visual_gap = ""
    try:
        from app.models.visual_analysis import VisualAnalysis
        from sqlalchemy import select
        latest_img = db.execute(
            select(Evidence).where(
                Evidence.verification_session_id == session.id,
                Evidence.evidence_type == "CUSTOMER_IMAGE",
            ).order_by(Evidence.created_at.desc())
        ).scalars().first()
        if latest_img:
            va = db.execute(
                select(VisualAnalysis).where(VisualAnalysis.evidence_id == latest_img.id).order_by(VisualAnalysis.created_at.desc())
            ).scalars().first()
            if va and va.result_json:
                unc = va.result_json.get("uncertainties") or []
                obs = va.result_json.get("key_visual_observations") or []
                if unc:
                    visual_gap = unc[0]
                elif obs:
                    visual_gap = obs[0]
    except Exception:
        pass

    # Prefer merchant-configured follow-up questions for this session's workflow scenario if available
    try:
        snapshot = session.workflow_snapshot_json or {}
        configured_fqs = []
        for step in snapshot.get("steps", []):
            cfg = step.get("config") or step.get("config_json") or {}
            for opt in (cfg.get("options") or cfg.get("choices") or cfg.get("scenarios") or []):
                if isinstance(opt, dict) and isinstance(opt.get("follow_up_questions"), list):
                    configured_fqs.extend(opt.get("follow_up_questions"))
        if configured_fqs and (reason == "Please provide follow-up evidence for this item." or not any(q.lower() in reason.lower() for q in configured_fqs)):
            reason = configured_fqs[0]
        elif (customer_claim and visual_gap and (
            reason == "Please provide follow-up evidence for this item."
            or "upload more evidence" in reason.lower()
            or "follow-up evidence" in reason.lower()
            or "upload another photo" in reason.lower()
        )):
            reason = f"Based on your claim ('{customer_claim}') and the observation ('{visual_gap}'), please capture a clear photo focusing specifically on this area."
    except Exception:
        pass

    # Semantic Deduplication helper
    def extract_semantic_keywords(text: str) -> set:
        import re
        words = set(re.findall(r"\w+", text.lower()))
        stopwords = {"a", "an", "the", "please", "capture", "take", "photo", "image", "upload", "of", "you", "your", "for", "item", "and", "or", "in", "on", "is", "it", "this", "to"}
        return words - stopwords

    # Deduplication check: prevent asking the same question or semantically equivalent requests
    existing_requests = session.evidence_requests or []
    new_keywords = extract_semantic_keywords(reason)
    for prev_req in existing_requests:
        prev_reason = (getattr(prev_req, "reason", "") or "").strip().lower()
        if reason.strip().lower() == prev_reason:
            logger.info("Adaptive question '%s' was already asked previously; skipping duplicate.", reason)
            return run, None
        
        # Check semantic equivalence
        prev_keywords = extract_semantic_keywords(prev_reason)
        if new_keywords and prev_keywords:
            intersection = new_keywords & prev_keywords
            union = new_keywords | prev_keywords
            jaccard = len(intersection) / float(len(union))
            if jaccard >= 0.65:
                logger.info("Adaptive question '%s' is semantically equivalent to previous '%s' (Jaccard: %.2f); skipping duplicate.", reason, prev_reason, jaccard)
                return run, None


    # Anti-repetition: if last fulfilled request was CUSTOMER_IMAGE and this is CUSTOMER_IMAGE again,
    # but the reasoning run has a 'question' field (MCQ/TEXT intent), override to the more efficient type.
    if requested_type == "CUSTOMER_IMAGE" and existing_requests:
        fulfilled_image_reqs = [
            r for r in existing_requests
            if getattr(r, "requested_evidence_type", "") == "CUSTOMER_IMAGE"
            and getattr(r, "status", "") == "FULFILLED"
        ]
        if fulfilled_image_reqs:
            # Last follow-up was also an image request — try to offer MCQ/TEXT if a question is available
            question_text = run.result_json.get("question")
            llama_options = run.result_json.get("options")
            if question_text and isinstance(llama_options, list) and 2 <= len(llama_options) <= 5:
                logger.info(
                    "Switching consecutive CUSTOMER_IMAGE follow-up to MCQ (anti-repetition): '%s'",
                    question_text,
                )
                requested_type = "MCQ"
                reason = question_text
                options = [str(o).strip() for o in llama_options if str(o).strip()]
            elif question_text and not llama_options:
                logger.info(
                    "Switching consecutive CUSTOMER_IMAGE follow-up to CUSTOMER_TEXT (anti-repetition): '%s'",
                    question_text,
                )
                requested_type = "CUSTOMER_TEXT"
                reason = question_text
                options = None


    try:
        req = evidence_request_service.create_evidence_request(
            db=db,
            session=session,
            step_key=step_key,
            requested_evidence_type=requested_type,
            reason=reason,
            options=options,
        )
        return run, req
    except Exception as exc:
        logger.warning(
            "Failed to create evidence request from reasoning run %s: %s",
            run.id,
            exc,
        )
        return run, None


async def handle_customer_fulfillment(
    db: Session,
    raw_token: str,
    request_id: str,
    file: Optional[UploadFile] = None,
    text_content: Optional[str] = None,
    selected_option: Optional[str] = None,
) -> Tuple[EvidenceRequest, Evidence, Optional[ReasoningRun]]:
    """Handle customer uploading evidence to fulfill an active evidence request.

    Orchestrates:
    1. Token & session validation.
    2. Evidence request lookup (must be PENDING).
    3. Storage & creation of customer image or text evidence.
    4. Transition of EvidenceRequest to FULFILLED.
    5. Automated Gemini Vision visual analysis if image.
    6. Automated local Llama reasoning cycle.

    Fail-safe:
    If AI visual analysis or reasoning encounters an issue, the customer's
    submitted evidence and fulfilled request remain securely stored and valid.
    """
    # 1. Fetch and validate session
    session = public_verification_service.get_session_by_token(db, raw_token)
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
            detail=f"Verification session is in '{session.status}' state; must be IN_PROGRESS",
        )

    # 2. Fetch target evidence request
    evidence_req = evidence_request_service.get_request_by_id(
        db=db,
        request_id=request_id,
        session_id=session.id,
    )
    if not evidence_req:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence request not found for this verification session",
        )

    if evidence_req.status != EvidenceRequestStatus.PENDING.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Evidence request is in '{evidence_req.status}' state; only PENDING requests can be fulfilled",
        )

    # 3. Create customer evidence (Image or Text/Option)
    evidence = None
    if file is not None and getattr(file, "filename", None):
        evidence = await evidence_service.create_customer_image_evidence(
            db=db,
            raw_token=raw_token,
            file=file,
            workflow_step_key=evidence_req.workflow_step_key,
        )
    elif text_content or selected_option:
        from app.schemas.evidence import EvidenceTextCreateRequest
        ans_text = (selected_option or text_content or "").strip()
        text_data = EvidenceTextCreateRequest(
            workflow_step_key=evidence_req.workflow_step_key,
            text=ans_text,
        )
        evidence = evidence_service.create_customer_text_evidence(
            db=db,
            raw_token=raw_token,
            data=text_data,
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Fulfillment requires either a photo file or text/option response",
        )

    # 4. Mark request as FULFILLED
    fulfilled_req = evidence_request_service.fulfill_request(db, evidence_req)

    # 5. Automatically trigger Gemini Vision analysis (only for image evidence)
    if evidence.evidence_type == "CUSTOMER_IMAGE":
        try:
            from app.services import evidence_processing_service
            evidence_processing_service.analyze_evidence_image(
                db=db,
                merchant_id=session.merchant_id,
                verification_identifier=session.id,
                evidence_identifier=evidence.id,
                force_reanalyze=True,
            )
        except Exception as exc:
            logger.warning(
                "Automated visual analysis during adaptive fulfillment failed gracefully: %s",
                exc,
            )

    # 6. Automatically trigger Llama reasoning cycle (fail-safe)
    reasoning_run = None
    try:
        run, _ = run_adaptive_reasoning_cycle(
            db=db,
            merchant_id=session.merchant_id,
            verification_identifier=session.id,
        )
        reasoning_run = run
    except Exception as exc:
        logger.warning(
            "Automated adaptive reasoning cycle during fulfillment failed gracefully: %s",
            exc,
        )

    return fulfilled_req, evidence, reasoning_run
