import logging
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Request, Depends, status
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db, init_db
from app.api.router import api_router
from app.schemas.common import RootResponse, HealthResponse, ErrorResponse

# Configure clean application logging
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s - %(message)s",
)
logger = logging.getLogger("refund_verification")


import time
from app.ai.qwen_vision import qwen_vision_service
from app.ai.ollama_reasoning import ollama_reasoning_service


def ensure_storage_directories() -> None:
    """Ensure all required local storage directories exist."""
    base_storage = Path(settings.STORAGE_PATH)
    for subfolder in ["product_references", "evidence", "reports"]:
        (base_storage / subfolder).mkdir(parents=True, exist_ok=True)


def init_local_ai_services() -> None:
    """Initialize, verify and warm up local AI vision and reasoning models."""
    logger.info("AI MODEL INITIALIZATION STARTING...")
    start_total = time.time()

    ollama_ok = ollama_reasoning_service.check_health()
    llama_avail = ollama_reasoning_service.check_model_available() if ollama_ok else False
    qwen_avail = qwen_vision_service.warmup_model() if ollama_ok else False

    llama_warmed = False
    if llama_avail:
        llama_start = time.time()
        llama_warmed = ollama_reasoning_service.warmup_model()
        llama_dur = time.time() - llama_start
    else:
        llama_dur = 0.0

    qwen_warmed = qwen_avail  # warmup_model called above checks availability & warms weights

    total_dur = time.time() - start_total

    print("\n" + "=" * 52)
    print(" AI MODEL INITIALIZATION")
    print("-" * 52)
    print(f" Ollama Reachable      : {'[OK] YES' if ollama_ok else '[FAIL] NO'}")
    print(f" Llama 3.2 1B Available: {'[OK] YES' if llama_avail else '[FAIL] NOT FOUND'}")
    print(f" Qwen2.5-VL 3B Avail.  : {'[OK] YES' if qwen_avail else '[FAIL] NOT FOUND'}")
    print(f" Llama Reasoning Model : {'[OK] READY (' + f'{llama_dur:.2f}s)' if llama_warmed else '[FAIL] NOT WARMED'}")
    print(f" Qwen Vision Model     : {'[OK] READY' if qwen_warmed else '[FAIL] NOT WARMED'}")
    print(f" AI Services Readiness : {'[OK] ALL LOCAL AI READY' if (llama_warmed and qwen_warmed) else 'PARTIAL / OFFLINE'}")
    print(f" Total Warm-up Time    : {total_dur:.2f}s")
    print("=" * 52 + "\n")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown events."""
    logger.info("Starting Refund Evidence Verification API")
    qwen_vision_service.log_startup_diagnostics()
    ensure_storage_directories()
    init_db()
    init_local_ai_services()
    logger.info("Server ready")
    yield
    logger.info("Shutting down Refund Evidence Verification API")


# Create FastAPI application instance
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    lifespan=lifespan,
    responses={
        500: {"model": ErrorResponse, "description": "Internal Server Error"},
    },
)

# Configure CORS for local development and future Flutter application
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS if isinstance(settings.CORS_ORIGINS, list) else [settings.CORS_ORIGINS],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register modular API routes
app.include_router(api_router, prefix=settings.API_V1_STR)


# Root Endpoint
@app.get(
    "/",
    response_model=RootResponse,
    tags=["Root"],
    summary="Root service status",
)
def root() -> RootResponse:
    """Return basic API identity and running status."""
    return RootResponse(
        message="Refund Evidence Verification API",
        status="running",
    )


# Health Check Endpoint
@app.get(
    "/health",
    response_model=HealthResponse,
    tags=["Health"],
    summary="System and database health check",
    responses={
        200: {"model": HealthResponse, "description": "System is healthy"},
        503: {"model": HealthResponse, "description": "Database disconnected or unhealthy"},
    },
)
def health_check(db: Session = Depends(get_db)):
    """Actively verify SQLite database connectivity and report system health."""
    try:
        db.execute(text("SELECT 1"))
        return HealthResponse(
            status="healthy",
            database="connected",
        )
    except Exception as exc:
        logger.error("Health check failed - database disconnected: %s", exc, exc_info=True)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "unhealthy",
                "database": "disconnected",
            },
        )


# Centralized Exception Handlers
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """Handle standard HTTP exceptions with clean JSON responses."""
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors without exposing server internals."""
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={
            "detail": "Validation error",
            "errors": jsonable_encoder(exc.errors()),
        },
    )



@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """Catch-all exception handler to log stack trace and return sanitized error response."""
    logger.error("Unhandled server exception processing %s %s: %s", request.method, request.url, exc, exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal server error"},
    )
