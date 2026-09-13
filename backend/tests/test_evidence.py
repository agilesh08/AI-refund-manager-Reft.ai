"""Automated unit and integration test suite for Milestone 6: Customer Evidence Collection & Multi-Source Signal Ingestion."""
import io
from datetime import datetime, timedelta, timezone
from pathlib import Path
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import hash_verification_token
from app.models.evidence import Evidence, EvidenceType, EvidenceStatus
from app.models.evidence_event import EvidenceEvent, EvidenceEventType
from app.models.verification import VerificationSession, SessionStatus
from app.services.evidence_processing_service import process_evidence
from app.utils.file_storage import calculate_sha256, get_evidence_file_path


def make_test_image(color: str = "green", fmt: str = "JPEG") -> bytes:
    """Generate in-memory image bytes."""
    buf = io.BytesIO()
    img = Image.new("RGB", (30, 30), color=color)
    img.save(buf, format=fmt)
    buf.seek(0)
    return buf.getvalue()


def make_test_video() -> bytes:
    """Generate mock video binary content with MP4 header."""
    return b"\x00\x00\x00\x18ftypmp42\x00\x00\x00\x00mp42isom" + (b"A" * 200)


def register_and_auth(client: TestClient, email: str, name: str = "Test Store") -> tuple[str, str]:
    """Helper to register and login a merchant."""
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": name, "email": email, "password": "Password123!"},
    )
    merchant_id = reg.json()["id"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    token = login.json()["access_token"]
    return merchant_id, f"Bearer {token}"


def setup_verified_session(
    client: TestClient,
    auth: str,
    sku: str = "PROD-EV-1",
    allow_video: bool = False,
) -> tuple[dict, str]:
    """Create complete product, active workflow with image/text/video steps, and started verification session."""
    # 1. Product with 4 reference angles
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Evidence Test Product", "sku": sku, "price": "199.99"},
    )
    prod_id = prod_res.json()["id"]

    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        client.post(
            f"/api/v1/products/{prod_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", make_test_image(), "image/jpeg")},
        )

    # 2. Workflow with IMAGE, TEXT, and optional VIDEO step
    wf_res = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": "Evidence Collection Workflow"},
    )
    wf_id = wf_res.json()["id"]

    # Image step
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "damage_photo",
            "step_type": "IMAGE",
            "title": "Upload Damage Photo",
            "step_order": 1,
            "required": True,
            "config": {"min_images": 1, "max_images": 3},
        },
    )

    # Text step
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "issue_description",
            "step_type": "TEXT",
            "title": "Describe Damage",
            "step_order": 2,
            "required": True,
            "config": {"min_length": 5, "max_length": 500},
        },
    )

    # Video step if requested
    if allow_video:
        client.post(
            f"/api/v1/workflows/{wf_id}/steps",
            headers={"Authorization": auth},
            json={
                "step_key": "damage_video",
                "step_type": "CAMERA",
                "title": "Record Unboxing Video",
                "step_order": 3,
                "required": False,
                "config": {"allow_video": True},
            },
        )

    # Publish workflow
    client.post(f"/api/v1/workflows/{wf_id}/publish", headers={"Authorization": auth})

    # 3. Create session
    sess_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={
            "product_id": prod_id,
            "workflow_id": wf_id,
            "order_id": f"ORD-{sku}",
            "customer_name": "Test Customer",
        },
    )
    sess_data = sess_res.json()
    raw_token = sess_data["customer_link"].split("/")[-1]

    # 4. Start session (IN_PROGRESS required for evidence submission)
    client.post(f"/api/v1/public/verifications/{raw_token}/start")

    return sess_data, raw_token


# ===========================================================================
# Customer Evidence Upload Tests (Image, Video, Text)
# ===========================================================================

def test_successful_image_upload(client: TestClient, db_session: Session):
    """Test successful image upload: JPEG, PNG, WEBP with SHA-256 and event logging."""
    _, auth = register_and_auth(client, "ev_img_success@test.com")
    sess_data, token = setup_verified_session(client, auth, "SKU-IMG-SUCCESS")

    img_bytes = make_test_image("blue", "JPEG")
    expected_hash = calculate_sha256(img_bytes)

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("photo.jpg", img_bytes, "image/jpeg")},
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    assert data["evidence_id"].startswith("EV-")
    assert data["evidence_type"] == "CUSTOMER_IMAGE"
    assert data["workflow_step_key"] == "damage_photo"
    assert data["status"] == "READY_FOR_ANALYSIS"
    assert data["sha256_hash"] == expected_hash
    assert data["file_size_bytes"] == len(img_bytes)
    assert "storage_path" not in data  # Storage path never exposed

    # Verify metadata
    meta = data["metadata_json"]
    assert meta["capture_source"] == "customer_upload"
    assert meta["image_width"] == 30
    assert meta["image_height"] == 30
    assert meta["format"] == "JPEG"

    # Verify database persistence & events
    db_ev = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == data["evidence_id"])
    ).scalar_one()
    assert db_ev.sha256_hash == expected_hash
    assert Path(settings.STORAGE_PATH, db_ev.storage_path).exists()

    events = list(db_session.execute(
        select(EvidenceEvent).where(EvidenceEvent.evidence_id == db_ev.id).order_by(EvidenceEvent.created_at.asc())
    ).scalars().all())
    event_types = [e.event_type for e in events]
    assert event_types == [
        EvidenceEventType.EVIDENCE_UPLOADED.value,
        EvidenceEventType.EVIDENCE_VALIDATED.value,
        EvidenceEventType.EVIDENCE_READY_FOR_ANALYSIS.value,
    ]


def test_successful_video_upload(client: TestClient, db_session: Session):
    """Test successful video upload when workflow explicitly allows video."""
    _, auth = register_and_auth(client, "ev_vid_success@test.com")
    sess_data, token = setup_verified_session(client, auth, "SKU-VID-SUCCESS", allow_video=True)

    vid_bytes = make_test_video()
    expected_hash = calculate_sha256(vid_bytes)

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/video",
        data={"workflow_step_key": "damage_video"},
        files={"file": ("unboxing.mp4", vid_bytes, "video/mp4")},
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    assert data["evidence_type"] == "CUSTOMER_VIDEO"
    assert data["status"] == "READY_FOR_ANALYSIS"
    assert data["sha256_hash"] == expected_hash

    # Verify physical file stored under storage/evidence/
    db_ev = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == data["evidence_id"])
    ).scalar_one()
    assert "evidence/" in db_ev.storage_path
    assert "product_references" not in db_ev.storage_path
    assert Path(settings.STORAGE_PATH, db_ev.storage_path).exists()


def test_successful_text_evidence(client: TestClient, db_session: Session):
    """Test successful text evidence submission stored in database without filesystem writing."""
    _, auth = register_and_auth(client, "ev_txt_success@test.com")
    sess_data, token = setup_verified_session(client, auth, "SKU-TXT-SUCCESS")

    text_body = "The hinge snapped off upon opening the package."
    expected_hash = calculate_sha256(text_body.strip().encode("utf-8"))

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "issue_description", "text": text_body},
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    assert data["evidence_type"] == "CUSTOMER_TEXT"
    assert data["text_content"] == text_body
    assert data["sha256_hash"] == expected_hash
    assert data["status"] == "READY_FOR_ANALYSIS"

    # Verify DB: no storage_path or stored_filename for text
    db_ev = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == data["evidence_id"])
    ).scalar_one()
    assert db_ev.storage_path is None
    assert db_ev.stored_filename is None
    assert db_ev.text_content == text_body


# ===========================================================================
# Validation & Error Handling Tests
# ===========================================================================

def test_unsupported_image_type_rejected(client: TestClient):
    """Test uploading unsupported image formats (e.g. GIF, BMP) returns HTTP 400."""
    _, auth = register_and_auth(client, "ev_bad_type@test.com")
    _, token = setup_verified_session(client, auth, "SKU-BAD-IMG")

    gif_bytes = make_test_image("red", "GIF")
    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("photo.gif", gif_bytes, "image/gif")},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST


def test_corrupt_image_rejected(client: TestClient):
    """Test uploading corrupted image payload disguised with image/jpeg mime returns HTTP 400."""
    _, auth = register_and_auth(client, "ev_corrupt@test.com")
    _, token = setup_verified_session(client, auth, "SKU-CORRUPT")

    corrupt_bytes = b"not-a-valid-jpeg-image-stream-content"
    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("photo.jpg", corrupt_bytes, "image/jpeg")},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "decoded" in res.json()["detail"].lower()


def test_oversized_image_rejected(client: TestClient, monkeypatch):
    """Test uploading oversized image returns HTTP 413."""
    _, auth = register_and_auth(client, "ev_oversize_img@test.com")
    _, token = setup_verified_session(client, auth, "SKU-OVERSIZE-IMG")

    # Lower limit temporarily to 1MB
    monkeypatch.setattr(settings, "MAX_IMAGE_SIZE_MB", 1)
    large_bytes = b"0" * (1024 * 1024 + 10)

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("huge.jpg", large_bytes, "image/jpeg")},
    )
    assert res.status_code == status.HTTP_413_CONTENT_TOO_LARGE


def test_oversized_video_rejected(client: TestClient, monkeypatch):
    """Test uploading oversized video returns HTTP 413."""
    _, auth = register_and_auth(client, "ev_oversize_vid@test.com")
    _, token = setup_verified_session(client, auth, "SKU-OVERSIZE-VID", allow_video=True)

    monkeypatch.setattr(settings, "MAX_VIDEO_SIZE_MB", 1)
    large_bytes = b"0" * (1024 * 1024 + 10)

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/video",
        data={"workflow_step_key": "damage_video"},
        files={"file": ("huge.mp4", large_bytes, "video/mp4")},
    )
    assert res.status_code == status.HTTP_413_CONTENT_TOO_LARGE


def test_empty_upload_rejected(client: TestClient):
    """Test empty file upload returns HTTP 400."""
    _, auth = register_and_auth(client, "ev_empty@test.com")
    _, token = setup_verified_session(client, auth, "SKU-EMPTY")

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("empty.jpg", b"", "image/jpeg")},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "empty" in res.json()["detail"].lower()


def test_customer_filename_cannot_control_storage_path(client: TestClient, db_session: Session):
    """Test path traversal attempts in filename cannot escape storage/evidence/."""
    _, auth = register_and_auth(client, "ev_traversal@test.com")
    _, token = setup_verified_session(client, auth, "SKU-TRAVERSAL")

    img_bytes = make_test_image()
    malicious_filename = "../../../etc/passwd.jpg"

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": (malicious_filename, img_bytes, "image/jpeg")},
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()

    db_ev = db_session.execute(
        select(Evidence).where(Evidence.evidence_id == data["evidence_id"])
    ).scalar_one()

    # Verify stored_filename was safely generated without traversal
    assert ".." not in db_ev.stored_filename
    assert "etc" not in db_ev.stored_filename
    assert db_ev.storage_path.startswith("evidence/")


def test_text_length_and_whitespace_validation(client: TestClient):
    """Test text validation: length limit and whitespace-only rejection."""
    _, auth = register_and_auth(client, "ev_txt_val@test.com")
    _, token = setup_verified_session(client, auth, "SKU-TXT-VAL")

    # Whitespace only -> HTTP 422
    res_ws = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "issue_description", "text": "   \n\t   "},
    )
    assert res_ws.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Oversized text (>5000 chars) -> HTTP 422
    res_huge = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "issue_description", "text": "A" * 5001},
    )
    assert res_huge.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_invalid_workflow_step_key_rejected(client: TestClient):
    """Test non-existent step key returns HTTP 422."""
    _, auth = register_and_auth(client, "ev_bad_step@test.com")
    _, token = setup_verified_session(client, auth, "SKU-BAD-STEP")

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "completely_fake_step"},
        files={"file": ("photo.jpg", make_test_image(), "image/jpeg")},
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "not found" in res.json()["detail"].lower()


def test_workflow_step_type_mismatch_rejected(client: TestClient):
    """Test submitting incompatible evidence type to step returns HTTP 422."""
    _, auth = register_and_auth(client, "ev_mismatch@test.com")
    _, token = setup_verified_session(client, auth, "SKU-MISMATCH")

    # 1. Text evidence submitted to IMAGE step -> HTTP 422
    res_txt_on_img = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "damage_photo", "text": "This is text on an image step"},
    )
    assert res_txt_on_img.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 2. Image evidence submitted to TEXT step -> HTTP 422
    res_img_on_txt = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "issue_description"},
        files={"file": ("photo.jpg", make_test_image(), "image/jpeg")},
    )
    assert res_img_on_txt.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_video_on_non_video_step_rejected(client: TestClient):
    """Test uploading video when workflow step does not permit video returns HTTP 422."""
    _, auth = register_and_auth(client, "ev_no_vid@test.com")
    # allow_video=False in setup
    _, token = setup_verified_session(client, auth, "SKU-NO-VID", allow_video=False)

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/video",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("video.mp4", make_test_video(), "video/mp4")},
    )
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "video" in res.json()["detail"].lower()


# ===========================================================================
# Session State Validation Tests (CREATED, COMPLETED, CANCELLED, EXPIRED)
# ===========================================================================

def test_evidence_submission_before_session_start_rejected(client: TestClient):
    """Test submitting evidence when session is in CREATED state returns HTTP 400."""
    _, auth = register_and_auth(client, "ev_unstarted@test.com")

    # Create session but DO NOT start it
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "P", "sku": "SKU-UNSTARTED", "price": "10.00"},
    )
    prod_id = prod_res.json()["id"]
    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        client.post(
            f"/api/v1/products/{prod_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", make_test_image(), "image/jpeg")},
        )
    wf_res = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF"})
    wf_id = wf_res.json()["id"]
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={"step_key": "s1", "step_type": "TEXT", "title": "S1"},
    )
    client.post(f"/api/v1/workflows/{wf_id}/publish", headers={"Authorization": auth})

    sess_res = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf_id, "order_id": "ORD-UNSTARTED"},
    )
    raw_token = sess_res.json()["customer_link"].split("/")[-1]

    # Attempt text submission without starting -> HTTP 400
    res = client.post(
        f"/api/v1/public/verifications/{raw_token}/evidence/text",
        json={"workflow_step_key": "s1", "text": "Attempting evidence early"},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "started" in res.json()["detail"].lower()


def test_completed_session_evidence_rejected(client: TestClient, db_session: Session):
    """Test submitting evidence to completed session returns HTTP 400."""
    _, auth = register_and_auth(client, "ev_completed@test.com")
    sess_data, token = setup_verified_session(client, auth, "SKU-COMPLETED")

    # Manually transition session to COMPLETED
    db_entry = db_session.execute(
        select(VerificationSession).where(VerificationSession.verification_id == sess_data["verification_id"])
    ).scalar_one()
    db_entry.status = SessionStatus.COMPLETED.value
    db_session.commit()

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "issue_description", "text": "Post completion"},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "completed" in res.json()["detail"].lower()


def test_cancelled_session_returns_410(client: TestClient):
    """Test submitting or retrieving evidence on cancelled session returns HTTP 410 Gone."""
    _, auth = register_and_auth(client, "ev_cancelled@test.com")
    sess_data, token = setup_verified_session(client, auth, "SKU-CANCELLED")

    # Merchant cancels session
    client.post(f"/api/v1/verifications/{sess_data['verification_id']}/cancel", headers={"Authorization": auth})

    # Evidence upload -> HTTP 410
    res_upload = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "issue_description", "text": "Post cancellation"},
    )
    assert res_upload.status_code == status.HTTP_410_GONE

    # Evidence listing -> HTTP 410
    res_list = client.get(f"/api/v1/public/verifications/{token}/evidence")
    assert res_list.status_code == status.HTTP_410_GONE


def test_expired_session_returns_410(client: TestClient, db_session: Session):
    """Test submitting evidence on expired session returns HTTP 410 Gone."""
    _, auth = register_and_auth(client, "ev_expired@test.com")
    sess_data, token = setup_verified_session(client, auth, "SKU-EXPIRED")

    # Expire session in database
    db_entry = db_session.execute(
        select(VerificationSession).where(VerificationSession.verification_id == sess_data["verification_id"])
    ).scalar_one()
    db_entry.expires_at = datetime.now(timezone.utc) - timedelta(hours=1)
    db_session.commit()

    res = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "issue_description", "text": "Late evidence"},
    )
    assert res.status_code == status.HTTP_410_GONE
    assert "expired" in res.json()["detail"].lower()


def test_invalid_customer_token_returns_404(client: TestClient):
    """Test accessing evidence with invalid token returns HTTP 404."""
    res = client.get("/api/v1/public/verifications/invalid-fake-token-xyz/evidence")
    assert res.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# Isolation & Security Tests (Customer vs Customer, Merchant vs Merchant)
# ===========================================================================

def test_customer_isolation(client: TestClient):
    """Test Customer A cannot see or download Customer B's evidence."""
    _, auth = register_and_auth(client, "ev_isolation_cust@test.com")
    _, token_a = setup_verified_session(client, auth, "SKU-ISO-A")
    _, token_b = setup_verified_session(client, auth, "SKU-ISO-B")

    # Customer A uploads evidence
    ev_a = client.post(
        f"/api/v1/public/verifications/{token_a}/evidence/text",
        json={"workflow_step_key": "issue_description", "text": "Customer A Secret Note"},
    ).json()

    # Customer B lists evidence: must NOT see A's evidence
    list_b = client.get(f"/api/v1/public/verifications/{token_b}/evidence").json()
    assert len(list_b) == 0

    # Customer B attempts to get Customer A's evidence item directly -> HTTP 404
    get_res = client.get(f"/api/v1/public/verifications/{token_b}/evidence/{ev_a['evidence_id']}")
    assert get_res.status_code == status.HTTP_404_NOT_FOUND


def test_merchant_isolation(client: TestClient):
    """Test Merchant B cannot see or access Merchant A's evidence."""
    _, auth_a = register_and_auth(client, "m_iso_a@test.com", "Merchant A")
    _, auth_b = register_and_auth(client, "m_iso_b@test.com", "Merchant B")

    sess_a, token_a = setup_verified_session(client, auth_a, "SKU-M-A")

    # Customer submits evidence to Session A
    ev_a = client.post(
        f"/api/v1/public/verifications/{token_a}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("photo.jpg", make_test_image(), "image/jpeg")},
    ).json()

    # Merchant A can retrieve evidence list
    list_a = client.get(
        f"/api/v1/verifications/{sess_a['verification_id']}/evidence",
        headers={"Authorization": auth_a},
    )
    assert list_a.status_code == status.HTTP_200_OK
    assert len(list_a.json()) == 1

    # Merchant B cannot access Session A's evidence list -> HTTP 404
    list_b = client.get(
        f"/api/v1/verifications/{sess_a['verification_id']}/evidence",
        headers={"Authorization": auth_b},
    )
    assert list_b.status_code == status.HTTP_404_NOT_FOUND

    # Merchant B cannot access evidence item directly -> HTTP 404
    get_b = client.get(
        f"/api/v1/verifications/{sess_a['verification_id']}/evidence/{ev_a['evidence_id']}",
        headers={"Authorization": auth_b},
    )
    assert get_b.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# Duplicate Detection & Preservation Tests
# ===========================================================================

def test_duplicate_sha256_detected_and_preserved(client: TestClient, db_session: Session):
    """Test duplicate upload detection: second evidence record is preserved and marked with duplicate_of."""
    _, auth = register_and_auth(client, "ev_dup@test.com")
    _, token = setup_verified_session(client, auth, "SKU-DUP")

    img_bytes = make_test_image("purple", "PNG")

    # Upload 1
    res1 = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("photo1.png", img_bytes, "image/png")},
    )
    ev1 = res1.json()
    assert "duplicate_of" not in ev1["metadata_json"]

    # Upload 2 (identical content)
    res2 = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("photo2.png", img_bytes, "image/png")},
    )
    ev2 = res2.json()

    # Verify both records exist with distinct evidence IDs
    assert ev1["evidence_id"] != ev2["evidence_id"]
    assert ev2["metadata_json"]["duplicate_of"] == ev1["evidence_id"]

    # Verify both are preserved in database
    records = list(db_session.execute(
        select(Evidence).where(Evidence.sha256_hash == ev1["sha256_hash"])
    ).scalars().all())
    assert len(records) == 2


# ===========================================================================
# Workflow Snapshot Freezing Tests (v1 vs v2)
# ===========================================================================

def test_workflow_snapshot_validation_uses_frozen_version(client: TestClient):
    """Test evidence validation strictly uses frozen snapshot v1, ignoring later live workflow modifications."""
    _, auth = register_and_auth(client, "ev_frozen_wf@test.com")

    # Product setup
    prod_res = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Prod", "sku": "SKU-FROZEN", "price": "50.00"},
    )
    prod_id = prod_res.json()["id"]
    for angle in ["FRONT", "BACK", "LEFT", "RIGHT"]:
        client.post(
            f"/api/v1/products/{prod_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", make_test_image(), "image/jpeg")},
        )

    # Create Workflow v1 with step 'step_original'
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF Frozen"}).json()
    client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={"step_key": "step_original", "step_type": "TEXT", "title": "Original Step"},
    )
    client.post(f"/api/v1/workflows/{wf['id']}/publish", headers={"Authorization": auth})

    # Create session under Workflow v1
    sess = client.post(
        "/api/v1/verifications",
        headers={"Authorization": auth},
        json={"product_id": prod_id, "workflow_id": wf["id"], "order_id": "ORD-FROZEN-1"},
    ).json()
    token = sess["customer_link"].split("/")[-1]
    client.post(f"/api/v1/public/verifications/{token}/start")

    # Merchant archives the workflow afterwards
    client.post(f"/api/v1/workflows/{wf['id']}/archive", headers={"Authorization": auth})

    # Customer submitting against 'step_original' must STILL SUCCEED because snapshot is frozen!
    res_orig = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "step_original", "text": "Evidence against frozen step"},
    )
    assert res_orig.status_code == status.HTTP_201_CREATED

    # Submitting against a step that was never in snapshot v1 must FAIL
    res_invalid = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "step_future_v2", "text": "Evidence against non-existent step"},
    )
    assert res_invalid.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# ===========================================================================
# Evidence Download / Viewing & Boundary Processing Tests
# ===========================================================================

def test_evidence_download_file_and_text(client: TestClient):
    """Test downloading image evidence serves file content, and text evidence serves JSON."""
    _, auth = register_and_auth(client, "ev_download@test.com")
    sess_data, token = setup_verified_session(client, auth, "SKU-DOWNLOAD")

    # Upload image
    img_bytes = make_test_image("red", "JPEG")
    ev_img = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("red.jpg", img_bytes, "image/jpeg")},
    ).json()

    # Upload text
    ev_txt = client.post(
        f"/api/v1/public/verifications/{token}/evidence/text",
        json={"workflow_step_key": "issue_description", "text": "Downloadable text explanation"},
    ).json()

    # Customer downloads image -> binary content matches
    dl_img = client.get(f"/api/v1/public/verifications/{token}/evidence/{ev_img['evidence_id']}")
    assert dl_img.status_code == status.HTTP_200_OK
    assert dl_img.content == img_bytes
    assert dl_img.headers["content-type"] == "image/jpeg"

    # Customer views text -> returns JSON
    dl_txt = client.get(f"/api/v1/public/verifications/{token}/evidence/{ev_txt['evidence_id']}")
    assert dl_txt.status_code == status.HTTP_200_OK
    assert dl_txt.json()["text_content"] == "Downloadable text explanation"

    # Merchant downloads image -> binary content matches
    m_dl_img = client.get(
        f"/api/v1/verifications/{sess_data['verification_id']}/evidence/{ev_img['evidence_id']}",
        headers={"Authorization": auth},
    )
    assert m_dl_img.status_code == status.HTTP_200_OK
    assert m_dl_img.content == img_bytes


def test_evidence_processing_service_placeholder(client: TestClient, db_session: Session):
    """Test process_evidence boundary function validates status and returns placeholder without calling AI."""
    _, auth = register_and_auth(client, "ev_proc@test.com")
    sess_data, token = setup_verified_session(client, auth, "SKU-PROC")

    ev = client.post(
        f"/api/v1/public/verifications/{token}/evidence/image",
        data={"workflow_step_key": "damage_photo"},
        files={"file": ("photo.jpg", make_test_image(), "image/jpeg")},
    ).json()

    # Call boundary function
    res = process_evidence(db_session, ev["evidence_id"])
    assert res.placeholder is True
    assert res.status == "READY_FOR_ANALYSIS"
    assert res.evidence_id == ev["evidence_id"]
