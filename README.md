# Reft.AI — Refund Evidence Verification System

Reft.AI is an intelligent, local AI-powered evidence verification platform designed to automate and assist merchants in evaluating customer refund claims. By fusing local Vision-Language Models (Qwen2.5-VL 3B) and Local Reasoning Models (Llama 3.2 1B) with deterministic business logic signals, Reft.AI provides objective, explainable, and non-blocking verification for e-commerce merchants.

---

## 🌟 Key Features & Architecture

### 1. Fully Local AI Vision & Reasoning Pipeline
- **Qwen2.5-VL 3B** (`qwen2.5vl:3b-q4_K_M`): Pre-computes merchant product reference images one-by-one and performs forensic visual inspection of customer evidence.
- **Llama 3.2 1B** (`llama3.2:1b`): Consolidates multi-angle reference observations into canonical `ProductVisualProfile` records and generates structured evidence fusion reasoning explanations.
- **Zero Cloud Leakage**: Runs 100% locally via Ollama with zero external API dependencies or cloud image uploads.

### 2. High-Performance Concurrency & Non-Blocking Design
- **Dedicated Serialized AI Job Queue**: A single-worker background queue serializes all local AI model calls sequentially to prevent GPU VRAM overload on single-GPU setups (e.g. RTX 3050 6GB).
- **Instant Merchant Uploads**: Reference image uploads return HTTP 201 immediately (< 100ms), enqueuing AI jobs in the background.
- **SQLite WAL Mode & Busy Timeout**: Configured with `PRAGMA journal_mode=WAL;` and 30s busy timeout to eliminate database write locks.
- **SHA-256 Profile Caching**: Bypasses unnecessary Llama profile reconsolidations when product reference image hashes remain unchanged.

### 3. Product Verification Gating
- **Strict Verification Gating**: Merchants cannot initiate a customer verification session for a product until its trusted reference image processing status is `READY`.
- **Backend & Frontend Protection**: Rejects non-ready creation requests with HTTP 409 Conflict (`REFERENCE_ANALYSIS_IN_PROGRESS`).

---

## 📁 Repository Structure

```
├── backend/                  # FastAPI Backend Application
│   ├── app/                  # Application Core & Business Logic
│   │   ├── ai/               # Local Ollama AI Services (Qwen2.5-VL, Llama 3.2, AI Queue)
│   │   ├── api/              # FastAPI Router & Endpoint Controllers
│   │   ├── core/             # Database (SQLite WAL), Config, Security (JWT)
│   │   ├── models/           # SQLAlchemy Database ORM Models
│   │   ├── schemas/          # Pydantic Schemas & DTOs
│   │   └── services/         # Business Logic & Workflow Engine
│   ├── scripts/              # Verification & Diagnostic Utilities
│   ├── tests/                # Pytest Unit & Integration Test Suite
│   └── requirements.txt      # Python Dependencies
├── mobile/                   # Flutter Mobile Client Application
│   ├── lib/                  # Flutter Screens, Widgets, Services & Core Architecture
│   │   ├── core/             # Colors, Theme, Network API Client
│   │   ├── features/         # Merchant & Customer Verification Flows
│   │   └── services/         # Merchant & Customer HTTP API Services
│   └── pubspec.yaml          # Flutter Dependencies
└── README.md                 # System Documentation
```

---

## 🚀 Quick Start Guide

### Prerequisites
1. **Python 3.10+**
2. **Flutter SDK 3.x**
3. **Ollama** installed locally with the following models:
   ```bash
   ollama pull qwen2.5vl:3b-q4_K_M
   ollama pull llama3.2:1b
   ```

---

### Backend Setup

1. **Navigate to the backend folder**:
   ```bash
   cd backend
   ```

2. **Create and activate a Python virtual environment**:
   ```bash
   python -m venv venv
   # Windows:
   venv\Scripts\activate
   # Linux/macOS:
   source venv/bin/activate
   ```

3. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Start the FastAPI Server**:
   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
   *The server will initialize SQLite database schemas, enable WAL mode, and warm up Qwen2.5-VL 3B & Llama 3.2 1B models.*

5. **Run Test Suite**:
   ```bash
   python -m pytest tests/ -q
   ```

---

### Mobile App Setup

1. **Navigate to the mobile folder**:
   ```bash
   cd mobile
   ```

2. **Get Flutter Dependencies**:
   ```bash
   flutter pub get
   ```

3. **Run Static Analysis**:
   ```bash
   flutter analyze
   ```

4. **Run Application or Build Release APK**:
   ```bash
   # Run on connected device/emulator
   flutter run

   # Build release APK
   flutter build apk
   ```

---

## 🛡 License & Project Maintenance

Developed by Agilesh T , Concept or idea Is solenly drafted By Me 
