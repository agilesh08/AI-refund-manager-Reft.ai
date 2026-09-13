import json
from pathlib import Path
from typing import List, Optional, Union
from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Base application settings
    PROJECT_NAME: str = "Refund Evidence Verification API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"
    DEBUG: bool = False

    # Database configuration (SQLite default for prototype)
    DATABASE_URL: str = "sqlite:///./data/refund_verification.db"

    # Storage paths & limits
    STORAGE_PATH: str = "./storage"
    MAX_IMAGE_SIZE_MB: int = 10
    MAX_VIDEO_SIZE_MB: int = 50
    MAX_TEXT_EVIDENCE_LENGTH: int = 5000

    # CORS configuration
    CORS_ORIGINS: Union[List[str], str] = [
        "http://localhost",
        "http://localhost:3000",
        "http://localhost:8000",
        "http://localhost:8080",
    ]

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("[") and v.endswith("]"):
                try:
                    return json.loads(v)
                except Exception:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        elif isinstance(v, (list, tuple)):
            return [str(i).strip() for i in v]
        return []

    # Authentication & Security
    JWT_SECRET_KEY: str = "dev-secret-key-change-in-production-min-32-chars-long!"
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # Verification Sessions & Public Access (Milestone 5)
    VERIFICATION_SESSION_EXPIRY_HOURS: int = 72
    CUSTOMER_VERIFICATION_BASE_URL: str = "http://localhost:8000/v"

    # AI Configuration (Milestones 7, 8, 9)
    GEMINI_API_KEY: Optional[str] = None
    GEMINI_VISION_MODEL: str = "gemini-2.5-flash"
    GEMINI_VISION_PROMPT_VERSION: str = "v1"

    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_MODEL_NAME: str = "llama3.2:1b"
    OLLAMA_TIMEOUT_SECONDS: int = 90
    LLAMA_REASONING_PROMPT_VERSION: str = "v1"

    # Adaptive Evidence Follow-Up (Milestone 9)
    MAX_ADAPTIVE_FOLLOWUPS: int = 3

    # Evidence Fusion Engine (Milestone 11)
    LOCATION_MATCH_RADIUS_METERS: float = 500.0
    PAYMENT_ORDER_AMOUNT_TOLERANCE: float = 0.01
    SIGNAL_SOURCE_WEIGHT_INTEGRATION: float = 1.0
    SIGNAL_SOURCE_WEIGHT_SYSTEM_GENERATED: float = 0.95
    SIGNAL_SOURCE_WEIGHT_MERCHANT_PROVIDED: float = 0.90
    SIGNAL_SOURCE_WEIGHT_CUSTOMER_PROVIDED: float = 0.75
    FUSION_VERSION: str = "v1"
    LLAMA_FUSION_PROMPT_VERSION: str = "v1"

    @property
    def OLLAMA_MODEL(self) -> str:
        """Backwards compatibility alias for OLLAMA_MODEL_NAME."""
        return self.OLLAMA_MODEL_NAME

    _backend_dir = Path(__file__).resolve().parent.parent.parent
    _env_path = _backend_dir / ".env"

    model_config = SettingsConfigDict(
        env_file=str(_env_path) if _env_path.exists() else ".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


# Instantiate global settings object
settings = Settings()
