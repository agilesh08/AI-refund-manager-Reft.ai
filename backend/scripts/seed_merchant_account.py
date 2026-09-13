"""Seed merchant@example.com with password123 and demo verification sessions."""
import io
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from PIL import Image, ImageDraw

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.core.database import SessionLocal, init_db
from app.core.security import (
    generate_verification_id,
    generate_verification_token,
    hash_password,
    hash_verification_token,
)
from app.models.merchant import Merchant
from app.models.product import Product
from app.models.product_reference import ProductReference, ReferenceAngle
from app.models.verification import SessionStatus, VerificationSession
from app.models.verification_event import VerificationEvent, VerificationEventType
from app.models.workflow import Workflow, WorkflowStatus
from app.models.workflow_step import WorkflowStep, WorkflowStepType
from app.utils.file_storage import (
    calculate_sha256,
    generate_safe_filename,
    save_reference_file,
)


def create_solid_image(text: str, bg_color: tuple) -> bytes:
    img = Image.new("RGB", (300, 300), color=bg_color)
    draw = ImageDraw.Draw(img)
    draw.rectangle([(10, 10), (290, 290)], outline=(255, 255, 255), width=4)
    draw.text((25, 140), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def seed_merchant():
    init_db()
    db = SessionLocal()

    try:
        # 1. Create or update merchant@example.com
        merchant_email = "merchant@example.com"
        merchant = db.query(Merchant).filter(Merchant.email == merchant_email).first()
        if not merchant:
            merchant = Merchant(
                email=merchant_email,
                business_name="Acme Electronics Store",
                password_hash=hash_password("password123"),
                is_active=True,
            )
            db.add(merchant)
            db.commit()
            db.refresh(merchant)
            print(f"[+] Created merchant: {merchant.email}")
        else:
            merchant.password_hash = hash_password("password123")
            merchant.is_active = True
            merchant.business_name = "Acme Electronics Store"
            db.commit()
            db.refresh(merchant)
            print(f"[*] Updated merchant: {merchant.email} with password123")

        # 2. Product
        sku = "ACME-HEADPHONES-001"
        product = db.query(Product).filter(Product.merchant_id == merchant.id, Product.sku == sku).first()
        if not product:
            product = Product(
                merchant_id=merchant.id,
                name="Smart Wireless Headphones",
                sku=sku,
                description="High-fidelity wireless noise-cancelling headphones.",
                price=Decimal("149.99"),
            )
            db.add(product)
            db.commit()
            db.refresh(product)
            print(f"[+] Created product: {product.name}")

        # 3. References
        angle_colors = {
            ReferenceAngle.FRONT.value: ((40, 80, 160), "HEADPHONES - FRONT"),
            ReferenceAngle.BACK.value: ((60, 100, 180), "HEADPHONES - BACK"),
            ReferenceAngle.LEFT.value: ((80, 120, 200), "HEADPHONES - LEFT"),
            ReferenceAngle.RIGHT.value: ((100, 140, 220), "HEADPHONES - RIGHT"),
        }
        for angle_name, (color, label) in angle_colors.items():
            existing_ref = db.query(ProductReference).filter(
                ProductReference.product_id == product.id,
                ProductReference.angle == angle_name,
            ).first()
            if not existing_ref:
                img_bytes = create_solid_image(label, color)
                img_hash = calculate_sha256(img_bytes)
                filename = generate_safe_filename(product.id, angle_name, "png")
                rel_path = save_reference_file(img_bytes, filename)
                ref = ProductReference(
                    product_id=product.id,
                    angle=angle_name,
                    image_path=rel_path,
                    image_hash=img_hash,
                )
                db.add(ref)
                db.commit()

        # 4. Workflow
        workflow_name = "Standard Refund Verification"
        workflow = db.query(Workflow).filter(
            Workflow.merchant_id == merchant.id,
            Workflow.name == workflow_name,
        ).first()
        if not workflow:
            workflow = Workflow(
                merchant_id=merchant.id,
                name=workflow_name,
                description="Standard customer evidence collection workflow.",
                status=WorkflowStatus.ACTIVE.value,
                is_active=True,
                version=1,
            )
            db.add(workflow)
            db.commit()
            db.refresh(workflow)

            step1 = WorkflowStep(
                workflow_id=workflow.id,
                step_key="step_issue_type",
                step_type=WorkflowStepType.MCQ.value,
                title="What issue are you reporting?",
                description="Select the primary issue with your headphones.",
                step_order=1,
                required=True,
                config_json={
                    "options": [
                        {"value": "damaged", "label": "Product arrived damaged"},
                        {"value": "defective", "label": "No audio / defective unit"},
                        {"value": "wrong_item", "label": "Received incorrect model"},
                    ]
                },
            )
            step2 = WorkflowStep(
                workflow_id=workflow.id,
                step_key="step_photo_evidence",
                step_type=WorkflowStepType.CAMERA.value,
                title="Capture Product Photo",
                description="Take a clear photo showing the item and reported issue.",
                step_order=2,
                required=True,
                config_json={"camera_only": True, "allow_gallery": False},
            )
            db.add_all([step1, step2])
            db.commit()

        # 5. Create a sample Verification Session if none exist
        existing_sess = db.query(VerificationSession).filter(VerificationSession.merchant_id == merchant.id).first()
        if not existing_sess:
            now = datetime.now(timezone.utc)
            token = generate_verification_token()
            token_hash = hash_verification_token(token)
            vid = generate_verification_id()
            sess = VerificationSession(
                merchant_id=merchant.id,
                product_id=product.id,
                workflow_id=workflow.id,
                workflow_version=workflow.version,
                order_id="ORD-2026-1001",
                customer_name="Alice Johnson",
                customer_contact="alice@example.com",
                refund_reason="Damaged earcup during delivery",
                refund_amount=Decimal("149.99"),
                max_attempts=1,
                attempts_count=0,
                verification_id=vid,
                customer_token_hash=token_hash,
                status=SessionStatus.CREATED.value,
                workflow_snapshot_json={"name": workflow.name, "version": workflow.version},
                created_at=now,
                expires_at=now + timedelta(days=7),
            )
            db.add(sess)
            db.commit()
            print(f"[+] Created sample session: {vid} (token: {token})")

        print("\n[SUCCESS] merchant@example.com / password123 is ready to log in!")

    finally:
        db.close()


if __name__ == "__main__":
    seed_merchant()
