"""Secure file storage, SHA-256 calculation, and image validation utilities."""
import hashlib
import io
import logging
from pathlib import Path
import uuid
from fastapi import HTTPException, UploadFile, status
from PIL import Image

from app.core.config import settings

logger = logging.getLogger(__name__)

# Permitted MIME types and extensions for reference evidence
ALLOWED_MIME_TYPES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}
ALLOWED_PIL_FORMATS = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "WEBP": ".webp",
}


def calculate_sha256(content: bytes) -> str:
    """Calculate the cryptographic SHA-256 hex digest for binary content."""
    return hashlib.sha256(content).hexdigest()


def generate_safe_filename(product_id: str, angle: str, extension: str) -> str:
    """Generate a safe, random, collision-free filename.
    
    Prevents path traversal by ignoring client-provided filenames.
    """
    clean_ext = extension.lstrip(".")
    unique_suffix = uuid.uuid4().hex[:10]
    return f"product_{product_id}_{angle.lower()}_{unique_suffix}.{clean_ext}"


async def validate_and_read_image(
    upload_file: UploadFile,
    max_size_mb: int = settings.MAX_IMAGE_SIZE_MB,
) -> tuple[bytes, str]:
    """Validate uploaded file type, size, and decode integrity using Pillow.
    
    Returns (file_bytes, normalized_extension).
    Raises HTTP 400 for corrupt or invalid formats, HTTP 413 for oversized payloads.
    """
    # 1. Validate MIME type
    content_type = (upload_file.content_type or "").lower()
    if content_type not in ALLOWED_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type '{content_type}'. Allowed types: JPEG, PNG, WEBP",
        )

    # 2. Read content and enforce size limit
    content = await upload_file.read()
    max_bytes = max_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Image size exceeds maximum allowed limit of {max_size_mb}MB",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    # 3. Decode and verify image data using Pillow
    try:
        with Image.open(io.BytesIO(content)) as img:
            img.verify()
            if img.format not in ALLOWED_PIL_FORMATS:
                raise ValueError(f"Unsupported format: {img.format}")
            normalized_ext = ALLOWED_PIL_FORMATS[img.format]
    except Exception as exc:
        logger.warning("Image verification failed for uploaded file: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file cannot be decoded as a valid image",
        )

    return content, normalized_ext


def save_reference_file(file_bytes: bytes, filename: str) -> str:
    """Write binary image data to the product references storage folder.
    
    Returns the relative storage path (e.g. 'product_references/filename.jpg').
    """
    dest_dir = Path(settings.STORAGE_PATH) / "product_references"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = dest_dir / filename
    dest_file.write_bytes(file_bytes)

    relative_path = f"product_references/{filename}"
    logger.info("Saved product reference image: %s", relative_path)
    return relative_path


def delete_reference_file(relative_path: str) -> bool:
    """Safely remove a reference image from disk.
    
    Returns True if removed, False if file did not exist.
    """
    target = Path(settings.STORAGE_PATH) / relative_path
    try:
        # Guard against path traversal when deleting
        base_storage = Path(settings.STORAGE_PATH).resolve()
        resolved_target = target.resolve()
        if not resolved_target.is_relative_to(base_storage):
            logger.error("Path traversal attempt in delete_reference_file: %s", relative_path)
            return False

        if target.exists() and target.is_file():
            target.unlink()
            logger.info("Deleted product reference file: %s", relative_path)
            return True
    except Exception as exc:
        logger.error("Failed to delete reference file %s: %s", relative_path, exc)

    return False


def get_reference_file_path(relative_path: str) -> Path:
    """Resolve and validate a product reference file path within the references folder.
    
    Guarantees against path traversal attacks.
    Raises HTTPException 404 if file does not exist, 400 if path escapes storage.
    """
    ref_dir = (Path(settings.STORAGE_PATH) / "product_references").resolve()
    target = (Path(settings.STORAGE_PATH) / relative_path).resolve()

    if not target.is_relative_to(ref_dir):
        logger.error("Path traversal attempt in get_reference_file_path: %s", relative_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reference file path",
        )

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Reference file not found on disk",
        )

    return target


# ---------------------------------------------------------------------------
# Customer Evidence Storage Utilities (Milestone 6)
# ---------------------------------------------------------------------------

ALLOWED_VIDEO_MIME_TYPES = {
    "video/mp4": ".mp4",
    "video/quicktime": ".mov",
    "video/webm": ".webm",
}
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".webm"}


async def validate_and_read_video(
    upload_file: UploadFile,
    max_size_mb: int = settings.MAX_VIDEO_SIZE_MB,
) -> tuple[bytes, str, str]:
    """Validate uploaded video type, extension, size, and non-emptiness.
    
    Returns (file_bytes, normalized_extension, mime_type).
    Raises HTTP 400 for unsupported format or empty file, HTTP 413 for oversized file.
    """
    content_type = (upload_file.content_type or "").lower()
    filename = upload_file.filename or ""
    ext = Path(filename).suffix.lower()

    if content_type not in ALLOWED_VIDEO_MIME_TYPES and ext not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported video type '{content_type}'. Allowed formats: MP4, MOV, WEBM",
        )

    if content_type in ALLOWED_VIDEO_MIME_TYPES:
        normalized_ext = ALLOWED_VIDEO_MIME_TYPES[content_type]
        mime = content_type
    else:
        normalized_ext = ext
        ext_to_mime = {".mp4": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm"}
        mime = ext_to_mime.get(ext, "video/mp4")

    content = await upload_file.read()
    max_bytes = max_size_mb * 1024 * 1024
    if len(content) > max_bytes:
        raise HTTPException(
            status_code=status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"Video size exceeds maximum allowed limit of {max_size_mb}MB",
        )

    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty",
        )

    return content, normalized_ext, mime


def generate_safe_evidence_filename(session_prefix: str, evidence_type: str, extension: str) -> str:
    """Generate a safe, random, collision-free filename for customer evidence.
    
    Prevents path traversal by completely ignoring client-provided filenames.
    """
    clean_ext = extension.lstrip(".")
    unique_suffix = uuid.uuid4().hex[:12]
    clean_prefix = "".join(c for c in session_prefix if c.isalnum() or c in "-_")
    return f"ev_{clean_prefix}_{evidence_type.lower()}_{unique_suffix}.{clean_ext}"


def save_evidence_file(file_bytes: bytes, filename: str) -> str:
    """Write binary evidence data to the evidence storage folder.
    
    Returns the relative storage path (e.g. 'evidence/filename.jpg').
    """
    dest_dir = Path(settings.STORAGE_PATH) / "evidence"
    dest_dir.mkdir(parents=True, exist_ok=True)

    dest_file = dest_dir / filename
    dest_file.write_bytes(file_bytes)

    relative_path = f"evidence/{filename}"
    logger.info("Saved customer evidence file: %s", relative_path)
    return relative_path


def get_evidence_file_path(relative_path: str) -> Path:
    """Resolve and validate an evidence file path within the evidence storage folder.
    
    Guarantees against path traversal attacks.
    Raises HTTPException 404 if file does not exist, 400 if path escapes storage.
    """
    evidence_dir = (Path(settings.STORAGE_PATH) / "evidence").resolve()
    target = (Path(settings.STORAGE_PATH) / relative_path).resolve()

    if not target.is_relative_to(evidence_dir):
        logger.error("Path traversal attempt in get_evidence_file_path: %s", relative_path)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid file path",
        )

    if not target.exists() or not target.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Evidence file not found on disk",
        )

    return target
