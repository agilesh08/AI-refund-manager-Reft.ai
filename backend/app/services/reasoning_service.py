"""Reasoning orchestration service for local Ollama Llama 3.2 3B reasoning."""
import logging
import time
from datetime import timezone
from typing import List
from fastapi import HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.visual_analysis import VisualAnalysis
from app.models.evidence_request import EvidenceRequest
from app.models.verification_signal import VerificationSignal
from app.models.reasoning_run import ReasoningRun, ReasoningRunStatus, utc_now
from app.schemas.reasoning import ReasoningAction, ReasoningResult
from app.ai.ollama_reasoning import ollama_reasoning_service
from app.services import reasoning_context_service


logger = logging.getLogger(__name__)


def run_reasoning(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> ReasoningRun:
    """Execute a controlled local AI reasoning pass for a verification session.

    Args:
        db: Active database session.
        merchant_id: Authenticated merchant ID (enforces tenant isolation).
        verification_identifier: VerificationSession UUID id or verification_id string.

    Returns:
        ReasoningRun record (COMPLETED or FAILED).
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

    # 2. Enforce session state
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
            detail=f"Cannot run reasoning on session in '{session.status}' state; must be IN_PROGRESS",
        )

    # 3. Load evidence items and completed visual analyses
    evidence_items = db.execute(
        select(Evidence)
        .where(Evidence.verification_session_id == session.id)
        .order_by(Evidence.created_at.asc())
    ).scalars().all()

    visual_analyses = db.execute(
        select(VisualAnalysis)
        .join(Evidence)
        .where(Evidence.verification_session_id == session.id)
        .order_by(VisualAnalysis.created_at.desc())
    ).scalars().all()

    evidence_requests = db.execute(
        select(EvidenceRequest)
        .where(EvidenceRequest.verification_session_id == session.id)
        .order_by(EvidenceRequest.created_at.asc())
    ).scalars().all()

    signals = db.execute(
        select(VerificationSignal)
        .where(VerificationSignal.verification_session_id == session.id)
        .order_by(VerificationSignal.created_at.asc())
    ).scalars().all()

    # 4. Construct controlled reasoning context
    context = reasoning_context_service.build_reasoning_context(
        session=session,
        evidence_items=evidence_items,
        visual_analyses=visual_analyses,
        evidence_requests=evidence_requests,
        signals=signals,
    )


    # 5. Deterministic context hash
    context_hash = reasoning_context_service.calculate_context_hash(context)

    # 6. Check caching & idempotency
    cached_run = db.execute(
        select(ReasoningRun).where(
            ReasoningRun.verification_session_id == session.id,
            ReasoningRun.input_context_hash == context_hash,
            ReasoningRun.status == ReasoningRunStatus.COMPLETED.value,
        ).order_by(ReasoningRun.created_at.desc())
    ).scalars().first()

    if cached_run:
        logger.info(
            "Returning cached reasoning run %s for session %s (hash: %s)",
            cached_run.id,
            session.verification_id,
            context_hash[:8],
        )
        return cached_run

    # Prevent duplicate concurrent Ollama calls if a run is already actively PROCESSING
    in_progress_run = db.execute(
        select(ReasoningRun).where(
            ReasoningRun.verification_session_id == session.id,
            ReasoningRun.status == ReasoningRunStatus.PROCESSING.value,
        ).order_by(ReasoningRun.created_at.desc())
    ).scalars().first()

    if in_progress_run and in_progress_run.created_at:
        now = utc_now()
        created = in_progress_run.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed = (now - created).total_seconds()
        if elapsed < float(settings.OLLAMA_TIMEOUT_SECONDS):
            logger.warning(
                "Reasoning run %s already in progress for session %s (elapsed: %.1fs). Returning in-progress run to prevent duplicate queueing.",
                in_progress_run.id,
                session.verification_id,
                elapsed,
            )
            return in_progress_run
        else:
            in_progress_run.status = ReasoningRunStatus.FAILED.value
            in_progress_run.error_message = "Reasoning run timed out (stale processing state)"
            db.commit()

    # 7. Create ReasoningRun in PROCESSING state
    run = ReasoningRun(
        verification_session_id=session.id,
        model_name=ollama_reasoning_service.model_name,
        prompt_version=ollama_reasoning_service.prompt_version,
        input_context_hash=context_hash,
        status=ReasoningRunStatus.PROCESSING.value,
    )
    db.add(run)
    db.commit()
    db.refresh(run)

    # 8. Invoke Ollama reasoning service
    start_ts = time.time()
    try:
        raw_result = ollama_reasoning_service.generate_reasoning(context)
        from app.ai.ollama_reasoning import normalize_and_validate_reasoning_result
        result: ReasoningResult = normalize_and_validate_reasoning_result(raw_result)

        # 9. Guardrail & Closed Action Validation
        if result.action not in [
            ReasoningAction.ACCEPT_EVIDENCE,
            ReasoningAction.REQUEST_MORE_EVIDENCE,
            ReasoningAction.CONTINUE_WORKFLOW,
            ReasoningAction.COMPLETE_VERIFICATION,
        ]:
            raise ValueError(f"Action '{result.action}' is not in the allowed action vocabulary")

        # 9b. Programmatic Fail-Safe Enforcement:
        # If visual evidence analysis is FAILED or unavailable for required image evidence,
        # never allow ACCEPT_EVIDENCE.
        has_failed_visual = context.get("has_failed_visual_analysis", False)
        if has_failed_visual and result.action == ReasoningAction.ACCEPT_EVIDENCE:
            logger.warning(
                "FAIL-SAFE ENFORCED: Overriding ACCEPT_EVIDENCE for session %s because visual analysis failed or is missing",
                session.verification_id,
            )
            result.action = ReasoningAction.REQUEST_MORE_EVIDENCE
            result.requested_evidence_type = "CUSTOMER_IMAGE"
            result.reason = (
                "Visual evidence analysis could not be completed automatically. "
                "Please provide a clear, direct photo of the physical product received."
            )
            result.confidence = min(result.confidence, 0.40)
            result.reasoning_summary = (
                (result.reasoning_summary or "")
                + " [Fail-safe: Automatic visual analysis failed; positive acceptance withheld.]"
            ).strip()

        # 10. Frozen Workflow Validation
        if result.next_step_key is not None:
            snapshot_steps = (session.workflow_snapshot_json or {}).get("steps", [])
            valid_keys = {s.get("step_key") for s in snapshot_steps if s.get("step_key")}
            if result.next_step_key not in valid_keys:
                raise ValueError(
                    f"Recommended next_step_key '{result.next_step_key}' does not exist in the session's frozen workflow snapshot"
                )

        # Save success state
        run.result_json = result.model_dump()
        run.status = ReasoningRunStatus.COMPLETED.value
        run.completed_at = utc_now()

        # Audit event
        event = VerificationEvent(
            session_id=session.id,
            verification_id=session.verification_id,
            event_type=VerificationEventType.AI_REASONING_COMPLETED.value,
            metadata_json={
                "action": result.action.value,
                "confidence": result.confidence,
                "next_step_key": result.next_step_key,
                "run_id": run.id,
            },
        )
        db.add(event)
        db.commit()
        db.refresh(run)

        duration_ms = (time.time() - start_ts) * 1000
        logger.info(
            "Reasoning run %s completed successfully for session %s (Action: %s, duration: %.1fms)",
            run.id,
            session.verification_id,
            result.action.value,
            duration_ms,
        )
        return run

    except Exception as exc:
        duration_ms = (time.time() - start_ts) * 1000
        logger.error(
            "Reasoning execution failed for session %s after %.1fms: %s",
            session.verification_id,
            duration_ms,
            exc,
            exc_info=True,
        )
        run.status = ReasoningRunStatus.FAILED.value
        run.error_message = str(exc)
        run.completed_at = utc_now()

        # Fail-Safe: Verification session and customer evidence remain UNCHANGED
        event = VerificationEvent(
            session_id=session.id,
            verification_id=session.verification_id,
            event_type=VerificationEventType.AI_REASONING_FAILED.value,
            metadata_json={
                "error": str(exc)[:200],
                "run_id": run.id,
            },
        )
        db.add(event)
        db.commit()
        db.refresh(run)

        return run


def list_reasoning_runs(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> List[ReasoningRun]:
    """Retrieve full audit history of reasoning runs for an owned verification session.

    Args:
        db: Active database session.
        merchant_id: Authenticated merchant ID.
        verification_identifier: VerificationSession id or verification_id.

    Returns:
        List of ReasoningRun records in descending order of creation.
    """
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

    runs = db.execute(
        select(ReasoningRun)
        .where(ReasoningRun.verification_session_id == session.id)
        .order_by(ReasoningRun.created_at.desc())
    ).scalars().all()

    return runs
