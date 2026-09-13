"""Idempotent Local Demonstration Data Seed Script.

Prepares the Refund Evidence Verification System for real Android phone testing.
Seeds:
- Demo Merchant: demo@refundtest.local / Demo@12345!
- Demo Product: Demo Wireless Headphones (SKU: DEMO-HEADPHONES-001) with 4 reference angles (FRONT, BACK, LEFT, RIGHT)
- Demo Active Workflow: 3-step verification (MCQ -> TEXT -> IMAGE)
- Demo Verification Session: Order DEMO-ORDER-001 with active customer token
"""
import io
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import httpx
from PIL import Image, ImageDraw

# Add backend directory to Python path
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
    """Generate a clean, deterministic 300x300 PNG image with visual label."""
    img = Image.new("RGB", (300, 300), color=bg_color)
    draw = ImageDraw.Draw(img)
    # Simple rectangle frame
    draw.rectangle([(10, 10), (290, 290)], outline=(255, 255, 255), width=4)
    # Visual label line
    draw.text((25, 140), text, fill=(255, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def seed_demo_environment(lan_ip: str = "10.146.156.92") -> dict:
    """Idempotently seed the demo merchant, product, references, workflow, and session."""
    init_db()
    db = SessionLocal()

    try:
        # 1. Seed or reuse Demo Merchant
        merchant_email = "demo@refundtest.local"
        merchant = (
            db.query(Merchant).filter(Merchant.email == merchant_email).first()
        )
        if not merchant:
            merchant = Merchant(
                email=merchant_email,
                business_name="Demo Electronics Store",
                password_hash=hash_password("Demo@12345!"),
                is_active=True,
            )
            db.add(merchant)
            db.commit()
            db.refresh(merchant)
            print(f"[+] Created Demo Merchant: {merchant.email} ({merchant.id})")
        else:
            merchant.business_name = "Demo Electronics Store"
            merchant.password_hash = hash_password("Demo@12345!")
            merchant.is_active = True
            db.commit()
            db.refresh(merchant)
            print(f"[*] Reusing Demo Merchant: {merchant.email} ({merchant.id})")

        # 2. Seed or reuse Demo Product
        sku = "DEMO-HEADPHONES-001"
        product = (
            db.query(Product)
            .filter(Product.merchant_id == merchant.id, Product.sku == sku)
            .first()
        )
        if not product:
            product = Product(
                merchant_id=merchant.id,
                name="Demo Wireless Headphones",
                sku=sku,
                description="High-fidelity wireless noise-cancelling headphones for demo testing.",
                price=Decimal("4999.00"),
            )
            db.add(product)
            db.commit()
            db.refresh(product)
            print(f"[+] Created Demo Product: {product.name} ({product.sku})")
        else:
            print(f"[*] Reusing Demo Product: {product.name} ({product.sku})")

        # 3. Seed 4 Trusted Reference Angles (FRONT, BACK, LEFT, RIGHT)
        angle_colors = {
            ReferenceAngle.FRONT.value: ((40, 80, 160), "HEADPHONES - FRONT VIEW"),
            ReferenceAngle.BACK.value: ((60, 100, 180), "HEADPHONES - BACK VIEW"),
            ReferenceAngle.LEFT.value: ((80, 120, 200), "HEADPHONES - LEFT VIEW"),
            ReferenceAngle.RIGHT.value: ((100, 140, 220), "HEADPHONES - RIGHT VIEW"),
        }

        for angle_name, (color, label) in angle_colors.items():
            existing_ref = (
                db.query(ProductReference)
                .filter(
                    ProductReference.product_id == product.id,
                    ProductReference.angle == angle_name,
                )
                .first()
            )
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
                print(f"[+] Created Reference Angle: {angle_name} -> {rel_path}")
            else:
                print(f"[*] Reusing Reference Angle: {angle_name}")

        # 4. Seed or reuse Active Verification Workflow
        workflow_name = "Demo Refund Verification Workflow"
        workflow = (
            db.query(Workflow)
            .filter(
                Workflow.merchant_id == merchant.id,
                Workflow.name == workflow_name,
            )
            .first()
        )
        if not workflow:
            workflow = Workflow(
                merchant_id=merchant.id,
                name=workflow_name,
                description="Standard 3-step customer evidence collection workflow for demo.",
                status=WorkflowStatus.DRAFT.value,
                is_active=False,
                version=1,
            )
            db.add(workflow)
            db.commit()
            db.refresh(workflow)

            # Step 1: MCQ
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
            # Step 2: TEXT
            step2 = WorkflowStep(
                workflow_id=workflow.id,
                step_key="step_description",
                step_type=WorkflowStepType.TEXT.value,
                title="Describe what happened.",
                description="Explain the damage or issue observed.",
                step_order=2,
                required=True,
                config_json={"min_length": 5, "max_length": 1000},
            )
            # Step 3: IMAGE
            step3 = WorkflowStep(
                workflow_id=workflow.id,
                step_key="step_product_photo",
                step_type=WorkflowStepType.IMAGE.value,
                title="Upload a clear photo showing the product condition.",
                description="Ensure the damaged or defective part is clearly visible.",
                step_order=3,
                required=True,
                config_json={"min_images": 1, "max_images": 4},
            )
            db.add_all([step1, step2, step3])
            db.commit()

            # Publish Workflow to ACTIVE
            workflow.status = WorkflowStatus.ACTIVE.value
            workflow.is_active = True
            db.commit()
            db.refresh(workflow)
            print(f"[+] Created and Published Workflow: {workflow.name} ({workflow.id})")
        else:
            workflow.status = WorkflowStatus.ACTIVE.value
            workflow.is_active = True
            db.commit()
            db.refresh(workflow)
            print(f"[*] Reusing Active Workflow: {workflow.name} ({workflow.id})")

        # 5. Seed or Refresh Demo Verification Session
        order_id = "DEMO-ORDER-001"
        session = (
            db.query(VerificationSession)
            .filter(
                VerificationSession.merchant_id == merchant.id,
                VerificationSession.order_id == order_id,
            )
            .first()
        )

        # Generate a fresh, active raw customer token
        raw_customer_token = generate_verification_token(32)
        token_hash = hash_verification_token(raw_customer_token)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=72)

        # Build frozen workflow snapshot
        ordered_steps = sorted(workflow.steps, key=lambda s: s.step_order)
        snapshot = {
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "workflow_version": workflow.version,
            "steps": [
                {
                    "id": s.id,
                    "step_key": s.step_key,
                    "step_type": s.step_type,
                    "title": s.title,
                    "description": s.description,
                    "step_order": s.step_order,
                    "required": s.required,
                    "config_json": s.config_json or {},
                }
                for s in ordered_steps
            ],
        }

        if not session:
            v_id = generate_verification_id()
            session = VerificationSession(
                verification_id=v_id,
                merchant_id=merchant.id,
                product_id=product.id,
                workflow_id=workflow.id,
                workflow_version=workflow.version,
                workflow_snapshot_json=snapshot,
                order_id=order_id,
                customer_name="Demo Customer",
                customer_contact="demo.customer@refundtest.local",
                refund_reason="Product arrived damaged",
                refund_amount=Decimal("4999.00"),
                status=SessionStatus.CREATED.value,
                customer_token_hash=token_hash,
                expires_at=expires_at,
            )
            db.add(session)
            db.flush()

            # Record creation audit event
            event = VerificationEvent(
                session_id=session.id,
                verification_id=session.verification_id,
                event_type=VerificationEventType.SESSION_CREATED.value,
                metadata_json={
                    "source": "demo_seed_script",
                    "order_id": order_id,
                    "product_id": product.id,
                },
            )
            db.add(event)
            db.commit()
            db.refresh(session)
            print(f"[+] Created Demo Verification Session: {session.verification_id} (ID: {session.id})")
        else:
            # Re-arm existing session with new active token and CREATED status
            session.customer_token_hash = token_hash
            session.status = SessionStatus.CREATED.value
            session.expires_at = expires_at
            session.workflow_snapshot_json = snapshot
            session.product_id = product.id
            session.refund_amount = Decimal("4999.00")
            session.refund_reason = "Product arrived damaged"
            db.commit()
            db.refresh(session)
            print(f"[*] Re-armed Demo Verification Session: {session.verification_id} (ID: {session.id})")

        # URLs
        http_verification_url = f"http://{lan_ip}:8000/api/v1/public/verifications/{raw_customer_token}"
        deep_link_url = f"refundverify://verify/{raw_customer_token}"

        return {
            "merchant_name": merchant.business_name,
            "merchant_email": merchant.email,
            "merchant_password": "Demo@12345!",
            "product_name": product.name,
            "product_sku": product.sku,
            "verification_id": session.verification_id,
            "session_id": session.id,
            "customer_token": raw_customer_token,
            "customer_verification_url": http_verification_url,
            "deep_link_url": deep_link_url,
        }

    finally:
        db.close()


def verify_public_endpoint(token: str, base_url: str = "http://127.0.0.1:8000"):
    """Verify that the seeded customer token returns a valid sanitized public response."""
    url = f"{base_url}/api/v1/public/verifications/{token}"
    print(f"\n[?] Validating customer token via: {url}")
    try:
        resp = httpx.get(url, timeout=10.0)
        if resp.status_code == 200:
            data = resp.json()
            print(f"[PASS] HTTP 200 OK received from public endpoint!")
            print(f"       Product: {data.get('product', {}).get('name')}")
            print(f"       Merchant: {data.get('merchant', {}).get('business_name')}")
            print(f"       Status: {data.get('status')}")
            # Security verification
            assert "customer_token_hash" not in str(data), "Token hash must not be exposed!"
            assert "password_hash" not in str(data), "Password hash must not be exposed!"
            assert "fraud_score" not in str(data), "Fraud scores must not exist!"
            print("[PASS] Anti-leak security checks verified: No hashes or fraud scores exposed.")
            return True
        else:
            print(f"[FAIL] Public endpoint returned HTTP {resp.status_code}: {resp.text}")
            return False
    except Exception as e:
        print(f"[FAIL] Could not connect to public endpoint: {e}")
        return False


if __name__ == "__main__":
    lan_ip = sys.argv[1] if len(sys.argv) > 1 else "10.146.156.92"
    credentials = seed_demo_environment(lan_ip=lan_ip)

    print("\n" + "=" * 60)
    print("DEMO CREDENTIALS FOR PHYSICAL ANDROID PHONE TESTING")
    print("=" * 60)
    print(f"Merchant:                  {credentials['merchant_name']}")
    print(f"Merchant email:            {credentials['merchant_email']}")
    print(f"Merchant password:         {credentials['merchant_password']}")
    print(f"Product:                   {credentials['product_name']} ({credentials['product_sku']})")
    print(f"Verification ID:           {credentials['verification_id']}")
    print(f"Customer verification token: {credentials['customer_token']}")
    print(f"Customer verification URL: {credentials['customer_verification_url']}")
    print(f"Mobile Deep Link URL:      {credentials['deep_link_url']}")
    print("=" * 60)

    # Validate against running backend
    verify_public_endpoint(credentials["customer_token"])
