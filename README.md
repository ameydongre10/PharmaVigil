# GenAR PADER Regulatory Report Generation Engine

[![Tests](https://img.shields.io/badge/Tests-120%2F120%20Passing-brightgreen.svg)](https://github.com/ameydongre10/submission)
[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.111%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Regulatory Standard](https://img.shields.io/badge/FDA-21%20CFR%20314.80-red.svg)](https://www.accessdata.fda.gov/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An enterprise-grade, deterministic, and hallucination-free regulatory report generation system for **Periodic Adverse Drug Experience Reports (PADER)** under **FDA 21 CFR § 314.80**.

Combines rigorous mathematical aggregation, strict context boundary isolation, grounded LLM narrative generation, automated number-level verification, and an auditable human review sign-off workflow.

---

## 📑 Table of Contents
1. [Key Architecture & Core Principles](#-key-architecture--core-principles)
2. [Repository Structure](#-repository-structure)
3. [Quick Start & Local Execution](#-quick-start--local-execution)
4. [Web Dashboard & REST API](#-web-dashboard--rest-api)
5. [Hosting & Deployment (Render / Docker)](#-hosting--deployment-render--docker)
6. [Regulatory Compliance & Non-Negotiable Rules](#-regulatory-compliance--non-negotiable-rules)
7. [Running the Test Suite](#-running-the-test-suite)

---

## 🏛 Key Architecture & Core Principles

```
                                      ┌─────────────────────────────────────┐
                                      │       Raw ICSR Safety Dataset       │
                                      │        (Excel / CSV Records)        │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │     Deterministic Analysis Layer    │
                                      │   (Math & Aggregation, No LLM)      │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │       Evidence Extraction Layer     │
                                      │  (Factual IDs, Metric Traceability) │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │    Section-Specific Context Packets │
                                      │ (Strict Boundaries, No Raw DFs)     │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │      Grounded LLM Generation        │
                                      │  (OpenAI / Gemini / Anthropic/Mock) │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │    Grounding & Hallucination Guard  │
                                      │ (Automated Number & Fact Audit)     │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │      Regulatory Report Assembly     │
                                      │    (Draft: DRAFT_PENDING_REVIEW)    │
                                      └──────────────────┬──────────────────┘
                                                         │
                                                         ▼
                                      ┌─────────────────────────────────────┐
                                      │      Human Medical Officer Sign-Off │
                                      │  (APPROVED / NEEDS_REVISION / REJ)  │
                                      └─────────────────────────────────────┘
```

### Core Safety Guarantees:
1. **Zero Hallucinated Math**: The LLM *never* performs calculations or statistics. Every sum, count, percentage, and period date is computed deterministically in `src/analysis_engine.py`.
2. **Strict Context Boundaries**: Raw tabular lines/DataFrames are *never* dumped into LLM prompts. Only targeted, pre-computed `EvidenceItem` packets with explicit IDs are passed.
3. **Automated Number-Level Audit**: Every single number generated in narrative text is extracted via regex and verified against the evidence pool. Unsupported figures fail validation.
4. **Mandatory Human Sign-Off**: Automated validation `PASS` does **not** equal submission approval. Reports default to `DRAFT_PENDING_REVIEW`. Only an explicit human medical reviewer sign-off action can mark a report `HUMAN_APPROVED`.
5. **Clear Separation of In-Scope vs Limitations**: FDA regulatory requirements (8 core sections) are cleanly separated from data limitations (e.g., Expectedness / CCDS label absence).

---

## 📂 Repository Structure

```
submission/
├── app.py                      # FastAPI Web Application & Interactive Dashboard
├── run_pader.py                # Command Line Interface (CLI) Pipeline runner
├── demo_phase3.py              # Phase 3 Evidence & Context engineering demo
├── demo_phase4.py              # Phase 4 Grounded LLM Generation demo
├── requirements.txt            # Production dependencies
├── render.yaml                 # Render Blueprint for 1-click cloud deployment
├── Dockerfile                  # Container definition for Docker & Cloud Run
├── Procfile                    # Web service process configuration
├── pytest.ini                  # Pytest configuration (pythonpath = .)
├── .env.example                # Example environment variables
│
├── src/                        # Core Engine Package
│   ├── __init__.py
│   ├── analysis_engine.py      # Deterministic case & reaction analysis
│   ├── context_builder.py      # Section-specific context packet construction
│   ├── data_loader.py          # Normalization & schema validation
│   ├── evaluator.py            # Automated completeness & grounding evaluation
│   ├── evidence_collector.py   # Transformation of analysis results into evidence
│   ├── evidence_models.py      # Pydantic schemas for evidence and packets
│   ├── generation_models.py    # LLM request, response, and validation models
│   ├── grounding_validator.py  # Hallucination detector & regex number auditor
│   ├── human_review.py         # Audit trail and reviewer sign-off manager
│   ├── llm_client.py           # Multi-provider LLM abstraction (Mock, OpenAI, Gemini, etc.)
│   ├── models.py               # Core AnalysisResult schema
│   ├── orchestrator.py         # End-to-end pipeline coordinator
│   ├── prompts.py              # Section prompts & grounding instructions
│   ├── report_assembler.py     # Markdown document assembly
│   ├── report_config.py        # PADER section specifications & requirements
│   ├── report_models.py        # Top-level PADERReport and ReviewRecord models
│   └── section_generator.py    # Structured JSON generation via LLM
│
├── tests/                      # Full Automated Test Suite (120 Tests)
│   ├── test_analysis.py        # Deterministic analysis tests
│   ├── test_api.py             # FastAPI REST endpoints tests
│   ├── test_evidence.py        # Evidence collection & context packet tests
│   ├── test_generation.py      # Grounded LLM generation tests
│   ├── test_hardening.py       # Hardening, regression, edge cases (1,036 lines)
│   └── test_pipeline.py        # End-to-end pipeline & human review tests
│
├── sample_data/                # Bundled Test & Demo Datasets
│   ├── sample_icsr_dataset.xlsx# 1,068-row reference dataset (Excel)
│   └── sample_icsr_dataset.csv # 1,068-row reference dataset (CSV)
│
├── scripts/
│   └── generate_sample_data.py # Reference dataset generator
│
└── docs/
    ├── DEPLOYMENT_GUIDE.md     # Detailed Render & Docker hosting guide
    └── version1_design.md      # Engineering architecture specification
```

---

## ⚡ Quick Start & Local Execution

### 1. Clone & Set Up Environment

```bash
git clone https://github.com/ameydongre10/submission.git
cd submission

python -m venv .venv
source .venv/bin/activate  # On Windows: .\.venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Run CLI Report Generation

```bash
# Generate a draft report with offline Mock LLM (100% grounded)
python run_pader.py --mock --output-dir outputs

# Inspect generated report:
cat outputs/pader_report.md
```

### 3. Launch Web Dashboard & REST API

```bash
python app.py
# Or with uvicorn:
uvicorn app:app --host 0.0.0.0 --port 8000 --reload
```

Open your browser to:
- **Interactive Web Dashboard**: `http://localhost:8000`
- **Swagger API Documentation**: `http://localhost:8000/docs`
- **ReDoc Technical Reference**: `http://localhost:8000/redoc`

---

## 🌐 Web Dashboard & REST API

The application serves a complete, responsive Regulatory Pharmacovigilance Dashboard:
- **1-Click Reference Dataset**: Analyze the bundled 1,068-row Bisoprolol dataset instantly without uploading files.
- **Drag-and-Drop Ingestion**: Upload custom `.xlsx` or `.csv` files with automatic validation.
- **Live LLM Switcher**: Toggle between offline deterministic mock and live API keys (OpenAI, Gemini, Anthropic).
- **Compliance & Grounding Metrics**: Displays factual consistency %, grounding score %, and unsupported claim counts.
- **Regulatory Reviewer Console**: Authorized safety officers can review and sign off (`APPROVED`, `NEEDS_REVISION`, `REJECTED`) with timestamped audit records.
- **Export Formats**: One-click download of the complete Markdown document (`.md`) or structured JSON audit payload.

### Core API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/health` | Service health check (for Render / uptime monitors) |
| `GET` | `/api/sample-data` | Pre-computed summary of bundled ICSR dataset |
| `POST` | `/api/upload` | Upload and validate a new ICSR dataset (.xlsx / .csv) |
| `POST` | `/api/generate` | Run full end-to-end report generation pipeline |
| `GET` | `/api/reports` | List generated reports in session |
| `GET` | `/api/reports/{id}` | Retrieve complete structured JSON report |
| `GET` | `/api/reports/{id}/markdown` | Get raw regulatory Markdown text |
| `GET` | `/api/reports/{id}/download` | Download `.md` report attachment |
| `POST` | `/api/reports/{id}/review` | Submit human reviewer sign-off decision |

---

## 🚀 Hosting & Deployment (Render / Docker)

### Deploy on Render in 2 Minutes:
1. Fork or push this repository to GitHub.
2. Go to [Render Dashboard](https://dashboard.render.com/) -> **New +** -> **Blueprint**.
3. Select your repository. Render automatically reads `render.yaml`.
4. Click **Apply**. Render will install requirements, configure health checks, and publish your live URL!

For detailed instructions and Docker/Cloud Run commands, see [docs/DEPLOYMENT_GUIDE.md](docs/DEPLOYMENT_GUIDE.md).

---

## 🛡 Regulatory Compliance & Non-Negotiable Rules

The pipeline enforces regulatory rules throughout:

| Rule | Enforcement Location | Description |
|---|---|---|
| **Rule A** | `src/orchestrator.py` | Newly generated reports must default to `DRAFT_PENDING_REVIEW`. |
| **Rule B** | `src/evaluator.py` | Automated evaluator `PASS` does **not** change review status to `HUMAN_APPROVED`. |
| **Rule C** | `src/human_review.py` | Only an explicit, audited human action can set `HUMAN_APPROVED`. |
| **Rule D & E** | `src/human_review.py` | Reviewer can set `NEEDS_REVISION` or `REJECTED`. |
| **Rule F** | `src/human_review.py` | Simulated test approvals are marked `is_simulated: true` and cannot masquerade as real medical review. |
| **Rule G & H** | `src/evaluator.py` | Validates completeness across all 8 mandatory PADER sections and tracks limitations separately. |

---

## 🧪 Running the Test Suite

The test suite covers deterministic analysis, grounding verification, hardening edge cases, regression benchmarks, and REST API behavior:

```bash
pytest
```

**Output:**
```
collected 120 items
tests/test_analysis.py .........                                         [  7%]
tests/test_api.py .....                                                  [ 11%]
tests/test_evidence.py .....................                             [ 29%]
tests/test_generation.py ..........                                      [ 37%]
tests/test_hardening.py ................................................ [ 77%]
..................                                                       [ 92%]
tests/test_pipeline.py .........                                         [100%]

======================= 120 passed in 5.35s =======================
```

---

## 📄 License
This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
