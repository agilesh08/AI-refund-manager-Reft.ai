"""Local AI reasoning service using Ollama and Llama 3.2 3B."""
import json
import logging
import time
from typing import Any, Dict, Optional
import httpx

from app.core.config import settings
from app.schemas.reasoning import ReasoningResult
from app.schemas.evidence_fusion import FusionExplanation

logger = logging.getLogger(__name__)

LLAMA_FUSION_EXPLANATION_SYSTEM_INSTRUCTION = """You are a neutral, objective AI explanation component for a refund evidence verification system.
Your SOLE task is to translate pre-computed, deterministic evidence fusion facts into a clear, concise, professional human-readable explanation.

CRITICAL RULES:
1. You MUST NOT determine or alter the verification assessment state.
2. You MUST NOT calculate or alter confidence scores.
3. You MUST NOT invent any facts, evidence, or contradictions.
4. You MUST NOT declare a customer to be fraudulent, fake, lying, or dishonest.
5. You MUST NOT approve or reject any refund claim.
6. Use strictly objective, polite, professional language suitable for merchant review.
7. Return ONLY valid JSON matching the exact schema.

OUTPUT SCHEMA:
{
  "summary": "Concise high-level neutral summary of the assessment findings",
  "key_points": [
    "Verified fact or observation 1",
    "Verified fact or observation 2"
  ],
  "recommended_review": "Professional, actionable recommendation for merchant human review"
}
"""

LLAMA_REASONING_SYSTEM_INSTRUCTION = """You are an evidence-verification reasoning engine for a refund verification system.
Your job is to identify the next most useful piece of evidence needed to resolve uncertainty.
You reason strictly over the structured facts provided to you.

CRITICAL RULES & EVIDENCE-AWARE FOLLOW-UP STRATEGY:
1. FAIL-SAFE RULE FOR VISUAL ANALYSIS:
   - If visual evidence is required by the workflow and Gemini visual analysis failed or is missing (visual_analysis_status == 'FAILED' or has_failed_visual_analysis is true or status == 'UNAVAILABLE'):
     Under NO circumstance may you choose 'ACCEPT_EVIDENCE'. You must NEVER treat unanalyzed or failed visual evidence as verified.
     Instead, choose 'REQUEST_MORE_EVIDENCE' (with specific, polite guidance) or 'CONTINUE_WORKFLOW'.
2. DO NOT OVERRIDE GEMINI OBSERVATIONS:
   - You must strictly respect Gemini's structured observations.
   - If Gemini observes 'SCREEN_DISPLAY_APPEARANCE' or 'SCREENSHOT_APPEARANCE', you must NOT claim the photo is direct physical evidence.
   - If Gemini observes a product mismatch ('MISMATCH' or 'is_same_product_type' == 'not_observed'), you must NOT claim the product matches.
3. NEVER ACCUSE THE CUSTOMER OF FRAUD:
   - You must never determine whether a customer is fraudulent, fake, lying, or dishonest. Never accuse the customer.
   - You must never make a final refund approval or rejection. Sole authoritative decision is made by the merchant.
4. You must not infer facts that are not present. Never invent facts or arbitrary workflow steps.
5. You may ONLY select one of the allowed actions from the closed vocabulary:
   - ACCEPT_EVIDENCE
   - REQUEST_MORE_EVIDENCE
   - CONTINUE_WORKFLOW
   - COMPLETE_VERIFICATION
6. When action is REQUEST_MORE_EVIDENCE — FOLLOW-UP TYPE DECISION TREE:
   You MUST choose the MOST EFFICIENT type. Follow this strict decision order:

   A. Use MCQ when:
      - The unknown fact has a small number of discrete correct answers (3-5 options).
      - Examples: "Was the product packaging damaged on arrival?", "Which item is missing?",
        "Did the product stop working immediately after unboxing or after some time?",
        "Where did you purchase the product?", "What condition was the product when received?"
      - Set 'requested_evidence_type': "MCQ".
      - Put the question in 'question' and exactly 3-5 options in 'options'.
      - DO NOT ask for MCQ if the customer already answered a similar MCQ.

   B. Use CUSTOMER_TEXT when:
      - The unknown fact requires a free-form description (more than 5 possible answers).
      - Examples: "Please describe the damage you observed.", "What was the exact error message?",
        "Describe the missing component.", "When did the product stop working?"
      - Set 'requested_evidence_type': "CUSTOMER_TEXT".
      - Put the specific question in 'question'.
      - DO NOT repeat a CUSTOMER_TEXT question that was already asked.

   C. Use CUSTOMER_IMAGE ONLY when:
      - Visual confirmation is genuinely required AND has not yet been provided.
      - No text answer could substitute for visual confirmation.
      - CLAIM-AWARE ALIGNMENT (CRITICAL):
        * You MUST align your follow-up request directly with the customer's stated refund reason.
        * If customer claimed "Received wrong product":
          You MUST request evidence showing the physical product received and its brand/model markings.
          NEVER ask for a photo of "damage", "cracks", or "defects" when the customer claimed wrong product!
          Example: "Please capture a clear photo of the physical product you received, including the full item and any visible model or brand markings."
        * If evidence appears to be photographed from another screen (laptop/phone display):
          Example: "Please capture a photo of the physical product directly using your phone camera. Avoid screenshots or photos of another screen."
        * If customer claimed "Product arrived damaged":
          Example: "Please capture a clear photo of the damaged area showing the crack or break clearly."
      - For OTHER CUSTOMER_IMAGE requests:
        * NEVER say "Upload another photo" or "Please upload another photo".
        * Specify EXACTLY what object, area, side, angle, label, or condition must be visible.
        * Put this exact guidance into 'reason'.


   D. DO NOT repeat same follow-up type consecutively:
      - If previous follow-up was CUSTOMER_IMAGE and customer responded, try MCQ or TEXT next.
      - Check 'adaptive_followups.history' to determine what was already asked.

7. USE PREVIOUS FOLLOW-UPS AND NEVER REPEAT:
   - Check 'adaptive_followups.history'.
   - NEVER ask the customer the same question twice.
   - NEVER request an evidence type that was already successfully supplied unless the previous evidence was explicitly insufficient or unclear.
8. You may ONLY select 'next_step_key' from the supplied 'allowed_next_steps' list.
9. Distinguish insufficient evidence from contradictory evidence. 'not_visible' does not mean absent. 'unclear' does not mean false.
10. Respect 'adaptive_followup_count' vs 'max_adaptive_followups'. If limit reached, choose CONTINUE_WORKFLOW or COMPLETE_VERIFICATION.
11. Return ONLY valid JSON matching the exact output schema. Do NOT echo or include input context fields such as 'previous_questions', 'previous_answers', 'deterministic_facts', 'adaptive_followups', or internal context. Do not include markdown codeblocks or commentary.

OUTPUT SCHEMA:
{
  "action": "ACCEPT_EVIDENCE" | "REQUEST_MORE_EVIDENCE" | "CONTINUE_WORKFLOW" | "COMPLETE_VERIFICATION",
  "reasoning_summary": "Objective factual reasoning synthesis",
  "confidence": 0.0 to 1.0,
  "next_step_key": "step_key_from_allowed_steps" | null,
  "requested_evidence_type": "CUSTOMER_IMAGE" | "MCQ" | "CUSTOMER_TEXT" | null,
  "reason": "Targeted, user-safe guidance for follow-up evidence" | null,
  "question": "Specific question for customer if MCQ or CUSTOMER_TEXT" | null,
  "options": ["Option 1", "Option 2", "Option 3"] | null,
  "missing_evidence": [
    {
      "evidence_type": "CUSTOMER_IMAGE" | "MCQ" | "CUSTOMER_TEXT",
      "purpose": "Why this evidence is required"
    }
  ],
  "observations_used": ["Fact 1", "Fact 2"],
  "limitations": ["Limitation 1", "Limitation 2"]
}
"""


def normalize_and_validate_reasoning_result(raw_data: Any) -> ReasoningResult:
    """Normalize dictionary data by ignoring extra fields, logging ignored keys, and validating ReasoningResult schema.

    Args:
        raw_data: Python dictionary or object from LLM response.

    Returns:
        Validated ReasoningResult instance.

    Raises:
        ValueError: If required fields are missing, malformed, or invalid.
    """
    if isinstance(raw_data, ReasoningResult):
        return raw_data

    if not isinstance(raw_data, dict):
        raise ValueError("Reasoning response data must be a dictionary object")

    allowed_fields = set(ReasoningResult.model_fields.keys())
    extra_keys = set(raw_data.keys()) - allowed_fields

    if extra_keys:
        logger.warning(
            "Ignoring unexpected extra fields in Ollama reasoning response: %s",
            sorted(list(extra_keys)),
        )

    normalized_data = {k: v for k, v in raw_data.items() if k in allowed_fields}

    try:
        return ReasoningResult.model_validate(normalized_data)
    except Exception as exc:
        logger.error("Reasoning response failed schema validation: %s (Raw Data: %s)", exc, raw_data)
        raise ValueError(f"Ollama response failed schema validation: {exc}")



class OllamaReasoningService:
    """Encapsulated service for invoking local Ollama LLM models."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        model_name: Optional[str] = None,
        timeout_seconds: Optional[int] = None,
        prompt_version: Optional[str] = None,
    ) -> None:
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model_name = model_name or settings.OLLAMA_MODEL_NAME
        self.timeout_seconds = timeout_seconds or settings.OLLAMA_TIMEOUT_SECONDS
        self.prompt_version = prompt_version or settings.LLAMA_REASONING_PROMPT_VERSION


    def check_health(self) -> bool:
        """Lightweight check to test if local Ollama HTTP server is reachable."""
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                return resp.status_code == 200
        except Exception as exc:
            logger.warning("Ollama health check failed at %s: %s", self.base_url, exc)
            return False

    def check_model_available(self) -> bool:
        """Verify if the configured model is installed locally in Ollama."""
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.base_url}/api/tags")
                if resp.status_code != 200:
                    return False
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", [])]
                # Match exact name or base prefix (e.g. llama3.2:1b or llama3.2:3b)
                target = self.model_name.lower()
                return any(m.lower() == target or m.lower().startswith(f"{target}:") for m in models)
        except Exception as exc:
            logger.warning("Failed to inspect Ollama models: %s", exc)
            return False

    def warmup_model(self) -> bool:
        """Warm up local Llama 3.2 1B reasoning model to preload weights into VRAM."""
        try:
            start_t = time.time()
            payload = {
                "model": self.model_name,
                "prompt": "Respond with JSON: {\"status\": \"ready\"}",
                "stream": False,
                "keep_alive": "24h",
                "options": {"temperature": 0.1},
            }
            with httpx.Client(timeout=15.0) as client:
                resp = client.post(f"{self.base_url}/api/generate", json=payload)
                if resp.status_code == 200:
                    dur = time.time() - start_t
                    logger.info("Llama 3.2 1B warmed up successfully in %.2fs", dur)
                    return True
        except Exception as exc:
            logger.warning("Llama 3.2 1B warm-up check failed: %s", exc)
        return False

    def generate_reasoning(self, structured_context: Dict[str, Any]) -> ReasoningResult:
        """Submit structured context to local Ollama and obtain validated ReasoningResult.

        Args:
            structured_context: Controlled reasoning context payload.

        Returns:
            ReasoningResult validated Pydantic model.

        Raises:
            RuntimeError: If Ollama is offline, model is missing, or response is invalid.
            TimeoutError: If Ollama execution exceeds configured timeout.
            ValueError: If response violates schema constraints.
        """
        # 1. Check local server availability
        if not self.check_health():
            raise RuntimeError(f"Local Ollama service is unreachable at {self.base_url}")

        # 2. Check model availability
        if not self.check_model_available():
            raise RuntimeError(
                f"Configured Ollama model '{self.model_name}' is unavailable on local Ollama server"
            )

        # 3. Formulate prompt messages
        messages = [
            {"role": "system", "content": LLAMA_REASONING_SYSTEM_INSTRUCTION},
            {
                "role": "user",
                "content": (
                    f"=== REASONING CONTEXT ({self.prompt_version}) ===\n"
                    f"{json.dumps(structured_context, indent=2)}\n\n"
                    "Analyze the structured facts, evaluate evidence sufficiency for the current step, "
                    "and select the next action strictly adhering to the JSON schema."
                ),
            },
        ]

        payload = {
            "model": self.model_name,
            "messages": messages,
            "format": ReasoningResult.model_json_schema(),
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        start_time = time.time()
        v_id = structured_context.get("verification", {}).get("verification_id", "unknown")
        context_bytes = len(json.dumps(structured_context))
        logger.info(
            "OLLAMA_REASONING_START: verification_id=%s, model=%s, context_bytes=%d",
            v_id,
            self.model_name,
            context_bytes,
        )

        # 4. Invoke Ollama API
        try:
            with httpx.Client(timeout=float(self.timeout_seconds)) as client:
                response = client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )
        except httpx.TimeoutException as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error(
                "OLLAMA_REASONING_TIMEOUT: verification_id=%s, timeout_s=%d, elapsed_ms=%.1f: %s",
                v_id,
                self.timeout_seconds,
                elapsed_ms,
                exc,
            )
            raise TimeoutError(f"Ollama reasoning call timed out after {self.timeout_seconds}s")
        except httpx.RequestError as exc:
            elapsed_ms = (time.time() - start_time) * 1000
            logger.error("Error communicating with Ollama after %.1fms: %s", elapsed_ms, exc)
            raise RuntimeError(f"Communication error with Ollama server: {exc}")

        elapsed_ms = (time.time() - start_time) * 1000
        logger.info(
            "OLLAMA_REASONING_COMPLETED: verification_id=%s, duration_ms=%.1f",
            v_id,
            elapsed_ms,
        )
        logger.info("OLLAMA_REASONING_DURATION_MS: %d", int(elapsed_ms))

        if response.status_code != 200:
            logger.error("Ollama returned error HTTP %d: %s", response.status_code, response.text)
            raise RuntimeError(f"Ollama returned HTTP error {response.status_code}: {response.text[:200]}")

        # 5. Extract raw response string
        resp_json = response.json()
        content = resp_json.get("message", {}).get("content", "")
        if not content or not content.strip():
            raise RuntimeError("Ollama returned an empty response")

        # 6. Parse JSON safely without swallowing invalid JSON errors
        try:
            raw_data = json.loads(content)
        except Exception as exc:
            logger.error("Ollama response contains invalid JSON: %s (Content: %s)", exc, content[:300])
            raise ValueError(f"Ollama returned invalid JSON: {exc}")

        # 7. Normalize dictionary and validate ReasoningResult schema
        return normalize_and_validate_reasoning_result(raw_data)

    def generate_fusion_explanation(self, fusion_summary: Dict[str, Any]) -> Optional[FusionExplanation]:
        """Submit structured fusion facts to local Ollama and obtain validated FusionExplanation.

        Fail-safe: If Ollama is unreachable, model is missing, execution times out,
        or response fails schema validation (e.g. prohibited language), logs a warning
        and returns None. The deterministic fusion result is NEVER compromised or blocked.
        """
        try:
            if not self.check_health():
                logger.warning("Ollama service unreachable; skipping human explanation")
                return None

            if not self.check_model_available():
                logger.warning("Ollama model '%s' unavailable; skipping human explanation", self.model_name)
                return None

            prompt_version = settings.LLAMA_FUSION_PROMPT_VERSION
            messages = [
                {"role": "system", "content": LLAMA_FUSION_EXPLANATION_SYSTEM_INSTRUCTION},
                {
                    "role": "user",
                    "content": (
                        f"=== DETERMINISTIC FUSION SUMMARY ({prompt_version}) ===\n"
                        f"{json.dumps(fusion_summary, indent=2)}\n\n"
                        "Generate an objective, neutral, professional human-readable explanation "
                        "summarizing the verified facts and recommending appropriate merchant review. "
                        "Strictly adhere to the JSON schema without altering the assessment state."
                    ),
                },
            ]

            payload = {
                "model": self.model_name,
                "messages": messages,
                "format": "json",
                "stream": False,
                "options": {
                    "temperature": 0.1,
                },
            }

            with httpx.Client(timeout=float(self.timeout_seconds)) as client:
                response = client.post(
                    f"{self.base_url}/api/chat",
                    json=payload,
                )

            if response.status_code != 200:
                logger.warning("Ollama explanation call returned HTTP %d", response.status_code)
                return None

            resp_json = response.json()
            content = resp_json.get("message", {}).get("content", "")
            if not content or not content.strip():
                logger.warning("Ollama explanation returned empty content")
                return None

            return FusionExplanation.model_validate_json(content)
        except Exception as exc:
            logger.warning("Failed to generate Llama fusion explanation (fail-safe active): %s", exc)
            return None

    def consolidate_product_visual_profile(
        self,
        product_info: Dict[str, Any],
        reference_analyses: List[Dict[str, Any]],
    ) -> ProductVisualProfileResult:
        """Consolidate 4 structured Qwen reference observations into a ProductVisualProfileResult using Llama 3.2 1B.

        NO images are passed to Llama—only text observations.
        """
        from app.schemas.product_reference_analysis import ProductVisualProfileResult

        system_instruction = (
            "You are a Product Visual Profile Consolidation Engine.\n"
            "Your job is to synthesize individual visual observations from 4 reference angles (FRONT, BACK, LEFT, RIGHT) "
            "into a single canonical Product Visual Profile for forensic evidence verification.\n\n"
            "CRITICAL RULES:\n"
            "1. Do NOT invent features or markings not present in the input reference observations.\n"
            "2. Preserve feature provenance (record which angle established each observation).\n"
            "3. Return ONLY valid JSON matching the exact output schema.\n"
        )

        compact_obs = []
        for ref in reference_analyses:
            if isinstance(ref, dict):
                compact_obs.append({
                    "angle": ref.get("angle"),
                    "summary": ref.get("summary"),
                    "metadata": ref.get("metadata", {}),
                })
            else:
                compact_obs.append(ref)

        user_content = (
            f"=== PRODUCT METADATA ===\n"
            f"Product Name: {product_info.get('name', 'Unknown')}\n"
            f"SKU: {product_info.get('sku', 'Unknown')}\n"
            f"Category: {product_info.get('category', 'Unknown')}\n"
            f"Description: {product_info.get('description', 'None')}\n\n"
            f"=== STRUCTURED REFERENCE OBSERVATIONS ({len(reference_analyses)} ANGLES) ===\n"
            f"{json.dumps(compact_obs, indent=2)}\n\n"
            f"Synthesize these observations into a Canonical Product Visual Profile adhering strictly to the JSON schema."
        )

        payload = {
            "model": self.model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_content},
            ],
            "format": ProductVisualProfileResult.model_json_schema(),
            "stream": False,
            "options": {
                "temperature": 0.1,
            },
        }

        start_time = time.time()
        logger.info(
            "OLLAMA_PROFILE_CONSOLIDATION_START: product_id=%s, model=%s, angle_count=%d",
            product_info.get("id", "unknown"),
            self.model_name,
            len(reference_analyses),
        )

        with httpx.Client(timeout=float(self.timeout_seconds)) as client:
            resp = client.post(f"{self.base_url}/api/chat", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"Ollama returned HTTP error {resp.status_code}: {resp.text[:200]}")

            resp_json = resp.json()
            content = resp_json.get("message", {}).get("content", "").strip()

            if not content:
                raise RuntimeError("Llama returned empty profile consolidation response")

            # Strip markdown code blocks if present
            clean_str = content
            if clean_str.startswith("```"):
                lines = clean_str.splitlines()
                if lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].startswith("```"):
                    lines = lines[:-1]
                clean_str = "\n".join(lines).strip()

            raw_data = json.loads(clean_str)
            dur_ms = int((time.time() - start_time) * 1000)
            logger.info("OLLAMA_PROFILE_CONSOLIDATION_SUCCESS in %dms", dur_ms)
            return ProductVisualProfileResult.model_validate(raw_data)


# Global singleton instance
ollama_reasoning_service = OllamaReasoningService()
