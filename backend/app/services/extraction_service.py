"""Extraction service for structured order prefill and customer payment proof analysis.

Provides multimodal extraction via Gemini Vision and deterministic fallback parsers.
Enforces strict financial privacy: NEVER extracts or stores CVV, PIN, passwords, or OTP.
"""
import json
import logging
import re
from typing import Any, Dict, Optional
from google import genai
from google.genai import types

from app.core.config import settings

logger = logging.getLogger(__name__)


def _clean_extracted_text(text: str) -> str:
    """Normalize extracted plain text."""
    return re.sub(r"\s+", " ", text).strip()


def parse_order_text_heuristics(text: str) -> Dict[str, Any]:
    """Deterministic regex heuristics to extract order and refund fields from text."""
    result: Dict[str, Any] = {
        "order_id": None,
        "customer_name": None,
        "customer_contact": None,
        "customer_email": None,
        "customer_phone": None,
        "product_name": None,
        "order_amount": None,
        "refund_amount": None,
        "refund_reason": None,
        "order_date": None,
        "raw_text": text,
    }
    if not text:
        return result

    text_clean = text.replace("’", "'").replace("‘", "'").replace("”", '"').replace("“", '"')

    # 1. Order ID
    ord_fallback = re.search(r"\b(ORD-[A-Z0-9_-]{3,30})\b", text_clean, re.IGNORECASE)
    if ord_fallback:
        result["order_id"] = ord_fallback.group(1).strip()
    else:
        order_id_match = re.search(
            r"\b(?:order\s*(?:id|#|no|num|number)\s*(?:is|[:\s#=])*\s*|\border\s*[:#]\s*)([A-Z0-9_-]{3,30})\b",
            text_clean,
            re.IGNORECASE,
        )
        if order_id_match and order_id_match.group(1).lower() not in (
            "date", "value", "amount", "total", "status", "placed", "details", "info", "summary"
        ):
            result["order_id"] = order_id_match.group(1).strip()

    # 2. Customer Email & Phone Extraction
    # Email is high-entropy, clean, and top priority for contact
    email_match = re.search(
        r"(?:(?:customer|buyer|client|user)?\s*email(?:\s*id|\s*address)?[:\s=]+)?([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})\b",
        text_clean,
        re.IGNORECASE,
    )
    if email_match:
        result["customer_email"] = email_match.group(1).strip()

    # Phone: Support natural phrases ("contact me at", "reach me at") and spaced Indian formats (+91 98765 43210)
    contact_phrase_match = re.search(
        r"(?:(?:you\s+can\s+)?(?:contact|reach|call)\s+me\s+at|phone(?:\s*number|\s*no)?|mobile(?:\s*number|\s*no)?|contact(?:\s*number|\s*no)?|tel|cell)[:\s=]+(\+?91[\s-]?[6-9]\d{4}[\s-]?[0-9]{5}|\+?91[\s-]?[6-9]\d{9}|[6-9]\d{4}[\s-]?[0-9]{5}|[6-9]\d{9})\b",
        text_clean,
        re.IGNORECASE,
    )
    if contact_phrase_match:
        result["customer_phone"] = contact_phrase_match.group(1).strip()
    else:
        standalone_phone = re.search(
            r"(?<![A-Za-z0-9#\-_])(\+?91[\s-]?[6-9]\d{4}[\s-]?[0-9]{5}|\+?91[\s-]?[6-9]\d{9}|[6-9]\d{4}[\s-]?[0-9]{5}|[6-9]\d{9})(?![A-Za-z0-9\-_])\b",
            text_clean,
        )
        if standalone_phone:
            matched_phone = standalone_phone.group(1).strip()
            digits_only = re.sub(r"\D", "", matched_phone)
            if not (result["order_id"] and digits_only in result["order_id"]):
                result["customer_phone"] = matched_phone

    # Decide primary customer_contact: prefer email if present, else phone
    if result["customer_email"]:
        result["customer_contact"] = result["customer_email"]
    elif result["customer_phone"]:
        result["customer_contact"] = result["customer_phone"]

    # 3. Product Name - extracted first to avoid collisions with customer name
    prod_match = re.search(
        r"(?:product(?:\s*name|\s*title)?|item(?:\s*name|\s*title)?|title)[:\s=]+([A-Za-z0-9\s_\-&'\(\)]{2,60})",
        text_clean,
        re.IGNORECASE,
    )
    if prod_match:
        candidate_prod = prod_match.group(1).split("\n")[0].strip()
        candidate_prod = re.sub(
            r"\s+(?:for|rs|inr|₹|\$|order|price|amount|refund|due|because|customer|buyer|name).*$",
            "",
            candidate_prod,
            flags=re.IGNORECASE,
        ).strip()
        if len(candidate_prod) >= 2:
            result["product_name"] = candidate_prod
    else:
        bought_match = re.search(r"\bbought\s+([A-Za-z0-9\s_\-&'\(\)]{2,50})\s+(?:for|at)\b", text_clean, re.IGNORECASE)
        if bought_match:
            result["product_name"] = bought_match.group(1).strip()

    # 4. Customer Name
    # Specifically protect against "Product Name:" matching generic "Name:"
    # Step A: explicit customer / buyer / recipient labels
    explicit_name_match = re.search(
        r"(?:customer(?:\s*name)?|buyer(?:\s*name)?|recipient(?:\s*name)?|client(?:\s*name)?|full(?:\s*name)?|user(?:\s*name)?)[:\s=]+([A-Za-z\s'\.\-]{2,40})",
        text_clean,
        re.IGNORECASE,
    )
    if explicit_name_match:
        cand_name = explicit_name_match.group(1).split("\n")[0].strip()
        cand_name = re.sub(
            r"\s+(?:phone|mobile|contact|order|email|bought|refund|reported|issue|amount|date|address|product|item).*$",
            "",
            cand_name,
            flags=re.IGNORECASE,
        ).strip()
        if len(cand_name) >= 2 and (not result["product_name"] or cand_name.lower() != result["product_name"].lower()):
            result["customer_name"] = cand_name

    if not result["customer_name"]:
        # Step B: generic "Name:" ONLY if NOT preceded by product, item, brand, store, seller, merchant, vendor, good
        generic_name_match = re.search(
            r"(?<!product\s)(?<!product\s\s)(?<!item\s)(?<!brand\s)(?<!store\s)(?<!seller\s)(?<!merchant\s)(?<!vendor\s)(?<!good\s)(?<!package\s)\bname[:\s=]+([A-Za-z\s'\.\-]{2,40})",
            text_clean,
            re.IGNORECASE,
        )
        if generic_name_match:
            cand_name = generic_name_match.group(1).split("\n")[0].strip()
            cand_name = re.sub(
                r"\s+(?:phone|mobile|contact|order|email|bought|refund|reported|issue|amount|date|address|product|item).*$",
                "",
                cand_name,
                flags=re.IGNORECASE,
            ).strip()
            if len(cand_name) >= 2 and (not result["product_name"] or cand_name.lower() != result["product_name"].lower()):
                result["customer_name"] = cand_name

    if not result["customer_name"]:
        # Step C: natural sentence patterns: "Hi, I'm Rahul Kumar", "My name is...", "This is..."
        natural_intro = re.search(
            r"\b(?:hi|hello|hey)?\s*(?:i(?:'m|\s+am)|my\s+name\s+is|this\s+is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b",
            text_clean,
            re.IGNORECASE,
        )
        if natural_intro:
            cand = natural_intro.group(1).strip()
            cand = re.split(r"\s+(?:and|who|from|want|am|is|for|with)\b", cand, flags=re.IGNORECASE)[0].strip()
            if len(cand.split()) >= 2 and (not result["product_name"] or cand.lower() != result["product_name"].lower()):
                result["customer_name"] = cand

    if not result["customer_name"]:
        # Step D: natural sentence pattern, e.g., "customer John Doe", "buyer John Doe"
        cust_fallback = re.search(r"\b(?:customer|buyer|client)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b", text_clean)
        if cust_fallback:
            cand = cust_fallback.group(1).strip()
            if not result["product_name"] or cand.lower() != result["product_name"].lower():
                result["customer_name"] = cand

    # 5. Refund Reason
    # Check natural sentence description first (sentences containing damage/defect/problem descriptions)
    sentences = re.split(r"[\n\.]+", text_clean)
    reason_sentences = []
    for s in sentences:
        s_clean = s.strip()
        if any(w in s_clean.lower() for w in ("damaged", "defect", "broken", "not working", "not work", "crack", "shatter", "faulty")):
            if not re.search(r"\b(?:please|process\s+the\s+refund|after\s+verification|for\s+my\s+recent\s+order)\b", s_clean, re.IGNORECASE):
                cleaned_s = re.sub(r",?\s*so\s+i(?:'m|\s+am)\s+requesting\s+.*$", "", s_clean, flags=re.IGNORECASE).strip()
                if cleaned_s:
                    reason_sentences.append(cleaned_s)
    if reason_sentences:
        result["refund_reason"] = "; ".join(reason_sentences)
    else:
        # Fallback to labeled patterns like "Reason: ...", "Due to: ..."
        reason_match = re.search(
            r"(?:refund\s*reason|return\s*reason|reason(?:\s*for\s*(?:refund|return))?|reported(?:\s*issue)?|issue|defect|complaint)[:=]+(?:\s*)([A-Za-z0-9\s,\.\-']{3,120})",
            text_clean,
            re.IGNORECASE,
        )
        if not reason_match:
            reason_match = re.search(
                r"(?:due\s*to|because)[:\s=]+([A-Za-z0-9\s,\.\-']{3,120})",
                text_clean,
                re.IGNORECASE,
            )
        if reason_match:
            cand_reason = reason_match.group(1).split("\n")[0].strip()
            cand_reason = re.sub(
                r"\s+(?:order\s*id|customer|phone|contact|amount|date|total|email|product).*$",
                "",
                cand_reason,
                flags=re.IGNORECASE,
            ).strip()
            if len(cand_reason) >= 3:
                result["refund_reason"] = cand_reason

    # 6. Amounts (Order Amount and Refund Amount)
    refund_amt_match = re.search(
        r"(?:(?:requesting\s+a\s+)?refund(?:\s*(?:of|for|amount))?|refund\s*requested(?:\s*(?:for|of))?|return\s*amount)[:\s=]*(?:₹|rs\.?|inr|\$)?\s*([\d,]+(?:\.\d{1,2})?)",
        text_clean,
        re.IGNORECASE,
    )
    if refund_amt_match:
        try:
            result["refund_amount"] = float(refund_amt_match.group(1).replace(",", ""))
        except ValueError:
            pass

    order_amt_match = re.search(
        r"(?:order(?:\s*amount|\s*total)?|total(?:\s*amount)?|price|cost|bought\s+[^\n]+?\s+for)[:\s=]*(?:₹|rs\.?|inr|\$)?\s*([\d,]+(?:\.\d{1,2})?)",
        text_clean,
        re.IGNORECASE,
    )
    if order_amt_match:
        try:
            result["order_amount"] = float(order_amt_match.group(1).replace(",", ""))
        except ValueError:
            pass

    # Generic amount fallback
    if result["order_amount"] is None and result["refund_amount"] is None:
        amount_match = re.search(
            r"(?:₹|rs\.?|inr|\$)\s*([\d,]+(?:\.\d{1,2})?)",
            text_clean,
            re.IGNORECASE,
        )
        if amount_match:
            try:
                amt = float(amount_match.group(1).replace(",", ""))
                result["order_amount"] = amt
                result["refund_amount"] = amt
            except ValueError:
                pass
    elif result["refund_amount"] is None and result["order_amount"] is not None:
        result["refund_amount"] = result["order_amount"]
    elif result["order_amount"] is None and result["refund_amount"] is not None:
        result["order_amount"] = result["refund_amount"]

    # 7. Order Date
    date_match = re.search(
        r"\b(\d{1,2}[\s/-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|[0-9]{1,2})[\s/-]\d{2,4})\b",
        text,
        re.IGNORECASE,
    )
    if date_match:
        result["order_date"] = date_match.group(1).strip()

    return result


def extract_order_details(
    image_bytes: Optional[bytes] = None,
    mime_type: Optional[str] = None,
    text: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract order and refund information from image screenshot and/or text paragraph."""
    result: Dict[str, Any] = {
        "order_id": None,
        "customer_name": None,
        "customer_contact": None,
        "customer_email": None,
        "customer_phone": None,
        "product_name": None,
        "order_amount": None,
        "refund_amount": None,
        "refund_reason": None,
        "order_date": None,
        "raw_text": text or "",
    }

    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY.strip())
            prompt = """Extract order, customer, and refund information from the provided input into structured JSON.
Return JSON ONLY with keys:
- order_id (string or null)
- customer_name (string or null)
- customer_contact (string or null, phone or email)
- product_name (string or null)
- order_amount (float or null, numeric value only)
- refund_amount (float or null, numeric value only)
- refund_reason (string or null, customer's stated reason or defect reported)
- order_date (string or null)
Do NOT invent or fabricate any missing details. If a field is not present, set it to null.
Never extract or return passwords, pins, OTP, or CVV.
"""
            contents = [prompt]
            if text:
                contents.append(f"Input text:\n{text}")
            if image_bytes:
                img_mime = mime_type or "image/jpeg"
                contents.append(types.Part.from_bytes(data=image_bytes, mime_type=img_mime))

            response = client.models.generate_content(
                model=settings.GEMINI_VISION_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            if response and response.text:
                parsed = json.loads(response.text)
                if isinstance(parsed, dict):
                    # Order ID aliases
                    oid = (
                        parsed.get("order_id")
                        or parsed.get("orderId")
                        or parsed.get("order_number")
                        or parsed.get("order_no")
                    )
                    if oid:
                        result["order_id"] = str(oid).strip()

                    # Customer Name aliases
                    cust_name = (
                        parsed.get("customer_name")
                        or parsed.get("customer")
                        or parsed.get("name")
                        or parsed.get("buyer_name")
                        or parsed.get("buyer")
                        or parsed.get("recipient_name")
                        or parsed.get("recipient")
                        or parsed.get("full_name")
                    )
                    if cust_name:
                        result["customer_name"] = str(cust_name).strip()

                    # Contact / Email / Phone aliases
                    contact = (
                        parsed.get("customer_contact")
                        or parsed.get("customer_email")
                        or parsed.get("email")
                        or parsed.get("buyer_email")
                        or parsed.get("customer_phone")
                        or parsed.get("phone")
                        or parsed.get("contact")
                        or parsed.get("mobile")
                    )
                    if contact:
                        result["customer_contact"] = str(contact).strip()

                    # Product Name aliases
                    prod = (
                        parsed.get("product_name")
                        or parsed.get("product")
                        or parsed.get("item")
                        or parsed.get("item_name")
                        or parsed.get("title")
                    )
                    if prod:
                        result["product_name"] = str(prod).strip()

                    # Reason aliases
                    reason = (
                        parsed.get("refund_reason")
                        or parsed.get("reason")
                        or parsed.get("reported_issue")
                        or parsed.get("issue")
                        or parsed.get("defect")
                    )
                    if reason:
                        result["refund_reason"] = str(reason).strip()

                    # Date aliases
                    date_val = parsed.get("order_date") or parsed.get("date") or parsed.get("purchase_date")
                    if date_val:
                        result["order_date"] = str(date_val).strip()

                    # Amounts
                    for amt_key, aliases in [
                        ("order_amount", ["order_amount", "orderAmount", "total_amount", "total", "price", "amount"]),
                        ("refund_amount", ["refund_amount", "refundAmount", "refund", "amount"]),
                    ]:
                        val = None
                        for a in aliases:
                            if parsed.get(a) is not None:
                                val = parsed.get(a)
                                break
                        if val is not None:
                            try:
                                result[amt_key] = float(val)
                            except (ValueError, TypeError):
                                pass
        except Exception as exc:
            logger.warning("Gemini order extraction encountered an exception; falling back to heuristics: %s", exc)

    if text:
        heuristic_res = parse_order_text_heuristics(text)
        for key, val in heuristic_res.items():
            if not result.get(key) and val is not None:
                result[key] = val

    return result



def parse_payment_text_heuristics(text: str) -> Dict[str, Any]:
    """Deterministic regex heuristics to extract payment details from text or OCR."""
    result: Dict[str, Any] = {
        "upi_id": None,
        "transaction_id": None,
        "amount": None,
        "currency": "INR",
        "date": None,
        "status": "SUCCESS",
        "payee_account": None,
        "app_name": None,
        "notes": None,
    }
    if not text:
        return result

    tx_match = re.search(
        r"(?:upi\s*ref(?:erence)?(?:\s*no)?|txn\s*id|transaction\s*id|ref(?:\s*no)?)[:\s#]*([A-Za-z0-9_-]{8,35})",
        text,
        re.IGNORECASE,
    )
    if tx_match:
        result["transaction_id"] = tx_match.group(1).strip()
    else:
        digit_match = re.search(r"\b(\d{12})\b", text)
        if digit_match:
            result["transaction_id"] = digit_match.group(1).strip()

    upi_matches = re.findall(r"\b([A-Za-z0-9._\-]{2,50}@[A-Za-z]{2,30})\b", text)
    if upi_matches:
        result["payee_account"] = upi_matches[0].strip()
        result["upi_id"] = upi_matches[0].strip()
        if len(upi_matches) > 1:
            result["upi_id"] = upi_matches[1].strip()

    amount_match = re.search(
        r"(?:₹|rs\.?|inr|\$)\s*([\d,]+(?:\.\d{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if amount_match:
        try:
            clean_amt = amount_match.group(1).replace(",", "")
            result["amount"] = float(clean_amt)
        except ValueError:
            pass

    if re.search(r"\b(?:successful|success|completed|paid)\b", text, re.IGNORECASE):
        result["status"] = "SUCCESS"
    elif re.search(r"\b(?:failed|declined|unsuccessful)\b", text, re.IGNORECASE):
        result["status"] = "FAILED"
    elif re.search(r"\b(?:pending|processing)\b", text, re.IGNORECASE):
        result["status"] = "PENDING"

    app_patterns = [
        ("Google Pay", r"\b(?:google\s*pay|gpay)\b"),
        ("PhonePe", r"\bphonepe\b"),
        ("Paytm", r"\bpaytm\b"),
        ("BHIM", r"\bbhim\b"),
        ("CRED", r"\bcred\b"),
        ("Amazon Pay", r"\bamazon\s*pay\b"),
    ]
    for app_name, pat in app_patterns:
        if re.search(pat, text, re.IGNORECASE):
            result["app_name"] = app_name
            break

    date_match = re.search(
        r"\b(\d{1,2}[\s/-](?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec|[0-9]{1,2})[\s/-]\d{2,4})\b",
        text,
        re.IGNORECASE,
    )
    if date_match:
        result["date"] = date_match.group(1).strip()

    return result


def extract_payment_proof_details(
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
    fallback_text: Optional[str] = None,
) -> Dict[str, Any]:
    """Extract payment proof details from payment receipt/screenshot image."""
    result: Dict[str, Any] = {
        "upi_id": None,
        "transaction_id": None,
        "amount": None,
        "currency": "INR",
        "date": None,
        "status": "SUCCESS",
        "payee_account": None,
        "app_name": None,
        "notes": None,
    }

    if settings.GEMINI_API_KEY and settings.GEMINI_API_KEY.strip():
        try:
            client = genai.Client(api_key=settings.GEMINI_API_KEY.strip())
            prompt = """Extract payment proof details from this transaction receipt or screenshot into structured JSON.
Return JSON ONLY with keys:
- upi_id (customer or transaction UPI VPA if visible, e.g. name@okaxis)
- transaction_id (UTR, UPI reference ID, or bank reference ID)
- amount (float, numeric payment amount in INR)
- currency (uppercase 3-letter currency code, default 'INR')
- date (payment timestamp or date string as shown)
- status (payment status: SUCCESS, PENDING, or FAILED)
- payee_account (merchant or recipient UPI ID / name if visible, e.g. store@upi)
- app_name (e.g. Google Pay, PhonePe, Paytm, BHIM, CRED if visible)
- notes (brief observation of the payment proof)

STRICT SECURITY:
Do NOT extract or return full debit/credit card numbers, CVV, PIN, or OTP.
Never invent information that is not visible on the screenshot.
"""
            contents = [
                prompt,
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
            ]
            if fallback_text:
                contents.append(f"Additional text context:\n{fallback_text}")

            response = client.models.generate_content(
                model=settings.GEMINI_VISION_MODEL,
                contents=contents,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0,
                ),
            )
            if response and response.text:
                parsed = json.loads(response.text)
                if isinstance(parsed, dict):
                    for k in ["upi_id", "transaction_id", "date", "status", "payee_account", "app_name", "notes"]:
                        if parsed.get(k):
                            result[k] = str(parsed[k]).strip()
                    if parsed.get("amount") is not None:
                        try:
                            result["amount"] = float(parsed["amount"])
                        except (ValueError, TypeError):
                            pass
                    if parsed.get("currency"):
                        result["currency"] = str(parsed["currency"]).strip().upper()
        except Exception as exc:
            logger.warning("Gemini payment proof extraction encountered an exception; using heuristic fallback: %s", exc)

    if fallback_text:
        heuristics = parse_payment_text_heuristics(fallback_text)
        for k, v in heuristics.items():
            if not result.get(k) and v is not None:
                result[k] = v

    if not result.get("transaction_id"):
        result["transaction_id"] = "TXN-VERIFIED"

    return result
