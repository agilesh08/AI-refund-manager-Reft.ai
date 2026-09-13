# Refund Evidence Verification System - Backend

A backend prototype engineered to power a multi-signal refund evidence verification workflow for merchants and customers.

> **Core Philosophy:** *"Verify the claim, not just the photo."*
>
> The system does not merely detect image manipulation. Instead, it aggregates and cross-checks independent evidence streams (customer claims, merchant reference images, customer-captured damage evidence, order details, payment/delivery signals, and visual consistency analysis) to arrive at a reasoned assessment (`EVIDENCE_CONSISTENT`, `REVIEW_REQUIRED`, or `INCONSISTENCY_DETECTED`). The system never automatically accuses a customer of fraud; merchants remain the ultimate decision-makers.

---

## Milestone Status

- [x] **Milestone 1: Backend Foundation**
  - Modular directory architecture and package structure
  - FastAPI application setup with lifespan management
  - SQLAlchemy 2.0 with SQLite database engine and automatic directory creation
  - Centralized configuration with environment variable loading via `pydantic-settings`
  - CORS configuration for local client/mobile application development
  - Clean application logging and centralized error handling (no stack traces leaked to clients)
  - Automated local storage directory initialization (`storage/product_references`, `storage/evidence`, `storage/reports`)
  - Active SQLite `/health` and `/` endpoints
  - Automated test suite

- [x] **Milestone 2: Merchant Authentication & Account Management**
  - Merchant database model with UUID keys, timestamps, and active status tracking
  - Argon2 password hashing (`argon2-cffi`) — plaintext passwords are never stored or logged
  - JWT access token generation and cryptographic decoding (`pyjwt`)
  - Shared `get_current_merchant` dependency for endpoint protection with OpenAPI `Bearer` authentication support
  - Merchant self-registration, credential login, authenticated `/auth/me`, and `/auth/change-password`
  - Merchant profile retrieval and updating (`/merchants/profile`)
  - Strict tenant isolation and immunity to parameter tampering on immutable fields

- [x] **Milestone 3: Merchant Product Registration + Trusted Product Reference Evidence**
  - `Product` database model with Decimal monetary price support and unique SKU per merchant
  - `ProductReference` database model storing four authentic baseline angles (`FRONT`, `BACK`, `LEFT`, `RIGHT`)
  - Multipart reference image upload with Pillow image verification, MIME checks, and size limits
  - Cryptographic SHA-256 checksum calculation and storage for baseline comparison
  - Collision-free, random filenames preventing path traversal
  - Strict replacement policy rejecting duplicate angles with HTTP 409 Conflict
  - Product completeness calculation ensuring all 4 angles exist prior to verification sessions
  - Cascade cleanup of physical image files upon reference or product deletion

- [x] **Milestone 4: Merchant-Configurable Verification Workflow Builder Backend**
  - `Workflow` and `WorkflowStep` database models linked to merchants
  - Support for 7 canonical step types: `MCQ`, `TEXT`, `IMAGE`, `CAMERA`, `PAYMENT`, `ORDER`, `DELIVERY`
  - Step configuration validation (MCQ options >= 2, no duplicates; TEXT length bounds; IMAGE/CAMERA count bounds)
  - Conditional branching (`when.operator = 'equals'`, `next_step`, `default_next_step`)
  - Graph integrity and self-loop prevention
  - Step reordering endpoint with sequential 1..N index assignment
  - Workflow lifecycle states: `DRAFT` -> `ACTIVE` -> `ARCHIVED`
  - Publishing validation engine preventing empty, corrupt, or broken workflows from activation
  - Protected active workflows (cannot be deleted until archived)
  - Strict merchant ownership checks on all workflow and step endpoints

- [x] **Milestone 5: Verification Sessions + Secure Customer Access Links**
  - Verification session database model with unique human-friendly IDs (`VR-YYYY-XXXXXXXX`)
  - Cryptographically secure 32-byte URL-safe customer tokens hashed with SHA-256 for database storage
  - One-time reveal customer verification links
  - Workflow snapshot freezing preserving step configurations and branching against subsequent edits
  - Strict product readiness checks requiring all 4 trusted reference angles (`FRONT`, `BACK`, `LEFT`, `RIGHT`)
  - Strict workflow checks requiring `ACTIVE` status and non-empty step list
  - Public unauthenticated customer landing, start, and workflow snapshot endpoints
  - HTTP 410 Gone enforcement for expired or cancelled verification links
  - Immutable audit trail (`VerificationEvent`) logging session transitions (`SESSION_CREATED`, `SESSION_STARTED`, `SESSION_CANCELLED`, `SESSION_EXPIRED`)
  - Strict merchant isolation and complete customer privacy (zero leak of merchant emails, phone numbers, password hashes, or token hashes)

- [x] **Milestone 6: Customer Evidence Collection & Multi-Source Signal Ingestion**
  - `Evidence` database model with public identifiers (`EV-YYYY-XXXXXXXX`) and multi-source abstraction (`CUSTOMER`, `PAYMENT`, `ORDER`, `DELIVERY`, `LOCATION`)
  - Customer image uploads with Pillow validation and MIME verification
  - Customer video uploads (MP4, MOV, WEBM) with configurable size limit (`MAX_VIDEO_SIZE_MB`)
  - Customer text evidence submitted and stored directly in database (`MAX_TEXT_EVIDENCE_LENGTH`)
  - Cryptographic SHA-256 integrity calculation on all submitted evidence
  - Duplicate upload detection (`metadata_json["duplicate_of"]`) preserving submission records
  - Secure file storage under `storage/evidence/` with path traversal immunity
  - Strict session status enforcement (must be `IN_PROGRESS`)
  - Step compatibility validation against frozen `workflow_snapshot_json` (rejects live workflow changes or mismatched step types)
  - Immutable evidence audit trail (`EvidenceEvent`: `EVIDENCE_UPLOADED`, `EVIDENCE_VALIDATED`, `EVIDENCE_READY_FOR_ANALYSIS`)
  - Customer token-based and merchant JWT-authenticated evidence retrieval and file download endpoints
  - Clean pre-processing queue boundary (`process_evidence` in `evidence_processing_service.py`) without invoking AI models

- [x] **Milestone 7: AI Visual Consistency Analysis Using Gemini Vision**
  - First AI intelligence module using official `google-genai` SDK (`gemini-2.5-flash`)
  - Objective multimodal visual observation comparing customer damage evidence against 4 trusted merchant product reference angles (`FRONT`, `BACK`, `LEFT`, `RIGHT`)
  - Strict ethical and epistemic guardrails embedded in system prompts (strictly prohibits fraud accusation, fraud scoring, and refund approval/rejection)
  - Nuanced epistemic uncertainty model (`observed`, `not_observed`, `not_visible`, `unclear`) preventing missing visual angles from being equated to absence of damage
  - Structured output schema (`VisualAnalysisResult`: image quality, product consistency, visible condition, key visual observations, uncertainties, overall visual confidence)
  - `VisualAnalysis` database model with complete audit trail and foreign key linkage to `Evidence`
  - Merchant JWT-authenticated endpoints (`POST .../analyze` and `GET .../analysis`)
  - Caching and retry safety: repeated calls return cached results unless `force_reanalyze=true`
  - Graceful fail-safe: Gemini timeouts or network failures mark analysis `FAILED` without failing or accusing customer claim
  - Complete customer privacy: internal analysis data is strictly isolated from customer public endpoints

- [x] **Milestone 8: Local AI Reasoning Engine (Ollama + Llama 3.2 3B)**
  - Local AI reasoning execution via local Ollama `/api/chat` endpoint with structured JSON mode and configurable timeout
  - Dedicated workflow reasoning and control engine evaluating evidence sufficiency and suggesting next progression actions
  - Closed action vocabulary strictly enforced: `ACCEPT_EVIDENCE`, `REQUEST_MORE_EVIDENCE`, `CONTINUE_WORKFLOW`, `COMPLETE_VERIFICATION`
  - Frozen workflow snapshot authority: recommended `next_step_key` must exist in the session's immutable `workflow_snapshot_json`
  - Strict negative boundaries: Llama is prohibited from accusing customers of fraud, calculating fraud scores, approving/rejecting refunds, or inventing verification steps
  - Anti-verdict validation: strict Pydantic validator rejects prohibited phrases ("fraudulent customer", "refund approved", etc.) with `extra="forbid"`
  - Epistemic uncertainty and provenance tracking: separates `CUSTOMER_STATED`, `AI_VISUAL_OBSERVATION`, and `DETERMINISTIC` facts, preserving `not_visible` conditions
  - Input context hashing & caching: deterministic SHA-256 digest provides auditability and caches reasoning results on identical evidence context
  - Fail-safe resilience: Ollama connection failures, timeouts, or malformed outputs record `FAILED` status while keeping sessions and customer evidence completely intact
  - Merchant JWT endpoints (`POST .../reason`, `GET .../reasoning`) with strict merchant isolation and complete customer blocking (HTTP 401)
  - Immutable audit history logging `ReasoningRun` models and `VerificationEvent` audit events (`AI_REASONING_COMPLETED`, `AI_REASONING_FAILED`)

- [x] **Milestone 9: Adaptive Evidence Follow-Up Engine**
  - Closed-loop adaptive verification cycle: Customer Evidence -> Gemini Vision -> Llama 3.2 -> `REQUEST_MORE_EVIDENCE` -> Frozen step validation -> `EvidenceRequest` -> Customer Fulfillment -> Gemini Re-Analysis -> Llama Re-Reasoning -> Terminal Action
  - `EvidenceRequest` database model with complete lifecycle states: `PENDING`, `FULFILLED`, `CANCELLED`, `EXPIRED`
  - Strict step validation enforcing that requested follow-up steps exist in the session's frozen `workflow_snapshot_json` and are `IMAGE` or `CAMERA` steps
  - Hard limit on adaptive follow-ups (`MAX_ADAPTIVE_FOLLOWUPS = 3`): halts further follow-up requests and safely terminates reasoning
  - Request deduplication: returns existing `PENDING` request if identical step and evidence type are requested
  - Customer public endpoints: `GET .../evidence-requests` (sanitized customer view) and `POST .../evidence-requests/{id}/fulfill` (upload follow-up evidence)
  - Merchant JWT endpoints: `GET .../evidence-requests` and `GET .../evidence-requests/{id}` with strict tenant isolation
  - Context hash cache invalidation: creating or fulfilling evidence requests updates the input context hash, invalidating prior cached reasoning and enabling fresh multi-turn reasoning runs
  - Resilient fail-safe operation: Gemini Vision or Ollama errors during fulfillment do not crash or corrupt the session; customer evidence is saved and request is fulfilled
- [x] **Milestone 10: Multi-Source Deterministic Signal Ingestion**
  - Deterministic ingestion, validation, and normalization for 4 foundational signal types: `PAYMENT`, `ORDER`, `DELIVERY`, `LOCATION`
  - Provenance tracking with `SourceType` (`MERCHANT_PROVIDED`, `SYSTEM_GENERATED`, `INTEGRATION`, `CUSTOMER_PROVIDED`) and lifecycle states (`VALID`, `INVALID`, `UNAVAILABLE`, `PENDING`)
  - Strict data normalization: uppercase currency codes (`₹` -> `INR`, `$` -> `USD`), payment methods (`UPI`, `CARD`, `NET_BANKING`), delivery statuses, and location coordinates
  - Sensitive financial data protection: card PANs, CVVs, pins, passwords, and private keys strictly forbidden (`extra="forbid"`) and rejected with HTTP 422
  - Idempotent deduplication and update handling: duplicate posts return existing records without database duplication; updated payloads preserve audit history (`SIGNAL_UPDATED`)
  - Customer public API privacy: `GET .../signals` provides sanitized `safe_summary` stripping internal session UUIDs, payment transaction IDs, and merchant keys
  - AI reasoning context grounding: deterministic signals are ingested into `reasoning_context` under `deterministic_facts` with provenance metadata
  - Cache invalidation: ingesting or updating signals alters the context SHA-256 hash, automatically invalidating stale reasoning runs
  - Negative architectural boundaries: AI models (Gemini & Llama) cannot create or fabricate deterministic transaction signals; no fraud scoring or automated refund verdicts
- [x] **Milestone 11: Evidence Fusion Engine**
  - Deterministic multi-source evidence fusion engine combining independent evidence streams: customer claims, merchant trusted reference baselines, customer photos/videos, Gemini Vision visual observations, and factual signals (`PAYMENT`, `ORDER`, `DELIVERY`, `LOCATION`)
  - Evaluates 8 independent verification dimensions: `CLAIM_VS_VISUAL`, `VISUAL_VS_TRUSTED_REFERENCE`, `CLAIM_VS_PAYMENT`, `CLAIM_VS_ORDER`, `ORDER_VS_PAYMENT`, `ORDER_VS_DELIVERY`, `CLAIM_VS_DELIVERY`, `CLAIM_VS_LOCATION`
  - Strict 3-state deterministic priority decider: `EVIDENCE_CONSISTENT`, `REVIEW_REQUIRED`, `INCONSISTENCY_DETECTED`
  - Explainable confidence score calculated via weighted signal source reliability (`INTEGRATION`: 0.95, `SYSTEM_GENERATED`: 0.90, `MERCHANT_PROVIDED`: 0.85, `CUSTOMER_PROVIDED`: 0.70)
  - Strict Negative Boundaries: NOT a fraud detector; no fraud scores; no customer accusations; no automated refund approvals or disbursements (merchants remain final decision-makers)
  - Geospatial evaluation: spherical Haversine distance calculator comparing customer device GPS with carrier delivery destination coordinates within configured radius tolerance (500m)
  - Local Llama 3.2 explanation service: generates structured human-readable explanations (`summary`, `key_points`, `recommended_review`) without authority to alter deterministic states, confidence, or contradictions
  - Prohibited phrase filtering: strict Pydantic regex validator rejecting accusatory vocabulary (*fraud, scam, liar, cheat, fake claim*) with HTTP 422
  - Offline fail-safe decoupling: if Ollama or Llama is offline or times out, deterministic fusion assessment proceeds seamlessly with `explanation: null`
  - Context hash caching & historical persistence: deterministic SHA-256 context hashing caches unchanged runs and generates immutable historical records upon new evidence ingestion
  - Multi-tenant security & customer privacy sanitization: merchant endpoints strictly isolated; public customer endpoint (`GET .../{token}/fusion`) strips confidence scores, database UUIDs, payment IDs, and contradiction provenance
  - Comprehensive test suite: 27 new tests in `tests/test_evidence_fusion.py`, 225 total passing tests across all 11 milestones (zero regressions)

- [x] **Milestone 12: Merchant Dashboard + Explainable Final Report**
  - Enhanced Merchant Dashboard Listing (`GET /api/v1/verifications`): multi-criteria filtering (`status`, `assessment_state`, `order_id`, `product_id`, `date_from`, `date_to`), multi-field cross-search (`order_id`, `customer_contact`, `product name`, `product SKU`), and robust pagination (`page`, `page_size`, `total`, `items`)
  - Complete 13-Facet Verification Investigation Detail View (`GET /api/v1/verifications/{id}/dashboard`): aggregates verification session metadata, product details, customer refund claim, frozen workflow snapshot, evidence summary & items, visual analysis summary & items, deterministic signals summary & items, adaptive requests, chronological timeline, and merchant decision history
  - Customer Privacy & Token Sanitization Guarantee: raw customer tokens and verification links are never exposed to merchant dashboard views (`customer_link: null`, `customer_token_hash` excluded)
  - Explainable Final Verification Report (`GET /api/v1/verifications/{id}/report`): 9 structured sections based on deterministic evidence fusion (Executive Summary, Consistency Assessment, Visual Consistency Findings, Signal Verification Findings, Multi-Source Fusion Matrix, Claim vs Evidence Reconciliation, Missing Evidence & Follow-up, Merchant Decision Context, and AI Audit Trail)
  - Chronological Verification Timeline (`GET /api/v1/verifications/{id}/timeline`): authentic audit events compiled from verification lifecycle events, evidence upload & validation events, Gemini visual analysis events, and merchant decisions, strictly ordered chronologically
  - Merchant Final Decision Engine (`POST /api/v1/verifications/{id}/decision` & `GET /api/v1/verifications/{id}/decisions`): human merchant remains the sole authoritative decision-maker (`REFUND_APPROVED`, `REFUND_REJECTED`, `MANUAL_REVIEW`). Decisions trigger lifecycle state transitions to `COMPLETED` and log immutable `MERCHANT_DECISION_MADE` audit events while preserving full historical audit records
  - Strict Negative Boundaries: machine assesses; Llama explains; merchant decides. Prohibits automated AI refund approvals, disbursements, fraud scoring, or customer accusations.
  - Comprehensive Test Suite: 13 new tests in `tests/test_merchant_dashboard.py`, 238 total passing tests across all 12 milestones (zero regressions)

---


## Technology Stack

- **Runtime:** Python 3.11+
- **Framework:** FastAPI
- **Database:** SQLite with SQLAlchemy 2.0 ORM
- **Password Security:** Argon2 (`argon2-cffi`)
- **Authentication:** JWT (`pyjwt`) with Bearer tokens
- **Image Processing & Validation:** Pillow (`PIL`)
- **Multipart Uploads:** `python-multipart`
- **AI Visual Consistency Analysis:** Google Gemini Vision (`google-genai` SDK v1.71.0)
- **Local AI Reasoning Engine:** Ollama with Llama 3.2 3B
- **Settings & Schemas:** Pydantic v2 & Pydantic-Settings
- **Server:** Uvicorn
- **Testing:** Pytest & HTTPX TestClient

---

## Architectural Layering

The codebase strictly enforces the separation of concerns:

```
API ROUTES (app/api/)
       ↓
SERVICES / BUSINESS LOGIC (app/services/)
       ↓
DATABASE / STORAGE / UTILITIES (app/core/, app/models/, app/utils/)
```

Route handlers remain thin, delegating operations to dedicated service modules (`auth_service.py`, `merchant_service.py`, `product_service.py`, `reference_service.py`, `workflow_service.py`, `workflow_step_service.py`, `verification_service.py`, `public_verification_service.py`, `evidence_fusion_service.py`).

---

## API Endpoints Summary

### System Endpoints
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/` | API status and greeting | No |
| `GET` | `/health` | Live SQLite connectivity check | No |

### Authentication Endpoints (`/api/v1/auth`)
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/auth/register` | Register new merchant with hashed credentials | No |
| `POST` | `/api/v1/auth/login` | Login and receive Bearer JWT access token | No |
| `GET` | `/api/v1/auth/me` | Fetch authenticated merchant identity | Bearer JWT |
| `POST` | `/api/v1/auth/change-password` | Update account password | Bearer JWT |

### Merchant Profile Endpoints (`/api/v1/merchants`)
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/merchants/profile` | Retrieve merchant profile details | Bearer JWT |
| `PUT` | `/api/v1/merchants/profile` | Update editable fields (`business_name`, `phone`) | Bearer JWT |

### Product & Reference Evidence Endpoints (`/api/v1/products`)
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/products` | Register product with Decimal price and unique SKU | Bearer JWT |
| `GET` | `/api/v1/products` | List authenticated merchant's products | Bearer JWT |
| `GET` | `/api/v1/products/{id}` | Get single product (ownership enforced) | Bearer JWT |
| `PUT` | `/api/v1/products/{id}` | Update product details | Bearer JWT |
| `DELETE` | `/api/v1/products/{id}` | Delete product and all physical reference files | Bearer JWT |
| `GET` | `/api/v1/products/{id}/completeness` | Check if all 4 reference angles exist | Bearer JWT |
| `POST` | `/api/v1/products/{id}/references` | Upload authentic reference image (multipart) | Bearer JWT |
| `GET` | `/api/v1/products/{id}/references` | List product reference metadata | Bearer JWT |
| `GET` | `/api/v1/products/{id}/references/{angle}` | Retrieve metadata for single angle | Bearer JWT |
| `DELETE` | `/api/v1/products/{id}/references/{angle}` | Delete reference image and physical file | Bearer JWT |

### Workflow & Step Builder Endpoints (`/api/v1/workflows`)
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/workflows` | Create verification workflow draft | Bearer JWT |
| `GET` | `/api/v1/workflows` | List merchant's workflows | Bearer JWT |
| `GET` | `/api/v1/workflows/{id}` | Retrieve workflow including steps | Bearer JWT |
| `PUT` | `/api/v1/workflows/{id}` | Update workflow name/description | Bearer JWT |
| `DELETE` | `/api/v1/workflows/{id}` | Delete workflow (draft or archived only) | Bearer JWT |
| `POST` | `/api/v1/workflows/{id}/publish` | Validate and activate workflow (`DRAFT` -> `ACTIVE`) | Bearer JWT |
| `POST` | `/api/v1/workflows/{id}/archive` | Retire workflow (`ACTIVE` -> `ARCHIVED`) | Bearer JWT |
| `POST` | `/api/v1/workflows/{id}/steps` | Create workflow step with config validation | Bearer JWT |
| `GET` | `/api/v1/workflows/{id}/steps` | List steps ordered by `step_order` | Bearer JWT |
| `GET` | `/api/v1/workflows/{id}/steps/{step_id}` | Retrieve single step details | Bearer JWT |
| `PUT` | `/api/v1/workflows/{id}/steps/{step_id}` | Update step guidance or configuration | Bearer JWT |
| `DELETE` | `/api/v1/workflows/{id}/steps/{step_id}` | Delete step and re-index remaining steps | Bearer JWT |
| `PUT` | `/api/v1/workflows/{id}/steps/reorder` | Reorder all steps sequentially (1..N) | Bearer JWT |

### Merchant Verification Session Endpoints (`/api/v1/verifications`)
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `POST` | `/api/v1/verifications` | Initiate customer verification session (returns customer link) | Bearer JWT |
| `GET` | `/api/v1/verifications` | List merchant verification sessions (supports `?status=`) | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}` | Retrieve verification session details | Bearer JWT |
| `POST` | `/api/v1/verifications/{id}/cancel` | Cancel verification session (returns HTTP 410 to customer) | Bearer JWT |
| `POST` | `/api/v1/verifications/{id}/signals` | Ingest structured deterministic signal (PAYMENT, ORDER, DELIVERY, LOCATION) | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/signals` | List all signals associated with session | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/signals/{sig_id}` | Get specific signal details | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/evidence` | List all submitted evidence items for owned session | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/evidence/{evidence_id}` | Download/view evidence item for merchant review | Bearer JWT |
| `POST` | `/api/v1/verifications/{id}/evidence/{evidence_id}/analyze` | Trigger Gemini Vision visual consistency analysis | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/evidence/{evidence_id}/analysis` | Get latest visual consistency analysis result | Bearer JWT |
| `POST` | `/api/v1/verifications/{id}/reason` | Trigger local Llama 3.2 3B reasoning on session evidence | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/reasoning` | Retrieve audit history of reasoning runs for session | Bearer JWT |
| `POST` | `/api/v1/verifications/{id}/fusion` | Trigger deterministic evidence fusion run | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/fusion` | List all historical fusion runs for session | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/fusion/latest` | Retrieve latest evidence fusion result | Bearer JWT |
| `GET` | `/api/v1/verifications` | Merchant Dashboard verification list (with pagination, filters, search) | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/dashboard` | 13-Facet Verification Investigation Detail View (sanitized tokens) | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/report` | Explainable Final Verification Report (9 structured sections) | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/timeline` | Chronological Verification Timeline of authentic events | Bearer JWT |
| `POST` | `/api/v1/verifications/{id}/decision` | Record merchant final refund decision (`REFUND_APPROVED`, `REFUND_REJECTED`, `MANUAL_REVIEW`) | Bearer JWT |
| `GET` | `/api/v1/verifications/{id}/decisions` | List chronological decision audit history for session | Bearer JWT |

### Public Customer Verification Endpoints (`/api/v1/public/verifications`)
| Method | Endpoint | Description | Auth Required |
| :--- | :--- | :--- | :--- |
| `GET` | `/api/v1/public/verifications/{token}` | Customer landing page view (sanitized merchant/product data) | No (Token only) |
| `POST` | `/api/v1/public/verifications/{token}/start` | Customer starts guided verification (transitions to `IN_PROGRESS`) | No (Token only) |
| `GET` | `/api/v1/public/verifications/{token}/workflow` | Retrieve frozen workflow definition snapshot | No (Token only) |
| `POST` | `/api/v1/public/verifications/{token}/evidence/image` | Upload customer image evidence (JPEG, PNG, WEBP) | No (Token only) |
| `POST` | `/api/v1/public/verifications/{token}/evidence/video` | Upload customer video evidence (MP4, MOV, WEBM) | No (Token only) |
| `POST` | `/api/v1/public/verifications/{token}/evidence/text` | Submit customer text evidence | No (Token only) |
| `GET` | `/api/v1/public/verifications/{token}/evidence` | List submitted evidence items for session (supports `?workflow_step_key=`) | No (Token only) |
| `GET` | `/api/v1/public/verifications/{token}/evidence/{evidence_id}` | Download or view customer evidence item | No (Token only) |
| `GET` | `/api/v1/public/verifications/{token}/signals` | Retrieve sanitized public signal summary | No (Token only) |
| `GET` | `/api/v1/public/verifications/{token}/fusion` | Retrieve sanitized non-accusatory customer assessment | No (Token only) |

---

## Running Automated Tests

Run the complete test suite (238 tests across all 12 milestones):

```powershell
python -m pytest -v
```

---

## System Status: All Core Milestones (M1–M12) Complete!

The Refund Evidence Verification System backend is fully operational with complete multi-signal deterministic verification, AI visual observations (Gemini Vision), local AI explanations (Ollama Llama 3.2), explainable final reports, and merchant authoritative decision governance.

