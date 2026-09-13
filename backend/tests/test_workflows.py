import pytest
from fastapi import status
from fastapi.testclient import TestClient

from app.models.workflow import WorkflowStatus
from app.models.workflow_step import WorkflowStepType


def get_auth_merchant(client: TestClient, email: str, name: str = "Test Store") -> tuple[str, str]:
    """Register and login merchant, returning (merchant_id, auth_header)."""
    reg = client.post(
        "/api/v1/auth/register",
        json={"business_name": name, "email": email, "password": "Password123!"},
    )
    mid = reg.json()["id"]
    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    token = login.json()["access_token"]
    return mid, f"Bearer {token}"


# ===========================================================================
# Workflow Lifecycle & CRUD Tests
# ===========================================================================

def test_create_workflow_success(client: TestClient):
    """Test authenticated merchant can create a draft workflow."""
    _, auth = get_auth_merchant(client, "wf_create@merchant.com")
    res = client.post(
        "/api/v1/workflows",
        headers={"Authorization": auth},
        json={"name": "Standard Clothing Return", "description": "Workflow for garment returns"},
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["name"] == "Standard Clothing Return"
    assert data["description"] == "Workflow for garment returns"
    assert data["status"] == WorkflowStatus.DRAFT.value
    assert data["is_active"] is False
    assert data["version"] == 1
    assert "id" in data


def test_create_workflow_unauthenticated(client: TestClient):
    """Test unauthenticated request is rejected with 401."""
    res = client.post("/api/v1/workflows", json={"name": "No Auth"})
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_workflows_merchant_isolation(client: TestClient):
    """Test merchant can only list their own workflows."""
    _, auth_a = get_auth_merchant(client, "wf_list_a@test.com")
    _, auth_b = get_auth_merchant(client, "wf_list_b@test.com")

    client.post("/api/v1/workflows", headers={"Authorization": auth_a}, json={"name": "WF A1"})
    client.post("/api/v1/workflows", headers={"Authorization": auth_a}, json={"name": "WF A2"})
    client.post("/api/v1/workflows", headers={"Authorization": auth_b}, json={"name": "WF B1"})

    list_a = client.get("/api/v1/workflows", headers={"Authorization": auth_a}).json()
    assert len(list_a) == 2
    assert {w["name"] for w in list_a} == {"WF A1", "WF A2"}

    list_b = client.get("/api/v1/workflows", headers={"Authorization": auth_b}).json()
    assert len(list_b) == 1
    assert list_b[0]["name"] == "WF B1"


def test_get_workflow_isolation(client: TestClient):
    """Test Merchant B cannot get Merchant A's workflow (returns 404)."""
    _, auth_a = get_auth_merchant(client, "wf_get_a@test.com")
    _, auth_b = get_auth_merchant(client, "wf_get_b@test.com")

    wf = client.post("/api/v1/workflows", headers={"Authorization": auth_a}, json={"name": "Secret WF"}).json()

    res_a = client.get(f"/api/v1/workflows/{wf['id']}", headers={"Authorization": auth_a})
    assert res_a.status_code == status.HTTP_200_OK

    res_b = client.get(f"/api/v1/workflows/{wf['id']}", headers={"Authorization": auth_b})
    assert res_b.status_code == status.HTTP_404_NOT_FOUND


def test_update_workflow(client: TestClient):
    """Test updating workflow name and description."""
    _, auth = get_auth_merchant(client, "wf_upd@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "Initial Name"}).json()

    res = client.put(
        f"/api/v1/workflows/{wf['id']}",
        headers={"Authorization": auth},
        json={"name": "Updated Name", "description": "New description"},
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.json()["name"] == "Updated Name"
    assert res.json()["description"] == "New description"


def test_delete_draft_workflow_allowed(client: TestClient):
    """Test deleting draft workflow succeeds."""
    _, auth = get_auth_merchant(client, "wf_del_draft@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "To Delete"}).json()

    del_res = client.delete(f"/api/v1/workflows/{wf['id']}", headers={"Authorization": auth})
    assert del_res.status_code == status.HTTP_200_OK

    get_res = client.get(f"/api/v1/workflows/{wf['id']}", headers={"Authorization": auth})
    assert get_res.status_code == status.HTTP_404_NOT_FOUND


def test_active_workflow_cannot_be_deleted(client: TestClient):
    """Test active workflow deletion is blocked with HTTP 400 until archived."""
    _, auth = get_auth_merchant(client, "wf_del_active@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "Active WF"}).json()

    # Add a step and publish
    client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={"step_key": "step1", "step_type": "ORDER", "title": "Order check"},
    )
    pub = client.post(f"/api/v1/workflows/{wf['id']}/publish", headers={"Authorization": auth})
    assert pub.status_code == status.HTTP_200_OK

    # Attempt delete active workflow -> HTTP 400
    del_res = client.delete(f"/api/v1/workflows/{wf['id']}", headers={"Authorization": auth})
    assert del_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Archive the workflow first" in del_res.json()["detail"]

    # Archive workflow
    arch = client.post(f"/api/v1/workflows/{wf['id']}/archive", headers={"Authorization": auth})
    assert arch.status_code == status.HTTP_200_OK

    # Delete archived workflow -> HTTP 200 OK
    del_arch = client.delete(f"/api/v1/workflows/{wf['id']}", headers={"Authorization": auth})
    assert del_arch.status_code == status.HTTP_200_OK


# ===========================================================================
# Step Types and Configuration Validation Tests
# ===========================================================================

def test_create_all_canonical_step_types(client: TestClient):
    """Test creating all 7 canonical step types with valid configs."""
    _, auth = get_auth_merchant(client, "wf_steps_all@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "Multi-Step WF"}).json()
    wf_id = wf["id"]

    # 1. MCQ
    mcq = client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "damage_reason",
            "step_type": "MCQ",
            "title": "What is wrong with the product?",
            "config": {
                "options": [
                    {"value": "torn_thread", "label": "Torn thread"},
                    {"value": "broken_part", "label": "Broken part"},
                ]
            },
        },
    )
    assert mcq.status_code == status.HTTP_201_CREATED
    assert mcq.json()["step_order"] == 1

    # 2. TEXT
    txt = client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "problem_desc",
            "step_type": "TEXT",
            "title": "Describe the problem",
            "config": {"min_length": 10, "max_length": 500, "multiline": True},
        },
    )
    assert txt.status_code == status.HTTP_201_CREATED
    assert txt.json()["step_order"] == 2

    # 3. IMAGE
    img = client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "damage_photo",
            "step_type": "IMAGE",
            "title": "Upload photo",
            "config": {"min_images": 1, "max_images": 3},
        },
    )
    assert img.status_code == status.HTTP_201_CREATED

    # 4. CAMERA
    cam = client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "product_capture",
            "step_type": "CAMERA",
            "title": "Capture product",
            "config": {"min_images": 1, "max_images": 4},
        },
    )
    assert cam.status_code == status.HTTP_201_CREATED

    # 5. PAYMENT
    pay = client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={"step_key": "payment_step", "step_type": "PAYMENT", "title": "Verify Payment"},
    )
    assert pay.status_code == status.HTTP_201_CREATED

    # 6. ORDER
    ordr = client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={"step_key": "order_step", "step_type": "ORDER", "title": "Verify Order"},
    )
    assert ordr.status_code == status.HTTP_201_CREATED

    # 7. DELIVERY
    delv = client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={"step_key": "delivery_step", "step_type": "DELIVERY", "title": "Verify Delivery", "required": False},
    )
    assert delv.status_code == status.HTTP_201_CREATED
    assert delv.json()["required"] is False

    # List steps
    steps = client.get(f"/api/v1/workflows/{wf_id}/steps", headers={"Authorization": auth}).json()
    assert len(steps) == 7


def test_invalid_step_type_rejected(client: TestClient):
    """Test rejecting unsupported step type."""
    _, auth = get_auth_merchant(client, "wf_bad_type@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF"}).json()

    res = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={"step_key": "s1", "step_type": "BIOMETRIC_SCAN", "title": "Scan"},
    )
    assert res.status_code in (status.HTTP_422_UNPROCESSABLE_CONTENT, status.HTTP_400_BAD_REQUEST)


def test_mcq_config_validation(client: TestClient):
    """Test MCQ validation rejects less than 2 options and duplicate values."""
    _, auth = get_auth_merchant(client, "wf_mcq_val@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF"}).json()

    # 1 option only -> HTTP 422
    res1 = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "mcq1",
            "step_type": "MCQ",
            "title": "Single opt",
            "config": {"options": [{"value": "v1", "label": "L1"}]},
        },
    )
    assert res1.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # Duplicate values -> HTTP 422
    res2 = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "mcq2",
            "step_type": "MCQ",
            "title": "Dup val",
            "config": {
                "options": [
                    {"value": "same", "label": "Option 1"},
                    {"value": "same", "label": "Option 2"},
                ]
            },
        },
    )
    assert res2.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "Duplicate option value" in res2.json()["detail"]


def test_text_and_image_config_validation(client: TestClient):
    """Test TEXT and IMAGE/CAMERA boundary checks."""
    _, auth = get_auth_merchant(client, "wf_cfg_bounds@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF"}).json()

    # TEXT: min > max -> HTTP 422
    res_text = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "t1",
            "step_type": "TEXT",
            "title": "Text",
            "config": {"min_length": 50, "max_length": 10},
        },
    )
    assert res_text.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # IMAGE: max_images < min_images -> HTTP 422
    res_img = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "i1",
            "step_type": "IMAGE",
            "title": "Img",
            "config": {"min_images": 5, "max_images": 2},
        },
    )
    assert res_img.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


def test_duplicate_step_key_rejected(client: TestClient):
    """Test duplicate step_key in same workflow returns HTTP 409."""
    _, auth = get_auth_merchant(client, "wf_dup_key@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF"}).json()

    res1 = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={"step_key": "common_key", "step_type": "ORDER", "title": "Order"},
    )
    assert res1.status_code == status.HTTP_201_CREATED

    res2 = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={"step_key": "common_key", "step_type": "PAYMENT", "title": "Payment"},
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in res2.json()["detail"]


# ===========================================================================
# Step Reordering Tests
# ===========================================================================

def test_reorder_workflow_steps_success(client: TestClient):
    """Test reordering steps assigns sequential 1..N order."""
    _, auth = get_auth_merchant(client, "wf_reorder@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "Reorder WF"}).json()
    wf_id = wf["id"]

    s1 = client.post(f"/api/v1/workflows/{wf_id}/steps", headers={"Authorization": auth}, json={"step_key": "s1", "step_type": "ORDER", "title": "S1"}).json()
    s2 = client.post(f"/api/v1/workflows/{wf_id}/steps", headers={"Authorization": auth}, json={"step_key": "s2", "step_type": "PAYMENT", "title": "S2"}).json()
    s3 = client.post(f"/api/v1/workflows/{wf_id}/steps", headers={"Authorization": auth}, json={"step_key": "s3", "step_type": "DELIVERY", "title": "S3"}).json()

    # Reorder to s3, s1, s2
    reorder_res = client.put(
        f"/api/v1/workflows/{wf_id}/steps/reorder",
        headers={"Authorization": auth},
        json={"step_ids": [s3["id"], s1["id"], s2["id"]]},
    )
    assert reorder_res.status_code == status.HTTP_200_OK
    reordered = reorder_res.json()

    assert [s["id"] for s in reordered] == [s3["id"], s1["id"], s2["id"]]
    assert [s["step_order"] for s in reordered] == [1, 2, 3]


def test_reorder_validation_errors(client: TestClient):
    """Test reordering rejects missing, duplicate, or foreign step IDs."""
    _, auth = get_auth_merchant(client, "wf_reorder_err@test.com")
    wf1 = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF1"}).json()
    wf2 = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF2"}).json()

    s1 = client.post(f"/api/v1/workflows/{wf1['id']}/steps", headers={"Authorization": auth}, json={"step_key": "s1", "step_type": "ORDER", "title": "S1"}).json()
    s2 = client.post(f"/api/v1/workflows/{wf1['id']}/steps", headers={"Authorization": auth}, json={"step_key": "s2", "step_type": "PAYMENT", "title": "S2"}).json()
    foreign_s = client.post(f"/api/v1/workflows/{wf2['id']}/steps", headers={"Authorization": auth}, json={"step_key": "foreign", "step_type": "DELIVERY", "title": "F"}).json()

    # 1. Duplicate IDs -> HTTP 422
    res_dup = client.put(
        f"/api/v1/workflows/{wf1['id']}/steps/reorder",
        headers={"Authorization": auth},
        json={"step_ids": [s1["id"], s1["id"]]},
    )
    assert res_dup.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 2. Missing step ID -> HTTP 422
    res_missing = client.put(
        f"/api/v1/workflows/{wf1['id']}/steps/reorder",
        headers={"Authorization": auth},
        json={"step_ids": [s1["id"]]},
    )
    assert res_missing.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 3. Foreign step ID -> HTTP 422
    res_foreign = client.put(
        f"/api/v1/workflows/{wf1['id']}/steps/reorder",
        headers={"Authorization": auth},
        json={"step_ids": [s1["id"], foreign_s["id"]]},
    )
    assert res_foreign.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# ===========================================================================
# Conditional Branching & Graph Validation Tests
# ===========================================================================

def test_conditional_branching_self_loop_rejected(client: TestClient):
    """Test that self-loops in conditions or default_next_step are rejected."""
    _, auth = get_auth_merchant(client, "wf_loop@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "WF"}).json()

    # Self-loop in condition -> HTTP 422
    res_cond = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "loop_step",
            "step_type": "MCQ",
            "title": "Loop",
            "config": {
                "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
                "conditions": [
                    {"when": {"step_key": "loop_step", "operator": "equals", "value": "a"}, "next_step": "loop_step"}
                ],
            },
        },
    )
    assert res_cond.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "Self-loop detected" in res_cond.json()["detail"]

    # Self-loop in default_next_step -> HTTP 422
    res_def = client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "def_loop",
            "step_type": "ORDER",
            "title": "Order",
            "config": {"default_next_step": "def_loop"},
        },
    )
    assert res_def.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT


# ===========================================================================
# Publish & Archive Tests
# ===========================================================================

def test_publish_empty_workflow_rejected(client: TestClient):
    """Test publishing a workflow without any steps returns HTTP 422."""
    _, auth = get_auth_merchant(client, "wf_pub_empty@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "Empty WF"}).json()

    res = client.post(f"/api/v1/workflows/{wf['id']}/publish", headers={"Authorization": auth})
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "must have at least one step" in res.json()["detail"]


def test_publish_workflow_with_invalid_graph_rejected(client: TestClient):
    """Test publishing rejects workflow when branch references non-existent step."""
    _, auth = get_auth_merchant(client, "wf_pub_broken@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "Broken Graph WF"}).json()

    client.post(
        f"/api/v1/workflows/{wf['id']}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "step1",
            "step_type": "MCQ",
            "title": "Step 1",
            "config": {
                "options": [{"value": "yes", "label": "Yes"}, {"value": "no", "label": "No"}],
                "conditions": [
                    {"when": {"step_key": "step1", "operator": "equals", "value": "yes"}, "next_step": "non_existent_target"}
                ],
            },
        },
    )

    pub_res = client.post(f"/api/v1/workflows/{wf['id']}/publish", headers={"Authorization": auth})
    assert pub_res.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT
    assert "unknown next_step" in pub_res.json()["detail"]


def test_publish_valid_workflow_and_archive(client: TestClient):
    """Test publishing a valid workflow transitions to ACTIVE, and archive transitions to ARCHIVED."""
    _, auth = get_auth_merchant(client, "wf_pub_valid@test.com")
    wf = client.post("/api/v1/workflows", headers={"Authorization": auth}, json={"name": "Valid Return WF"}).json()
    wf_id = wf["id"]

    # Step 1: MCQ branching to step2
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "step1",
            "step_type": "MCQ",
            "title": "Choose path",
            "config": {
                "options": [{"value": "detail", "label": "Provide detail"}, {"value": "skip", "label": "Skip"}],
                "conditions": [
                    {"when": {"step_key": "step1", "operator": "equals", "value": "detail"}, "next_step": "step2"}
                ],
                "default_next_step": "step2",
            },
        },
    )

    # Step 2: TEXT
    client.post(
        f"/api/v1/workflows/{wf_id}/steps",
        headers={"Authorization": auth},
        json={
            "step_key": "step2",
            "step_type": "TEXT",
            "title": "Detail Description",
            "config": {"min_length": 5, "max_length": 500},
        },
    )

    # Publish
    pub_res = client.post(f"/api/v1/workflows/{wf_id}/publish", headers={"Authorization": auth})
    assert pub_res.status_code == status.HTTP_200_OK
    pub_data = pub_res.json()
    assert pub_data["status"] == WorkflowStatus.ACTIVE.value
    assert pub_data["is_active"] is True

    # Archive
    arch_res = client.post(f"/api/v1/workflows/{wf_id}/archive", headers={"Authorization": auth})
    assert arch_res.status_code == status.HTTP_200_OK
    arch_data = arch_res.json()
    assert arch_data["status"] == WorkflowStatus.ARCHIVED.value
    assert arch_data["is_active"] is False

    # Attempting to re-publish archived workflow is rejected
    repub_res = client.post(f"/api/v1/workflows/{wf_id}/publish", headers={"Authorization": auth})
    assert repub_res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Archived workflows cannot be republished" in repub_res.json()["detail"]


# ===========================================================================
# Merchant Isolation & Security Tests
# ===========================================================================

def test_merchant_isolation_workflow_and_steps(client: TestClient):
    """Test Merchant A cannot access, modify, reorder, publish, or delete Merchant B's workflows or steps."""
    _, auth_a = get_auth_merchant(client, "iso_wf_a@test.com")
    _, auth_b = get_auth_merchant(client, "iso_wf_b@test.com")

    # Merchant A creates workflow and step
    wf_a = client.post("/api/v1/workflows", headers={"Authorization": auth_a}, json={"name": "Merchant A WF"}).json()
    step_a = client.post(
        f"/api/v1/workflows/{wf_a['id']}/steps",
        headers={"Authorization": auth_a},
        json={"step_key": "step_a1", "step_type": "ORDER", "title": "A Order"},
    ).json()

    # Merchant B attempts:
    # 1. Get workflow -> 404
    assert client.get(f"/api/v1/workflows/{wf_a['id']}", headers={"Authorization": auth_b}).status_code == status.HTTP_404_NOT_FOUND

    # 2. Update workflow -> 404
    assert client.put(f"/api/v1/workflows/{wf_a['id']}", headers={"Authorization": auth_b}, json={"name": "Hacked"}).status_code == status.HTTP_404_NOT_FOUND

    # 3. Publish workflow -> 404
    assert client.post(f"/api/v1/workflows/{wf_a['id']}/publish", headers={"Authorization": auth_b}).status_code == status.HTTP_404_NOT_FOUND

    # 4. Archive workflow -> 404
    assert client.post(f"/api/v1/workflows/{wf_a['id']}/archive", headers={"Authorization": auth_b}).status_code == status.HTTP_404_NOT_FOUND

    # 5. Delete workflow -> 404
    assert client.delete(f"/api/v1/workflows/{wf_a['id']}", headers={"Authorization": auth_b}).status_code == status.HTTP_404_NOT_FOUND

    # 6. List steps -> 404
    assert client.get(f"/api/v1/workflows/{wf_a['id']}/steps", headers={"Authorization": auth_b}).status_code == status.HTTP_404_NOT_FOUND

    # 7. Get step -> 404
    assert client.get(f"/api/v1/workflows/{wf_a['id']}/steps/{step_a['id']}", headers={"Authorization": auth_b}).status_code == status.HTTP_404_NOT_FOUND

    # 8. Update step -> 404
    assert client.put(f"/api/v1/workflows/{wf_a['id']}/steps/{step_a['id']}", headers={"Authorization": auth_b}, json={"title": "Hacked Step"}).status_code == status.HTTP_404_NOT_FOUND

    # 9. Delete step -> 404
    assert client.delete(f"/api/v1/workflows/{wf_a['id']}/steps/{step_a['id']}", headers={"Authorization": auth_b}).status_code == status.HTTP_404_NOT_FOUND

    # 10. Reorder steps -> 404
    assert client.put(f"/api/v1/workflows/{wf_a['id']}/steps/reorder", headers={"Authorization": auth_b}, json={"step_ids": [step_a["id"]]}).status_code == status.HTTP_404_NOT_FOUND
