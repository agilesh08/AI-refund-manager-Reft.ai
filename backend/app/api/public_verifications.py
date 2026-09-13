from typing import List, Optional, Union
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile, status
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.evidence import EvidenceType
from app.schemas.evidence import EvidenceTextCreateRequest, EvidenceResponse
from app.schemas.evidence_request import (
    CustomerEvidenceRequestResponse,
    EvidenceRequestFulfillResponse,
)
from app.schemas.verification_signal import CustomerSignalResponse
from app.schemas.evidence_fusion import CustomerFusionResponse
from app.schemas.verification import (
    CustomerVerificationResponse,
    CustomerWorkflowResponse,
    VerificationStartResponse,
)
from app.services import (
    public_verification_service,
    evidence_service,
    evidence_request_service,
    adaptive_verification_service,
    verification_signal_service,
    evidence_fusion_service,
)
from app.utils.file_storage import get_evidence_file_path



router = APIRouter()


@router.get(
    "/{token}",
    response_model=CustomerVerificationResponse,
    status_code=status.HTTP_200_OK,
    summary="Public verification session landing view",
)
def get_public_verification_overview(
    token: str,
    db: Session = Depends(get_db),
) -> CustomerVerificationResponse:
    """Retrieve customer landing page information for a verification session.
    
    Returns sanitized merchant and product details.
    Returns HTTP 410 Gone if expired or cancelled.
    """
    return public_verification_service.get_customer_session_overview(
        db=db,
        raw_token=token,
    )


@router.post(
    "/{token}/start",
    response_model=VerificationStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Start customer verification workflow",
)
def start_public_verification(
    token: str,
    db: Session = Depends(get_db),
) -> VerificationStartResponse:
    """Transition verification session to IN_PROGRESS when customer begins verification.
    
    Idempotent if already started. Returns HTTP 410 Gone if expired or cancelled.
    """
    return public_verification_service.start_customer_session(
        db=db,
        raw_token=token,
    )


@router.get(
    "/{token}/workflow",
    response_model=CustomerWorkflowResponse,
    status_code=status.HTTP_200_OK,
    summary="Get customer workflow steps snapshot",
)
def get_public_workflow(
    token: str,
    db: Session = Depends(get_db),
) -> CustomerWorkflowResponse:
    """Retrieve the frozen workflow definition snapshot for this customer's session."""
    return public_verification_service.get_customer_workflow(
        db=db,
        raw_token=token,
    )


# ---------------------------------------------------------------------------
# Customer Evidence Endpoints (Milestone 6)
# ---------------------------------------------------------------------------

@router.post(
    "/{token}/evidence/image",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload customer image evidence",
)
async def upload_customer_image(
    token: str,
    file: UploadFile = File(..., description="Customer image file (JPEG, PNG, WEBP)"),
    workflow_step_key: Optional[str] = Form(None, description="Optional step key from frozen workflow"),
    db: Session = Depends(get_db),
) -> EvidenceResponse:
    """Upload customer damage or product photo evidence.
    
    Validates MIME type, Pillow decode integrity, size limit, and frozen workflow step compatibility.
    Calculates SHA-256 and detects exact duplicates without discarding submission records.
    """
    evidence = await evidence_service.create_customer_image_evidence(
        db=db,
        raw_token=token,
        file=file,
        workflow_step_key=workflow_step_key,
    )
    return EvidenceResponse.model_validate(evidence)


@router.post(
    "/{token}/evidence/video",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Upload customer video evidence",
)
async def upload_customer_video(
    token: str,
    file: UploadFile = File(..., description="Customer video file (MP4, MOV, WEBM)"),
    workflow_step_key: Optional[str] = Form(None, description="Optional step key from frozen workflow"),
    db: Session = Depends(get_db),
) -> EvidenceResponse:
    """Upload customer video evidence (MP4, MOV, WEBM up to configured size limit).
    
    Permitted only if the frozen workflow explicitly allows video evidence.
    """
    evidence = await evidence_service.create_customer_video_evidence(
        db=db,
        raw_token=token,
        file=file,
        workflow_step_key=workflow_step_key,
    )
    return EvidenceResponse.model_validate(evidence)


@router.post(
    "/{token}/evidence/text",
    response_model=EvidenceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Submit customer text evidence",
)
def submit_customer_text(
    token: str,
    data: EvidenceTextCreateRequest,
    db: Session = Depends(get_db),
) -> EvidenceResponse:
    """Submit customer explanation or text answers.
    
    Validated against frozen workflow step and stored in the database without filesystem writing.
    """
    evidence = evidence_service.create_customer_text_evidence(
        db=db,
        raw_token=token,
        data=data,
    )
    return EvidenceResponse.model_validate(evidence)


@router.get(
    "/{token}/evidence",
    response_model=List[EvidenceResponse],
    status_code=status.HTTP_200_OK,
    summary="List submitted evidence items for customer session",
)
def list_customer_evidence(
    token: str,
    workflow_step_key: Optional[str] = Query(None, description="Filter by workflow step key"),
    db: Session = Depends(get_db),
) -> List[EvidenceResponse]:
    """Retrieve all evidence items submitted by the customer for this session."""
    items = evidence_service.list_customer_evidence(
        db=db,
        raw_token=token,
        workflow_step_key=workflow_step_key,
    )
    return [EvidenceResponse.model_validate(item) for item in items]


@router.get(
    "/{token}/evidence/{evidence_id}",
    summary="Download or view customer evidence item",
)
def get_customer_evidence_file(
    token: str,
    evidence_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve or stream a specific evidence item.
    
    If image or video, securely streams file with content-type without exposing filesystem path.
    If text evidence, returns sanitized JSON.
    """
    evidence = evidence_service.get_customer_evidence_item(
        db=db,
        raw_token=token,
        evidence_identifier=evidence_id,
    )
    if evidence.evidence_type == EvidenceType.CUSTOMER_TEXT.value or not evidence.storage_path:
        return EvidenceResponse.model_validate(evidence)

    file_path = get_evidence_file_path(evidence.storage_path)
    return FileResponse(
        path=file_path,
        media_type=evidence.mime_type or "application/octet-stream",
        filename=evidence.stored_filename,
    )


# ---------------------------------------------------------------------------
# Customer Adaptive Evidence Follow-up Endpoints (Milestone 9)
# ---------------------------------------------------------------------------

@router.get(
    "/{token}/evidence-requests",
    response_model=List[CustomerEvidenceRequestResponse],
    status_code=status.HTTP_200_OK,
    summary="List targeted evidence requests for customer session",
)
def list_customer_evidence_requests(
    token: str,
    db: Session = Depends(get_db),
) -> List[CustomerEvidenceRequestResponse]:
    """Retrieve targeted follow-up evidence requests issued for this session."""
    session = public_verification_service.get_session_by_token(db, token)
    requests = evidence_request_service.list_session_requests(db, session.id)
    return [CustomerEvidenceRequestResponse.model_validate(r) for r in requests]


@router.post(
    "/{token}/evidence-requests/{request_id}/fulfill",
    response_model=EvidenceRequestFulfillResponse,
    status_code=status.HTTP_200_OK,
    summary="Fulfill targeted evidence request with image, MCQ, or text evidence",
)
async def fulfill_customer_evidence_request(
    token: str,
    request_id: str,
    file: Optional[UploadFile] = File(None, description="Customer follow-up image file (JPEG, PNG, WEBP)"),
    text_content: Optional[str] = Form(None, description="Customer text response if TEXT follow-up"),
    selected_option: Optional[str] = Form(None, description="Customer selected option if MCQ follow-up"),
    db: Session = Depends(get_db),
) -> EvidenceRequestFulfillResponse:
    """Customer fulfills a specific follow-up request with an image, selected choice, or text statement.

    Triggers automatic downstream Gemini Vision re-analysis (for images) and Llama re-reasoning.
    """
    fulfilled_req, evidence, followup_run = await adaptive_verification_service.handle_customer_fulfillment(
        db=db,
        raw_token=token,
        request_id=request_id,
        file=file,
        text_content=text_content,
        selected_option=selected_option,
    )
    reasoning_action = None
    next_step = None
    if followup_run and followup_run.result_json:
        reasoning_action = followup_run.result_json.get("action")
        next_step = followup_run.result_json.get("next_step_key")

    return EvidenceRequestFulfillResponse(
        request=CustomerEvidenceRequestResponse.model_validate(fulfilled_req),
        evidence=EvidenceResponse.model_validate(evidence),
        reasoning_action=reasoning_action,
        next_step_key=next_step,
        message="Follow-up evidence uploaded and processed successfully",
    )


# ---------------------------------------------------------------------------
# Customer Deterministic Signals View (Milestone 10)
# ---------------------------------------------------------------------------

@router.get(
    "/{token}/signals",
    response_model=List[CustomerSignalResponse],
    status_code=status.HTTP_200_OK,
    summary="List customer-visible verification signals",
)
def list_customer_signals(
    token: str,
    db: Session = Depends(get_db),
) -> List[CustomerSignalResponse]:
    """Retrieve sanitized deterministic signals relevant to the customer verification flow.

    Sensitive payment credentials and merchant internal IDs are never exposed.
    """
    return verification_signal_service.list_customer_signals(db=db, raw_token=token)


# ---------------------------------------------------------------------------
# Customer Evidence Fusion View (Milestone 11)
# ---------------------------------------------------------------------------

@router.get(
    "/{token}/fusion",
    response_model=CustomerFusionResponse,
    status_code=status.HTTP_200_OK,
    summary="Get customer-facing sanitized verification fusion assessment",
)
def get_customer_fusion(
    token: str,
    db: Session = Depends(get_db),
) -> CustomerFusionResponse:
    """Retrieve sanitized verification assessment for the customer.

    Strips merchant internal IDs, payment references, and internal confidence scores.
    Uses polite, neutral, non-accusatory language.
    """
    return evidence_fusion_service.get_customer_fusion(db=db, raw_token=token)


# ---------------------------------------------------------------------------
# Customer Live Analysis & Completion Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/{token}/analyze",
    status_code=status.HTTP_200_OK,
    summary="Trigger real-time analysis and follow-up evaluation for customer session",
)
def trigger_customer_analysis(
    token: str,
    db: Session = Depends(get_db),
):
    """Execute real-time analysis and reasoning check on customer-submitted evidence.
    
    Returns whether adaptive follow-up is required or if evidence is ready for review.
    """
    return public_verification_service.analyze_customer_session(db=db, raw_token=token)


@router.post(
    "/{token}/complete",
    response_model=VerificationStartResponse,
    status_code=status.HTTP_200_OK,
    summary="Mark customer verification session completed",
)
def complete_customer_verification(
    token: str,
    db: Session = Depends(get_db),
) -> VerificationStartResponse:
    """Transition verification session to COMPLETED once customer finishes submitting evidence.
    
    Enforces one-attempt verification lifecycle.
    """
    return public_verification_service.complete_customer_session(db=db, raw_token=token)


@router.post(
    "/{token}/extract-payment-proof",
    status_code=status.HTTP_200_OK,
    summary="Extract payment proof details from uploaded customer payment receipt",
)
async def extract_payment_proof(
    token: str,
    file: UploadFile = File(..., description="Uploaded payment confirmation screenshot"),
    db: Session = Depends(get_db),
) -> dict:
    """Extract payment transaction metadata (UPI ID, Txn ID, Amount, Date, Status, Payee)."""
    from app.services.extraction_service import extract_payment_proof_details

    session = public_verification_service.get_session_by_token(db, token)

    image_bytes = await file.read()
    mime_type = file.content_type or "image/jpeg"

    extracted = extract_payment_proof_details(
        image_bytes=image_bytes,
        mime_type=mime_type,
    )

    # Check against merchant-configured expected payment account if present in workflow snapshot
    expected_payee = None
    snapshot = session.workflow_snapshot_json or {}
    for step in snapshot.get("steps", []):
        cfg = step.get("config") or step.get("config_json") or {}
        if cfg.get("expected_payment_account"):
            expected_payee = str(cfg.get("expected_payment_account")).strip()
            break
        if cfg.get("upi_id"):
            expected_payee = str(cfg.get("upi_id")).strip()
            break

    account_matched = None
    if expected_payee and extracted.get("payee_account"):
        account_matched = (
            expected_payee.lower() in extracted["payee_account"].lower()
            or extracted["payee_account"].lower() in expected_payee.lower()
        )

    extracted["expected_payee"] = expected_payee
    extracted["account_matched"] = account_matched

    return {"status": "SUCCESS", "extracted": extracted}


@router.post(
    "/{token}/payment-proof",
    status_code=status.HTTP_201_CREATED,
    summary="Submit customer payment proof screenshot and structured payment details",
)
async def submit_payment_proof(
    token: str,
    workflow_step_key: str = Form(..., description="Workflow step key for payment step"),
    payee_account: Optional[str] = Form(None, description="Payee UPI ID or merchant recipient"),
    payer_account: Optional[str] = Form(None, description="Payer UPI ID or customer account"),
    transaction_id: Optional[str] = Form(None, description="Transaction reference ID or UTR"),
    amount: Optional[float] = Form(None, description="Payment amount"),
    currency: Optional[str] = Form("INR", description="Payment currency"),
    payment_status: Optional[str] = Form("PAID", description="Payment status (e.g. PAID)"),
    payment_method: Optional[str] = Form("UPI", description="Payment method (e.g. UPI)"),
    file: Optional[UploadFile] = File(None, description="Optional payment receipt screenshot"),
    db: Session = Depends(get_db),
) -> dict:
    """Customer submits payment proof image and confirmed transaction details.

    Stores image as CUSTOMER_IMAGE evidence, ingests deterministic PAYMENT signal,
    and runs payee reconciliation against merchant-configured account.
    """
    session = public_verification_service.get_session_by_token(db, token)

    # 1. Validate workflow_step_key against session workflow snapshot
    snapshot = session.workflow_snapshot_json or {}
    steps = snapshot.get("steps", [])
    step = next((s for s in steps if s.get("step_key") == workflow_step_key), None)
    if not step:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Workflow step '{workflow_step_key}' not found in verification session workflow snapshot",
        )

    # 2. Upload image evidence if file provided
    evidence_id = None
    if file and file.filename:
        ev = await evidence_service.create_customer_image_evidence(
            db=db,
            raw_token=token,
            file=file,
            workflow_step_key=workflow_step_key,
        )
        evidence_id = ev.id

    # 3. Formulate and ingest deterministic PAYMENT signal
    txn = (transaction_id or "").strip() or f"TXN-{session.verification_id}"
    payee = (payee_account or "").strip() or None
    payer = (payer_account or "").strip() or None
    clean_status = (payment_status or "PAID").strip().upper()
    if clean_status in ("SUCCESS", "COMPLETED", "SETTLED"):
        clean_status = "PAID"
    clean_method = (payment_method or "UPI").strip().upper()
    clean_currency = (currency or "INR").strip().upper()
    pay_amount = float(amount) if amount is not None else float(session.refund_amount or 0.0)

    from app.schemas.verification_signal import SignalIngestRequest, SignalType, SourceType
    signal_req = SignalIngestRequest(
        signal_type=SignalType.PAYMENT,
        source_type=SourceType.CUSTOMER_PROVIDED,
        source_reference=f"proof_{session.verification_id}",
        confidence=0.90 if evidence_id else 0.80,
        data={
            "payment_id": txn,
            "order_id": session.order_id,
            "amount": pay_amount,
            "currency": clean_currency,
            "payment_status": clean_status,
            "payment_method": clean_method,
            "transaction_reference": txn,
            "payee_account": payee,
            "payer_account": payer,
        },
    )
    sig = verification_signal_service.ingest_customer_signal(
        db=db,
        raw_token=token,
        request=signal_req,
    )

    # 4. Payee matching check against merchant workflow config
    expected_payee = None
    cfg = step.get("config") or step.get("config_json") or {}
    if cfg.get("expected_payment_account"):
        expected_payee = str(cfg.get("expected_payment_account")).strip()
    elif cfg.get("upi_id"):
        expected_payee = str(cfg.get("upi_id")).strip()

    account_matched = None
    if expected_payee and payee:
        account_matched = (
            expected_payee.lower() in payee.lower()
            or payee.lower() in expected_payee.lower()
        )

    return {
        "status": "SUCCESS",
        "message": "Payment proof and details submitted successfully",
        "evidence_id": evidence_id,
        "signal_id": sig.id,
        "expected_payee": expected_payee,
        "account_matched": account_matched,
    }


