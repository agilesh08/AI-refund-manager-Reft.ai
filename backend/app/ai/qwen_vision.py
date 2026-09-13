"""Local Qwen2.5-VL 3B Vision AI integration service via Ollama.

Provides structured forensic visual consistency analysis comparing customer evidence images
against pre-computed trusted merchant product reference observations using local qwen2.5vl:3b-q4_K_M model.
"""
import base64
import io
import json
import logging
import time
from typing import Any, Dict, List, Optional
import httpx
from PIL import Image

from app.core.config import settings
from app.schemas.visual_analysis import (
    VisualAnalysisResult,
    ImageQualityAnalysis,
    ProductConsistencyAnalysis,
    VisibleConditionAnalysis,
    EvidenceCaptureAssessment,
    ProductIdentityAnalysis,
)
from app.schemas.product_reference_analysis import (
    ProductReferenceAnalysisResult,
    ReferenceImageVisualMetadata,
)

logger = logging.getLogger(__name__)

QWEN_VISION_SYSTEM_INSTRUCTION = """You are an expert Forensic Visual Consistency Engine for a refund evidence verification platform.
Your duty is to perform objective, structured, forensic visual inspection of customer-submitted evidence images compared against merchant baseline specifications and product visual profiles.

STRICT CONSTRAINTS:
1. Return ONLY a valid JSON object. No explanation, no markdown text outside the JSON.
2. DO NOT make refund approval or rejection decisions. The merchant remains the final authority.
3. DO NOT accuse the customer of fraud, scam, or fake claims. State objective physical and visual facts.
4. Epistemic Uncertainty: Differentiate between:
   - 'observed': Clearly visible in the image.
   - 'not_observed': The area is visible but feature/damage is absent.
   - 'not_visible': Out of frame, obscured, hidden, or occluded.
   - 'unclear': In frame but lighting, glare, low resolution, or angle makes it ambiguous.
   'not_visible' MUST NOT be assumed to mean 'undamaged' or 'not present'.

CAPTURE METHOD INSPECTION (VERY IMPORTANT):
Determine if the evidence image is:
- 'PHYSICAL_PHOTO' / 'DIRECT_PHYSICAL_APPEARANCE': Direct physical object photo with ambient lighting and natural depth.
- 'SCREEN_PHOTO' / 'SCREEN_DISPLAY_APPEARANCE': Photo taken of a laptop, phone, monitor, or tablet display. Look for: screen bezel/frame, screen reflection, moiré patterns, display pixels, UI borders, desktop taskbar, browser chrome, cursor, monitor edges.
- 'SCREENSHOT_APPEARANCE': Crisp pixel-flat electronic screenshot.
- 'COMPOSITE_IMAGE': Digitally edited or composited image.
- 'UNCLEAR': Capture method cannot be determined.

FORENSIC COMPARISON & CLAIM CONSISTENCY:
- Compare customer image against the canonical Product Visual Profile.
- If customer claim is 'Wrong product received' and image shows a different physical product, note the product mismatch factually. DO NOT call it fraud; the customer may genuinely have received the wrong item.
- Check for visible damage, packaging, product brand/model markings, color, shape, and image quality.
- State whether the image provides sufficient evidence to verify the customer's stated claim or if targeted additional evidence is needed.
"""


def optimize_image_for_inference(image_bytes: bytes, max_dim: int = 1024, quality: int = 85) -> bytes:
    """Downscale and compress image in-memory for low VRAM usage during local vision inference.

    Original evidence files on disk remain untouched.
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        # Resize if dimensions exceed max_dim
        width, height = img.size
        if width > max_dim or height > max_dim:
            if width > height:
                new_w = max_dim
                new_h = int(height * (max_dim / width))
            else:
                new_h = max_dim
                new_w = int(width * (max_dim / height))
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

        output = io.BytesIO()
        img.save(output, format="JPEG", quality=quality)
        return output.getvalue()
    except Exception as exc:
        logger.warning("Image optimization failed, sending raw bytes: %s", exc)
        return image_bytes


class QwenVisionService:
    """Encapsulated local visual analysis service using Qwen2.5-VL 3B via Ollama."""

    def __init__(
        self,
        ollama_url: Optional[str] = None,
        model_name: Optional[str] = None,
        prompt_version: str = "v3.0-qwen-local",
    ) -> None:
        self.ollama_url = ollama_url or getattr(settings, "OLLAMA_BASE_URL", "http://localhost:11434")
        self.model_name = model_name or "qwen2.5vl:3b-q4_K_M"
        self.prompt_version = prompt_version

    def log_startup_diagnostics(self) -> None:
        """Log startup diagnostics for local vision model."""
        logger.info(
            "QWEN VISION DIAGNOSTICS: OLLAMA_URL=%s | MODEL=%s | PROMPT_VERSION=%s",
            self.ollama_url,
            self.model_name,
            self.prompt_version,
        )

    def warmup_model(self) -> bool:
        """Warm up local Qwen2.5-VL model with a tiny 1x1 test image to preload weights into VRAM."""
        try:
            start_t = time.time()
            tiny_b64 = "/9j/4AAQSkZJRgABAQEASABIAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////wgALCAABAAEBAREA/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPxA="
            payload = {
                "model": self.model_name,
                "messages": [
                    {
                        "role": "user",
                        "content": 'Respond with JSON: {"status": "ok"}',
                        "images": [tiny_b64],
                    }
                ],
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.1,
                },
            }
            with httpx.Client(timeout=30.0) as client:
                resp = client.post(f"{self.ollama_url}/api/chat", json=payload)
                if resp.status_code == 200:
                    dur = time.time() - start_t
                    logger.info("Qwen2.5-VL 3B warmed up successfully in %.2fs", dur)
                    return True
        except Exception as exc:
            logger.warning("Qwen2.5-VL 3B warm-up check failed: %s", exc)
        return False

    def analyze_reference_image(
        self,
        image_bytes: bytes,
        angle: str,
        product_info: Dict[str, Any],
    ) -> ProductReferenceAnalysisResult:
        """Perform individual Qwen visual analysis on ONE merchant reference image.

        Processes references one-at-a-time to prevent VRAM overflow.
        """
        opt_bytes = optimize_image_for_inference(image_bytes, max_dim=1024)
        img_b64 = base64.b64encode(opt_bytes).decode("utf-8")

        prompt = (
            f"You are a forensic product visual evidence analyzer.\n"
            f"Extract detailed visual metadata from this SINGLE merchant product reference photo.\n\n"
            f"--- MERCHANDISE SPECIFICATIONS ---\n"
            f"Product Name: {product_info.get('name', 'Unknown')}\n"
            f"SKU: {product_info.get('sku', 'Unknown')}\n"
            f"Category: {product_info.get('category', 'Unknown')}\n"
            f"Description: {product_info.get('description', 'None')}\n"
            f"Reference Angle: {angle.upper()}\n\n"
            f"--- INSTRUCTIONS ---\n"
            f"Extract objective visual metadata. DO NOT invent details not visible.\n"
            f"Return strictly a JSON object with this EXACT structure:\n"
            f"{{\n"
            f'  "angle": "{angle.upper()}",\n'
            f'  "summary": "Factual visual synthesis of this reference image",\n'
            f'  "confidence": 0.95,\n'
            f'  "metadata": {{\n'
            f'    "product_category": "{product_info.get("category", "General")}",\n'
            f'    "brand": "{product_info.get("name", "").split()[0] if product_info.get("name") else "Unspecified"}",\n'
            f'    "model": "{product_info.get("sku", "Unspecified")}",\n'
            f'    "visible_product_identity": "concise description of visible item",\n'
            f'    "shape": "geometric silhouette and shape details",\n'
            f'    "dimensions_proportions": "estimated visual proportions or unclear",\n'
            f'    "color": "primary and secondary colors visible",\n'
            f'    "material": "visible materials (plastic, metal, etc.) or unclear",\n'
            f'    "texture_finish": "matte, glossy, brushed, etc. or unclear",\n'
            f'    "distinctive_features": ["feature 1", "feature 2"],\n'
            f'    "buttons_ports_components": ["component 1", "component 2"],\n'
            f'    "logos_markings": ["logo or marking 1"],\n'
            f'    "visible_text": ["printed label text 1"],\n'
            f'    "packaging_characteristics": "packaging details if visible or null",\n'
            f'    "physical_condition": "NEW",\n'
            f'    "orientation_angle": "{angle.upper()}",\n'
            f'    "important_landmarks": ["landmark 1", "landmark 2"],\n'
            f'    "image_quality": "GOOD",\n'
            f'    "occlusions": ["occluded detail if any"],\n'
            f'    "uncertainties": ["detail not inferable from this single angle"]\n'
            f"  }}\n"
            f"}}\n\n"
            f"Produce VALID JSON ONLY."
        )

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": prompt,
                    "images": [img_b64],
                }
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_ctx": 4096,
            },
        }

        start_t = time.time()
        logger.info(
            "Invoking Qwen2.5-VL 3B for SINGLE reference analysis (Angle: %s, Product: %s)",
            angle,
            product_info.get("sku", "Unknown"),
        )

        response_text = ""
        try:
            with httpx.Client(timeout=90.0) as client:
                resp = client.post(f"{self.ollama_url}/api/chat", json=payload)
                dur_ms = int((time.time() - start_t) * 1000)

                # Diagnostic logging
                logger.info(
                    "QWEN_REF_ANALYSIS_HTTP: status=%d, dur_ms=%d, angle=%s",
                    resp.status_code,
                    dur_ms,
                    angle,
                )

                if resp.status_code != 200:
                    raise RuntimeError(f"Ollama HTTP status {resp.status_code}: {resp.text[:200]}")

                res_json = resp.json()
                msg = res_json.get("message") or {}
                response_text = (msg.get("content") or "").strip()

                logger.info(
                    "QWEN_REF_DIAGNOSTICS: model=%s, angle=%s, res_keys=%s, msg_keys=%s, content_len=%d",
                    res_json.get("model", self.model_name),
                    angle,
                    list(res_json.keys()),
                    list(msg.keys()) if isinstance(msg, dict) else [],
                    len(response_text),
                )

        except Exception as exc:
            logger.error("Failed to analyze reference angle %s via Qwen: %s", angle, exc)
            raise RuntimeError(f"Reference visual analysis failed for angle {angle}: {exc}") from exc

        if not response_text:
            raise RuntimeError(f"Qwen2.5-VL returned empty response text for reference angle {angle}")

        # Parse JSON and validate against ProductReferenceAnalysisResult
        clean_json_str = self._clean_json_markdown(response_text)
        data = json.loads(clean_json_str)
        return ProductReferenceAnalysisResult.model_validate(data)

    def analyze_evidence_image(
        self,
        evidence_bytes: bytes,
        evidence_mime_type: str,
        reference_images: Optional[List[Dict[str, Any]]] = None,
        product_info: Optional[Dict[str, Any]] = None,
        claim_context: Optional[Dict[str, Any]] = None,
        visual_profile: Optional[Dict[str, Any]] = None,
    ) -> VisualAnalysisResult:
        """Perform visual analysis comparing customer evidence to product visual profile.

        Submits ONE customer image payload to prevent VRAM overflow.
        """
        product_info = product_info or {}
        opt_evidence_bytes = optimize_image_for_inference(evidence_bytes, max_dim=1024)
        evidence_b64 = base64.b64encode(opt_evidence_bytes).decode("utf-8")

        images_b64: List[str] = [evidence_b64]

        # Optionally include max 1 matching reference image if provided
        ref_context_text = ""
        if reference_images and len(reference_images) > 0:
            top_ref = reference_images[0]
            ref_bytes = optimize_image_for_inference(top_ref["bytes"], max_dim=800)
            images_b64.append(base64.b64encode(ref_bytes).decode("utf-8"))
            ref_context_text = f"\nImage #2: Trusted Reference Baseline ({top_ref.get('angle', 'FRONT')} angle)"

        refund_reason = ""
        claim_notes = ""
        if claim_context:
            refund_reason = str(claim_context.get("refund_reason") or claim_context.get("workflow_step_key") or "").upper()
            claim_notes = str(claim_context.get("customer_notes") or claim_context.get("claim_text") or "")

        # Format visual profile text context
        profile_text = "No pre-computed profile available."
        if visual_profile:
            profile_text = json.dumps(visual_profile, indent=2)

        prompt_lines = [
            QWEN_VISION_SYSTEM_INSTRUCTION,
            "",
            "--- MERCHANDISE SPECIFICATIONS ---",
            f"Product Name: {product_info.get('name', 'Unknown')}",
            f"SKU: {product_info.get('sku', 'Unknown')}",
            f"Category: {product_info.get('category', 'Unknown')}",
            f"Description: {product_info.get('description', 'None')}",
            "",
            "--- CONSOLIDATED PRODUCT VISUAL PROFILE ---",
            profile_text,
            "",
            "--- CLAIM CONTEXT ---",
            f"Customer Refund Reason: {refund_reason or 'Not specified'}",
            f"Customer Notes: {claim_notes or 'None'}",
            "",
            "--- IMAGES PROVIDED ---",
            "Image #1: Customer Evidence Subject Photo",
        ]
        if ref_context_text:
            prompt_lines.append(ref_context_text)

        prompt_lines.extend([
            "",
            "--- REQUIRED FORENSIC ANALYSIS & OUTPUT SCHEMA ---",
            "Evaluate Image #1 (Customer Evidence) against the product visual profile and specifications.",
            "Return strictly a JSON object with this EXACT structure:",
            "{",
            '  "capture_assessment": {',
            '    "type": "PHYSICAL_PHOTO|SCREEN_PHOTO|SCREENSHOT|COMPOSITE|UNCLEAR",',
            '    "capture_context": "PHYSICAL_PHOTO|SCREEN_DISPLAY|SCREENSHOT|DIGITAL_IMAGE|UNCLEAR",',
            '    "screen_artifact_detected": false,',
            '    "physical_scene_detected": true,',
            '    "confidence": 0.9,',
            '    "observations": ["screen bezel visible", "moire patterns", "reflections"]',
            '  },',
            '  "product_identity": {',
            '    "apparent_product_type": "string category/name",',
            '    "matches_trusted_product": "MATCH|MISMATCH|UNCERTAIN|NOT_APPLICABLE",',
            '    "confidence": 0.85,',
            '    "identifying_features_visible": ["branding", "color", "shape"],',
            '    "notes": "forensic description"',
            '  },',
            '  "image_quality": {',
            '    "is_clear": true,',
            '    "lighting": "good|dim|harsh|unclear",',
            '    "blur_detected": false,',
            '    "resolution_adequate": true,',
            '    "overall": "GOOD|ACCEPTABLE|POOR|INSUFFICIENT",',
            '    "product_visibility": "CLEAR|PARTIAL|UNCLEAR|NOT_VISIBLE",',
            '    "issues": ["blur", "darkness", "crop"]',
            '  },',
            '  "product_consistency": {',
            '    "is_same_product_type": "observed|not_observed|unclear",',
            '    "matched_reference_angle": "FRONT|BACK|LEFT|RIGHT|MULTIPLE|NONE",',
            '    "brand_marking_visible": "observed|not_observed|not_visible|unclear",',
            '    "color_consistency": "consistent|inconsistent|unclear",',
            '    "shape_consistency": "consistent|inconsistent|unclear",',
            '    "notes": "comparison with visual profile"',
            '  },',
            '  "visible_condition": {',
            '    "claimed_damage_visible": "observed|not_observed|not_visible|unclear",',
            '    "damage_type_detected": "crack|scratch|tear|dent|none",',
            '    "damage_location": "front left corner|none",',
            '    "damage_severity_observation": "minor|moderate|severe|none",',
            '    "notes": "condition observations"',
            '  },',
            '  "key_visual_observations": [',
            '    "Objective observation 1",',
            '    "Objective observation 2"',
            '  ],',
            '  "uncertainties": [',
            '    "Limitation or occluded area 1"',
            '  ],',
            '  "overall_visual_confidence": 0.88',
            "}",
            "",
            "CRITICAL: Produce VALID JSON ONLY.",
        ])

        full_prompt = "\n".join(prompt_lines)

        payload = {
            "model": self.model_name,
            "messages": [
                {
                    "role": "user",
                    "content": full_prompt,
                    "images": images_b64,
                }
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_ctx": 8192,
            },
        }

        start_t = time.time()
        logger.info(
            "Invoking Qwen2.5-VL 3B model %s for customer evidence analysis (%d image payload)",
            self.model_name,
            len(images_b64),
        )

        response_text = ""
        last_exc = None
        for attempt in range(2):
            try:
                with httpx.Client(timeout=120.0) as client:
                    resp = client.post(f"{self.ollama_url}/api/chat", json=payload)
                    dur_ms = int((time.time() - start_t) * 1000)

                    # Diagnostic logging
                    logger.info(
                        "QWEN_EVIDENCE_ANALYSIS_HTTP: attempt=%d, status=%d, dur_ms=%d, payload_images=%d",
                        attempt + 1,
                        resp.status_code,
                        dur_ms,
                        len(images_b64),
                    )

                    if resp.status_code != 200:
                        raise RuntimeError(f"Ollama API returned HTTP status {resp.status_code}: {resp.text[:300]}")

                    res_json = resp.json()
                    msg = res_json.get("message") or {}
                    response_text = (msg.get("content") or "").strip()

                    logger.info(
                        "QWEN_DIAGNOSTICS: model=%s, res_keys=%s, msg_keys=%s, content_len=%d, done=%s",
                        res_json.get("model", self.model_name),
                        list(res_json.keys()),
                        list(msg.keys()) if isinstance(msg, dict) else [],
                        len(response_text),
                        res_json.get("done", False),
                    )
                    if response_text:
                        break
                    else:
                        logger.warning("Attempt %d: Qwen returned empty response text. Retrying after 1s...", attempt + 1)
                        time.sleep(1.0)
            except Exception as exc:
                last_exc = exc
                logger.warning("Attempt %d failed: %s", attempt + 1, exc)
                if attempt == 0:
                    time.sleep(1.0)

        if not response_text:
            if last_exc:
                raise RuntimeError(f"Local Qwen2.5-VL vision analysis failed: {last_exc}") from last_exc
            raise RuntimeError("Qwen2.5-VL returned empty response text after retry")

        return self._parse_and_validate_response(response_text)

    def _clean_json_markdown(self, response_text: str) -> str:
        """Strip markdown fences if present."""
        clean_json_str = response_text.strip()
        if clean_json_str.startswith("```"):
            lines = clean_json_str.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_json_str = "\n".join(lines).strip()
        return clean_json_str

    def _parse_and_validate_response(self, response_text: str) -> VisualAnalysisResult:
        """Parse raw response text, strip markdown formatting if present, and validate schema."""
        clean_json_str = self._clean_json_markdown(response_text)

        try:
            data = json.loads(clean_json_str)
        except Exception as exc:
            logger.warning("Failed to parse Qwen vision JSON output directly: %s. Output: %s", exc, clean_json_str[:300])
            try:
                start_idx = clean_json_str.find("{")
                end_idx = clean_json_str.rfind("}")
                if start_idx != -1 and end_idx != -1:
                    data = json.loads(clean_json_str[start_idx : end_idx + 1])
                else:
                    raise
            except Exception as inner_exc:
                raise ValueError(f"Malformed JSON from Qwen2.5-VL vision model: {exc}") from inner_exc

        capture_data = data.get("capture_assessment") or data.get("evidence_capture_assessment") or {}
        capture_type = str(capture_data.get("type") or capture_data.get("capture_context") or "PHYSICAL_PHOTO").upper()
        if "SCREEN" in capture_type and "PHOTO" in capture_type:
            capture_type = "SCREEN_PHOTO"
        elif "SCREEN" in capture_type:
            capture_type = "SCREENSHOT"
        elif "PHYSICAL" in capture_type:
            capture_type = "PHYSICAL_PHOTO"
        else:
            capture_type = "UNCLEAR"

        capture_assessment = EvidenceCaptureAssessment(
            type=capture_type,
            capture_context=capture_type,
            screen_artifact_detected=bool(capture_data.get("screen_artifact_detected", False)),
            physical_scene_detected=bool(capture_data.get("physical_scene_detected", True)),
            confidence=float(capture_data.get("confidence", 0.85)),
            observations=list(capture_data.get("observations") or []),
        )

        identity_data = data.get("product_identity") or {}
        product_identity = ProductIdentityAnalysis(
            apparent_product_type=str(identity_data.get("apparent_product_type") or "Observed item"),
            matches_trusted_product=str(identity_data.get("matches_trusted_product") or "UNCERTAIN").upper(),
            confidence=float(identity_data.get("confidence", 0.8)),
            identifying_features_visible=list(identity_data.get("identifying_features_visible") or []),
            notes=identity_data.get("notes"),
        )

        quality_data = data.get("image_quality") or {}
        image_quality = ImageQualityAnalysis(
            is_clear=bool(quality_data.get("is_clear", True)),
            lighting=str(quality_data.get("lighting", "good")),
            blur_detected=bool(quality_data.get("blur_detected", False)),
            resolution_adequate=bool(quality_data.get("resolution_adequate", True)),
            overall=str(quality_data.get("overall", "GOOD")).upper(),
            product_visibility=str(quality_data.get("product_visibility", "CLEAR")).upper(),
            issues=list(quality_data.get("issues") or []),
        )

        consistency_data = data.get("product_consistency") or {}
        product_consistency = ProductConsistencyAnalysis(
            is_same_product_type=str(consistency_data.get("is_same_product_type", "observed")),
            matched_reference_angle=consistency_data.get("matched_reference_angle"),
            brand_marking_visible=str(consistency_data.get("brand_marking_visible", "observed")),
            color_consistency=str(consistency_data.get("color_consistency", "consistent")),
            shape_consistency=str(consistency_data.get("shape_consistency", "consistent")),
            notes=consistency_data.get("notes"),
        )

        condition_data = data.get("visible_condition") or data.get("condition") or {}
        visible_condition = VisibleConditionAnalysis(
            claimed_damage_visible=str(condition_data.get("claimed_damage_visible", "not_visible")),
            damage_type_detected=condition_data.get("damage_type_detected"),
            damage_location=condition_data.get("damage_location"),
            damage_severity_observation=condition_data.get("damage_severity_observation"),
            notes=condition_data.get("notes"),
        )

        key_observations = list(data.get("key_visual_observations") or [])
        uncertainties = list(data.get("uncertainties") or [])
        overall_conf = float(data.get("overall_visual_confidence") or 0.85)

        return VisualAnalysisResult(
            image_quality=image_quality,
            product_consistency=product_consistency,
            visible_condition=visible_condition,
            capture_assessment=capture_assessment,
            product_identity=product_identity,
            key_visual_observations=key_observations,
            uncertainties=uncertainties,
            overall_visual_confidence=overall_conf,
        )


# Global singleton service instance
qwen_vision_service = QwenVisionService()
