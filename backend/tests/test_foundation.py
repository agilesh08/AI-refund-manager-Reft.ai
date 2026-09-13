from pathlib import Path
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import SessionLocal, get_db
from app.main import app


def test_root_endpoint(client: TestClient):
    """Test GET / returns 200 and expected status payload."""
    response = client.get("/")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["message"] == "Refund Evidence Verification API"
    assert data["status"] == "running"


def test_health_endpoint(client: TestClient):
    """Test GET /health verifies database connectivity and returns 200."""
    response = client.get("/health")
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["status"] == "healthy"
    assert data["database"] == "connected"


def test_database_connection():
    """Test direct SQLite database connection and query execution."""
    db: Session = SessionLocal()
    try:
        result = db.execute(text("SELECT 1")).scalar()
        assert result == 1
    finally:
        db.close()


def test_storage_directories_exist():
    """Test that all required storage directories are created and writable."""
    base_storage = Path(settings.STORAGE_PATH)
    required_folders = ["product_references", "evidence", "reports"]

    for folder_name in required_folders:
        folder_path = base_storage / folder_name
        assert folder_path.exists(), f"Directory missing: {folder_path}"
        assert folder_path.is_dir(), f"Not a directory: {folder_path}"

        # Verify directory is writable
        test_file = folder_path / ".test_write"
        try:
            test_file.write_text("ok", encoding="utf-8")
            assert test_file.read_text(encoding="utf-8") == "ok"
        finally:
            if test_file.exists():
                test_file.unlink()


def test_health_failure_handling(client: TestClient):
    """Test GET /health returns 503 when the database fails."""
    class FailingDBSession:
        def execute(self, *args, **kwargs):
            raise RuntimeError("Database connection lost")

    def override_get_db_failing():
        yield FailingDBSession()

    app.dependency_overrides[get_db] = override_get_db_failing
    try:
        response = client.get("/health")
        assert response.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
        data = response.json()
        assert data["status"] == "unhealthy"
        assert data["database"] == "disconnected"
    finally:
        app.dependency_overrides.pop(get_db, None)
