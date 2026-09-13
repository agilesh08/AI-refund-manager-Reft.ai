"""Evidence Fusion Service for Milestone 11.

Combines independent evidence sources (claim, trusted references, customer evidence,
Gemini visual observations, and deterministic signals: payment, order, delivery, location)
into an explainable verification assessment:
- EVIDENCE_CONSISTENT
- REVIEW_REQUIRED
- INCONSISTENCY_DETECTED

The assessment state and dimensions are 100% deterministic. Llama 3.2 is invoked solely
to generate human-readable explanations and cannot modify or override the result.
"""
import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from fastapi import HTTPException, status
from sqlalchemy import select, or_
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.evidence_fusion import (
    EvidenceFusionResult,
    VerificationAssessmentState,
    utc_now,
)
from app.models.evidence_request import EvidenceRequest
from app.models.product_reference import ProductReference
from app.models.verification import VerificationSession, SessionStatus
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.verification_signal import VerificationSignal, SignalStatus, SignalType
from app.models.visual_analysis import VisualAnalysis, VisualAnalysisStatus
from app.schemas.evidence_fusion import (
    ContradictionItem,
    ContradictionSeverity,
    CustomerFusionResponse,
    DimensionStatus,
    DimensionType,
    FusionDimensionResult,
    FusionExplanation,
    FusionResponse,
    FusionResultSchema,
    MissingEvidenceItem,
)
from app.ai.ollama_reasoning import ollama_reasoning_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Geospatial Utility Functions
# ---------------------------------------------------------------------------

def calculate_haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate the great-circle distance between two GPS coordinates in meters using Haversine formula."""
    r_earth = 6371000.0  # Mean radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return r_earth * c


# ---------------------------------------------------------------------------
# Context Hashing Utility
# ---------------------------------------------------------------------------

def calculate_fusion_context_hash(
    session: VerificationSession,
    evidence_items: List[Evidence],
    visual_analyses: List[VisualAnalysis],
    signals: List[VerificationSignal],
    evidence_requests: List[EvidenceRequest],
    references: List[ProductReference],
    fusion_version: str = "v1",
) -> str:
    """Calculate deterministic SHA-256 hash digest of all inputs feeding evidence fusion."""
    payload = {
        "session_id": session.id,
        "product_id": session.product_id,
        "workflow_id": session.workflow_id,
        "order_id": session.order_id,
        "refund_reason": session.refund_reason,
        "refund_amount": str(session.refund_amount) if session.refund_amount else None,
        "workflow_snapshot": session.workflow_snapshot_json,
        "evidence_items": [
            {
                "id": e.id,
                "evidence_type": e.evidence_type,
                "sha256": e.sha256_hash,
                "status": e.status,
            }
            for e in sorted(evidence_items, key=lambda x: x.id)
        ],
        "visual_analyses": [
            {
                "id": a.id,
                "evidence_id": a.evidence_id,
                "status": a.status,
                "confidence": a.overall_confidence,
                "result": a.result_json,
            }
            for a in sorted(visual_analyses, key=lambda x: x.id)
        ],
        "signals": [
            {
                "id": s.id,
                "signal_type": s.signal_type,
                "source_type": s.source_type,
                "source_reference": s.source_reference,
                "status": s.status,
                "data": s.data_json,
            }
            for s in sorted(signals, key=lambda x: x.id)
        ],
        "evidence_requests": [
            {
                "id": r.id,
                "step_key": r.workflow_step_key,
                "type": r.requested_evidence_type,
                "status": r.status,
            }
            for r in sorted(evidence_requests, key=lambda x: x.id)
        ],
        "references": [
            {
                "angle": ref.angle,
                "sha256": getattr(ref, "image_hash", getattr(ref, "sha256_hash", None)),
            }
            for ref in sorted(references, key=lambda x: x.angle)
        ],
        "fusion_version": fusion_version,
    }
    canonical_json = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Source Reliability Weights
# ---------------------------------------------------------------------------

def get_source_weight(source_type: Optional[str]) -> float:
    """Return configured reliability weight for a signal source."""
    if not source_type:
        return settings.SIGNAL_SOURCE_WEIGHT_CUSTOMER_PROVIDED
    weights = {
        "INTEGRATION": settings.SIGNAL_SOURCE_WEIGHT_INTEGRATION,
        "SYSTEM_GENERATED": settings.SIGNAL_SOURCE_WEIGHT_SYSTEM_GENERATED,
        "MERCHANT_PROVIDED": settings.SIGNAL_SOURCE_WEIGHT_MERCHANT_PROVIDED,
        "CUSTOMER_PROVIDED": settings.SIGNAL_SOURCE_WEIGHT_CUSTOMER_PROVIDED,
    }
    return weights.get(source_type.upper(), 0.75)


# ---------------------------------------------------------------------------
# Dimension Evaluators
# ---------------------------------------------------------------------------

def evaluate_claim_vs_visual(
    session: VerificationSession,
    evidence_items: List[Evidence],
    visual_analyses: List[VisualAnalysis],
) -> Tuple[FusionDimensionResult, List[ContradictionItem], List[MissingEvidenceItem]]:
    """Evaluate customer refund claim against completed visual observations."""
    image_evidences = [e for e in evidence_items if e.evidence_type == EvidenceType.CUSTOMER_IMAGE.value]
    if not image_evidences:
        snapshot = session.workflow_snapshot_json or {}
        steps = snapshot.get("steps", [])
        has_image_step = any(s.get("step_type") in ("IMAGE", "CAMERA") for s in steps)
        if has_image_step:
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_VISUAL,
                    status=DimensionStatus.INSUFFICIENT,
                    confidence=0.30,
                    evidence_ids=[],
                    details={"reason": "Required image evidence not yet submitted"},
                ),
                [],
                [MissingEvidenceItem(workflow_step_key="damage_photo", reason="Image evidence is required to verify condition")],
            )
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_VISUAL,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "Workflow does not require visual evidence"},
            ),
            [],
            [],
        )

    # Check for visual analyses (distinguish completed vs failed)
    completed_analyses = [a for a in visual_analyses if a.status == VisualAnalysisStatus.COMPLETED.value]
    failed_analyses = [a for a in visual_analyses if a.status == VisualAnalysisStatus.FAILED.value]

    if not completed_analyses:
        if failed_analyses:
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_VISUAL,
                    status=DimensionStatus.INSUFFICIENT,
                    confidence=0.25,
                    evidence_ids=[e.id for e in image_evidences],
                    details={
                        "reason": "Visual analysis failed for submitted image evidence",
                        "failed_count": len(failed_analyses),
                    },
                ),
                [],
                [MissingEvidenceItem(workflow_step_key=image_evidences[0].workflow_step_key or "image", reason="Visual analysis failed; clear replacement image required")],
            )
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_VISUAL,
                status=DimensionStatus.INSUFFICIENT,
                confidence=0.35,
                evidence_ids=[e.id for e in image_evidences],
                details={"reason": "Visual analysis pending or unavailable"},
            ),
            [],
            [MissingEvidenceItem(workflow_step_key=image_evidences[0].workflow_step_key or "image", reason="Visual analysis pending")],
        )

def is_wrong_product_claim(reason_str: Optional[str]) -> bool:
    """Helper to detect if customer refund reason indicates wrong product received."""
    r = str(reason_str or "").lower()
    return any(kw in r for kw in ("wrong", "different", "incorrect", "mismatch", "not what i ordered", "received wrong", "wrong_item", "wrong_product"))


def evaluate_claim_vs_visual(
    session: VerificationSession,
    evidence_items: List[Evidence],
    visual_analyses: List[VisualAnalysis],
) -> Tuple[FusionDimensionResult, List[ContradictionItem], List[MissingEvidenceItem]]:
    """Evaluate customer refund claim against completed visual observations in a claim-aware manner."""
    image_evidences = [e for e in evidence_items if e.evidence_type == EvidenceType.CUSTOMER_IMAGE.value]
    if not image_evidences:
        snapshot = session.workflow_snapshot_json or {}
        steps = snapshot.get("steps", [])
        has_image_step = any(s.get("step_type") in ("IMAGE", "CAMERA") for s in steps)
        if has_image_step:
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_VISUAL,
                    status=DimensionStatus.INSUFFICIENT,
                    confidence=0.30,
                    evidence_ids=[],
                    details={"reason": "Required image evidence not yet submitted"},
                ),
                [],
                [MissingEvidenceItem(workflow_step_key="damage_photo", reason="Image evidence is required to verify condition")],
            )
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_VISUAL,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "Workflow does not require visual evidence"},
            ),
            [],
            [],
        )

    # Check for visual analyses (distinguish completed vs failed)
    completed_analyses = [a for a in visual_analyses if a.status == VisualAnalysisStatus.COMPLETED.value]
    failed_analyses = [a for a in visual_analyses if a.status == VisualAnalysisStatus.FAILED.value]

    if not completed_analyses:
        if failed_analyses:
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_VISUAL,
                    status=DimensionStatus.INSUFFICIENT,
                    confidence=0.25,
                    evidence_ids=[e.id for e in image_evidences],
                    details={
                        "reason": "Visual analysis failed for submitted image evidence",
                        "failed_count": len(failed_analyses),
                    },
                ),
                [],
                [MissingEvidenceItem(workflow_step_key=image_evidences[0].workflow_step_key or "image", reason="Visual analysis failed; clear replacement image required")],
            )
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_VISUAL,
                status=DimensionStatus.INSUFFICIENT,
                confidence=0.35,
                evidence_ids=[e.id for e in image_evidences],
                details={"reason": "Visual analysis pending or unavailable"},
            ),
            [],
            [MissingEvidenceItem(workflow_step_key=image_evidences[0].workflow_step_key or "image", reason="Visual analysis pending")],
        )

    # Inspect the latest completed visual analysis
    latest_analysis = completed_analyses[-1]
    res_json = latest_analysis.result_json or {}
    vis_cond = res_json.get("visible_condition", {})
    consistency = res_json.get("product_consistency", {})
    identity = res_json.get("product_identity") or {}
    observations = res_json.get("key_visual_observations", [])
    uncertainties = res_json.get("uncertainties", [])
    overall_conf = latest_analysis.overall_confidence or 0.80

    ev_ids = [latest_analysis.evidence_id] if latest_analysis.evidence_id else []

    # Check product mismatch
    is_identical = consistency.get("is_identical_model")
    branding = consistency.get("branding_match")
    shape = consistency.get("structural_shape_match")
    is_same_type = consistency.get("is_same_product_type")
    matches_trusted = identity.get("matches_trusted_product")

    is_mismatch = (
        is_identical is False
        or branding is False
        or shape is False
        or is_same_type == "not_observed"
        or matches_trusted == "MISMATCH"
    )

    # CLAIM-AWARE EVALUATION BRANCH FOR "WRONG PRODUCT" CLAIMS
    if is_wrong_product_claim(session.refund_reason):
        if is_mismatch:
            # Customer claimed wrong product AND uploaded photo shows a different product -> SUPPORTS CLAIM
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_VISUAL,
                    status=DimensionStatus.CONSISTENT,
                    confidence=round(overall_conf, 2),
                    evidence_ids=ev_ids,
                    details={
                        "observations": observations,
                        "claim_alignment": "SUPPORTING_CLAIM",
                        "summary": "Customer evidence appears different from merchant reference product, supporting the wrong-product claim.",
                    },
                ),
                [],
                [],
            )
        elif is_identical is True or is_same_type == "observed" or matches_trusted == "MATCH":
            # Customer claimed wrong product, but uploaded identical matching item -> Discrepancy requiring review
            contra = ContradictionItem(
                dimension=DimensionType.CLAIM_VS_VISUAL.value,
                severity=ContradictionSeverity.MEDIUM,
                description="Customer claimed wrong product received, but uploaded evidence appears identical to merchant reference product.",
                source_a="CUSTOMER_STATED",
                source_b="AI_VISUAL_OBSERVATION",
                evidence_ids=ev_ids,
            )
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_VISUAL,
                    status=DimensionStatus.INSUFFICIENT,
                    confidence=round(min(overall_conf * 0.6, 0.50), 2),
                    evidence_ids=ev_ids,
                    details={"observations": observations, "claim_alignment": "CONTRADICTORY_TO_CLAIM"},
                ),
                [contra],
                [],
            )

    # EVALUATION BRANCH FOR DAMAGE CLAIMS & GENERAL CLAIMS
    damage_severity = str(vis_cond.get("damage_severity_observation", "")).upper()
    is_not_visible = damage_severity == "NOT_VISIBLE" or any("not_visible" in str(u).lower() for u in uncertainties)
    is_unclear = damage_severity == "UNCLEAR" or any("unclear" in str(u).lower() for u in uncertainties)

    def has_damage_keyword(text: str) -> bool:
        t = str(text).lower()
        if "undamaged" in t or "no damage" in t or "pristine" in t:
            return False
        return any(w in t for w in ("damage", "broken", "crack", "fracture", "break", "shattered", "defect", "scratched", "torn", "dent", "faulty"))

    if vis_cond.get("claimed_damage_visible") == "observed" or vis_cond.get("localized_damage") is True:
        damage_observed = True
    elif vis_cond.get("claimed_damage_visible") == "not_observed" or vis_cond.get("localized_damage") is False:
        damage_observed = False
    else:
        damage_observed = any(has_damage_keyword(o) for o in observations)


    if is_not_visible or is_unclear:
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_VISUAL,
                status=DimensionStatus.INSUFFICIENT,
                confidence=round(min(overall_conf * 0.5, 0.45), 2),
                evidence_ids=ev_ids,
                details={
                    "damage_severity_observation": damage_severity,
                    "uncertainties": uncertainties,
                },
            ),
            [],
            [
                MissingEvidenceItem(
                    workflow_step_key=image_evidences[0].workflow_step_key or "damage_photo",
                    reason="The damaged area is not sufficiently visible or is unclear in the available evidence",
                )
            ],
        )

    if damage_observed:
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_VISUAL,
                status=DimensionStatus.CONSISTENT,
                confidence=round(overall_conf, 2),
                evidence_ids=ev_ids,
                details={"observations": observations, "visible_condition": vis_cond},
            ),
            [],
            [],
        )

    # If high confidence that damage is NOT present despite customer claiming it
    if overall_conf >= 0.80:
        contra = ContradictionItem(
            dimension=DimensionType.CLAIM_VS_VISUAL.value,
            severity=ContradictionSeverity.HIGH,
            description="Visual observation indicates undamaged product condition contrasting with customer damage claim.",
            source_a="CUSTOMER_STATED",
            source_b="AI_VISUAL_OBSERVATION",
            evidence_ids=ev_ids,
        )
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_VISUAL,
                status=DimensionStatus.INCONSISTENT,
                confidence=round(overall_conf, 2),
                evidence_ids=ev_ids,
                details={"observations": observations},
            ),
            [contra],
            [],
        )

    return (
        FusionDimensionResult(
            dimension=DimensionType.CLAIM_VS_VISUAL,
            status=DimensionStatus.INSUFFICIENT,
            confidence=round(min(overall_conf * 0.5, 0.45), 2),
            evidence_ids=ev_ids,
            details={"observations": observations},
        ),
        [],
        [
            MissingEvidenceItem(
                workflow_step_key=image_evidences[0].workflow_step_key or "damage_photo",
                reason="Visual observations inconclusive",
            )
        ],
    )


def evaluate_visual_vs_trusted_reference(
    visual_analyses: List[VisualAnalysis],
    session: Optional[VerificationSession] = None,
) -> Tuple[FusionDimensionResult, List[ContradictionItem]]:
    """Compare customer product image against merchant baseline references with claim-aware logic."""
    completed = [a for a in visual_analyses if a.status == VisualAnalysisStatus.COMPLETED.value]
    failed = [a for a in visual_analyses if a.status == VisualAnalysisStatus.FAILED.value]
    if not completed:
        if failed:
            return (
                FusionDimensionResult(
                    dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE,
                    status=DimensionStatus.INSUFFICIENT,
                    confidence=0.25,
                    evidence_ids=[],
                    details={"reason": "Visual analysis failed; product reference comparison could not be completed"},
                ),
                [],
            )
        return (
            FusionDimensionResult(
                dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "No completed visual analysis available"},
            ),
            [],
        )

    analysis = completed[-1]
    res_json = analysis.result_json or {}
    consistency = res_json.get("product_consistency", {})
    identity = res_json.get("product_identity") or {}
    capture = res_json.get("capture_assessment") or res_json.get("evidence_capture_assessment") or {}

    is_identical = consistency.get("is_identical_model")
    branding = consistency.get("branding_match")
    color = consistency.get("color_match")
    shape = consistency.get("structural_shape_match")
    is_same_type = consistency.get("is_same_product_type")

    matches_trusted = identity.get("matches_trusted_product")
    capture_type = str(capture.get("type") or capture.get("capture_context") or "UNCLEAR").upper()

    ev_ids = [analysis.evidence_id] if analysis.evidence_id else []
    conf = analysis.overall_confidence or 0.85

    # Check for product mismatch
    is_mismatch = (
        is_identical is False
        or branding is False
        or shape is False
        or is_same_type == "not_observed"
        or matches_trusted == "MISMATCH"
    )

    # Check for capture quality concern (screen or screenshot or printout)
    has_capture_concern = capture_type in (
        "SCREEN_DISPLAY_APPEARANCE",
        "SCREENSHOT_APPEARANCE",
        "PRINTED_IMAGE_APPEARANCE",
        "SCREEN_DISPLAY",
        "SCREENSHOT",
    ) or capture.get("screen_artifact_detected") is True

    details_payload = {
        **consistency,
        "product_identity": identity,
        "capture_assessment": capture,
    }

    # CLAIM-AWARE MISMATCH HANDLING
    if is_mismatch:
        refund_reason = getattr(session, "refund_reason", None) if session else None
        if is_wrong_product_claim(refund_reason):
            # Product mismatch is expected and supports a "wrong product" claim.
            # Do NOT create a HIGH severity contradiction that triggers INCONSISTENCY_DETECTED / REJECT.
            # Return INSUFFICIENT / REVIEW_REQUIRED with a neutral medium/low note.
            desc = "Customer evidence appears different from the merchant reference product, which may be consistent with the reported wrong-product claim. Manual review is recommended."
            if has_capture_concern:
                desc += " (Evidence photo appears captured from a screen; physical photo recommended)."
            contra = ContradictionItem(
                dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE.value,
                severity=ContradictionSeverity.MEDIUM,
                description=desc,
                source_a="CUSTOMER_IMAGE",
                source_b="MERCHANT_REFERENCE",
                evidence_ids=ev_ids,
            )
            return (
                FusionDimensionResult(
                    dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE,
                    status=DimensionStatus.INSUFFICIENT,
                    confidence=round(min(conf * 0.70, 0.60), 2),
                    evidence_ids=ev_ids,
                    details={
                        **details_payload,
                        "claim_context_note": "Product mismatch supports wrong-product claim; requires manual review.",
                    },
                ),
                [contra],
            )
        else:
            # Standard product mismatch for non-wrong-product claim -> HIGH contradiction
            desc = "Product in evidence does not match trusted merchant product reference model."
            if has_capture_concern:
                desc += f" (Evidence appearance indicates {capture_type.replace('_', ' ').lower()} rather than direct physical photo)."
            contra = ContradictionItem(
                dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE.value,
                severity=ContradictionSeverity.HIGH,
                description=desc,
                source_a="CUSTOMER_IMAGE",
                source_b="MERCHANT_REFERENCE",
                evidence_ids=ev_ids,
            )
            return (
                FusionDimensionResult(
                    dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE,
                    status=DimensionStatus.INCONSISTENT,
                    confidence=round(conf, 2),
                    evidence_ids=ev_ids,
                    details=details_payload,
                ),
                [contra],
            )

    # If product appears to match but is captured from a screen or display:
    # Mark as INSUFFICIENT with quality concern so review is required
    if (is_identical is True or is_same_type == "observed" or matches_trusted == "MATCH") and has_capture_concern:
        return (
            FusionDimensionResult(
                dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE,
                status=DimensionStatus.INSUFFICIENT,
                confidence=round(min(conf * 0.70, 0.55), 2),
                evidence_ids=ev_ids,
                details=details_payload,
            ),
            [],
        )


    if is_identical is True or (branding is True and shape is True) or matches_trusted == "MATCH" or is_same_type == "observed":
        return (
            FusionDimensionResult(
                dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE,
                status=DimensionStatus.CONSISTENT,
                confidence=round(conf, 2),
                evidence_ids=ev_ids,
                details=details_payload,
            ),
            [],
        )

    return (
        FusionDimensionResult(
            dimension=DimensionType.VISUAL_VS_TRUSTED_REFERENCE,
            status=DimensionStatus.INSUFFICIENT,
            confidence=round(conf * 0.5, 2),
            evidence_ids=ev_ids,
            details=details_payload,
        ),
        [],
    )


def evaluate_claim_vs_payment(
    session: VerificationSession,
    signals: List[VerificationSignal],
) -> Tuple[FusionDimensionResult, List[ContradictionItem]]:
    """Evaluate payment signal consistency against the claim and merchant payment identity."""
    pay_signals = [s for s in signals if s.signal_type == SignalType.PAYMENT.value and s.status == SignalStatus.VALID.value]
    if not pay_signals:
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_PAYMENT,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "No valid payment signal ingested"},
            ),
            [],
        )

    pay_sig = pay_signals[-1]
    pay_data = pay_sig.data_json or {}
    pay_status = str(pay_data.get("payment_status", "")).upper()
    source_weight = get_source_weight(pay_sig.source_type)

    # Check merchant-configured expected payment account if configured in frozen workflow snapshot
    expected_payee = None
    snapshot = session.workflow_snapshot_json or {}
    for step in snapshot.get("steps", []):
        cfg = step.get("config") or step.get("config_json") or {}
        if cfg.get("expected_payment_account"):
            expected_payee = str(cfg.get("expected_payment_account")).strip()
            break
        elif cfg.get("upi_id"):
            expected_payee = str(cfg.get("upi_id")).strip()
            break

    cust_payee = str(pay_data.get("payee_account") or "").strip()

    if expected_payee:
        if not cust_payee:
            # Payment proof does not expose recipient identity -> INSUFFICIENT / REVIEW_REQUIRED
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_PAYMENT,
                    status=DimensionStatus.INSUFFICIENT,
                    confidence=0.45,
                    evidence_ids=[pay_sig.id],
                    details={
                        "reason": "Payment recipient identity is not visible in customer payment proof",
                        "expected_recipient": expected_payee,
                    },
                ),
                [],
            )

        payee_matched = (
            expected_payee.lower() in cust_payee.lower()
            or cust_payee.lower() in expected_payee.lower()
        )
        if not payee_matched:
            # Clear mismatch -> INCONSISTENT with HIGH severity contradiction
            safe_cust_payee = cust_payee
            for phrase in ("scam", "scammer", "fraud", "fraudulent", "liar", "fake"):
                if phrase in safe_cust_payee.lower():
                    safe_cust_payee = re.sub(phrase, "[unverified]", safe_cust_payee, flags=re.IGNORECASE)

            contra = ContradictionItem(
                dimension=DimensionType.CLAIM_VS_PAYMENT.value,
                severity=ContradictionSeverity.HIGH,
                description=f"Payment recipient in customer proof ('{safe_cust_payee}') does not match merchant configured recipient. Expected {expected_payee}, found {safe_cust_payee}.",
                source_a="CUSTOMER_PROOF",
                source_b="MERCHANT_PAYMENT_CONFIG",
                evidence_ids=[pay_sig.id],
            )
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_PAYMENT,
                    status=DimensionStatus.INCONSISTENT,
                    confidence=0.92,
                    evidence_ids=[pay_sig.id],
                    details={
                        "claimed_payee": cust_payee,
                        "expected_payee": expected_payee,
                        "matched": False,
                    },
                ),
                [contra],
            )

    if pay_status in ("PAID", "COMPLETED", "SETTLED"):
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_PAYMENT,
                status=DimensionStatus.CONSISTENT,
                confidence=round(source_weight, 2),
                evidence_ids=[pay_sig.id],
                details={
                    "payment_status": pay_status,
                    "currency": pay_data.get("currency"),
                    "payee_account": cust_payee or None,
                    "expected_payee": expected_payee,
                },
            ),
            [],
        )

    if pay_status in ("FAILED", "DECLINED", "CANCELLED"):
        contra = ContradictionItem(
            dimension=DimensionType.CLAIM_VS_PAYMENT.value,
            severity=ContradictionSeverity.HIGH,
            description="Claim assumes a completed purchase, but payment status is recorded as FAILED.",
            source_a="CUSTOMER_CLAIM",
            source_b="PAYMENT_SIGNAL",
            evidence_ids=[pay_sig.id],
        )
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_PAYMENT,
                status=DimensionStatus.INCONSISTENT,
                confidence=round(source_weight, 2),
                evidence_ids=[pay_sig.id],
                details={"payment_status": pay_status},
            ),
            [contra],
        )

    return (
        FusionDimensionResult(
            dimension=DimensionType.CLAIM_VS_PAYMENT,
            status=DimensionStatus.INSUFFICIENT,
            confidence=0.45,
            evidence_ids=[pay_sig.id],
            details={"payment_status": pay_status},
        ),
        [],
    )


def evaluate_claim_vs_order(
    session: VerificationSession,
    signals: List[VerificationSignal],
) -> Tuple[FusionDimensionResult, List[ContradictionItem]]:
    """Evaluate claimed order details against deterministic order signal."""
    order_signals = [s for s in signals if s.signal_type == SignalType.ORDER.value and s.status == SignalStatus.VALID.value]
    if not order_signals:
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_ORDER,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "No valid order signal ingested"},
            ),
            [],
        )

    ord_sig = order_signals[-1]
    ord_data = ord_sig.data_json or {}
    order_status = str(ord_data.get("order_status", "")).upper()
    source_weight = get_source_weight(ord_sig.source_type)

    if order_status == "CANCELLED":
        contra = ContradictionItem(
            dimension=DimensionType.CLAIM_VS_ORDER.value,
            severity=ContradictionSeverity.HIGH,
            description="Refund claim exists for an order recorded as CANCELLED.",
            source_a="CUSTOMER_CLAIM",
            source_b="ORDER_SIGNAL",
            evidence_ids=[ord_sig.id],
        )
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_ORDER,
                status=DimensionStatus.INCONSISTENT,
                confidence=round(source_weight, 2),
                evidence_ids=[ord_sig.id],
                details={"order_status": order_status},
            ),
            [contra],
        )

    # Check SKU if present in signal
    sig_sku = ord_data.get("item_sku") or ord_data.get("sku")
    if sig_sku and session.product and session.product.sku:
        if sig_sku.strip().upper() != session.product.sku.strip().upper():
            contra = ContradictionItem(
                dimension=DimensionType.CLAIM_VS_ORDER.value,
                severity=ContradictionSeverity.HIGH,
                description=f"Claimed product SKU ({session.product.sku}) does not match order record SKU ({sig_sku}).",
                source_a="CUSTOMER_CLAIM",
                source_b="ORDER_SIGNAL",
                evidence_ids=[ord_sig.id],
            )
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_ORDER,
                    status=DimensionStatus.INCONSISTENT,
                    confidence=round(source_weight, 2),
                    evidence_ids=[ord_sig.id],
                    details={"claimed_sku": session.product.sku, "order_sku": sig_sku},
                ),
                [contra],
            )

    return (
        FusionDimensionResult(
            dimension=DimensionType.CLAIM_VS_ORDER,
            status=DimensionStatus.CONSISTENT,
            confidence=round(source_weight, 2),
            evidence_ids=[ord_sig.id],
            details={"order_status": order_status},
        ),
        [],
    )


def evaluate_order_vs_payment(
    signals: List[VerificationSignal],
) -> Tuple[FusionDimensionResult, List[ContradictionItem]]:
    """Verify consistency between order and payment signals."""
    pay_signals = [s for s in signals if s.signal_type == SignalType.PAYMENT.value and s.status == SignalStatus.VALID.value]
    ord_signals = [s for s in signals if s.signal_type == SignalType.ORDER.value and s.status == SignalStatus.VALID.value]

    if not pay_signals or not ord_signals:
        return (
            FusionDimensionResult(
                dimension=DimensionType.ORDER_VS_PAYMENT,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "Both order and payment signals required for cross-comparison"},
            ),
            [],
        )

    pay_sig = pay_signals[-1]
    ord_sig = ord_signals[-1]
    pay_data = pay_sig.data_json or {}
    ord_data = ord_sig.data_json or {}
    ev_ids = [pay_sig.id, ord_sig.id]

    # Compare order_id references
    pay_order_id = str(pay_data.get("order_id", "")).strip()
    ord_order_id = str(ord_data.get("order_id", "")).strip()
    if pay_order_id and ord_order_id and pay_order_id != ord_order_id:
        contra = ContradictionItem(
            dimension=DimensionType.ORDER_VS_PAYMENT.value,
            severity=ContradictionSeverity.HIGH,
            description=f"Payment order reference ({pay_order_id}) does not match order identifier ({ord_order_id}).",
            source_a="PAYMENT_SIGNAL",
            source_b="ORDER_SIGNAL",
            evidence_ids=ev_ids,
        )
        return (
            FusionDimensionResult(
                dimension=DimensionType.ORDER_VS_PAYMENT,
                status=DimensionStatus.INCONSISTENT,
                confidence=0.95,
                evidence_ids=ev_ids,
                details={"payment_order_id": pay_order_id, "order_id": ord_order_id},
            ),
            [contra],
        )

    # Compare amounts
    pay_amount = pay_data.get("amount")
    ord_amount = ord_data.get("order_amount")
    if pay_amount is not None and ord_amount is not None:
        diff = abs(float(pay_amount) - float(ord_amount))
        if diff > settings.PAYMENT_ORDER_AMOUNT_TOLERANCE:
            # Payment mismatch -> REVIEW_REQUIRED via MEDIUM severity contradiction
            contra = ContradictionItem(
                dimension=DimensionType.ORDER_VS_PAYMENT.value,
                severity=ContradictionSeverity.MEDIUM,
                description=f"Payment amount ({pay_amount}) differs from recorded order amount ({ord_amount}).",
                source_a="PAYMENT_SIGNAL",
                source_b="ORDER_SIGNAL",
                evidence_ids=ev_ids,
            )
            return (
                FusionDimensionResult(
                    dimension=DimensionType.ORDER_VS_PAYMENT,
                    status=DimensionStatus.INCONSISTENT,
                    confidence=0.90,
                    evidence_ids=ev_ids,
                    details={"payment_amount": pay_amount, "order_amount": ord_amount, "diff": diff},
                ),
                [contra],
            )

    return (
        FusionDimensionResult(
            dimension=DimensionType.ORDER_VS_PAYMENT,
            status=DimensionStatus.CONSISTENT,
            confidence=0.95,
            evidence_ids=ev_ids,
            details={"payment_amount": pay_amount, "order_amount": ord_amount},
        ),
        [],
    )


def evaluate_order_vs_delivery(
    signals: List[VerificationSignal],
) -> Tuple[FusionDimensionResult, List[ContradictionItem]]:
    """Verify consistency between order and delivery signals."""
    ord_signals = [s for s in signals if s.signal_type == SignalType.ORDER.value and s.status == SignalStatus.VALID.value]
    del_signals = [s for s in signals if s.signal_type == SignalType.DELIVERY.value and s.status == SignalStatus.VALID.value]

    if not ord_signals or not del_signals:
        return (
            FusionDimensionResult(
                dimension=DimensionType.ORDER_VS_DELIVERY,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "Both order and delivery signals required"},
            ),
            [],
        )

    ord_sig = ord_signals[-1]
    del_sig = del_signals[-1]
    ord_data = ord_sig.data_json or {}
    del_data = del_sig.data_json or {}
    ev_ids = [ord_sig.id, del_sig.id]

    ord_order_id = str(ord_data.get("order_id", "")).strip()
    del_order_id = str(del_data.get("order_id", "")).strip()
    if ord_order_id and del_order_id and ord_order_id != del_order_id:
        contra = ContradictionItem(
            dimension=DimensionType.ORDER_VS_DELIVERY.value,
            severity=ContradictionSeverity.HIGH,
            description=f"Delivery order reference ({del_order_id}) does not match order record ({ord_order_id}).",
            source_a="DELIVERY_SIGNAL",
            source_b="ORDER_SIGNAL",
            evidence_ids=ev_ids,
        )
        return (
            FusionDimensionResult(
                dimension=DimensionType.ORDER_VS_DELIVERY,
                status=DimensionStatus.INCONSISTENT,
                confidence=0.95,
                evidence_ids=ev_ids,
                details={"delivery_order_id": del_order_id, "order_id": ord_order_id},
            ),
            [contra],
        )

    ord_status = str(ord_data.get("order_status", "")).upper()
    del_status = str(del_data.get("delivery_status", "")).upper()

    if ord_status == "CANCELLED" and del_status == "DELIVERED":
        contra = ContradictionItem(
            dimension=DimensionType.ORDER_VS_DELIVERY.value,
            severity=ContradictionSeverity.HIGH,
            description="Order record is CANCELLED but delivery status is recorded as DELIVERED.",
            source_a="ORDER_SIGNAL",
            source_b="DELIVERY_SIGNAL",
            evidence_ids=ev_ids,
        )
        return (
            FusionDimensionResult(
                dimension=DimensionType.ORDER_VS_DELIVERY,
                status=DimensionStatus.INCONSISTENT,
                confidence=0.95,
                evidence_ids=ev_ids,
                details={"order_status": ord_status, "delivery_status": del_status},
            ),
            [contra],
        )

    # Compatible statuses:
    # SHIPPED/CONFIRMED/PROCESSING + IN_TRANSIT/OUT_FOR_DELIVERY/DELIVERED
    # DELIVERED + DELIVERED
    return (
        FusionDimensionResult(
            dimension=DimensionType.ORDER_VS_DELIVERY,
            status=DimensionStatus.CONSISTENT,
            confidence=0.95,
            evidence_ids=ev_ids,
            details={"order_status": ord_status, "delivery_status": del_status},
        ),
        [],
    )


def evaluate_claim_vs_delivery(
    session: VerificationSession,
    signals: List[VerificationSignal],
) -> Tuple[FusionDimensionResult, List[ContradictionItem]]:
    """Compare customer claim context with deterministic courier delivery status."""
    del_signals = [s for s in signals if s.signal_type == SignalType.DELIVERY.value and s.status == SignalStatus.VALID.value]
    if not del_signals:
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_DELIVERY,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "No valid delivery signal ingested"},
            ),
            [],
        )

    del_sig = del_signals[-1]
    del_data = del_sig.data_json or {}
    del_status = str(del_data.get("delivery_status", "")).upper()
    source_weight = get_source_weight(del_sig.source_type)

    claim_text = (session.refund_reason or "").lower()
    non_delivery_phrases = [
        "not delivered",
        "never delivered",
        "never received",
        "package missing",
        "did not arrive",
        "never arrived",
        "missing package",
        "not arrived",
    ]
    is_non_delivery_claim = any(p in claim_text for p in non_delivery_phrases)

    if is_non_delivery_claim and del_status == "DELIVERED":
        contra = ContradictionItem(
            dimension=DimensionType.CLAIM_VS_DELIVERY.value,
            severity=ContradictionSeverity.HIGH,
            description="Customer-provided delivery statement conflicts with the available delivery record.",
            source_a="CUSTOMER_STATED",
            source_b="DELIVERY_SIGNAL",
            evidence_ids=[del_sig.id],
        )
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_DELIVERY,
                status=DimensionStatus.INCONSISTENT,
                confidence=round(source_weight, 2),
                evidence_ids=[del_sig.id],
                details={"claim_statement": session.refund_reason, "delivery_status": del_status},
            ),
            [contra],
        )

    # If customer states delivered package arrived damaged, DELIVERED is compatible
    if del_status == "DELIVERED":
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_DELIVERY,
                status=DimensionStatus.CONSISTENT,
                confidence=round(source_weight, 2),
                evidence_ids=[del_sig.id],
                details={"delivery_status": del_status, "carrier": del_data.get("carrier")},
            ),
            [],
        )

    if del_status in ("IN_TRANSIT", "OUT_FOR_DELIVERY"):
        # If customer claims arrived damaged but parcel is still in transit
        if any(w in claim_text for w in ("damaged", "broken", "cracked", "defective")):
            contra = ContradictionItem(
                dimension=DimensionType.CLAIM_VS_DELIVERY.value,
                severity=ContradictionSeverity.HIGH,
                description="Customer claims package arrived damaged, but tracking record indicates shipment is still IN_TRANSIT.",
                source_a="CUSTOMER_STATED",
                source_b="DELIVERY_SIGNAL",
                evidence_ids=[del_sig.id],
            )
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_DELIVERY,
                    status=DimensionStatus.INCONSISTENT,
                    confidence=round(source_weight, 2),
                    evidence_ids=[del_sig.id],
                    details={"delivery_status": del_status},
                ),
                [contra],
            )

    return (
        FusionDimensionResult(
            dimension=DimensionType.CLAIM_VS_DELIVERY,
            status=DimensionStatus.CONSISTENT,
            confidence=round(source_weight, 2),
            evidence_ids=[del_sig.id],
            details={"delivery_status": del_status},
        ),
        [],
    )


def evaluate_claim_vs_location(
    signals: List[VerificationSignal],
) -> Tuple[FusionDimensionResult, List[ContradictionItem], List[MissingEvidenceItem]]:
    """Compare device location coordinates with destination delivery location."""
    loc_signals = [s for s in signals if s.signal_type == SignalType.LOCATION.value and s.status == SignalStatus.VALID.value]
    del_signals = [s for s in signals if s.signal_type == SignalType.DELIVERY.value and s.status == SignalStatus.VALID.value]

    if not loc_signals:
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_LOCATION,
                status=DimensionStatus.NOT_APPLICABLE,
                confidence=0.0,
                evidence_ids=[],
                details={"reason": "No location signal ingested"},
            ),
            [],
            [],
        )

    loc_sig = loc_signals[-1]
    loc_data = loc_sig.data_json or {}
    dev_lat = loc_data.get("latitude")
    dev_lon = loc_data.get("longitude")
    accuracy = loc_data.get("accuracy_meters")

    # If accuracy missing or non-positive -> INSUFFICIENT
    if accuracy is None or accuracy <= 0.0:
        return (
            FusionDimensionResult(
                dimension=DimensionType.CLAIM_VS_LOCATION,
                status=DimensionStatus.INSUFFICIENT,
                confidence=0.0,
                evidence_ids=[loc_sig.id],
                details={"reason": "Location accuracy is unavailable or insufficient"},
            ),
            [],
            [MissingEvidenceItem(workflow_step_key="location", reason="Location signal lacks required accuracy metric")],
        )

    # Check if delivery signal has location coordinates
    del_lat = None
    del_lon = None
    del_ev_id = None
    if del_signals:
        del_sig = del_signals[-1]
        del_data = del_sig.data_json or {}
        del_loc = del_data.get("delivery_location") or {}
        if isinstance(del_loc, dict):
            del_lat = del_loc.get("latitude")
            del_lon = del_loc.get("longitude")
            del_ev_id = del_sig.id

    if dev_lat is not None and dev_lon is not None and del_lat is not None and del_lon is not None:
        dist_meters = calculate_haversine_distance(dev_lat, dev_lon, del_lat, del_lon)
        ev_ids = [loc_sig.id]
        if del_ev_id:
            ev_ids.append(del_ev_id)

        if dist_meters <= settings.LOCATION_MATCH_RADIUS_METERS:
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_LOCATION,
                    status=DimensionStatus.CONSISTENT,
                    confidence=0.85,
                    evidence_ids=ev_ids,
                    details={
                        "distance_meters": round(dist_meters, 1),
                        "radius_threshold_meters": settings.LOCATION_MATCH_RADIUS_METERS,
                        "within_range": True,
                    },
                ),
                [],
                [],
            )
        else:
            # Outside range: record INCONSISTENT with LOW severity (does not automatically accuse customer)
            contra = ContradictionItem(
                dimension=DimensionType.CLAIM_VS_LOCATION.value,
                severity=ContradictionSeverity.LOW,
                description=f"Device location was recorded outside expected delivery radius ({round(dist_meters, 1)}m > {settings.LOCATION_MATCH_RADIUS_METERS}m).",
                source_a="CUSTOMER_LOCATION",
                source_b="DELIVERY_DESTINATION",
                evidence_ids=ev_ids,
            )
            return (
                FusionDimensionResult(
                    dimension=DimensionType.CLAIM_VS_LOCATION,
                    status=DimensionStatus.INCONSISTENT,
                    confidence=0.80,
                    evidence_ids=ev_ids,
                    details={
                        "distance_meters": round(dist_meters, 1),
                        "radius_threshold_meters": settings.LOCATION_MATCH_RADIUS_METERS,
                        "within_range": False,
                    },
                ),
                [contra],
                [],
            )

    return (
        FusionDimensionResult(
            dimension=DimensionType.CLAIM_VS_LOCATION,
            status=DimensionStatus.NOT_APPLICABLE,
            confidence=0.0,
            evidence_ids=[loc_sig.id],
            details={"reason": "Delivery destination coordinates unavailable for comparison"},
        ),
        [],
        [],
    )


# ---------------------------------------------------------------------------
# Overall Confidence Calculation
# ---------------------------------------------------------------------------

def calculate_overall_confidence(
    dimensions: List[FusionDimensionResult],
    signals: List[VerificationSignal],
    contradictions: List[ContradictionItem],
    missing_items: Optional[List[MissingEvidenceItem]] = None,
    failed_analyses: Optional[List[Any]] = None,
) -> float:
    """Calculate transparent, deterministic assessment confidence score.

    Weighted by source reliability, visual confidence, and evidence completeness.
    Derives confidence from actual evidence quality, agreement, visual confidence,
    and merchant reference consistency.
    Failed analysis must NOT count as successful evidence.
    100% confidence is extremely rare; 50% is not a generic fallback.
    Meaningful contradictions significantly reduce confidence; unclear visual analysis reduces confidence.
    """
    applicable = [d for d in dimensions if d.status != DimensionStatus.NOT_APPLICABLE]
    if not applicable:
        return 0.30

    total_weighted_conf = 0.0
    total_weights = 0.0

    for d in applicable:
        dim_weight = 1.0
        if d.dimension in (DimensionType.CLAIM_VS_VISUAL, DimensionType.VISUAL_VS_TRUSTED_REFERENCE):
            dim_weight = 1.5
        elif d.dimension in (DimensionType.ORDER_VS_PAYMENT, DimensionType.CLAIM_VS_ORDER, DimensionType.CLAIM_VS_PAYMENT):
            dim_weight = 1.2
        elif d.dimension == DimensionType.CLAIM_VS_LOCATION:
            dim_weight = 0.8

        total_weighted_conf += d.confidence * dim_weight
        total_weights += dim_weight

    base_conf = total_weighted_conf / max(total_weights, 0.001)

    # Missing evidence deduction
    missing_count = len(missing_items or [])
    if missing_count > 0:
        base_conf -= min(0.08 * missing_count, 0.30)

    # Failed analysis deduction
    failed_count = len(failed_analyses or [])
    if failed_count > 0:
        base_conf -= min(0.12 * failed_count, 0.35)

    # Contradiction deductions: meaningful contradictions meaningfully reduce confidence
    high_contra = sum(1 for c in contradictions if getattr(c, "severity", None) == ContradictionSeverity.HIGH)
    med_contra = sum(1 for c in contradictions if getattr(c, "severity", None) == ContradictionSeverity.MEDIUM)
    low_contra = sum(1 for c in contradictions if getattr(c, "severity", None) == ContradictionSeverity.LOW)

    if high_contra > 0:
        base_conf -= (0.45 + min(0.15 * (high_contra - 1), 0.30))
    if med_contra > 0:
        base_conf -= min(0.18 * med_contra, 0.36)
    if low_contra > 0:
        base_conf -= min(0.06 * low_contra, 0.15)

    return round(min(max(base_conf, 0.10), 0.98), 4)


def map_confidence_to_recommendation(
    confidence: Optional[float],
    assessment_state: Optional[str] = None,
) -> Tuple[str, str]:
    """Map deterministic evidence fusion confidence to merchant recommendation code and human label.

    Boundary Rules:
    confidence < 0.35:
        Code: REJECT, Label: REJECT
    0.35 <= confidence < 0.50:
        Code: CAN_REJECT_REVIEW_REQUIRED, Label: CAN REJECT — REVIEW REQUIRED
    0.50 <= confidence < 0.75:
        Code: REVIEW_REQUIRED, Label: REVIEW REQUIRED
    0.75 <= confidence < 0.85:
        Code: MOSTLY_APPROVE, Label: MOSTLY APPROVE
    confidence >= 0.85:
        Code: APPROVED, Label: APPROVED

    Hard overrides:
    INCONSISTENCY_DETECTED → capped at REVIEW_REQUIRED or lower regardless of raw confidence.

    Returns:
        Tuple of (code, human_label)
    """
    if confidence is None:
        return "REVIEW_REQUIRED", "REVIEW REQUIRED"

    c = float(confidence)
    norm_state = (assessment_state or "").upper()

    # Hard override for inconsistency
    if norm_state == VerificationAssessmentState.INCONSISTENCY_DETECTED.value:
        if c < 0.35:
            return "REJECT", "REJECT"
        if c < 0.50:
            return "CAN_REJECT_REVIEW_REQUIRED", "CAN REJECT — REVIEW REQUIRED"
        return "REVIEW_REQUIRED", "REVIEW REQUIRED"

    if c < 0.35:
        return "REJECT", "REJECT"
    elif c < 0.50:
        return "CAN_REJECT_REVIEW_REQUIRED", "CAN REJECT — REVIEW REQUIRED"
    elif c < 0.75:
        return "REVIEW_REQUIRED", "REVIEW REQUIRED"
    elif c < 0.85:
        return "MOSTLY_APPROVE", "MOSTLY APPROVE"
    else:
        return "APPROVED", "APPROVED"



# ---------------------------------------------------------------------------
# Core Fusion Evaluation Engine
# ---------------------------------------------------------------------------

def perform_evidence_fusion(
    db: Session,
    session: VerificationSession,
    evidence_items: List[Evidence],
    visual_analyses: List[VisualAnalysis],
    signals: List[VerificationSignal],
    evidence_requests: List[EvidenceRequest],
    references: List[ProductReference],
) -> EvidenceFusionResult:
    """Execute deterministic multi-source evidence fusion.

    Calculates dimensions, contradictions, missing evidence, confidence, and final state.
    Dispatches Llama for human-readable explanation without altering the deterministic result.
    """
    context_hash = calculate_fusion_context_hash(
        session=session,
        evidence_items=evidence_items,
        visual_analyses=visual_analyses,
        signals=signals,
        evidence_requests=evidence_requests,
        references=references,
        fusion_version=settings.FUSION_VERSION,
    )

    # 1. Cache check
    existing = db.execute(
        select(EvidenceFusionResult).where(
            EvidenceFusionResult.verification_session_id == session.id,
            EvidenceFusionResult.input_context_hash == context_hash,
        )
    ).scalar_one_or_none()

    if existing:
        logger.info("Returning cached fusion result %s (hash: %s...)", existing.id, context_hash[:8])
        return existing

    # 2. Record audit start event
    start_event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.FUSION_STARTED.value,
        metadata_json={"fusion_version": settings.FUSION_VERSION, "context_hash": context_hash},
    )
    db.add(start_event)
    db.flush()

    # 3. Evaluate each dimension
    all_dimensions: List[FusionDimensionResult] = []
    all_contradictions: List[ContradictionItem] = []
    all_missing: List[MissingEvidenceItem] = []

    # D1: Claim vs Visual
    d1, c1, m1 = evaluate_claim_vs_visual(session, evidence_items, visual_analyses)
    all_dimensions.append(d1)
    all_contradictions.extend(c1)
    all_missing.extend(m1)

    # D2: Visual vs Reference
    d2, c2 = evaluate_visual_vs_trusted_reference(visual_analyses, session=session)
    all_dimensions.append(d2)
    all_contradictions.extend(c2)


    # D3: Claim vs Payment
    d3, c3 = evaluate_claim_vs_payment(session, signals)
    all_dimensions.append(d3)
    all_contradictions.extend(c3)

    # D4: Claim vs Order
    d4, c4 = evaluate_claim_vs_order(session, signals)
    all_dimensions.append(d4)
    all_contradictions.extend(c4)

    # D5: Order vs Payment
    d5, c5 = evaluate_order_vs_payment(signals)
    all_dimensions.append(d5)
    all_contradictions.extend(c5)

    # D6: Order vs Delivery
    d6, c6 = evaluate_order_vs_delivery(signals)
    all_dimensions.append(d6)
    all_contradictions.extend(c6)

    # D7: Claim vs Delivery
    d7, c7 = evaluate_claim_vs_delivery(session, signals)
    all_dimensions.append(d7)
    all_contradictions.extend(c7)

    # D8: Claim vs Location
    d8, c8, m8 = evaluate_claim_vs_location(signals)
    all_dimensions.append(d8)
    all_contradictions.extend(c8)
    all_missing.extend(m8)

    # Include any pending adaptive evidence requests from M9
    pending_m9 = [r for r in evidence_requests if r.status == "PENDING"]
    for req in pending_m9:
        if not any(m.workflow_step_key == req.workflow_step_key for m in all_missing):
            all_missing.append(
                MissingEvidenceItem(
                    workflow_step_key=req.workflow_step_key,
                    reason=f"Targeted evidence request pending: {req.reason or 'additional evidence requested'}",
                )
            )

    # 4. Calculate Final Assessment State via Priority Rules
    has_high_contradiction = any(c.severity == ContradictionSeverity.HIGH for c in all_contradictions)
    has_medium_contradiction = any(c.severity == ContradictionSeverity.MEDIUM for c in all_contradictions)
    has_insufficient_dim = any(d.status == DimensionStatus.INSUFFICIENT for d in all_dimensions)
    has_missing_evidence = len(all_missing) > 0

    if has_high_contradiction:
        assessment_state = VerificationAssessmentState.INCONSISTENCY_DETECTED
    elif has_missing_evidence or has_insufficient_dim or has_medium_contradiction:
        assessment_state = VerificationAssessmentState.REVIEW_REQUIRED
    elif any(d.status == DimensionStatus.INCONSISTENT for d in all_dimensions):
        # Low severity contradiction (e.g. location mismatch) -> REVIEW_REQUIRED
        assessment_state = VerificationAssessmentState.REVIEW_REQUIRED
    else:
        assessment_state = VerificationAssessmentState.EVIDENCE_CONSISTENT

    # 5. Calculate Confidence
    failed_va = [a for a in visual_analyses if getattr(a, "status", None) == VisualAnalysisStatus.FAILED.value]
    overall_confidence = calculate_overall_confidence(
        dimensions=all_dimensions,
        signals=signals,
        contradictions=all_contradictions,
        missing_items=all_missing,
        failed_analyses=failed_va,
    )

    # 6. Assemble Result Schema
    explanation_facts = [
        {"dimension": d.dimension.value, "status": d.status.value, "confidence": d.confidence}
        for d in all_dimensions
        if d.status != DimensionStatus.NOT_APPLICABLE
    ]

    result_schema = FusionResultSchema(
        assessment_state=assessment_state,
        overall_confidence=overall_confidence,
        dimensions=all_dimensions,
        contradictions=all_contradictions,
        missing_evidence=all_missing,
        explanation_facts=explanation_facts,
    )

    # 7. Persist EvidenceFusionResult Record
    fusion_record = EvidenceFusionResult(
        verification_session_id=session.id,
        assessment_state=assessment_state.value,
        overall_confidence=overall_confidence,
        fusion_version=settings.FUSION_VERSION,
        input_context_hash=context_hash,
        result_json=result_schema.model_dump(),
        explanation_json=None,
        created_at=utc_now(),
        completed_at=utc_now(),
    )
    db.add(fusion_record)
    db.flush()

    # 8. Dispatch to Llama 3.2 for Human-Readable Explanation (Fail-Safe)
    explanation_payload = {
        "assessment_state": assessment_state.value,
        "overall_confidence": overall_confidence,
        "contradictions": [c.model_dump() for c in all_contradictions],
        "missing_evidence": [m.model_dump() for m in all_missing],
        "dimensions": [d.model_dump() for d in all_dimensions if d.status != DimensionStatus.NOT_APPLICABLE],
    }

    try:
        explanation = ollama_reasoning_service.generate_fusion_explanation(explanation_payload)
        if explanation:
            fusion_record.explanation_json = explanation.model_dump()
            db.flush()
    except Exception as exc:
        logger.warning("Llama explanation generation failed (fusion record remains valid): %s", exc)

    # 9. Audit completion event
    comp_event = VerificationEvent(
        session_id=session.id,
        verification_id=session.verification_id,
        event_type=VerificationEventType.FUSION_COMPLETED.value,
        metadata_json={
            "fusion_id": fusion_record.id,
            "assessment_state": assessment_state.value,
            "overall_confidence": overall_confidence,
            "context_hash": context_hash,
        },
    )
    db.add(comp_event)
    db.commit()
    db.refresh(fusion_record)

    return fusion_record


# ---------------------------------------------------------------------------
# Public Service Functions
# ---------------------------------------------------------------------------

def run_session_fusion(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> EvidenceFusionResult:
    """Run evidence fusion for a merchant's verification session enforcing tenant isolation."""
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
            detail="Verification session has been cancelled",
        )

    evidence_items = list(session.evidence_items or [])
    analyses = db.execute(
        select(VisualAnalysis).where(
            VisualAnalysis.evidence_id.in_([e.id for e in evidence_items])
        )
    ).scalars().all() if evidence_items else []

    signals = list(session.signals or [])
    requests = list(session.evidence_requests or [])
    references = list(session.product.references or []) if session.product else []

    return perform_evidence_fusion(
        db=db,
        session=session,
        evidence_items=evidence_items,
        visual_analyses=analyses,
        signals=signals,
        evidence_requests=requests,
        references=references,
    )


def list_session_fusions(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> List[EvidenceFusionResult]:
    """Retrieve historical evidence fusion results for a merchant's verification session."""
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

    return db.execute(
        select(EvidenceFusionResult).where(
            EvidenceFusionResult.verification_session_id == session.id
        ).order_by(EvidenceFusionResult.created_at.desc())
    ).scalars().all()


def get_latest_session_fusion(
    db: Session,
    merchant_id: str,
    verification_identifier: str,
) -> EvidenceFusionResult:
    """Retrieve the latest evidence fusion result for a merchant's verification session."""
    fusions = list_session_fusions(db, merchant_id, verification_identifier)
    if not fusions:
        # If no fusion executed yet, run one dynamically
        return run_session_fusion(db, merchant_id, verification_identifier)
    return fusions[0]


def get_customer_fusion(
    db: Session,
    raw_token: str,
) -> CustomerFusionResponse:
    """Retrieve sanitized customer-safe verification assessment.

    Strips internal database keys, payment IDs, and private merchant facts.
    """
    token_hash = hashlib.sha256(raw_token.strip().encode("utf-8")).hexdigest()
    session = db.execute(
        select(VerificationSession).where(
            VerificationSession.customer_token_hash == token_hash
        )
    ).scalar_one_or_none()

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verification session not found",
        )

    # Retrieve latest fusion or compute if none exists
    fusions = db.execute(
        select(EvidenceFusionResult).where(
            EvidenceFusionResult.verification_session_id == session.id
        ).order_by(EvidenceFusionResult.created_at.desc())
    ).scalars().all()

    if not fusions:
        evidence_items = list(session.evidence_items or [])
        analyses = db.execute(
            select(VisualAnalysis).where(
                VisualAnalysis.evidence_id.in_([e.id for e in evidence_items])
            )
        ).scalars().all() if evidence_items else []
        signals = list(session.signals or [])
        requests = list(session.evidence_requests or [])
        references = list(session.product.references or []) if session.product else []

        fusion = perform_evidence_fusion(
            db=db,
            session=session,
            evidence_items=evidence_items,
            visual_analyses=analyses,
            signals=signals,
            evidence_requests=requests,
            references=references,
        )
    else:
        fusion = fusions[0]

    state = fusion.assessment_state
    res_json = fusion.result_json or {}
    missing_items = res_json.get("missing_evidence", [])
    missing_steps = [m.get("workflow_step_key") for m in missing_items if m.get("workflow_step_key")]

    if state == VerificationAssessmentState.EVIDENCE_CONSISTENT.value:
        status_display = "Evidence Consistent"
        customer_summary = "All currently submitted evidence is consistent with your claim."
    elif state == VerificationAssessmentState.INCONSISTENCY_DETECTED.value:
        status_display = "Under Merchant Review"
        customer_summary = "The available information contains a discrepancy that requires merchant review."
    else:
        status_display = "Additional Review Required"
        customer_summary = "Verification is currently under review because additional evidence may be needed."

    return CustomerFusionResponse(
        assessment_state=state,
        status_display=status_display,
        customer_summary=customer_summary,
        has_missing_evidence=len(missing_steps) > 0,
        missing_steps=missing_steps,
        completed_at=fusion.completed_at,
    )
