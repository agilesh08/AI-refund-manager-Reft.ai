"""Gemini Vision AI integration service.

Provides visual consistency analysis comparing customer evidence images against
trusted merchant product reference images.
"""
import logging
from typing import Any, Dict, List, Optional
from google import genai
from google.genai import types

from app.core.config import settings
from app.schemas.visual_analysis import VisualAnalysisResult

logger = logging.getLogger(__name__)

GEMINI_VISION_SYSTEM_INSTRUCTION = """You are the Visual Consistency Observation Engine for an evidence verification platform.
Your responsibility is strictly limited to objective visual observation and comparison between merchant reference images and customer-submitted evidence images.

STRICT CONSTRAINTS:
1. DO NOT make refund approval or rejection recommendations.
2. DO NOT make any accusations of fraud, deception, or dishonesty. Never use words like 'fraud', 'scam', 'fake', or 'deceptive'.
3. DO NOT calculate or provide fraud risk scores.
4. DO NOT make definitive assumptions about angles or product parts that are out of frame, occluded, or not visible.
5. All observations must be objective, factual visual descriptions.

EPISTEMIC UNCERTAINTY INSTRUCTIONS:
- You must strictly differentiate between:
  - 'observed': Clearly and unambiguously visible in the image.
  - 'not_observed': The relevant area is clearly visible, but the feature/damage is absent.
  - 'not_visible': The area or angle is out of frame, obscured, hidden, or occluded.
  - 'unclear': The area is in frame but lighting, glare, low resolution, or distance makes it ambiguous.
- Under NO circumstance should 'not_visible' be equated to 'false' or 'not damaged'. If an area cannot be seen, report it as 'not_visible'.

CAPTURE ASSESSMENT (PHYSICAL VS DISPLAY / SCREEN):
Assess whether the submitted image appears to show:
- 'DIRECT_PHYSICAL_APPEARANCE': A real physical object photographed directly with depth of field, perspective, and natural ambient lighting.
- 'SCREEN_DISPLAY_APPEARANCE': An image displayed on a phone, laptop, monitor, or tablet screen that has been photographed.
  Look for visual indicators: monitor/laptop frame or bezel, visible desktop or mobile OS UI (taskbar, browser tabs, status bar, desktop icons), screen reflections or glare, moire pattern, pixel grid lines, perspective distortion of a monitor, unnatural image-within-image borders.
- 'SCREENSHOT_APPEARANCE': A direct electronic screenshot (crisp pixel-flat rendering without camera distortion).
- 'PRINTED_IMAGE_APPEARANCE': A physical paper printout of an image photographed (paper texture, halftone dots, edge curl).
- 'UNCLEAR': The capture method cannot be determined with confidence due to lighting, tight crop, or low resolution.
IMPORTANT: State observations factually without accusation (e.g. 'Evidence appears to show the product image displayed on a laptop screen').

IMAGE QUALITY ASSESSMENT:
- Evaluate overall quality: 'GOOD', 'ACCEPTABLE', 'POOR', 'INSUFFICIENT'.
- Evaluate product visibility: 'CLEAR', 'PARTIAL', 'UNCLEAR', 'NOT_VISIBLE'.
- Note issues such as blur, dim lighting, harsh glare, occlusion, severe crop, low resolution, or display interference.

PRODUCT IDENTITY & REFERENCE COMPARISON:
- Identify the apparent product type/name in the customer evidence (e.g. computer mouse, in-ear earphones, smartphone, athletic shoe).
- Determine whether it matches the merchant's trusted product: 'MATCH', 'MISMATCH', 'UNCERTAIN', 'NOT_APPLICABLE'.
- Note visible brand markings, model identifiers, physical contours, material textures, and colors.
- Identify which reference angle (FRONT, BACK, LEFT, RIGHT) it matches, or note an unrepresented angle.

CONDITION & DAMAGE OBSERVATIONS:
- Report any visible damage (scratches, cracks, dents, tears, liquid damage, broken parts).
- State the exact location where damage is observed.
- Note visible packaging condition if present.
"""


class GeminiVisionService:
    """Encapsulated service for invoking Google Gemini Vision models."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_version: Optional[str] = None,
    ) -> None:
        self.api_key = api_key or settings.GEMINI_API_KEY
        self.model_name = model_name or settings.GEMINI_VISION_MODEL
        self.prompt_version = prompt_version or settings.GEMINI_VISION_PROMPT_VERSION
        self._client: Optional[genai.Client] = None

    @classmethod
    def log_startup_diagnostics(cls) -> None:
        """Log safe startup diagnostics without revealing secrets."""
        is_configured = bool(settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip())
        logger.info(
            "GEMINI STARTUP DIAGNOSTICS: GEMINI_CONFIGURED=%s | GEMINI_MODEL=%s | GEMINI_AUTH_MODE=API_KEY",
            is_configured,
            settings.GEMINI_VISION_MODEL,
        )

    def get_client(self) -> genai.Client:
        """Obtain or initialize the Gemini client strictly in API key mode."""
        if self._client is None:
            if not self.api_key or not self.api_key.strip():
                raise ValueError(
                    "Gemini API key is not configured. Set GEMINI_API_KEY in environment or .env."
                )
            # Strictly use configured API key; do not fall back to ambient OAuth credentials
            self._client = genai.Client(api_key=self.api_key.strip())
        return self._client

    @staticmethod
    def _is_auth_error(exc: Exception) -> bool:
        """Detect Gemini authentication/authorization errors that must fast-fail without retry.

        Returns True for HTTP 401, ACCESS_TOKEN_TYPE_UNSUPPORTED, API_KEY_INVALID,
        UNAUTHENTICATED. These indicate configuration problems — retrying is pointless
        and makes the customer wait needlessly.
        """
        exc_str = str(exc).upper()
        auth_markers = (
            "401",
            "UNAUTHENTICATED",
            "ACCESS_TOKEN_TYPE_UNSUPPORTED",
            "API_KEY_INVALID",
            "PERMISSION_DENIED",
            "INVALID_API_KEY",
        )
        return any(m in exc_str for m in auth_markers)


    def analyze_evidence_image(
        self,
        evidence_bytes: bytes,
        evidence_mime_type: str,
        reference_images: List[Dict[str, Any]],
        product_info: Dict[str, Any],
        claim_context: Optional[Dict[str, Any]] = None,
    ) -> VisualAnalysisResult:
        """Perform multimodal visual analysis comparing customer evidence to merchant reference angles.

        Args:
            evidence_bytes: Raw binary bytes of the customer's submitted photo.
            evidence_mime_type: MIME type of customer evidence (e.g. image/jpeg, image/png).
            reference_images: List of dicts, each with 'angle' (str), 'bytes' (bytes), 'mime_type' (str).
            product_info: Dict containing product details (name, sku, category, description).
            claim_context: Optional dict with customer claim details (step key, customer notes, claim text, refund_reason).

        Returns:
            VisualAnalysisResult structured schema.
        """
        client = self.get_client()

        # Build contents array for multimodal invocation
        contents: List[Any] = []

        # System and task preamble
        intro_text = [
            f"=== GEMINI VISION VISUAL CONSISTENCY ANALYSIS ({self.prompt_version}) ===",
            "TASK: Analyze the submitted customer evidence image against the merchant's trusted reference angles.",
            "",
            "--- MERCHANT PRODUCT SPECIFICATION ---",
            f"Product Name: {product_info.get('name', 'Unknown')}",
            f"SKU: {product_info.get('sku', 'Unknown')}",
            f"Category: {product_info.get('category', 'Unknown')}",
            f"Description: {product_info.get('description', 'None')}",
            "",
        ]

        if claim_context:
            refund_reason = str(claim_context.get("refund_reason") or claim_context.get("workflow_step_key") or "").upper()
            claim_notes = str(claim_context.get("customer_notes") or claim_context.get("claim_text") or "")
            intro_text.extend([
                "--- CLAIM CONTEXT ---",
                f"Workflow Step: {claim_context.get('workflow_step_key', 'Unknown')}",
                f"Refund Reason: {claim_context.get('refund_reason', 'Not specified')}",
                f"Claimed Notes: {claim_notes or 'None'}",
                "",
            ])

            claim_instructions = []
            if "WRONG" in refund_reason or "different" in claim_notes.lower():
                claim_instructions.append(
                    "SPECIFIC CLAIM FOCUS (WRONG PRODUCT RECEIVED):\n"
                    "- What specific physical product or device is visible in the customer evidence?\n"
                    "- Does it match the merchant's specified product (name, category, design)?\n"
                    "- Is the evidence showing a real physical product or an image displayed on another screen?\n"
                    "- Is enough of the product visible to establish its identity?"
                )
            elif "DAMAG" in refund_reason or "DEFECT" in refund_reason or "broken" in claim_notes.lower():
                claim_instructions.append(
                    "SPECIFIC CLAIM FOCUS (PRODUCT ARRIVED DAMAGED):\n"
                    "- Is visible physical damage observed on the product? What type and exact location?\n"
                    "- Is the reported damaged area in frame and clearly visible?\n"
                    "- Is the item photographed directly or shown on another screen?"
                )
            elif "MISSING" in refund_reason or "incomplete" in claim_notes.lower():
                claim_instructions.append(
                    "SPECIFIC CLAIM FOCUS (MISSING COMPONENT / ACCESSORY):\n"
                    "- What components/accessories are visible versus absent?\n"
                    "- Is the packaging or unboxing state visible?"
                )

            if claim_instructions:
                intro_text.extend(["--- CLAIM-AWARE PRIORITIES ---"] + claim_instructions + [""])

        intro_text.append("--- MERCHANT TRUSTED REFERENCE IMAGES ---")
        intro_text.append("The following reference images represent the verified standard product from 4 canonical angles:")
        contents.append("\n".join(intro_text))

        # Add reference images with their labeled angle
        for ref in reference_images:
            angle = ref.get("angle", "UNKNOWN")
            contents.append(f"\n[REFERENCE IMAGE - ANGLE: {angle}]")
            contents.append(
                types.Part.from_bytes(
                    data=ref["bytes"],
                    mime_type=ref.get("mime_type", "image/jpeg"),
                )
            )

        # Add customer evidence
        contents.append("\n--- CUSTOMER SUBMITTED SUBJECT EVIDENCE ---")
        contents.append("Below is the evidence photo submitted by the customer for this refund claim:")
        contents.append(
            types.Part.from_bytes(
                data=evidence_bytes,
                mime_type=evidence_mime_type,
            )
        )

        contents.append(
            "\nAnalyze the customer image thoroughly against the trusted reference images according to the instructions. "
            "Evaluate image quality, product identity, capture appearance (direct physical vs screen/display), product consistency, and visible condition/damage. "
            "Return output strictly adhering to the JSON schema."
        )

        # Configure structured output with Gemini
        config = types.GenerateContentConfig(
            system_instruction=GEMINI_VISION_SYSTEM_INSTRUCTION,
            temperature=0.2,
            response_mime_type="application/json",
            response_schema=VisualAnalysisResult,
        )

        logger.info(
            "Invoking Gemini Vision model %s (prompt %s) with %d reference images",
            self.model_name,
            self.prompt_version,
            len(reference_images),
        )

        try:
            response = client.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )
        except Exception as exc:
            if self._is_auth_error(exc):
                # Auth errors are configuration failures — fast-fail immediately.
                # Customer should not wait through retries for a misconfigured API key.
                logger.error(
                    "Gemini Vision AUTHENTICATION FAILURE (fast-fail): %s. "
                    "Check GEMINI_API_KEY in .env — OAuth/ADC tokens are not supported.",
                    exc,
                )
                raise ValueError(
                    f"Gemini Vision authentication failed (API key invalid or unsupported). "
                    f"Configure GEMINI_API_KEY correctly in .env. Detail: {exc}"
                ) from exc
            raise

        if not response.text:
            raise RuntimeError("Gemini Vision returned empty text response")

        result = VisualAnalysisResult.model_validate_json(response.text)
        return result



# Global singleton service instance
gemini_vision_service = GeminiVisionService()
