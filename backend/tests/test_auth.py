from datetime import timedelta
import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.merchant import Merchant
from app.core.security import create_access_token


def test_register_merchant_success(client: TestClient, db_session: Session):
    """Test successful merchant registration and ensure password is never leaked."""
    payload = {
        "business_name": "Acme Retailers",
        "email": "owner@acme.com",
        "phone": "+1-555-0199",
        "password": "SecurePassword123!",
    }
    response = client.post("/api/v1/auth/register", json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    assert data["business_name"] == "Acme Retailers"
    assert data["email"] == "owner@acme.com"
    assert data["phone"] == "+1-555-0199"
    assert data["is_active"] is True
    assert "id" in data
    assert "created_at" in data

    # Security check: password and password_hash must NEVER appear in response
    assert "password" not in data
    assert "password_hash" not in data

    # Database check: verify password is saved as hash and not plaintext
    merchant = db_session.execute(
        select(Merchant).where(Merchant.email == "owner@acme.com")
    ).scalar_one_or_none()
    assert merchant is not None
    assert merchant.password_hash != "SecurePassword123!"
    assert merchant.password_hash.startswith("$argon2")


def test_register_duplicate_email_fails(client: TestClient):
    """Test duplicate email registration returns HTTP 409 Conflict."""
    payload = {
        "business_name": "First Store",
        "email": "duplicate@test.com",
        "password": "Password123!",
    }
    res1 = client.post("/api/v1/auth/register", json=payload)
    assert res1.status_code == status.HTTP_201_CREATED

    res2 = client.post("/api/v1/auth/register", json=payload)
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in res2.json()["detail"]


def test_email_normalization_on_register_and_login(client: TestClient):
    """Test that email normalization handles mixed-case emails consistently."""
    register_payload = {
        "business_name": "Mixed Case Store",
        "email": "User.Name+Tag@Example.COM",
        "password": "Password123!",
    }
    reg_res = client.post("/api/v1/auth/register", json=register_payload)
    assert reg_res.status_code == status.HTTP_201_CREATED
    assert reg_res.json()["email"] == "user.name+tag@example.com"

    # Login with all lowercase
    login_payload = {
        "email": "user.name+tag@example.com",
        "password": "Password123!",
    }
    login_res = client.post("/api/v1/auth/login", json=login_payload)
    assert login_res.status_code == status.HTTP_200_OK

    # Login with uppercase
    login_upper = {
        "email": "USER.NAME+TAG@EXAMPLE.COM",
        "password": "Password123!",
    }
    login_upper_res = client.post("/api/v1/auth/login", json=login_upper)
    assert login_upper_res.status_code == status.HTTP_200_OK


def test_login_success(client: TestClient):
    """Test valid credentials return Bearer access token."""
    client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Login Test",
            "email": "login@test.com",
            "password": "ValidPassword123!",
        },
    )

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "login@test.com", "password": "ValidPassword123!"},
    )
    assert login_res.status_code == status.HTTP_200_OK
    data = login_res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert len(data["access_token"]) > 20


def test_login_invalid_password_fails_generically(client: TestClient):
    """Test invalid password returns generic 401 without revealing specifics."""
    client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Pass Fail Test",
            "email": "passfail@test.com",
            "password": "CorrectPassword123!",
        },
    )

    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "passfail@test.com", "password": "WrongPassword!"},
    )
    assert login_res.status_code == status.HTTP_401_UNAUTHORIZED
    assert login_res.json()["detail"] == "Invalid email or password"


def test_login_unknown_email_fails_generically(client: TestClient):
    """Test unknown email returns generic 401 without revealing account existence."""
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "nonexistent@test.com", "password": "AnyPassword123!"},
    )
    assert login_res.status_code == status.HTTP_401_UNAUTHORIZED
    assert login_res.json()["detail"] == "Invalid email or password"


def test_get_current_merchant_me(client: TestClient):
    """Test GET /api/v1/auth/me returns merchant profile when authenticated."""
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Profile Merchant",
            "email": "me@merchant.com",
            "phone": "123456",
            "password": "Password123!",
        },
    )
    merchant_id = reg.json()["id"]

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "me@merchant.com", "password": "Password123!"},
    )
    token = login.json()["access_token"]

    # Request /auth/me with valid Bearer token
    me_res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == status.HTTP_200_OK
    me_data = me_res.json()
    assert me_data["id"] == merchant_id
    assert me_data["email"] == "me@merchant.com"
    assert me_data["business_name"] == "Profile Merchant"
    assert "password_hash" not in me_data


def test_auth_me_unauthenticated_failures(client: TestClient):
    """Test /auth/me fails when missing token or with invalid token."""
    # Missing token
    res_missing = client.get("/api/v1/auth/me")
    assert res_missing.status_code == status.HTTP_401_UNAUTHORIZED

    # Invalid / forged token
    res_invalid = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer invalid.token.payload"},
    )
    assert res_invalid.status_code == status.HTTP_401_UNAUTHORIZED


def test_auth_me_expired_token_fails(client: TestClient):
    """Test /auth/me fails when token is expired."""
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Expiry Test",
            "email": "expiry@merchant.com",
            "password": "Password123!",
        },
    )
    merchant_id = reg.json()["id"]

    # Create expired token (expired 10 minutes ago)
    expired_token = create_access_token(
        subject=merchant_id,
        expires_delta=timedelta(minutes=-10),
    )

    res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_inactive_merchant_cannot_login_or_access_protected(client: TestClient, db_session: Session):
    """Test that deactivated merchants cannot login or use protected routes."""
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Inactive Merchant",
            "email": "inactive@test.com",
            "password": "Password123!",
        },
    )
    merchant_id = reg.json()["id"]

    # Issue token before deactivation
    token = create_access_token(subject=merchant_id)

    # Deactivate merchant in database
    merchant = db_session.execute(
        select(Merchant).where(Merchant.id == merchant_id)
    ).scalar_one()
    merchant.is_active = False
    db_session.commit()

    # Attempt login -> HTTP 403 Forbidden
    login_res = client.post(
        "/api/v1/auth/login",
        json={"email": "inactive@test.com", "password": "Password123!"},
    )
    assert login_res.status_code == status.HTTP_403_FORBIDDEN
    assert "inactive" in login_res.json()["detail"].lower()

    # Attempt /auth/me with existing token -> HTTP 403 Forbidden
    me_res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == status.HTTP_403_FORBIDDEN


def test_change_password_workflow(client: TestClient):
    """Test changing password and verify old password stops working while new password works."""
    client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Password Change Store",
            "email": "pwchange@test.com",
            "password": "OriginalPassword1!",
        },
    )

    login = client.post(
        "/api/v1/auth/login",
        json={"email": "pwchange@test.com", "password": "OriginalPassword1!"},
    )
    token = login.json()["access_token"]

    # Attempt password change with wrong current password -> HTTP 400
    wrong_attempt = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "WrongCurrentPassword!",
            "new_password": "BrandNewPassword2!",
        },
    )
    assert wrong_attempt.status_code == status.HTTP_400_BAD_REQUEST

    # Perform valid password change
    valid_change = client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "current_password": "OriginalPassword1!",
            "new_password": "BrandNewPassword2!",
        },
    )
    assert valid_change.status_code == status.HTTP_200_OK

    # Old password must now fail
    old_login = client.post(
        "/api/v1/auth/login",
        json={"email": "pwchange@test.com", "password": "OriginalPassword1!"},
    )
    assert old_login.status_code == status.HTTP_401_UNAUTHORIZED

    # New password must succeed
    new_login = client.post(
        "/api/v1/auth/login",
        json={"email": "pwchange@test.com", "password": "BrandNewPassword2!"},
    )
    assert new_login.status_code == status.HTTP_200_OK


def test_security_jwt_secret_and_tampering(client: TestClient):
    """Explicitly verify JWT secret is from settings and tokens signed with wrong key are rejected."""
    from app.core.config import settings
    import jwt

    assert settings.JWT_SECRET_KEY is not None
    assert len(settings.JWT_SECRET_KEY) >= 32

    # Register merchant
    reg = client.post(
        "/api/v1/auth/register",
        json={
            "business_name": "Tamper Test Store",
            "email": "tamper@test.com",
            "password": "Password123!",
        },
    )
    merchant_id = reg.json()["id"]

    # Generate token signed with an unauthorized external secret key
    attacker_token = jwt.encode(
        {"sub": merchant_id},
        "attacker-compromised-secret-key-32-chars-long!",
        algorithm="HS256",
    )

    # Protected endpoint must reject attacker token with 401
    tampered_res = client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {attacker_token}"},
    )
    assert tampered_res.status_code == status.HTTP_401_UNAUTHORIZED

