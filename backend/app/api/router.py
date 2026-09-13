"""Central API router mounting versioned endpoint sub-routers."""
from fastapi import APIRouter
from app.api import auth, merchants, products, workflows, verifications, public_verifications

api_router = APIRouter()

# Mount authentication, merchant, product, workflow, and verification endpoints
api_router.include_router(auth.router, prefix="/auth", tags=["Authentication"])
api_router.include_router(merchants.router, prefix="/merchants", tags=["Merchants"])
api_router.include_router(products.router, prefix="/products", tags=["Products & References"])
api_router.include_router(workflows.router, prefix="/workflows", tags=["Workflows & Steps"])
api_router.include_router(verifications.router, prefix="/verifications", tags=["Verification Sessions"])
api_router.include_router(public_verifications.router, prefix="/public/verifications", tags=["Customer Verification"])


