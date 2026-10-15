"""
FastAPI Regulatory PADER Generation & Human Review Backend.

Provides:
1. REST API for dataset upload, deterministic analytics, grounded LLM generation,
   grounding verification, and human review sign-off.
2. Root API status probe at `/` and health probe at `/api/health`.
3. Auto-generated OpenAPI / Swagger docs at `/docs` and ReDoc at `/redoc`.
"""

import os
import sys
import json
import shutil
import tempfile
import secrets
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Header, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from src.data_loader import load_and_normalize_data, validate_data
from src.analysis_engine import AnalysisEngine
from src.evidence_collector import collect_evidence
from src.context_builder import ContextBuilder
from src.report_config import PADER_CONFIG
from src.llm_client import MockLLMClient, OpenAICompatibleLLMClient, LLMClient, create_llm_client
from src.section_generator import SectionGenerator
from src.grounding_validator import GroundingValidator
from src.report_assembler import ReportAssembler
from src.evaluator import PADEREvaluator
from src.human_review import HumanReviewManager
from src.orchestrator import PADEROrchestrator
from src.report_models import (
    PADERReport, ReportMetadata, ReviewDecision, ReportStatus, SectionStatus
)
from src.auth import (
    init_auth_db, register_user, authenticate_user, create_user_session,
    get_user_from_token, delete_session, record_doctor_verification,
    get_verification_by_report
)

# Initialize Authentication & Verification Database
init_auth_db()

app = FastAPI(
    title="GenAR PADER Regulatory Report Engine",
    description="Automated, Deterministically-Grounded Periodic Adverse Drug Experience Report (PADER) Generation and Regulatory Review System.",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    # A wildcard origin combined with credentials is rejected by browsers and
    # makes credentialed API access available to arbitrary websites.
    allow_origins=[
        "https://ameydongre10.github.io",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.middleware("http")
async def limit_request_body(request, call_next):
    """Reject oversized request bodies before route handling when length is known."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > 26 * 1024 * 1024:
                return JSONResponse(status_code=413, content={"detail": "Request body exceeds the 26 MiB limit."})
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Invalid Content-Length header."})
    return await call_next(request)

# In-memory report and active-dataset state is suitable for this single-process
# demo deployment only; use shared persistent storage before scaling workers.
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
REPORTS_DB: Dict[str, PADERReport] = {}
REPORTS_PATH = OUTPUTS_DIR / "reports.json"
SAMPLE_DATA_DIR = BASE_DIR / "sample_data"
SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SAMPLE_PATH = BASE_DIR / "Bisoprolol_icsr_sample_1068rows.xlsx"
FALLBACK_SAMPLE_PATH = SAMPLE_DATA_DIR / "sample_icsr_dataset.xlsx"

ACTIVE_DATASET_PATH: Optional[str] = None


def persist_reports() -> None:
    """Atomically persist report state for restarts on a persistent disk."""
    temp_path = REPORTS_PATH.with_suffix(".json.tmp")
    payload = {report_id: report.model_dump(mode="json") for report_id, report in REPORTS_DB.items()}
    temp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    temp_path.replace(REPORTS_PATH)


def load_reports() -> None:
    """Load persisted reports; ignore no corruption silently."""
    if not REPORTS_PATH.exists():
        return
    try:
        content = json.loads(REPORTS_PATH.read_text(encoding="utf-8"))
        if not isinstance(content, dict):
            raise ValueError("Report store must contain a JSON object")
        REPORTS_DB.update({key: PADERReport.model_validate(value) for key, value in content.items()})
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"Unable to load persisted reports from {REPORTS_PATH.name}") from exc


load_reports()


def require_user(authorization: Optional[str]) -> Dict[str, Any]:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Authentication required.")
    user = get_user_from_token(authorization[7:].strip())
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid token.")
    return user


class RegisterRequest(BaseModel):
    username: str = Field(..., min_length=1, description="Unique username or email")
    password: str = Field(..., min_length=12, max_length=256, description="Password (12-256 characters)")
    full_name: str = Field(..., min_length=1, description="Full Name and medical title")
    # Public self-registration does not grant medical reviewer privileges.
    role: str = Field("analyst", description="Self-registration role: analyst or user")
    email: Optional[str] = None
    medical_license: Optional[str] = Field(None, description="Medical registration/license number (required for doctors)")
    specialty: Optional[str] = Field(None, description="Clinical specialty, e.g. Pharmacovigilance")
    affiliation: Optional[str] = Field(None, description="Hospital or institutional affiliation")


class LoginRequest(BaseModel):
    username: str = Field(..., description="Username or email")
    password: str = Field(..., description="Password")


class GenerateRequest(BaseModel):
    file_path: Optional[str] = Field(None, description="Path to an uploaded dataset returned by this server")
    llm_provider: Optional[str] = Field("mock", description="LLM provider: mock, openai, gemini, anthropic, or generic")
    api_key: Optional[str] = Field(None, description="LLM API key (if live generation is selected)")
    model_name: Optional[str] = Field("gpt-4o-mini", description="LLM model identifier")
    base_url: Optional[str] = Field(None, description="Custom LLM API Base URL")
    review_decision: Optional[str] = Field("PENDING_REVIEW", description="Initial review decision")
    reviewer_name: Optional[str] = Field("Qualified Safety Reviewer", description="Name of the reviewer")
    reviewer_notes: Optional[str] = Field(None, description="Review notes")


class ReviewRequest(BaseModel):
    decision: str = Field(..., description="Decision: APPROVED, NEEDS_REVISION, REJECTED, or SIMULATED_APPROVED")
    reviewer_name: Optional[str] = Field("Qualified Safety Reviewer", description="Full Name and Title of Reviewer")
    notes: Optional[str] = Field("", description="Sign-off notes or audit rationale")
    doctor_license: Optional[str] = Field(None, description="Medical License / Registration Number")
    specialty: Optional[str] = Field(None, description="Specialty / Department")
    affiliation: Optional[str] = Field(None, description="Hospital or institutional affiliation")
    token: Optional[str] = Field(None, description="Session token if Authorization header not provided")


class ReportMetadataUpdate(BaseModel):
    product_name: Optional[str] = Field(None, min_length=1, max_length=200)
    sponsor_name: Optional[str] = Field(None, min_length=1, max_length=200)
    application_number: Optional[str] = Field(None, min_length=1, max_length=100)


class RegenerateSectionRequest(BaseModel):
    section_name: str = Field(..., description="Name of LLM-generated section to regenerate")
    llm_provider: Optional[str] = Field("mock", description="mock or live")
    api_key: Optional[str] = Field(None, description="Optional API key")


def get_active_dataset_path(preferred_path: Optional[str] = None) -> str:
    """Resolves the dataset path, strictly prioritizing preferred path, active uploaded file, or falling back to sample."""
    if preferred_path:
        if os.path.exists(preferred_path):
            return preferred_path
        raise HTTPException(
            status_code=404,
            detail=f"Specified uploaded dataset '{preferred_path}' was not found on the server. Please re-upload your dataset."
        )
    if ACTIVE_DATASET_PATH and os.path.exists(ACTIVE_DATASET_PATH):
        return ACTIVE_DATASET_PATH
    if DEFAULT_SAMPLE_PATH.exists():
        return str(DEFAULT_SAMPLE_PATH)
    if FALLBACK_SAMPLE_PATH.exists():
        return str(FALLBACK_SAMPLE_PATH)
    csv_fallback = SAMPLE_DATA_DIR / "sample_icsr_dataset.csv"
    if csv_fallback.exists():
        return str(csv_fallback)
    raise HTTPException(status_code=404, detail="No ICSR dataset available. Please upload a dataset.")


@app.api_route("/api/health", methods=["GET", "HEAD"], tags=["System"])
def health_check():
    """Health check endpoint for Render / cloud load balancers."""
    return {
        "status": "healthy",
        "service": "pader-regulatory-engine",
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0",
        "active_dataset": Path(get_active_dataset_path()).name,
        "sample_data_ready": DEFAULT_SAMPLE_PATH.exists() or FALLBACK_SAMPLE_PATH.exists()
    }


# ===========================================================================
# AUTHENTICATION & ROLE-BASED ACCESS CONTROL (RBAC) ENDPOINTS
# ===========================================================================

@app.post("/api/auth/register", tags=["Authentication"])
def register(req: RegisterRequest):
    """Registers a new user (Doctor/Verifier or Safety Analyst) with credentials and role."""
    if req.role.strip().lower() not in ("analyst", "user"):
        raise HTTPException(status_code=403, detail="Self-registration is limited to analyst or user accounts.")
    try:
        user = register_user(
            username=req.username,
            password=req.password,
            full_name=req.full_name,
            role=req.role,
            email=req.email,
            medical_license=req.medical_license,
            specialty=req.specialty,
            affiliation=req.affiliation
        )
        token = create_user_session(user["id"])
        return {
            "status": "success",
            "token": token,
            "user": user
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/api/auth/login", tags=["Authentication"])
def login(req: LoginRequest):
    """Authenticates a user and issues a secure session Bearer token."""
    user = authenticate_user(req.username, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid username or password.")
    token = create_user_session(user["id"])
    return {
        "status": "success",
        "token": token,
        "user": user
    }


@app.get("/api/auth/me", tags=["Authentication"])
def get_current_user(authorization: Optional[str] = Header(None)):
    """Returns currently authenticated user profile based on Bearer token."""
    if not authorization:
        raise HTTPException(status_code=401, detail="Authorization header missing.")
    token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    user = get_user_from_token(token) if token else None
    if not user:
        raise HTTPException(status_code=401, detail="Session expired or invalid token.")
    return {"status": "success", "user": user}


@app.post("/api/auth/logout", tags=["Authentication"])
def logout(authorization: Optional[str] = Header(None)):
    """Logs out and invalidates the session token."""
    if authorization:
        token = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
        if token:
            delete_session(token)
    return {"status": "success", "message": "Logged out successfully."}


# ===========================================================================
# DATASET INGESTION & EXPLORATION ENDPOINTS
# ===========================================================================

@app.get("/api/sample-data", tags=["Dataset"])
def get_sample_data_summary(file_path: Optional[str] = Query(None)):
    """Returns metadata and preview statistics for the active dataset (or requested path)."""
    path = get_active_dataset_path(file_path)
    df = load_and_normalize_data(path)
    engine = AnalysisEngine(df)

    vol = engine.get_case_volume().value
    period = engine.get_reporting_period().value
    reactions = engine.get_reactions(top_n=10).value if engine.get_reactions(top_n=10) else {}
    serious_rx = engine.get_serious_reactions(top_n=10).value if engine.get_serious_reactions(top_n=10) else {}
    countries = engine.get_country_distribution().value
    age = engine.get_age_distribution().value
    alerts = engine.get_alert_cases().value

    preview_cols = [c for c in ["safetyreportid", "receivedate", "serious_bool", "standard_country", "patient_reaction_reactionmeddrapt"] if c in df.columns]

    return {
        "dataset_name": getattr(app.state, "active_dataset_name", None) if path == ACTIVE_DATASET_PATH else Path(path).name,
        "is_custom_dataset": bool(ACTIVE_DATASET_PATH is not None and path == ACTIVE_DATASET_PATH),
        "total_rows": len(df),
        "total_cases": vol.get("total_cases", 0),
        "serious_cases": vol.get("serious_cases", 0),
        "serious_percentage": vol.get("serious_pct", 0),
        "non_serious_cases": vol.get("non_serious_cases", 0),
        "expedited_alerts": alerts.get("total_alerts", 0),
        "reporting_period": period,
        "top_reactions": reactions,
        "top_serious_reactions": serious_rx,
        "country_distribution": countries,
        "age_distribution": age,
        "preview_sample": df[preview_cols].head(5).to_dict(orient="records") if preview_cols else []
    }


@app.post("/api/upload", tags=["Dataset"])
async def upload_dataset(file: UploadFile = File(...)):
    """Uploads an ICSR dataset (.xlsx or .csv), validates its schema robustly, and sets it as the active dataset."""
    global ACTIVE_DATASET_PATH
    fname = (file.filename or "").lower()
    if not (fname.endswith(".xlsx") or fname.endswith(".csv")):
        raise HTTPException(
            status_code=400,
            detail="Invalid file type. Only ICSR datasets in .csv or .xlsx format are supported."
        )

    # Bound memory and disk use for unauthenticated uploads. Read one extra
    # byte so oversized payloads are rejected without buffering them in full.
    max_upload_bytes = 25 * 1024 * 1024
    content = await file.read(max_upload_bytes + 1)
    if len(content) > max_upload_bytes:
        raise HTTPException(status_code=413, detail="Dataset file exceeds the 25 MiB upload limit.")
    if not content or not content.strip():
        raise HTTPException(
            status_code=400,
            detail="Empty dataset: The uploaded file is empty (0 bytes). Please provide an ICSR dataset with at least one record."
        )

    clean_filename = Path(file.filename).name
    # Use an unpredictable server-controlled name rather than trusting client
    # filenames; concurrent uploads with the same name must not overwrite.
    suffix = ".xlsx" if fname.endswith(".xlsx") else ".csv"
    fd, temp_path = tempfile.mkstemp(prefix="uploaded_", suffix=suffix, dir=OUTPUTS_DIR)
    os.close(fd)
    temp_file = Path(temp_path)
    try:
        temp_file.write_bytes(content)
    except Exception:
        temp_file.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="Upload failure: unable to write file to disk.")

    try:
        df = load_and_normalize_data(str(temp_file))
        issues = validate_data(df)
        engine = AnalysisEngine(df)
        vol = engine.get_case_volume().value
        period = engine.get_reporting_period().value
        reactions = engine.get_reactions(top_n=10).value if engine.get_reactions(top_n=10) else {}
        serious_rx = engine.get_serious_reactions(top_n=10).value if engine.get_serious_reactions(top_n=10) else {}
        alerts = engine.get_alert_cases().value
        countries = engine.get_country_distribution().value
        age = engine.get_age_distribution().value

        ACTIVE_DATASET_PATH = str(temp_file)
        app.state.active_dataset_name = clean_filename

        return {
            "status": "success",
            "filename": clean_filename,
            "stored_path": str(temp_file),
            "is_custom_dataset": True,
            "total_rows": len(df),
            "rows_count": len(df),
            "total_cases": vol.get("total_cases", 0),
            "unique_cases": vol.get("total_cases", 0),
            "serious_cases": vol.get("serious_cases", 0),
            "serious_percentage": vol.get("serious_pct", 0),
            "non_serious_cases": vol.get("non_serious_cases", 0),
            "expedited_alerts": alerts.get("total_alerts", 0),
            "reporting_period": period,
            "top_reactions": reactions,
            "top_serious_reactions": serious_rx,
            "country_distribution": countries,
            "age_distribution": age,
            "validation_issues": issues
        }
    except ValueError as ve:
        temp_file.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(ve))
    except Exception as e:
        temp_file.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"Backend processing failure: Unable to parse ICSR dataset. {str(e)}")


@app.post("/api/dataset/reset", tags=["Dataset"])
def reset_dataset():
    """Resets the active dataset back to the default bundled Bisoprolol reference dataset."""
    global ACTIVE_DATASET_PATH
    ACTIVE_DATASET_PATH = None
    app.state.active_dataset_name = None
    return {"status": "success", "active_dataset": Path(get_active_dataset_path()).name}


# ===========================================================================
# PADER PIPELINE & REPORT GENERATION ENDPOINTS
# ===========================================================================

@app.post("/api/generate", tags=["PADER Pipeline"])
def generate_report(req: GenerateRequest):
    """Executes the complete PADER regulatory generation pipeline on the active or provided dataset."""
    file_path = get_active_dataset_path(req.file_path)
    # Never permit a client-supplied arbitrary server path to be processed.
    # Explicit paths are supported only for files created by the upload route.
    if req.file_path and Path(file_path).resolve().parent != OUTPUTS_DIR.resolve():
        raise HTTPException(status_code=400, detail="Specified dataset must be uploaded through /api/upload.")

    # Configure LLM Client
    if req.llm_provider.lower() == "mock" or not req.api_key:
        client = MockLLMClient()
    else:
        # Determine base URL if not provided
        base_url = req.base_url
        if not base_url:
            if req.llm_provider.lower() == "gemini":
                base_url = "https://generativelanguage.googleapis.com/v1beta/openai"
            elif req.llm_provider.lower() == "anthropic":
                base_url = "https://api.anthropic.com/v1"
            else:
                base_url = "https://api.openai.com/v1"

        client = OpenAICompatibleLLMClient(
            api_key=req.api_key,
            model_name=req.model_name or "gpt-4o-mini",
            base_url=base_url
        )

    decision_enum = ReviewDecision(req.review_decision) if req.review_decision in ReviewDecision.__members__ else ReviewDecision.PENDING_REVIEW

    orchestrator = PADEROrchestrator(llm_client=client)
    report = orchestrator.run(
        file_path=file_path,
        output_dir=str(OUTPUTS_DIR),
        review_decision=decision_enum,
        reviewer_name=req.reviewer_name or "Qualified Safety Reviewer",
        reviewer_notes=req.reviewer_notes,
        is_simulated_review=(decision_enum == ReviewDecision.SIMULATED_APPROVED)
    )

    # Cache report
    report_id = f"PADER-{report.metadata.product_name}-{report.metadata.reporting_period_end}"
    if report_id in REPORTS_DB:
        report_id = f"{report_id}-{secrets.token_hex(4).upper()}"
    if report.evaluation:
        report.evaluation.report_id = report_id
    REPORTS_DB[report_id] = report
    persist_reports()

    # Render markdown
    assembler = ReportAssembler()
    markdown_content = assembler.to_markdown(report)

    is_custom = bool(ACTIVE_DATASET_PATH and file_path == ACTIVE_DATASET_PATH) or bool(req.file_path and file_path == req.file_path)

    return {
        "status": "success",
        "report_id": report_id,
        "product_name": report.metadata.product_name,
        "report_status": report.status.value,
        "evaluation": report.evaluation.model_dump() if report.evaluation else {},
        "total_sections": len(report.sections),
        "human_approved": report.evaluation.is_human_approved if report.evaluation else False,
        "markdown_preview": markdown_content[:1500] + "\n\n...(full document available at /api/reports/{id}/markdown)",
        "report": report.model_dump(),
        "dataset_analyzed": getattr(app.state, "active_dataset_name", None) if file_path == ACTIVE_DATASET_PATH else Path(file_path).name,
        "is_custom_dataset": is_custom
    }


@app.get("/api/reports", tags=["PADER Pipeline"])
def list_reports(authorization: Optional[str] = Header(None)):
    """Lists persisted reports. Requires an authenticated application user."""
    require_user(authorization)
    items = []
    for rid, rep in REPORTS_DB.items():
        items.append({
            "report_id": rid,
            "product_name": rep.metadata.product_name,
            "period": f"{rep.metadata.reporting_period_start} to {rep.metadata.reporting_period_end}",
            "generated_at_utc": rep.metadata.generated_at_utc,
            "status": rep.status.value,
            "human_approved": rep.evaluation.is_human_approved if rep.evaluation else False,
            "factual_score": rep.evaluation.factual_consistency_score if rep.evaluation else 0.0,
            "grounding_score": rep.evaluation.grounding_score if rep.evaluation else 0.0
        })
    return {"reports": items, "count": len(items)}


@app.get("/api/reports/{report_id}", tags=["PADER Pipeline"])
def get_report(report_id: str, authorization: Optional[str] = Header(None)):
    """Retrieves full structured details for a specific report."""
    require_user(authorization)
    if not REPORTS_DB:
        load_reports()
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    return REPORTS_DB[report_id].model_dump()


@app.put("/api/reports/{report_id}", tags=["PADER Pipeline"])
def update_report_metadata(report_id: str, req: ReportMetadataUpdate, authorization: Optional[str] = Header(None)):
    """Update editable report metadata; only an authenticated analyst may edit drafts."""
    user = require_user(authorization)
    if user.get("role") not in ("analyst", "user"):
        raise HTTPException(status_code=403, detail="Only analysts may edit report metadata.")
    report = REPORTS_DB.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    if report.status != ReportStatus.DRAFT_PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="Only draft reports can be edited.")
    updates = req.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(report.metadata, field, value)
    REPORTS_DB[report_id] = report
    persist_reports()
    return report.model_dump()


@app.delete("/api/reports/{report_id}", status_code=204, tags=["PADER Pipeline"])
def delete_report(report_id: str, authorization: Optional[str] = Header(None)):
    """Delete an unreviewed draft. Reviewed reports are retained as audit records."""
    user = require_user(authorization)
    if user.get("role") not in ("analyst", "user"):
        raise HTTPException(status_code=403, detail="Only analysts may delete draft reports.")
    report = REPORTS_DB.get(report_id)
    if not report:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    if report.review_record or report.status != ReportStatus.DRAFT_PENDING_REVIEW:
        raise HTTPException(status_code=409, detail="Reviewed reports cannot be deleted.")
    del REPORTS_DB[report_id]
    persist_reports()
    return Response(status_code=204)


@app.get("/api/reports/{report_id}/markdown", tags=["PADER Pipeline"])
def get_report_markdown(report_id: str, authorization: Optional[str] = Header(None)):
    """Returns the regulatory Markdown document representation of the report."""
    require_user(authorization)
    if not REPORTS_DB:
        load_reports()
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    assembler = ReportAssembler()
    md = assembler.to_markdown(REPORTS_DB[report_id])
    return PlainTextResponse(content=md, media_type="text/markdown")


@app.get("/api/reports/{report_id}/download", tags=["PADER Pipeline"])
def download_report(report_id: str, authorization: Optional[str] = Header(None)):
    """Downloads the report as a Markdown file."""
    require_user(authorization)
    if not REPORTS_DB:
        load_reports()
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    assembler = ReportAssembler()
    md = assembler.to_markdown(REPORTS_DB[report_id])
    filename = f"{report_id}.md"
    return Response(
        content=md,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


# ===========================================================================
# DOCTOR HUMAN VERIFICATION & AUDIT SIGN-OFF ENDPOINTS
# ===========================================================================

@app.post("/api/reports/{report_id}/review", tags=["Human Review"])
def review_report(report_id: str, req: ReviewRequest, authorization: Optional[str] = Header(None)):
    """
    Submits an official medical reviewer sign-off action (APPROVED, NEEDS_REVISION, REJECTED).
    Requires an authenticated user with Doctor / Verifier role, validated by backend database.
    """
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")

    try:
        decision_enum = ReviewDecision(req.decision)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid decision. Must be one of: {[d.value for d in ReviewDecision]}")

    # Determine caller token
    token = None
    if authorization and authorization.lower().startswith("bearer "):
        token = authorization[7:].strip()
    elif req.token:
        token = req.token.strip()

    doctor_user = None
    if token:
        user = get_user_from_token(token)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid or expired session token. Please sign in.")
        if user.get("role") not in ("doctor", "verifier"):
            raise HTTPException(
                status_code=403,
                detail=f"Access denied: User '{user.get('username')}' has role '{user.get('role')}'. Only authenticated medical professionals with the Doctor/Verifier role may sign off."
            )
        doctor_user = user
    elif decision_enum != ReviewDecision.SIMULATED_APPROVED:
        # A claimed reviewer name or license is not proof of identity. Only an
        # authenticated doctor/verifier session may create a real sign-off.
        raise HTTPException(
            status_code=401,
            detail="Authentication required: Only authenticated medical professionals with the Doctor/Verifier role may sign off on regulatory reports."
        )

    # Fallback fixture if simulated
    if not doctor_user:
        doctor_user = {
            "id": 0,
            "full_name": req.reviewer_name or "Automated Test Runner",
            "role": "verifier",
            "medical_license": "SIMULATED-TEST",
            "specialty": "Automated Testing",
            "affiliation": "Test Harness"
        }

    # Record verification in database with cryptographic signature
    verif_record = record_doctor_verification(
        report_id=report_id,
        doctor_user=doctor_user,
        decision=decision_enum.value,
        notes=req.notes
    )

    mgr = HumanReviewManager()
    updated_report = mgr.apply_decision(
        report=REPORTS_DB[report_id],
        decision=decision_enum,
        reviewer_name=doctor_user.get("full_name") or req.reviewer_name,
        notes=req.notes,
        is_simulated=(decision_enum == ReviewDecision.SIMULATED_APPROVED),
        doctor_license=doctor_user.get("medical_license"),
        specialty=doctor_user.get("specialty"),
        affiliation=doctor_user.get("affiliation"),
        verification_id=verif_record.get("verification_id"),
        signature_hash=verif_record.get("signature_hash")
    )

    REPORTS_DB[report_id] = updated_report
    persist_reports()

    # Save to disk as well
    review_path = OUTPUTS_DIR / "review.json"
    if updated_report.review_record:
        with open(review_path, "w", encoding="utf-8") as f:
            f.write(json.dumps(updated_report.review_record.model_dump(), indent=2))

    return {
        "status": "success",
        "report_id": report_id,
        "new_status": updated_report.status.value,
        "is_human_approved": updated_report.evaluation.is_human_approved if updated_report.evaluation else False,
        "review_record": updated_report.review_record.model_dump() if updated_report.review_record else None,
        "verification": verif_record
    }


@app.get("/api/reports/{report_id}/verification", tags=["Human Review"])
def get_report_verification_details(report_id: str):
    """Retrieves official cryptographic verification record and verified doctor credentials from database."""
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    verif = get_verification_by_report(report_id)
    if not verif:
        return {
            "verified": False,
            "status": REPORTS_DB[report_id].status.value,
            "message": "Report has not been clinically verified by an authenticated medical professional."
        }
    return {
        "verified": True,
        "status": REPORTS_DB[report_id].status.value,
        "verification": verif
    }


# ===========================================================================
# BACKEND API ROOT & OPTIONAL DASHBOARD ROUTES
# ===========================================================================

@app.api_route("/", methods=["GET", "HEAD"], tags=["System"])
def root():
    """Backend API root endpoint providing service status and API links."""
    return {
        "status": "online",
        "service": "PharmaVigil Regulatory Report Engine Backend API",
        "version": "1.0.0",
        "message": "PharmaVigil FastAPI Backend is active and running.",
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "health_check": "/api/health",
        "frontend_url": "https://ameydongre10.github.io/PharmaVigil/"
    }


@app.api_route("/dashboard", methods=["GET", "HEAD"], response_class=HTMLResponse, tags=["Dashboard"])
def serve_dashboard():
    """Serves the standalone regulatory dashboard UI if accessed directly."""
    index_file = BASE_DIR / "index.html"
    if index_file.exists():
        return HTMLResponse(content=index_file.read_text(encoding="utf-8"))
    return HTMLResponse(content="<h1>PharmaVigil Regulatory Engine</h1><p>index.html not found</p>")


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
