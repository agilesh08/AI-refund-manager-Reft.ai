from typing import Any, Optional
from pydantic import BaseModel


class RootResponse(BaseModel):
    """Response model for the root endpoint."""
    message: str
    status: str


class HealthResponse(BaseModel):
    """Response model for the system health endpoint."""
    status: str
    database: str


class ErrorResponse(BaseModel):
    """Standardized error response model."""
    detail: str
    errors: Optional[Any] = None
