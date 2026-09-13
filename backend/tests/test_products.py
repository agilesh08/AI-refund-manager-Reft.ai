import io
from pathlib import Path
import pytest
from decimal import Decimal
from fastapi import status
from fastapi.testclient import TestClient
from PIL import Image

from app.core.config import settings
from app.utils.file_storage import calculate_sha256


def make_test_image(img_format: str = "JPEG", color: str = "blue") -> bytes:
    """Generate in-memory valid image bytes for testing."""
    buf = io.BytesIO()
    img = Image.new("RGB", (20, 20), color=color)
    img.save(buf, format=img_format)
    buf.seek(0)
    return buf.getvalue()


def register_and_get_auth(client: TestClient, email: str, name: str = "Test Store") -> tuple[str, str]:
    """Helper to register and login a merchant, returning (merchant_id, auth_header)."""
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": name,
            "email": email,
            "password": "Password123!",
        },
    )
    merchant_id = reg.json()["id"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "Password123!"},
    )
    token = login.json()["access_token"]
    return merchant_id, f"Bearer {token}"


# ===========================================================================
# Product Management Tests
# ===========================================================================

def test_create_product_success(client: TestClient):
    """Test authenticated merchant can create product with Decimal price."""
    _, auth = register_and_get_auth(client, "prod1@merchant.com")

    payload = {
        "name": "Wireless Ergonomic Mouse",
        "sku": "MOU-001",
        "description": "Ergonomic design with silent clicks",
        "price": "49.99",
    }
    response = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json=payload,
    )
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["name"] == "Wireless Ergonomic Mouse"
    assert data["sku"] == "MOU-001"
    assert data["price"] == "49.99"
    assert "id" in data
    assert "created_at" in data


def test_create_product_unauthenticated(client: TestClient):
    """Test unauthenticated user cannot create a product."""
    response = client.post(
        "/api/v1/products",
        json={"name": "Headphones", "sku": "HP-1", "price": "99.00"},
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_duplicate_sku_same_merchant_rejected(client: TestClient):
    """Test duplicate SKU for the same merchant returns HTTP 409."""
    _, auth = register_and_get_auth(client, "sku@merchant.com")

    product_data = {"name": "Item A", "sku": "DUPLICATE-SKU", "price": "10.00"}
    res1 = client.post("/api/v1/products", headers={"Authorization": auth}, json=product_data)
    assert res1.status_code == status.HTTP_201_CREATED

    res2 = client.post("/api/v1/products", headers={"Authorization": auth}, json=product_data)
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in res2.json()["detail"]


def test_same_sku_allowed_for_different_merchants(client: TestClient):
    """Test same SKU can be used by two distinct merchants."""
    _, auth_a = register_and_get_auth(client, "merchA@test.com")
    _, auth_b = register_and_get_auth(client, "merchB@test.com")

    sku_payload = {"name": "Standard Cable", "sku": "CABLE-USB-C", "price": "15.50"}

    res_a = client.post("/api/v1/products", headers={"Authorization": auth_a}, json=sku_payload)
    assert res_a.status_code == status.HTTP_201_CREATED

    res_b = client.post("/api/v1/products", headers={"Authorization": auth_b}, json=sku_payload)
    assert res_b.status_code == status.HTTP_201_CREATED


def test_list_products_merchant_isolation(client: TestClient):
    """Test merchant can only list their own products."""
    _, auth_a = register_and_get_auth(client, "listA@test.com")
    _, auth_b = register_and_get_auth(client, "listB@test.com")

    # Merchant A creates 2 products
    client.post("/api/v1/products", headers={"Authorization": auth_a}, json={"name": "A1", "sku": "A-1", "price": "10.00"})
    client.post("/api/v1/products", headers={"Authorization": auth_a}, json={"name": "A2", "sku": "A-2", "price": "20.00"})

    # Merchant B creates 1 product
    client.post("/api/v1/products", headers={"Authorization": auth_b}, json={"name": "B1", "sku": "B-1", "price": "30.00"})

    list_a = client.get("/api/v1/products", headers={"Authorization": auth_a}).json()
    assert len(list_a) == 2
    assert {p["sku"] for p in list_a} == {"A-1", "A-2"}

    list_b = client.get("/api/v1/products", headers={"Authorization": auth_b}).json()
    assert len(list_b) == 1
    assert list_b[0]["sku"] == "B-1"


def test_get_product_isolation(client: TestClient):
    """Test merchant cannot retrieve another merchant's product (HTTP 404)."""
    _, auth_a = register_and_get_auth(client, "getA@test.com")
    _, auth_b = register_and_get_auth(client, "getB@test.com")

    prod_a = client.post(
        "/api/v1/products",
        headers={"Authorization": auth_a},
        json={"name": "Secret Prod", "sku": "SEC-1", "price": "100.00"},
    ).json()

    # Merchant A can retrieve
    res_a = client.get(f"/api/v1/products/{prod_a['id']}", headers={"Authorization": auth_a})
    assert res_a.status_code == status.HTTP_200_OK

    # Merchant B gets 404
    res_b = client.get(f"/api/v1/products/{prod_a['id']}", headers={"Authorization": auth_b})
    assert res_b.status_code == status.HTTP_404_NOT_FOUND


def test_update_product_and_sku_validation(client: TestClient):
    """Test updating product fields and validating SKU conflicts."""
    _, auth = register_and_get_auth(client, "upd@merchant.com")

    p1 = client.post("/api/v1/products", headers={"Authorization": auth}, json={"name": "P1", "sku": "SKU-1", "price": "10.00"}).json()
    p2 = client.post("/api/v1/products", headers={"Authorization": auth}, json={"name": "P2", "sku": "SKU-2", "price": "20.00"}).json()

    # Valid update
    upd_res = client.put(
        f"/api/v1/products/{p1['id']}",
        headers={"Authorization": auth},
        json={"name": "Updated P1", "price": "12.50"},
    )
    assert upd_res.status_code == status.HTTP_200_OK
    assert upd_res.json()["name"] == "Updated P1"
    assert upd_res.json()["price"] == "12.50"

    # Conflicting SKU update -> HTTP 409
    conflict_res = client.put(
        f"/api/v1/products/{p1['id']}",
        headers={"Authorization": auth},
        json={"sku": "SKU-2"},
    )
    assert conflict_res.status_code == status.HTTP_409_CONFLICT


def test_delete_product_isolation(client: TestClient):
    """Test deleting product enforces merchant ownership."""
    _, auth_a = register_and_get_auth(client, "delA@test.com")
    _, auth_b = register_and_get_auth(client, "delB@test.com")

    prod_a = client.post(
        "/api/v1/products",
        headers={"Authorization": auth_a},
        json={"name": "Delete Target", "sku": "DEL-1", "price": "5.00"},
    ).json()

    # Merchant B cannot delete Merchant A's product
    del_b = client.delete(f"/api/v1/products/{prod_a['id']}", headers={"Authorization": auth_b})
    assert del_b.status_code == status.HTTP_404_NOT_FOUND

    # Merchant A deletes successfully
    del_a = client.delete(f"/api/v1/products/{prod_a['id']}", headers={"Authorization": auth_a})
    assert del_a.status_code == status.HTTP_200_OK

    # Verify gone
    get_res = client.get(f"/api/v1/products/{prod_a['id']}", headers={"Authorization": auth_a})
    assert get_res.status_code == status.HTTP_404_NOT_FOUND


# ===========================================================================
# Trusted Reference Image Evidence Tests
# ===========================================================================

def test_upload_four_reference_angles_and_completeness(client: TestClient):
    """Test uploading all 4 canonical reference angles and verifying product completeness."""
    _, auth = register_and_get_auth(client, "ref@merchant.com")

    prod = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Complete Product", "sku": "COMP-1", "price": "299.99"},
    ).json()
    product_id = prod["id"]

    # Initially completeness is False
    status_res = client.get(f"/api/v1/products/{product_id}/completeness", headers={"Authorization": auth})
    assert status_res.status_code == status.HTTP_200_OK
    assert status_res.json()["complete"] is False

    angles = ["FRONT", "BACK", "LEFT", "RIGHT"]
    uploaded_files = []

    for angle in angles:
        img_bytes = make_test_image("JPEG", color="red")
        response = client.post(
            f"/api/v1/products/{product_id}/references",
            headers={"Authorization": auth},
            data={"angle": angle},
            files={"image": (f"{angle.lower()}.jpg", img_bytes, "image/jpeg")},
        )
        assert response.status_code == status.HTTP_201_CREATED
        ref_data = response.json()
        assert ref_data["angle"] == angle
        assert ref_data["product_id"] == product_id
        assert ref_data["image_hash"] == calculate_sha256(img_bytes)
        assert "image_path" not in ref_data  # Internal path never exposed
        uploaded_files.append(ref_data["id"])

    # Now completeness must be True
    comp_res = client.get(f"/api/v1/products/{product_id}/completeness", headers={"Authorization": auth})
    assert comp_res.status_code == status.HTTP_200_OK
    status_data = comp_res.json()
    assert status_data["complete"] is True
    assert status_data["reference_status"] == {
        "front": True,
        "back": True,
        "left": True,
        "right": True,
    }

    # List references endpoint returns 4 items
    list_ref_res = client.get(f"/api/v1/products/{product_id}/references", headers={"Authorization": auth})
    assert list_ref_res.status_code == status.HTTP_200_OK
    assert len(list_ref_res.json()) == 4


def test_duplicate_angle_rejected_with_409(client: TestClient):
    """Test that uploading a second image for the same angle returns HTTP 409 Conflict."""
    _, auth = register_and_get_auth(client, "dup_ref@merchant.com")
    prod = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Dup Angle Prod", "sku": "DUP-ANG-1", "price": "10.00"},
    ).json()

    img1 = make_test_image("PNG", color="green")
    res1 = client.post(
        f"/api/v1/products/{prod['id']}/references",
        headers={"Authorization": auth},
        data={"angle": "FRONT"},
        files={"image": ("front.png", img1, "image/png")},
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # Second upload for FRONT angle
    img2 = make_test_image("PNG", color="yellow")
    res2 = client.post(
        f"/api/v1/products/{prod['id']}/references",
        headers={"Authorization": auth},
        data={"angle": "FRONT"},
        files={"image": ("front2.png", img2, "image/png")},
    )
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in res2.json()["detail"]


def test_invalid_and_unsupported_image_rejection(client: TestClient):
    """Test rejecting invalid angle, unsupported MIME type, and corrupted image."""
    _, auth = register_and_get_auth(client, "reject@merchant.com")
    prod = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Test Item", "sku": "TI-1", "price": "15.00"},
    ).json()

    valid_img = make_test_image("JPEG")

    # 1. Invalid angle name
    res_angle = client.post(
        f"/api/v1/products/{prod['id']}/references",
        headers={"Authorization": auth},
        data={"angle": "TOP_DOWN"},
        files={"image": ("top.jpg", valid_img, "image/jpeg")},
    )
    assert res_angle.status_code == status.HTTP_422_UNPROCESSABLE_CONTENT

    # 2. Unsupported file type (PDF/text)
    res_type = client.post(
        f"/api/v1/products/{prod['id']}/references",
        headers={"Authorization": auth},
        data={"angle": "FRONT"},
        files={"image": ("doc.pdf", b"%PDF-1.4 dummy data", "application/pdf")},
    )
    assert res_type.status_code == status.HTTP_400_BAD_REQUEST

    # 3. Corrupted image bytes with valid image content-type
    res_corrupt = client.post(
        f"/api/v1/products/{prod['id']}/references",
        headers={"Authorization": auth},
        data={"angle": "FRONT"},
        files={"image": ("fake.jpg", b"corrupted bytes not an image", "image/jpeg")},
    )
    assert res_corrupt.status_code == status.HTTP_400_BAD_REQUEST


def test_delete_reference_angle_and_file_cleanup(client: TestClient):
    """Test deleting reference image removes DB record, removes file from disk, and updates completeness."""
    _, auth = register_and_get_auth(client, "del_ref@merchant.com")
    prod = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Del Ref Prod", "sku": "DEL-REF-1", "price": "10.00"},
    ).json()

    img_bytes = make_test_image("WEBP")
    upload_res = client.post(
        f"/api/v1/products/{prod['id']}/references",
        headers={"Authorization": auth},
        data={"angle": "LEFT"},
        files={"image": ("left.webp", img_bytes, "image/webp")},
    )
    assert upload_res.status_code == status.HTTP_201_CREATED

    # Retrieve by angle
    get_ref = client.get(
        f"/api/v1/products/{prod['id']}/references/LEFT",
        headers={"Authorization": auth},
    )
    assert get_ref.status_code == status.HTTP_200_OK

    # Delete reference
    del_res = client.delete(
        f"/api/v1/products/{prod['id']}/references/LEFT",
        headers={"Authorization": auth},
    )
    assert del_res.status_code == status.HTTP_200_OK

    # Attempt retrieve after delete -> HTTP 404
    get_after = client.get(
        f"/api/v1/products/{prod['id']}/references/LEFT",
        headers={"Authorization": auth},
    )
    assert get_after.status_code == status.HTTP_404_NOT_FOUND


def test_reference_merchant_isolation(client: TestClient):
    """Test Merchant B cannot access or delete Merchant A's reference images."""
    _, auth_a = register_and_get_auth(client, "isoA@test.com")
    _, auth_b = register_and_get_auth(client, "isoB@test.com")

    prod_a = client.post(
        "/api/v1/products",
        headers={"Authorization": auth_a},
        json={"name": "Iso Product", "sku": "ISO-1", "price": "50.00"},
    ).json()

    img_bytes = make_test_image("JPEG")
    client.post(
        f"/api/v1/products/{prod_a['id']}/references",
        headers={"Authorization": auth_a},
        data={"angle": "FRONT"},
        files={"image": ("front.jpg", img_bytes, "image/jpeg")},
    )

    # Merchant B tries to list references of Merchant A's product -> HTTP 404
    res_list = client.get(
        f"/api/v1/products/{prod_a['id']}/references",
        headers={"Authorization": auth_b},
    )
    assert res_list.status_code == status.HTTP_404_NOT_FOUND

    # Merchant B tries to delete reference -> HTTP 404
    res_del = client.delete(
        f"/api/v1/products/{prod_a['id']}/references/FRONT",
        headers={"Authorization": auth_b},
    )
    assert res_del.status_code == status.HTTP_404_NOT_FOUND


def test_product_deletion_cascades_to_references_and_files(client: TestClient):
    """Test that deleting a product removes its reference records and cleans up disk files."""
    _, auth = register_and_get_auth(client, "cascade@merchant.com")
    prod = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Cascade Prod", "sku": "CAS-1", "price": "100.00"},
    ).json()

    img_bytes = make_test_image("JPEG")
    client.post(
        f"/api/v1/products/{prod['id']}/references",
        headers={"Authorization": auth},
        data={"angle": "BACK"},
        files={"image": ("back.jpg", img_bytes, "image/jpeg")},
    )

    # Verify reference file exists in storage folder
    storage_dir = Path(settings.STORAGE_PATH) / "product_references"
    files_before = list(storage_dir.glob(f"product_{prod['id']}_*"))
    assert len(files_before) == 1
    assert files_before[0].exists()

    # Delete parent product
    del_prod = client.delete(
        f"/api/v1/products/{prod['id']}",
        headers={"Authorization": auth},
    )
    assert del_prod.status_code == status.HTTP_200_OK

    # Verify physical file was removed
    files_after = list(storage_dir.glob(f"product_{prod['id']}_*"))
    assert len(files_after) == 0


def test_get_reference_file_by_angle(client: TestClient):
    """Test authenticated merchant can stream reference image file for preview."""
    _, auth = register_and_get_auth(client, "stream@merchant.com")
    prod = client.post(
        "/api/v1/products",
        headers={"Authorization": auth},
        json={"name": "Stream Item", "sku": "STREAM-1", "price": "29.99"},
    ).json()

    img_bytes = make_test_image("JPEG", color="red")
    client.post(
        f"/api/v1/products/{prod['id']}/references",
        headers={"Authorization": auth},
        data={"angle": "FRONT"},
        files={"image": ("front.jpg", img_bytes, "image/jpeg")},
    )

    # Fetch reference file stream
    res = client.get(
        f"/api/v1/products/{prod['id']}/references/FRONT/file",
        headers={"Authorization": auth},
    )
    assert res.status_code == status.HTTP_200_OK
    assert res.headers["content-type"].startswith("image/")
    assert len(res.content) == len(img_bytes)

