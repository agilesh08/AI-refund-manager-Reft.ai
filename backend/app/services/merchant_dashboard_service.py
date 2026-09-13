"""Service layer for Milestone 12: Merchant Dashboard, Investigation View, Timeline, and Explainable Report."""
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import select, or_, and_, func, desc, distinct
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.merchant_decision import MerchantDecision, DecisionType
from app.models.product import Product
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.evidence import Evidence, EvidenceType
from app.models.evidence_event import EvidenceEvent
from app.models.evidence_fusion import EvidenceFusionResult, VerificationAssessmentState
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.models.reasoning_run import ReasoningRun
from app.models.evidence_request import EvidenceRequest
from app.models.verification_signal import VerificationSignal, SignalStatus
from app.schemas.evidence import EvidenceResponse
from app.schemas.evidence_request import EvidenceRequestResponse
from app.schemas.evidence_fusion import (
    FusionResponse,
    FusionDimensionResult,
    ContradictionItem,
    MissingEvidenceItem,
    FusionExplanation,
)
from app.schemas.reasoning import ReasoningRunResponse
from app.services.evidence_fusion_service import map_confidence_to_recommendation
from app.schemas.merchant_dashboard import (
    DashboardVerificationItem,
    DashboardVerificationListResponse,
    MerchantDecisionCreateRequest,
    MerchantDecisionResponse,
    TimelineItemResponse,
    ReportAssessmentSection,
    ReportClaimSection,
    ReportEvidenceSummarySection,
    ReportVisualEvidenceItem,
    ReportSignalItem,
    ReportAiExplanationSection,
    ExplainableVerificationReportResponse,
    VerificationDetailDashboardResponse,
)

logger = logging.getLogger("refund_verification.merchant_dashboard")


def utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


# ===========================================================================
# 1. Dashboard Verification Listing Service
# ===========================================================================

def list_dashboard_verifications(
    db: Session,
    merchant_id: str,
    status: Optional[str] = None,
    assessment_state: Optional[str] = None,
    date_from: Optional[datetime] = None,
    date_to: Optional[datetime] = None,
    search: Optional[str] = None,
    order_id: Optional[str] = None,
    product_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
    status_filter: Optional[str] = None,
    assessment_state_filter: Optional[str] = None,
) -> DashboardVerificationListResponse:
    """List verification sessions for merchant dashboard with filtering, search, and pagination."""
    effective_status = status or status_filter
    effective_assessment_state = assessment_state or assessment_state_filter

    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 20
    if page_size > 100:
        page_size = 100

    # Subquery for the latest fusion result per verification session
    latest_fusion_subq = (
        select(
            EvidenceFusionResult.verification_session_id,
            EvidenceFusionResult.assessment_state,
            EvidenceFusionResult.overall_confidence,
            func.row_number()
            .over(
                partition_by=EvidenceFusionResult.verification_session_id,
                order_by=EvidenceFusionResult.created_at.desc(),
            )
            .label("rn"),
        )
        .subquery()
    )

    # Base query joined with Product and latest fusion
    query = (
        select(
            VerificationSession,
            Product.name.label("product_name"),
            latest_fusion_subq.c.assessment_state,
            latest_fusion_subq.c.overall_confidence,
        )
        .outerjoin(Product, VerificationSession.product_id == Product.id)
        .outerjoin(
            latest_fusion_subq,
            and_(
                latest_fusion_subq.c.verification_session_id == VerificationSession.id,
                latest_fusion_subq.c.rn == 1,
            ),
        )
        .where(VerificationSession.merchant_id == merchant_id)
    )

    count_query = (
        select(func.count(distinct(VerificationSession.id)))
        .select_from(VerificationSession)
        .outerjoin(Product, VerificationSession.product_id == Product.id)
        .outerjoin(
            latest_fusion_subq,
            and_(
                latest_fusion_subq.c.verification_session_id == VerificationSession.id,
                latest_fusion_subq.c.rn == 1,
            ),
        )
        .where(VerificationSession.merchant_id == merchant_id)
    )

    # Status filter
    if effective_status:
        clean_status = effective_status.strip().upper()
        query = query.where(VerificationSession.status == clean_status)
        count_query = count_query.where(VerificationSession.status == clean_status)

    # Assessment state filter
    if effective_assessment_state:
        clean_state = effective_assessment_state.strip().upper()
        query = query.where(latest_fusion_subq.c.assessment_state == clean_state)
        count_query = count_query.where(latest_fusion_subq.c.assessment_state == clean_state)

    # Date range filters
    if date_from:
        query = query.where(VerificationSession.created_at >= date_from)
        count_query = count_query.where(VerificationSession.created_at >= date_from)
    if date_to:
        query = query.where(VerificationSession.created_at <= date_to)
        count_query = count_query.where(VerificationSession.created_at <= date_to)

    # Order ID filter
    if order_id:
        query = query.where(VerificationSession.order_id == order_id.strip())
        count_query = count_query.where(VerificationSession.order_id == order_id.strip())

    # Product ID filter
    if product_id:
        query = query.where(VerificationSession.product_id == product_id.strip())
        count_query = count_query.where(VerificationSession.product_id == product_id.strip())

    # Search filter across multiple identifiers and text fields
    if search:
        s = f"%{search.strip()}%"
        search_clause = or_(
            VerificationSession.verification_id.ilike(s),
            VerificationSession.order_id.ilike(s),
            VerificationSession.customer_name.ilike(s),
            VerificationSession.customer_contact.ilike(s),
            Product.name.ilike(s),
            Product.sku.ilike(s),
        )
        query = query.where(search_clause)
        count_query = count_query.where(search_clause)

    # Total count
    total = db.execute(count_query).scalar_one() or 0

    # Order and paginate
    offset = (page - 1) * page_size
    query = query.order_by(VerificationSession.created_at.desc()).offset(offset).limit(page_size)

    rows = db.execute(query).all()

    items: List[DashboardVerificationItem] = []
    now = utc_now()
    for sess, prod_name, assess_state, conf in rows:
        # Check lazy hold expiry
        if (
            sess.status == SessionStatus.HELD.value
            and sess.hold_until is not None
            and sess.hold_until <= now
        ):
            restored = (
                SessionStatus.COMPLETED.value
                if sess.completed_at
                else (SessionStatus.IN_PROGRESS.value if sess.started_at else SessionStatus.CREATED.value)
            )
            sess.status = restored
            sess.held_at = None
            sess.hold_until = None
            sess.held_by = None
            db.commit()

        updated_at = sess.completed_at or sess.started_at or sess.created_at
        latest_dec = None
        if sess.merchant_decisions:
            latest_dec = sess.merchant_decisions[0].decision
        ev_count = len(sess.evidence_items) if sess.evidence_items else 0
        prod_obj = {
            "id": sess.product.id if sess.product else None,
            "name": sess.product.name if sess.product else prod_name,
            "sku": sess.product.sku if sess.product else None,
        }
        rec_code, rec_label = map_confidence_to_recommendation(conf, assess_state)
        items.append(
            DashboardVerificationItem(
                id=sess.id,
                verification_id=sess.verification_id,
                order_id=sess.order_id,
                product_name=prod_name,
                refund_amount=float(sess.refund_amount) if sess.refund_amount is not None else None,
                status=sess.status,
                customer_id=sess.customer_id,
                customer_email=sess.customer_email,
                assessment_state=assess_state,
                latest_assessment_state=assess_state,
                confidence=round(conf, 2) if conf is not None else None,
                latest_decision=latest_dec,
                evidence_count=ev_count,
                product=prod_obj,
                held_at=sess.held_at,
                hold_until=sess.hold_until,
                held_by=sess.held_by,
                created_at=sess.created_at,
                updated_at=updated_at,
                recommendation_code=rec_code,
                recommendation_label=rec_label,
            )
        )

    return DashboardVerificationListResponse(
        items=items,
        page=page,
        page_size=page_size,
        total=total,
    )


# ===========================================================================
# 2. Verification Timeline Service
# ===========================================================================

def build_verification_timeline(
    session: Optional[VerificationSession] = None,
    analyses: Optional[List[VisualAnalysis]] = None,
    db: Optional[Session] = None,
    merchant_id: Optional[str] = None,
    verification_identifier: Optional[str] = None,
) -> List[TimelineItemResponse]:
    """Compile a strictly chronological audit timeline from real event records."""
    if session is None:
        if db is None or merchant_id is None or verification_identifier is None:
            raise ValueError("Must provide either session or (db, merchant_id, verification_identifier)")
        return get_verification_timeline(db=db, merchant_id=merchant_id, verification_identifier=verification_identifier)

    timeline: List[TimelineItemResponse] = []

    # 1. Verification events
    for ev in session.events or []:
        event_type = ev.event_type
        meta = ev.metadata_json or {}
        timestamp = ev.created_at

        title = event_type.replace("_", " ").title()
        description = "Verification session event occurred."
        source = "SYSTEM"

        if event_type == VerificationEventType.SESSION_CREATED.value:
            title = "Verification Created"
            description = f"Session {session.verification_id} created for order {session.order_id}."
            source = "MERCHANT"
        elif event_type == VerificationEventType.SESSION_STARTED.value:
            title = "Customer Started Verification"
            description = "Customer accessed link and commenced guided workflow."
            source = "CUSTOMER"
        elif event_type == VerificationEventType.SESSION_CANCELLED.value:
            title = "Verification Cancelled"
            description = "Session was explicitly cancelled by the merchant."
            source = "MERCHANT"
        elif event_type == VerificationEventType.SESSION_EXPIRED.value:
            title = "Verification Expired"
            description = "Session exceeded configured expiration duration."
            source = "SYSTEM"
        elif event_type == VerificationEventType.SIGNAL_CREATED.value:
            sig_type = meta.get("signal_type", "FACTUAL")
            title = f"{sig_type} Signal Ingested"
            description = f"Deterministic {sig_type} signal recorded (ref: {meta.get('source_reference', 'N/A')})."
            source = "EXTERNAL_SIGNAL"
        elif event_type == VerificationEventType.SIGNAL_UPDATED.value:
            sig_type = meta.get("signal_type", "FACTUAL")
            title = f"{sig_type} Signal Updated"
            description = f"Signal payload updated for reference {meta.get('source_reference', 'N/A')}."
            source = "EXTERNAL_SIGNAL"
        elif event_type == VerificationEventType.FUSION_STARTED.value:
            title = "Evidence Fusion Started"
            description = "Deterministic multi-source evidence fusion initiated."
            source = "SYSTEM"
        elif event_type == VerificationEventType.FUSION_COMPLETED.value:
            state = meta.get("assessment_state", "COMPLETED")
            title = "Evidence Fusion Completed"
            description = f"Deterministic assessment reached: {state}."
            source = "SYSTEM"
        elif event_type == VerificationEventType.FUSION_FAILED.value:
            title = "Evidence Fusion Failed"
            description = "Fusion engine encountered an unexpected error."
            source = "SYSTEM"
        elif event_type == VerificationEventType.AI_REASONING_COMPLETED.value:
            action = meta.get("recommended_action", "ANALYZED")
            title = "AI Reasoning Completed"
            description = f"Llama 3.2 recommended workflow action: {action}."
            source = "LLAMA_REASONING"
        elif event_type == VerificationEventType.EVIDENCE_REQUEST_CREATED.value:
            step = meta.get("workflow_step_key", "followup")
            title = "Additional Evidence Requested"
            description = f"System requested follow-up evidence for step '{step}'."
            source = "LLAMA_REASONING"
        elif event_type == VerificationEventType.EVIDENCE_REQUEST_FULFILLED.value:
            title = "Follow-Up Evidence Submitted"
            description = "Customer provided requested follow-up evidence."
            source = "CUSTOMER"
        elif event_type == VerificationEventType.MERCHANT_DECISION_MADE.value:
            decision = meta.get("decision", "RECORDED")
            title = f"Merchant Decision: {decision}"
            description = f"Merchant finalized session: {decision}. Reason: {meta.get('reason', 'N/A')}."
            source = "MERCHANT"

        timeline.append(
            TimelineItemResponse(
                timestamp=timestamp,
                event_type=event_type,
                title=title,
                description=description,
                source=source,
                metadata=meta,
            )
        )

    # 2. Evidence events
    for ev in session.evidence_events or []:
        event_type = ev.event_type
        meta = ev.event_data_json or {}
        timestamp = ev.created_at

        title = "Customer Evidence Uploaded"
        description = f"Customer submitted evidence (step: {meta.get('workflow_step_key', 'general')})."
        source = "CUSTOMER"

        if event_type == "EVIDENCE_VALIDATED":
            title = "Evidence Validated"
            description = "Submitted evidence passed integrity, MIME, and bounds verification."
            source = "SYSTEM"
        elif event_type == "EVIDENCE_READY_FOR_ANALYSIS":
            title = "Evidence Ready For Analysis"
            description = "Evidence queued for consistency inspection."
            source = "SYSTEM"
        elif event_type == "EVIDENCE_REJECTED":
            title = "Evidence Rejected"
            description = f"Evidence submission rejected: {meta.get('reason', 'Failed validation')}."
            source = "SYSTEM"

        timeline.append(
            TimelineItemResponse(
                timestamp=timestamp,
                event_type=event_type,
                title=title,
                description=description,
                source=source,
                metadata=meta,
            )
        )

    # 3. Visual Analyses
    for vis in analyses or []:
        if vis.status == VisualAnalysisStatus.COMPLETED.value:
            timeline.append(
                TimelineItemResponse(
                    timestamp=vis.created_at,
                    event_type="VISUAL_ANALYSIS_COMPLETED",
                    title="Gemini Visual Consistency Analysis Completed",
                    description=f"Model {vis.model_name} analyzed evidence item against trusted baseline references.",
                    source="GEMINI_VISION",
                    metadata={"confidence": vis.overall_confidence, "evidence_id": vis.evidence_id},
                )
            )

    # 4. Merchant Decisions
    for dec in session.merchant_decisions or []:
        timeline.append(
            TimelineItemResponse(
                timestamp=dec.decided_at,
                event_type="MERCHANT_DECISION_RECORDED",
                title=f"Merchant Decision: {dec.decision}",
                description=f"Merchant recorded decision: {dec.decision}. Reason: {dec.decision_reason or 'No reason specified'}.",
                source="MERCHANT",
                metadata={"decision": dec.decision, "reason": dec.decision_reason},
            )
        )

    # Deduplicate events by timestamp and title if identical
    seen = set()
    unique_timeline: List[TimelineItemResponse] = []
    for item in sorted(timeline, key=lambda x: x.timestamp):
        key = (item.timestamp.isoformat(), item.event_type, item.title)
        if key not in seen:
            seen.add(key)
            unique_timeline.append(item)

    return unique_timeline


def get_verification_timeline(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> List[TimelineItemResponse]:
    """Retrieve compiled chronological timeline from real audit events."""
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

    evidence_items = list(session.evidence_items or [])
    analyses = []
    if evidence_items:
        analyses = list(
            db.execute(
                select(VisualAnalysis).where(
                    VisualAnalysis.evidence_id.in_([e.id for e in evidence_items])
                )
            ).scalars().all()
        )

    return build_verification_timeline(session=session, analyses=analyses)


# ===========================================================================
# 3. Explainable Verification Report Service
# ===========================================================================

def build_explainable_report(
    session: Optional[VerificationSession] = None,
    fusion: Optional[EvidenceFusionResult] = None,
    analyses: Optional[List[VisualAnalysis]] = None,
    db: Optional[Session] = None,
    merchant_id: Optional[str] = None,
    verification_identifier: Optional[str] = None,
) -> ExplainableVerificationReportResponse:
    """Formulate the comprehensive, explainable verification report from actual evidence."""
    if session is None:
        if db is None or merchant_id is None or verification_identifier is None:
            raise ValueError("Must provide either session or (db, merchant_id, verification_identifier)")
        return get_verification_report(db=db, merchant_id=merchant_id, verification_identifier=verification_identifier)

    assessment_state = fusion.assessment_state if fusion else "REVIEW_REQUIRED"
    overall_confidence = round(fusion.overall_confidence, 2) if (fusion and fusion.overall_confidence is not None) else 0.0
    conf_value = round(fusion.overall_confidence, 2) if (fusion and fusion.overall_confidence is not None) else None

    # A. Assessment Section
    assessment = ReportAssessmentSection(
        state=assessment_state,
        overall_confidence=overall_confidence,
        confidence=conf_value,
        rule_evaluation_summary=(
            f"Deterministic fusion evaluated assessment as {assessment_state} with confidence {overall_confidence}."
            if fusion
            else "Assessment pending completion of evidence processing and fusion evaluation."
        ),
        assessed_at=fusion.completed_at if fusion else None,
        fusion_id=fusion.id if fusion else None,
        input_context_hash=fusion.input_context_hash if fusion else None,
        reasoning=(
            (fusion.explanation_json.get("summary") or fusion.explanation_json.get("claim_assessment"))
            if (fusion and fusion.explanation_json and isinstance(fusion.explanation_json, dict))
            else f"State {assessment_state} derived from deterministic fusion."
        ),
    )

    # B. Claim Section
    claim = ReportClaimSection(
        refund_reason=session.refund_reason,
        refund_amount=float(session.refund_amount) if session.refund_amount is not None else None,
        claimed_item_condition=session.claimed_item_condition,
        order_id=session.order_id,
        customer_name=session.customer_name,
        customer_contact=session.customer_contact,
    )

    # C. Evidence Summary Section
    evidence_items = list(session.evidence_items or [])
    total_items = len(evidence_items)
    images_count = sum(1 for e in evidence_items if e.evidence_type == EvidenceType.CUSTOMER_IMAGE.value)
    videos_count = sum(1 for e in evidence_items if e.evidence_type == EvidenceType.CUSTOMER_VIDEO.value)
    text_count = sum(1 for e in evidence_items if e.evidence_type == EvidenceType.CUSTOMER_TEXT.value)
    adaptive_count = len(session.evidence_requests or [])
    analyzed_count = sum(1 for a in (analyses or []) if a.status == VisualAnalysisStatus.COMPLETED.value)
    failed_analysis_count = sum(1 for a in (analyses or []) if a.status == VisualAnalysisStatus.FAILED.value)
    res_json = fusion.result_json or {} if fusion else {}
    missing_count = len(res_json.get("missing_evidence", []))

    evidence_summary = ReportEvidenceSummarySection(
        total_items=total_items,
        total_evidence_count=total_items,
        images_count=images_count,
        videos_count=videos_count,
        text_count=text_count,
        adaptive_count=adaptive_count,
        analyzed_count=analyzed_count,
        failed_analysis_count=failed_analysis_count,
        missing_evidence_count=missing_count,
    )

    # D. Visual Evidence Items
    visual_evidence_items: List[ReportVisualEvidenceItem] = []
    analyses_by_ev = {a.evidence_id: a for a in (analyses or [])}
    for ev in evidence_items:
        if ev.evidence_type == EvidenceType.CUSTOMER_IMAGE.value:
            va = analyses_by_ev.get(ev.id)
            if va:
                res_json = va.result_json or {}
                visual_evidence_items.append(
                    ReportVisualEvidenceItem(
                        evidence_id=ev.evidence_id,
                        status=va.status,
                        model_name=va.model_name,
                        confidence=va.overall_confidence,
                        product_consistency=res_json.get("product_consistency"),
                        visible_condition=res_json.get("visible_condition"),
                        key_visual_observations=res_json.get("key_visual_observations") or [],
                        uncertainties=res_json.get("uncertainties") or [],
                    )
                )
            else:
                visual_evidence_items.append(
                    ReportVisualEvidenceItem(
                        evidence_id=ev.evidence_id,
                        status="PENDING",
                        model_name=None,
                        confidence=None,
                        product_consistency=None,
                        visible_condition=None,
                        key_visual_observations=[],
                        uncertainties=["Analysis pending or not yet initiated"],
                    )
                )

    # E. Trusted Reference Comparison
    ref_count = len(session.product.references) if session.product and session.product.references else 0
    ref_comparison: Dict[str, Any] = {
        "reference_angles_available": ref_count,
        "is_complete": ref_count == 4,
    }
    if visual_evidence_items and visual_evidence_items[0].product_consistency:
        ref_comparison["latest_consistency"] = visual_evidence_items[0].product_consistency

    # F. Deterministic Signals
    signal_items: List[ReportSignalItem] = []
    for sig in session.signals or []:
        if sig.status == SignalStatus.VALID.value:
            signal_items.append(
                ReportSignalItem(
                    id=sig.id,
                    signal_type=sig.signal_type,
                    source_type=sig.source_type,
                    source_reference=sig.source_reference,
                    status=sig.status,
                    confidence=sig.confidence,
                    observed_at=sig.observed_at,
                    data=sig.data_json or {},
                )
            )

    # G. Fusion Dimensions, Missing Evidence, Contradictions
    dimensions: List[FusionDimensionResult] = []
    missing_items: List[MissingEvidenceItem] = []
    contradiction_items: List[ContradictionItem] = []
    if fusion and fusion.result_json:
        fusion_data = fusion.result_json or {}
        for d in fusion_data.get("dimensions", []):
            dimensions.append(FusionDimensionResult.model_validate(d))
        for m in fusion_data.get("missing_evidence", []):
            missing_items.append(MissingEvidenceItem.model_validate(m))
        for c in fusion_data.get("contradictions", []):
            contradiction_items.append(ContradictionItem.model_validate(c))

    # H. AI Explanation
    if fusion and fusion.explanation_json:
        ai_explanation = ReportAiExplanationSection(
            source="LOCAL_LLAMA_EXPLANATION",
            model="llama3.2:1b",
            prompt_version=settings.LLAMA_FUSION_PROMPT_VERSION,
            status="COMPLETED",
            explanation=fusion.explanation_json,
        )
    else:
        ai_explanation = ReportAiExplanationSection(
            source="LOCAL_LLAMA_EXPLANATION",
            model="llama3.2:1b",
            prompt_version=settings.LLAMA_FUSION_PROMPT_VERSION,
            status="UNAVAILABLE",
            explanation=None,
        )

    # I. Merchant Decision
    latest_decision: Optional[MerchantDecisionResponse] = None
    if session.merchant_decisions:
        latest_decision = MerchantDecisionResponse.model_validate(session.merchant_decisions[0])

    # Construct the 9 Formal Sections
    plain_summary = (
        fusion.explanation_json.get("summary")
        if (fusion and fusion.explanation_json and isinstance(fusion.explanation_json, dict) and fusion.explanation_json.get("summary"))
        else f"Automated verification assessment for session {session.verification_id} based on collected evidence and signals."
    )
    review_rec = (assessment_state != "EVIDENCE_CONSISTENT")

    section_executive_summary = {
        "text": plain_summary,
        "overall_confidence": overall_confidence,
        "assessment_state": assessment_state,
        "review_recommended": review_rec,
    }

    section_consistency_assessment = {
        "state": assessment_state,
        "confidence": overall_confidence,
        "reasoning": (
            (fusion.explanation_json.get("summary") or fusion.explanation_json.get("claim_assessment"))
            if (fusion and fusion.explanation_json and isinstance(fusion.explanation_json, dict))
            else f"Assessment state {assessment_state} derived from deterministic fusion."
        ),
    }

    section_visual_consistency = {
        "total_images": len(visual_evidence_items),
        "items": [v.model_dump() for v in visual_evidence_items],
        "trusted_reference_angles_available": ref_count,
        "references_complete": (ref_count == 4),
    }

    payment_sig = next((s for s in (session.signals or []) if s.signal_type == "PAYMENT"), None)
    order_sig = next((s for s in (session.signals or []) if s.signal_type == "ORDER"), None)
    delivery_sig = next((s for s in (session.signals or []) if s.signal_type == "DELIVERY"), None)
    location_sig = next((s for s in (session.signals or []) if s.signal_type == "LOCATION"), None)

    section_signal_verification = {
        "payment_signal_status": "MATCHED" if payment_sig and payment_sig.status == "VALID" else ("NO_SIGNAL" if not payment_sig else "UNMATCHED"),
        "order_signal_status": "MATCHED" if order_sig and order_sig.status == "VALID" else ("NO_SIGNAL" if not order_sig else "UNMATCHED"),
        "delivery_signal_status": "MATCHED" if delivery_sig and delivery_sig.status == "VALID" else ("NO_SIGNAL" if not delivery_sig else "UNMATCHED"),
        "location_signal_status": "MATCHED" if location_sig and location_sig.status == "VALID" else ("NO_SIGNAL" if not location_sig else "UNMATCHED"),
        "signals": [s.model_dump() for s in signal_items],
    }

    section_fusion_matrix = {
        "dimensions": [d.model_dump() for d in dimensions],
        "contradictions": [c.model_dump() for c in contradiction_items],
    }

    section_claim_reconciliation = {
        "customer_claimed": {
            "refund_reason": session.refund_reason,
            "claimed_condition": session.claimed_item_condition,
            "refund_amount": float(session.refund_amount) if session.refund_amount is not None else None,
        },
        "evidence_shows": {
            "visual_summary": "Visual analysis indicates consistent observations." if visual_evidence_items else "No visual analysis available.",
            "signal_summary": f"{len(signal_items)} verified signals processed.",
        },
        "alignment": (
            "ALIGNED" if assessment_state == "EVIDENCE_CONSISTENT"
            else ("CONTRADICTORY" if assessment_state == "INCONSISTENCY_DETECTED" else "PARTIALLY_ALIGNED")
        ),
    }

    section_missing_evidence = {
        "missing_evidence": [m.model_dump() for m in missing_items],
        "total_missing": len(missing_items),
        "adaptive_requests": [
            {
                "request_id": r.id,
                "step_key": getattr(r, "workflow_step_key", getattr(r, "step_key", "")),
                "workflow_step_key": getattr(r, "workflow_step_key", getattr(r, "step_key", "")),
                "status": r.status,
                "reason": r.reason,
            }
            for r in (session.evidence_requests or [])
        ],
    }

    section_decision_context = {
        "previous_decisions": [
            {
                "decision_id": d.id,
                "decision": d.decision,
                "decision_reason": d.decision_reason or d.notes,
                "decided_at": d.decided_at.isoformat() if d.decided_at else None,
            }
            for d in (session.merchant_decisions or [])
        ],
        "latest_decision": latest_decision.model_dump() if latest_decision else None,
        "policy_recommendations": [
            "Merchant is the sole authoritative decision-maker.",
            "Review evidence consistency before approving or rejecting refund.",
        ],
        "available_actions": ["REFUND_APPROVED", "REFUND_REJECTED", "MANUAL_REVIEW"],
    }

    section_ai_audit_trail = {
        "gemini_vision_model": "gemini-2.5-flash",
        "llama_model": "llama3.2:1b",
        "fusion_engine_version": fusion.fusion_version if fusion else settings.FUSION_VERSION,
        "prompt_version": settings.LLAMA_FUSION_PROMPT_VERSION,
        "rules_evaluated": [d.dimension for d in dimensions] if dimensions else [],
    }

    # Full Investigation Trail & Recommendation
    if fusion and fusion.overall_confidence is not None:
        raw_confidence = fusion.overall_confidence
        rec_code, rec_label = map_confidence_to_recommendation(raw_confidence)
    else:
        raw_confidence = None
        rec_code, rec_label = "REVIEW_REQUIRED", "REVIEW REQUIRED"

    # Questions asked and customer answers
    questions_asked: List[Dict[str, Any]] = []
    snapshot = session.workflow_snapshot_json or {}
    snapshot_steps = snapshot.get("steps", [])
    ev_by_step: Dict[str, List[Any]] = {}
    for ev in evidence_items:
        if ev.workflow_step_key:
            ev_by_step.setdefault(ev.workflow_step_key, []).append(ev)

    if session.refund_reason:
        questions_asked.append({
            "step_key": "refund_claim",
            "title": "Refund Reason / Initial Claim",
            "step_type": "CUSTOMER_CLAIM",
            "required": True,
            "submitted": True,
            "answer": session.refund_reason,
            "condition": session.claimed_item_condition,
        })

    for step in snapshot_steps:
        s_key = step.get("step_key") or step.get("id") or "step"
        s_title = step.get("name") or step.get("title") or s_key
        s_type = step.get("step_type") or step.get("type") or "TEXT"
        s_req = step.get("required", True)
        matching_ev = ev_by_step.get(s_key, [])
        answers = []
        for me in matching_ev:
            if me.text_content:
                answers.append(me.text_content)
            elif me.original_filename:
                answers.append(f"Uploaded file: {me.original_filename}")
            else:
                answers.append(f"Evidence {me.evidence_id}")
        questions_asked.append({
            "step_key": s_key,
            "title": s_title,
            "step_type": s_type,
            "description": step.get("description"),
            "required": s_req,
            "submitted": len(matching_ev) > 0,
            "answer": "; ".join(answers) if answers else (None if s_req else "Optional (skipped)"),
            "evidence_count": len(matching_ev),
        })

    # Adaptive follow-up questions
    adaptive_follow_ups: List[Dict[str, Any]] = []
    for req in (session.evidence_requests or []):
        r_step = getattr(req, "workflow_step_key", getattr(req, "step_key", None))
        matching_ev = ev_by_step.get(r_step, []) if r_step else []
        ans_items = []
        for me in matching_ev:
            if me.text_content:
                ans_items.append(me.text_content)
            elif me.original_filename:
                ans_items.append(f"Uploaded file: {me.original_filename}")
        prompt_val = getattr(req, "prompt", None)
        if not prompt_val and isinstance(getattr(req, "options_json", None), dict):
            prompt_val = req.options_json.get("prompt")
        prompt_val = prompt_val or getattr(req, "reason", "Follow-up request")

        adaptive_follow_ups.append({
            "request_id": req.id,
            "prompt": prompt_val,
            "reason": getattr(req, "reason", ""),
            "status": req.status,
            "workflow_step_key": r_step,
            "customer_response": "; ".join(ans_items) if ans_items else ("Fulfilled" if req.status == "FULFILLED" else "Awaiting customer response"),
        })

    # Categorized visual findings (Observed, Not observed, Unclear)
    observed_findings: List[str] = []
    not_observed_findings: List[str] = []
    unclear_findings: List[str] = []

    for va in (analyses or []):
        res = va.result_json or {}
        for obs in res.get("key_visual_observations", []):
            if obs and obs not in observed_findings:
                observed_findings.append(obs)
        for unc in res.get("uncertainties", []):
            if unc and unc not in unclear_findings:
                unclear_findings.append(unc)
        vis_cond = res.get("visible_condition") or {}
        cd = vis_cond.get("claimed_damage_visible")
        if cd == "observed":
            dt = vis_cond.get("damage_type_detected") or "Damage"
            loc = vis_cond.get("damage_location") or "Product"
            sev = vis_cond.get("damage_severity_observation") or "Identified"
            f_str = f"Claimed damage observed: {dt} at {loc} ({sev})"
            if f_str not in observed_findings:
                observed_findings.append(f_str)
        elif cd in ("not_observed", "not_visible"):
            f_str = "Claimed damage not visible on examined product surface"
            if f_str not in not_observed_findings:
                not_observed_findings.append(f_str)
        elif cd == "unclear":
            f_str = "Claimed damage unclear or obscured"
            if f_str not in unclear_findings:
                unclear_findings.append(f_str)

        prod_cons = res.get("product_consistency") or {}
        st = prod_cons.get("is_same_product_type")
        if st == "observed":
            ang = prod_cons.get("matched_reference_angle") or "reference"
            f_str = f"Product type matches reference item (matched angle: {ang})"
            if f_str not in observed_findings:
                observed_findings.append(f_str)
        elif st == "not_observed":
            f_str = "Product does not match reference item specifications"
            if f_str not in not_observed_findings:
                not_observed_findings.append(f_str)
        elif st == "unclear":
            f_str = "Product reference match unclear"
            if f_str not in unclear_findings:
                unclear_findings.append(f_str)

    if not visual_evidence_items:
        unclear_findings.append("No visual evidence uploaded for inspection")

    visual_findings_categorized = {
        "observed": observed_findings,
        "not_observed": not_observed_findings,
        "unclear": unclear_findings,
    }

    # Deterministic signal statuses
    signal_status_map = {
        "PAYMENT": "Unavailable",
        "ORDER": "Unavailable",
        "DELIVERY": "Unavailable",
        "LOCATION": "Unavailable",
    }
    for sig in (session.signals or []):
        st = sig.status.upper() if sig.status else "UNAVAILABLE"
        human_st = "Verified" if st == "VALID" else ("Mismatch" if st in ("INVALID", "SUSPICIOUS") else "Unavailable")
        signal_status_map[sig.signal_type] = human_st

    return ExplainableVerificationReportResponse(
        verification_id=session.verification_id,
        assessment_state=assessment_state,
        overall_confidence=overall_confidence,
        executive_summary=section_executive_summary,
        consistency_assessment=section_consistency_assessment,
        visual_consistency_findings=section_visual_consistency,
        signal_verification_findings=section_signal_verification,
        multi_source_fusion_matrix=section_fusion_matrix,
        claim_vs_evidence_reconciliation=section_claim_reconciliation,
        missing_evidence_and_follow_up=section_missing_evidence,
        merchant_decision_context=section_decision_context,
        ai_audit_trail=section_ai_audit_trail,
        assessment=assessment,
        claim=claim,
        evidence_summary=evidence_summary,
        visual_evidence=visual_evidence_items,
        trusted_reference_comparison=ref_comparison,
        deterministic_signals=signal_items,
        fusion_dimensions=dimensions,
        missing_evidence=missing_items,
        contradictions=contradiction_items,
        ai_explanation=ai_explanation,
        merchant_decision=latest_decision,
        questions_asked=questions_asked,
        adaptive_follow_up_questions=adaptive_follow_ups,
        visual_findings_categorized=visual_findings_categorized,
        deterministic_signal_statuses=signal_status_map,
        recommendation_code=rec_code,
        recommendation_label=rec_label,
    )


def get_verification_report(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> ExplainableVerificationReportResponse:
    """Generate or retrieve explainable final verification report with 9 structured sections."""
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

    latest_fusion = (
        db.execute(
            select(EvidenceFusionResult)
            .where(EvidenceFusionResult.verification_session_id == session.id)
            .order_by(EvidenceFusionResult.created_at.desc())
        )
        .scalars()
        .first()
    )

    if not latest_fusion and session.status == SessionStatus.COMPLETED.value:
        try:
            from app.services import evidence_fusion_service
            latest_fusion = evidence_fusion_service.run_session_fusion(
                db=db,
                merchant_id=merchant_id,
                verification_identifier=session.id,
            )
        except Exception as exc:
            logger.warning("On-demand report fusion failed gracefully: %s", exc)

    evidence_items = list(session.evidence_items or [])
    analyses = []
    if evidence_items:
        analyses = list(
            db.execute(
                select(VisualAnalysis).where(
                    VisualAnalysis.evidence_id.in_([e.id for e in evidence_items])
                )
            ).scalars().all()
        )

    return build_explainable_report(session=session, fusion=latest_fusion, analyses=analyses)


# ===========================================================================
# 4. Detail / Investigation View Service
# ===========================================================================

def get_verification_investigation_detail(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> VerificationDetailDashboardResponse:
    """Retrieve full unified investigation view for a single verification session."""
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

    evidence_items = list(session.evidence_items or [])
    analyses = (
        db.execute(
            select(VisualAnalysis).where(
                VisualAnalysis.evidence_id.in_([e.id for e in evidence_items])
            )
        )
        .scalars()
        .all()
        if evidence_items
        else []
    )

    # Latest fusion
    latest_fusion = session.fusion_results[0] if session.fusion_results else None
    if not latest_fusion and session.status == SessionStatus.COMPLETED.value:
        try:
            from app.services import evidence_fusion_service
            latest_fusion = evidence_fusion_service.run_session_fusion(
                db=db,
                merchant_id=merchant_id,
                verification_identifier=session.id,
            )
        except Exception as exc:
            logger.warning("On-demand investigation fusion failed gracefully: %s", exc)

    fusion_resp: Optional[FusionResponse] = None
    if latest_fusion:
        res_json = latest_fusion.result_json or {}
        exp_obj = None
        if latest_fusion.explanation_json:
            try:
                exp_obj = FusionExplanation.model_validate(latest_fusion.explanation_json)
            except Exception:
                exp_obj = None
        fusion_resp = FusionResponse(
            id=latest_fusion.id,
            verification_session_id=latest_fusion.verification_session_id,
            assessment_state=latest_fusion.assessment_state,
            overall_confidence=latest_fusion.overall_confidence,
            dimensions=res_json.get("dimensions", []),
            contradictions=res_json.get("contradictions", []),
            missing_evidence=res_json.get("missing_evidence", []),
            explanation=exp_obj,
            fusion_version=latest_fusion.fusion_version,
            input_context_hash=latest_fusion.input_context_hash,
            created_at=latest_fusion.created_at,
            completed_at=latest_fusion.completed_at,
        )

    # Latest reasoning run
    latest_reasoning = session.reasoning_runs[0] if session.reasoning_runs else None
    reasoning_resp = ReasoningRunResponse.model_validate(latest_reasoning) if latest_reasoning else None

    # Timeline
    timeline = build_verification_timeline(session=session, analyses=analyses)

    # Report
    report = build_explainable_report(session=session, fusion=latest_fusion, analyses=analyses)

    # Sanitized verification dict (never expose customer_token_hash or customer_link)
    verification_dict = {
        "id": session.id,
        "verification_id": session.verification_id,
        "status": session.status,
        "order_id": session.order_id,
        "customer_id": session.customer_id,
        "customer_email": session.customer_email,
        "customer_link": None,
        "created_at": session.created_at,
        "started_at": session.started_at,
        "completed_at": session.completed_at,
        "expires_at": session.expires_at,
    }

    # Product dict
    product_dict = {
        "id": session.product.id if session.product else None,
        "name": session.product.name if session.product else "Unknown Product",
        "sku": session.product.sku if session.product else None,
        "price": float(session.product.price) if session.product and session.product.price else None,
        "reference_count": len(session.product.references) if session.product and session.product.references else 0,
    }

    # Claim dict
    claim_dict = {
        "refund_reason": session.refund_reason,
        "refund_amount": float(session.refund_amount) if session.refund_amount is not None else None,
        "claimed_item_condition": session.claimed_item_condition,
        "customer_name": session.customer_name,
        "customer_contact": session.customer_contact,
    }

    # Workflow snapshot dict
    workflow_dict = {
        "id": session.workflow_id,
        "version": session.workflow_version,
        "snapshot": session.workflow_snapshot_json,
    }

    # Evidence responses
    evidence_resps = [EvidenceResponse.model_validate(e) for e in evidence_items]

    # Adaptive requests responses
    adaptive_resps = [EvidenceRequestResponse.model_validate(r) for r in session.evidence_requests or []]

    # Latest merchant decision and decision history
    latest_decision = (
        MerchantDecisionResponse.model_validate(session.merchant_decisions[0])
        if session.merchant_decisions
        else None
    )
    all_decisions = [
        MerchantDecisionResponse.model_validate(d)
        for d in sorted(session.merchant_decisions or [], key=lambda d: d.created_at)
    ]

    return VerificationDetailDashboardResponse(
        verification=verification_dict,
        product=product_dict,
        claim=claim_dict,
        workflow=workflow_dict,
        evidence_summary=report.evidence_summary or ReportEvidenceSummarySection(),
        evidence=evidence_resps,
        evidence_items=evidence_resps,
        visual_analysis_summary={
            "total_analyses": len(report.visual_evidence),
            "completed": sum(1 for v in report.visual_evidence if v.status == "COMPLETED"),
        },
        visual_analysis=report.visual_evidence,
        visual_analysis_items=report.visual_evidence,
        signals_summary={
            "total_signals": len(report.deterministic_signals),
        },
        signals=report.deterministic_signals,
        signal_items=report.deterministic_signals,
        adaptive_requests=adaptive_resps,
        fusion=fusion_resp,
        fusion_result=fusion_resp,
        reasoning=reasoning_resp,
        llama_reasoning=reasoning_resp,
        timeline=timeline,
        merchant_decision=latest_decision,
        decisions=all_decisions,
        report=report,
        questions_asked=report.questions_asked,
        adaptive_follow_up_questions=report.adaptive_follow_up_questions,
        visual_findings_categorized=report.visual_findings_categorized,
        deterministic_signal_statuses=report.deterministic_signal_statuses,
        recommendation_code=report.recommendation_code,
        recommendation_label=report.recommendation_label,
    )


# ===========================================================================
# 5. Merchant Final Decision Service
# ===========================================================================

def record_merchant_decision(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
    data: MerchantDecisionCreateRequest,
) -> MerchantDecisionResponse:
    """Record an authoritative human merchant decision on a verification session."""
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

    if session.status == SessionStatus.CANCELLED.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Cannot record decision on a cancelled verification session",
        )

    if session.status == SessionStatus.EXPIRED.value:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Cannot record decision on an expired verification session",
        )

    notes_val = data.notes or data.decision_reason
    rejection_reasons_list = data.rejection_reasons if data.rejection_reasons else None
    action_taken_str = str(data.action_taken.value) if hasattr(data.action_taken, "value") else (str(data.action_taken) if data.action_taken else None)

    decision_record = MerchantDecision(
        verification_session_id=session.id,
        merchant_id=merchant_id,
        decision=data.decision.value,
        decision_reason=notes_val,
        notes=notes_val,
        rejection_reasons_json=rejection_reasons_list,
        action_taken=action_taken_str,
        decided_at=utc_now(),
    )
    db.add(decision_record)
    db.flush()

    # Record immutable audit event
    audit_event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.MERCHANT_DECISION_MADE.value,
        metadata_json={
            "decision": data.decision.value,
            "reason": notes_val,
            "notes": notes_val,
            "rejection_reasons": rejection_reasons_list,
            "action_taken": action_taken_str,
            "decision_id": decision_record.id,
        },
    )
    db.add(audit_event)

    # If decision is approved or rejected, mark session status completed if not already
    if data.decision in (DecisionType.REFUND_APPROVED, DecisionType.REFUND_REJECTED):
        if session.status != SessionStatus.COMPLETED.value:
            session.status = SessionStatus.COMPLETED.value
            session.completed_at = utc_now()

    db.commit()
    db.refresh(decision_record)

    logger.info(
        "Merchant %s recorded decision %s for session %s (decision_id: %s)",
        merchant_id,
        data.decision.value,
        session.verification_id,
        decision_record.id,
    )
    return MerchantDecisionResponse.model_validate(decision_record)


def list_merchant_decisions(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> List[MerchantDecisionResponse]:
    """Retrieve complete chronological history of merchant decisions for auditability."""
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

    decisions = (
        db.execute(
            select(MerchantDecision)
            .where(MerchantDecision.verification_session_id == session.id)
            .order_by(MerchantDecision.created_at.asc())
        )
        .scalars()
        .all()
    )

    return [MerchantDecisionResponse.model_validate(d) for d in decisions]
