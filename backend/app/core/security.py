"""Security, password hashing, and cryptographic token utilities."""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional, Any
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash
import jwt

from app.core.config import settings

# Initialize Argon2 password hasher
_password_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2."""
    return _password_hasher.hash(password)


def verify_password(plain_password: str, password_hash: str) -> bool:
    """Verify a plaintext password against an Argon2 hash.
    
    Returns True if valid, False otherwise. Never raises mismatch exceptions.
    """
    try:
        return _password_hasher.verify(password_hash, plain_password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False


def create_access_token(subject: str, expires_delta: Optional[timedelta] = None) -> str:
    """Create a signed JWT access token containing the merchant ID in the 'sub' claim."""
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode = {
        "sub": str(subject),
        "iat": now,
        "exp": expire,
    }
    encoded_jwt = jwt.encode(
        to_encode,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict[str, Any]]:
    """Decode and validate a JWT access token.
    
    Returns the payload dictionary if valid, or None if expired or invalid.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        return payload
    except jwt.PyJWTError:
        return None


def generate_verification_token(nbytes: int = 32) -> str:
    """Generate a cryptographically secure random token for verification links/sessions."""
    return secrets.token_urlsafe(nbytes)


def hash_verification_token(token: str) -> str:
    """Calculate SHA-256 hash of raw customer verification token for secure database storage."""
    import hashlib
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()


def generate_verification_id() -> str:
    """Generate a human-readable verification ID (e.g. VR-2026-8F29A71C).
    
    Safe to display on merchant dashboards, customer screens, and audit reports.
    """
    year = datetime.now(timezone.utc).year
    random_hex = secrets.token_hex(4).upper()
    return f"VR-{year}-{random_hex}"


def generate_evidence_id() -> str:
    """Generate a human-readable evidence ID (e.g. EV-2026-8F29A71C).
    
    Safe to expose to customers and merchants in responses and URLs.
    """
    year = datetime.now(timezone.utc).year
    random_hex = secrets.token_hex(4).upper()
    return f"EV-{year}-{random_hex}"

