import pytest
from fastapi import status
from fastapi.testclient import TestClient


def test_merchant_profile_requires_auth(client: TestClient):
    """Test that merchant profile endpoints require Bearer authentication."""
    get_res = client.get("/api/v1/merchants/profile")
    assert get_res.status_code == status.HTTP_401_UNAUTHORIZED

    put_res = client.put("/api/v1/merchants/profile", json={"business_name": "New Name"})
    assert put_res.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_merchant_profile(client: TestClient):
    """Test retrieving authenticated merchant profile."""
    client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Tech Supplies Co",
            "email": "contact@techsupplies.com",
            "phone": "+1-800-555-0100",
            "password": "Password123!",
        },
    )

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "contact@techsupplies.com", "password": "Password123!"},
    )
    token = login.json()["access_token"]

    res = client.get(
        "/api/v1/merchants/profile",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == status.HTTP_200_OK
    data = res.json()
    assert data["business_name"] == "Tech Supplies Co"
    assert data["email"] == "contact@techsupplies.com"
    assert data["phone"] == "+1-800-555-0100"
    assert "password_hash" not in data


def test_update_merchant_profile(client: TestClient):
    """Test updating business name and phone on merchant profile."""
    client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Old Business Name",
            "email": "update@merchant.com",
            "phone": "111-222-3333",
            "password": "Password123!",
        },
    )

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "update@merchant.com", "password": "Password123!"},
    )
    token = login.json()["access_token"]

    update_payload = {
        "business_name": "Refreshed Business Name",
        "phone": "+1-999-888-7777",
    }
    put_res = client.put(
        "/api/v1/merchants/profile",
        headers={"Authorization": f"Bearer {token}"},
        json=update_payload,
    )
    assert put_res.status_code == status.HTTP_200_OK
    data = put_res.json()
    assert data["business_name"] == "Refreshed Business Name"
    assert data["phone"] == "+1-999-888-7777"
    assert data["email"] == "update@merchant.com"


def test_update_profile_ignores_sensitive_fields(client: TestClient):
    """Ensure immutable fields like id, email, password_hash cannot be overridden via PUT."""
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Original Name",
            "email": "original@domain.com",
            "password": "Password123!",
        },
    )
    original_id = reg.json()["id"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "original@domain.com", "password": "Password123!"},
    )
    token = login.json()["access_token"]

    # Attempt to inject email, id, or password_hash changes
    malicious_payload = {
        "business_name": "Allowed Name Change",
        "id": "hacked-id-123",
        "email": "hacked@domain.com",
        "password_hash": "plaintext_fake_hash",
    }
    put_res = client.put(
        "/api/v1/merchants/profile",
        headers={"Authorization": f"Bearer {token}"},
        json=malicious_payload,
    )
    assert put_res.status_code == status.HTTP_200_OK
    data = put_res.json()
    assert data["id"] == original_id  # Untouched
    assert data["email"] == "original@domain.com"  # Untouched
    assert "password_hash" not in data


def test_merchant_isolation(client: TestClient):
    """Ensure Merchant A's token cannot access or modify Merchant B's profile."""
    # Register Merchant A
    client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Merchant Alpha",
            "email": "alpha@test.com",
            "password": "Password123!",
        },
    )
    login_a = client.post(
        "/api/v1/auth/login",
        json={"email": "alpha@test.com", "password": "Password123!"},
    )
    token_a = login_a.json()["access_token"]

    # Register Merchant B
    client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Merchant Beta",
            "email": "beta@test.com",
            "password": "Password123!",
        },
    )
    login_b = client.post(
        "/api/v1/auth/login",
        json={"email": "beta@test.com", "password": "Password123!"},
    )
    token_b = login_b.json()["access_token"]

    # Merchant A reads profile
    profile_a = client.get(
        "/api/v1/merchants/profile",
        headers={"Authorization": f"Bearer {token_a}"},
    ).json()
    assert profile_a["email"] == "alpha@test.com"

    # Merchant B reads profile
    profile_b = client.get(
        "/api/v1/merchants/profile",
        headers={"Authorization": f"Bearer {token_b}"},
    ).json()
    assert profile_b["email"] == "beta@test.com"

    # Profile IDs must differ
    assert profile_a["id"] != profile_b["id"]
