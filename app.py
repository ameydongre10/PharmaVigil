"""
FastAPI Regulatory PADER Generation & Human Review Backend.

Provides:
1. REST API for dataset upload, deterministic analytics, grounded LLM generation,
   grounding verification, and human review sign-off.
2. Complete interactive Regulatory Pharmacovigilance Web Dashboard at `/`.
3. Auto-generated OpenAPI / Swagger docs at `/docs` and ReDoc at `/redoc`.
"""

import os
import sys
import json
import shutil
import tempfile
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from pathlib import Path

# Ensure project root is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, BackgroundTasks
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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# In-memory storage for generated reports and active dataset
REPORTS_DB: Dict[str, PADERReport] = {}
OUTPUTS_DIR = BASE_DIR / "outputs"
OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
SAMPLE_DATA_DIR = BASE_DIR / "sample_data"
SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SAMPLE_PATH = BASE_DIR / "Bisoprolol_icsr_sample_1068rows.xlsx"
FALLBACK_SAMPLE_PATH = SAMPLE_DATA_DIR / "sample_icsr_dataset.xlsx"


class GenerateRequest(BaseModel):
    file_path: Optional[str] = Field(None, description="Path to uploaded or sample dataset (.xlsx or .csv)")
    llm_provider: Optional[str] = Field("mock", description="LLM provider: mock, openai, gemini, anthropic, or generic")
    api_key: Optional[str] = Field(None, description="LLM API key (if live generation is selected)")
    model_name: Optional[str] = Field("gpt-4o-mini", description="LLM model identifier")
    base_url: Optional[str] = Field(None, description="Custom LLM API Base URL")
    review_decision: Optional[str] = Field("PENDING_REVIEW", description="Initial review decision")
    reviewer_name: Optional[str] = Field("Qualified Safety Reviewer", description="Name of the reviewer")
    reviewer_notes: Optional[str] = Field(None, description="Review notes")


class ReviewRequest(BaseModel):
    decision: str = Field(..., description="Decision: APPROVED, NEEDS_REVISION, REJECTED, or SIMULATED_APPROVED")
    reviewer_name: str = Field(..., description="Full Name and Title of Reviewer")
    notes: Optional[str] = Field("", description="Sign-off notes or audit rationale")


class RegenerateSectionRequest(BaseModel):
    section_name: str = Field(..., description="Name of LLM-generated section to regenerate")
    llm_provider: Optional[str] = Field("mock", description="mock or live")
    api_key: Optional[str] = Field(None, description="Optional API key")


def get_active_dataset_path(preferred_path: Optional[str] = None) -> str:
    """Resolves the dataset path, falling back to bundled sample files."""
    if preferred_path and os.path.exists(preferred_path):
        return preferred_path
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
        "sample_data_ready": DEFAULT_SAMPLE_PATH.exists() or FALLBACK_SAMPLE_PATH.exists()
    }


@app.get("/api/sample-data", tags=["Dataset"])
def get_sample_data_summary():
    """Returns metadata and preview statistics for the default Bisoprolol ICSR dataset."""
    path = get_active_dataset_path()
    df = load_and_normalize_data(path)
    engine = AnalysisEngine(df)

    vol = engine.get_case_volume().value
    period = engine.get_reporting_period().value
    reactions = engine.get_reactions(top_n=10).value
    serious_rx = engine.get_serious_reactions(top_n=10).value
    countries = engine.get_country_distribution().value
    age = engine.get_age_distribution().value
    alerts = engine.get_alert_cases().value

    return {
        "dataset_name": Path(path).name,
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
        "preview_sample": df[["safetyreportid", "receivedate", "serious_bool", "standard_country", "patient_reaction_reactionmeddrapt"]].head(5).to_dict(orient="records")
    }


@app.post("/api/upload", tags=["Dataset"])
async def upload_dataset(file: UploadFile = File(...)):
    """Uploads an ICSR dataset (.xlsx or .csv) and validates its schema."""
    if not (file.filename.endswith(".xlsx") or file.filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx and .csv files are supported.")

    temp_file = OUTPUTS_DIR / f"uploaded_{int(datetime.now().timestamp())}_{file.filename}"
    with open(temp_file, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    try:
        df = load_and_normalize_data(str(temp_file))
        issues = validate_data(df)
        engine = AnalysisEngine(df)
        vol = engine.get_case_volume().value
        period = engine.get_reporting_period().value

        return {
            "status": "success",
            "filename": file.filename,
            "stored_path": str(temp_file),
            "rows_count": len(df),
            "unique_cases": vol.get("total_cases", 0),
            "serious_cases": vol.get("serious_cases", 0),
            "reporting_period": period,
            "validation_issues": issues
        }
    except Exception as e:
        if temp_file.exists():
            temp_file.unlink()
        raise HTTPException(status_code=422, detail=f"Failed to parse ICSR dataset: {str(e)}")


@app.post("/api/generate", tags=["PADER Pipeline"])
def generate_report(req: GenerateRequest):
    """Executes the complete PADER regulatory generation pipeline."""
    file_path = get_active_dataset_path(req.file_path)

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
    report_id = report.evaluation.report_id if report.evaluation else f"PADER-{report.metadata.product_name}-{report.metadata.reporting_period_end}"
    REPORTS_DB[report_id] = report

    # Render markdown
    assembler = ReportAssembler()
    markdown_content = assembler.to_markdown(report)

    return {
        "status": "success",
        "report_id": report_id,
        "report_status": report.status.value,
        "evaluation": report.evaluation.model_dump() if report.evaluation else {},
        "total_sections": len(report.sections),
        "human_approved": report.evaluation.is_human_approved if report.evaluation else False,
        "markdown_preview": markdown_content[:1500] + "\n\n...(full document available at /api/reports/{id}/markdown)",
        "report": report.model_dump()
    }


@app.get("/api/reports", tags=["PADER Pipeline"])
def list_reports():
    """Lists all generated reports in memory."""
    items = []
    for rid, rep in REPORTS_DB.items():
        items.append({
            "report_id": rid,
            "product_name": rep.metadata.product_name,
            "period": f"{rep.metadata.reporting_period_start} to {rep.metadata.reporting_period_end}",
            "generated_at_utc": rep.metadata.generated_at_utc,
            "status": rep.status.value,
            "human_approved": rep.evaluation.is_human_approved,
            "factual_score": rep.evaluation.factual_consistency_score,
            "grounding_score": rep.evaluation.grounding_score
        })
    return {"reports": items, "count": len(items)}


@app.get("/api/reports/{report_id}", tags=["PADER Pipeline"])
def get_report(report_id: str):
    """Retrieves full structured details for a specific report."""
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    return REPORTS_DB[report_id].model_dump()


@app.get("/api/reports/{report_id}/markdown", tags=["PADER Pipeline"])
def get_report_markdown(report_id: str):
    """Returns the regulatory Markdown document representation of the report."""
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")
    assembler = ReportAssembler()
    md = assembler.to_markdown(REPORTS_DB[report_id])
    return PlainTextResponse(content=md, media_type="text/markdown")


@app.get("/api/reports/{report_id}/download", tags=["PADER Pipeline"])
def download_report(report_id: str):
    """Downloads the report as a Markdown file."""
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


@app.post("/api/reports/{report_id}/review", tags=["Human Review"])
def review_report(report_id: str, req: ReviewRequest):
    """Submits an official human reviewer sign-off action (APPROVED, NEEDS_REVISION, REJECTED)."""
    if report_id not in REPORTS_DB:
        raise HTTPException(status_code=404, detail=f"Report {report_id} not found.")

    try:
        decision_enum = ReviewDecision(req.decision)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid decision. Must be one of: {[d.value for d in ReviewDecision]}")

    mgr = HumanReviewManager()
    updated_report = mgr.apply_decision(
        report=REPORTS_DB[report_id],
        decision=decision_enum,
        reviewer_name=req.reviewer_name,
        notes=req.notes,
        is_simulated=(decision_enum == ReviewDecision.SIMULATED_APPROVED)
    )

    REPORTS_DB[report_id] = updated_report

    # Save to disk as well
    review_path = OUTPUTS_DIR / "review.json"
    if updated_report.review_record:
        with open(review_path, "w") as f:
            f.write(json.dumps(updated_report.review_record.model_dump(), indent=2))

    return {
        "status": "success",
        "report_id": report_id,
        "new_status": updated_report.status.value,
        "is_human_approved": updated_report.evaluation.is_human_approved,
        "review_record": updated_report.review_record.model_dump() if updated_report.review_record else None
    }


# ===========================================================================
# INTERACTIVE REGULATORY DASHBOARD UI (HTML + Tailwind CSS + Lucide Icons)
# ===========================================================================

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse, tags=["Dashboard"])
def serve_dashboard():
    """Serves a modern, self-contained regulatory PADER dashboard."""
    return """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>GenAR PADER Regulatory Report Engine</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap');
    body { font-family: 'Inter', sans-serif; }
    code, pre { font-family: 'JetBrains Mono', monospace; }
    .prose table { width: 100%; border-collapse: collapse; margin: 1rem 0; font-size: 0.875rem; }
    .prose th { background: #f8fafc; text-align: left; padding: 0.75rem 1rem; border: 1px solid #e2e8f0; font-weight: 600; }
    .prose td { padding: 0.75rem 1rem; border: 1px solid #e2e8f0; }
    .prose tr:nth-child(even) { background: #fdfdfd; }
    .prose h1 { font-size: 1.5rem; font-weight: 700; margin: 1.5rem 0 0.5rem; color: #0f172a; border-bottom: 2px solid #e2e8f0; padding-bottom: 0.5rem; }
    .prose h2 { font-size: 1.25rem; font-weight: 600; margin: 1.25rem 0 0.5rem; color: #1e293b; }
    .prose h3 { font-size: 1.1rem; font-weight: 600; margin: 1rem 0 0.25rem; color: #334155; }
    .prose p { margin: 0.5rem 0; color: #334155; line-height: 1.6; }
    .prose ul { list-style-type: disc; margin-left: 1.5rem; margin-bottom: 0.5rem; }
    .prose hr { margin: 1.5rem 0; border: 0; border-top: 1px solid #e2e8f0; }
    .prose blockquote { border-left: 4px solid #cbd5e1; padding-left: 1rem; color: #64748b; font-style: italic; }
  </style>
</head>
<body class="bg-slate-50 text-slate-900 min-h-screen">
  <!-- Top Navigation -->
  <header class="bg-slate-900 text-white shadow-md border-b border-slate-800">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-3.5 flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-9 h-9 rounded-lg bg-teal-500 flex items-center justify-center text-slate-900 font-bold text-lg shadow-sm">
          <i class="fa-solid fa-notes-medical"></i>
        </div>
        <div>
          <h1 class="text-lg font-bold tracking-tight text-white leading-tight">GenAR PADER Engine</h1>
          <p class="text-xs text-slate-400">Periodic Adverse Drug Experience Report &bull; 21 CFR 314.80</p>
        </div>
      </div>
      <div class="flex items-center space-x-3 text-xs">
        <span class="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
          <span class="w-1.5 h-1.5 mr-1.5 bg-emerald-400 rounded-full animate-pulse"></span> Service Active
        </span>
        <a href="/docs" target="_blank" class="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-300 rounded border border-slate-700 transition">
          <i class="fa-solid fa-code mr-1"></i> API Docs
        </a>
      </div>
    </div>
  </header>

  <!-- Main Container -->
  <main class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-6">
    <!-- Grid -->
    <div class="grid grid-cols-1 lg:grid-cols-12 gap-6">
      
      <!-- LEFT CONTROL PANEL (4 Cols) -->
      <div class="lg:col-span-4 space-y-6">
        
        <!-- Dataset Selector Card -->
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
          <div class="flex items-center justify-between mb-3">
            <h2 class="text-sm font-bold text-slate-900 uppercase tracking-wider flex items-center">
              <i class="fa-solid fa-database text-teal-600 mr-2"></i> 1. Source ICSR Dataset
            </h2>
            <span class="text-xs text-slate-500" id="datasetBadge">Sample Ready</span>
          </div>

          <p class="text-xs text-slate-600 mb-4">
            Upload custom pharmacovigilance ICSR cases (.xlsx/.csv) or instantly analyze the bundled Bisoprolol reference dataset.
          </p>

          <button onclick="loadSampleData()" id="btnLoadSample" class="w-full mb-3 py-2 px-3 bg-teal-50 hover:bg-teal-100 text-teal-800 border border-teal-300 rounded-lg text-xs font-semibold flex items-center justify-center transition">
            <i class="fa-solid fa-bolt text-teal-600 mr-2"></i> Load Bundled Bisoprolol Dataset
          </button>

          <!-- Upload Dropzone -->
          <div class="relative border-2 border-dashed border-slate-300 hover:border-teal-500 rounded-lg p-4 text-center cursor-pointer transition" id="dropzone">
            <input type="file" id="fileInput" accept=".xlsx,.csv" class="absolute inset-0 w-full h-full opacity-0 cursor-pointer" onchange="handleFileUpload(event)">
            <i class="fa-solid fa-cloud-arrow-up text-2xl text-slate-400 mb-1"></i>
            <p class="text-xs font-medium text-slate-700">Drop ICSR Excel / CSV here</p>
            <p class="text-[10px] text-slate-400">or click to browse from device</p>
          </div>

          <!-- Dataset Stats Mini-Grid -->
          <div id="datasetStats" class="mt-4 pt-3 border-t border-slate-100 grid grid-cols-2 gap-2 text-xs">
            <div class="bg-slate-50 p-2 rounded">
              <span class="text-slate-500 text-[11px] block">Dataset:</span>
              <span class="font-semibold text-slate-800 truncate block" id="statDatasetName">Bisoprolol_1068rows</span>
            </div>
            <div class="bg-slate-50 p-2 rounded">
              <span class="text-slate-500 text-[11px] block">Unique Cases:</span>
              <span class="font-semibold text-slate-800" id="statCaseCount">756 cases</span>
            </div>
            <div class="bg-slate-50 p-2 rounded">
              <span class="text-slate-500 text-[11px] block">Serious Ratio:</span>
              <span class="font-semibold text-rose-600" id="statSeriousCount">85.7% (648)</span>
            </div>
            <div class="bg-slate-50 p-2 rounded">
              <span class="text-slate-500 text-[11px] block">15-Day Alerts:</span>
              <span class="font-semibold text-amber-600" id="statAlertCount">382 alerts</span>
            </div>
          </div>
        </div>

        <!-- LLM & Generation Configuration -->
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
          <h2 class="text-sm font-bold text-slate-900 uppercase tracking-wider mb-3 flex items-center">
            <i class="fa-solid fa-brain text-indigo-600 mr-2"></i> 2. Grounded Pipeline Engine
          </h2>

          <div class="space-y-3 text-xs">
            <div>
              <label class="block text-slate-700 font-medium mb-1">LLM Execution Mode</label>
              <select id="llmProvider" class="w-full border border-slate-300 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 focus:outline-none" onchange="toggleApiKeyField()">
                <option value="mock">Offline Deterministic Mock (100% Grounded)</option>
                <option value="openai">OpenAI (GPT-4o / GPT-4o-mini)</option>
                <option value="gemini">Google Gemini (Gemini 1.5 / 2.0)</option>
                <option value="anthropic">Anthropic Claude</option>
                <option value="generic">Custom OpenAI-Compatible API</option>
              </select>
            </div>

            <div id="apiKeyGroup" class="hidden">
              <label class="block text-slate-700 font-medium mb-1">API Key</label>
              <input type="password" id="apiKey" placeholder="sk-..." class="w-full border border-slate-300 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 focus:outline-none">
              <p class="text-[10px] text-slate-400 mt-0.5">Kept in-memory for the current request only.</p>
            </div>

            <div>
              <label class="block text-slate-700 font-medium mb-1">Model Identifier</label>
              <input type="text" id="modelName" value="gpt-4o-mini" class="w-full border border-slate-300 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 focus:outline-none">
            </div>

            <div class="bg-slate-50 border border-slate-200 rounded p-2.5 text-[11px] text-slate-600 space-y-1">
              <p><i class="fa-solid fa-shield-halved text-emerald-600 mr-1"></i> <strong>Zero Calculation Hallucination:</strong> Deterministic math layer calculates all sums, counts, and percentages.</p>
              <p><i class="fa-solid fa-filter text-indigo-600 mr-1"></i> <strong>Strict Context Boundaries:</strong> Raw tabular rows are never dumped into LLM prompts.</p>
            </div>

            <button onclick="triggerPipeline()" id="btnGenerate" class="w-full py-2.5 px-4 bg-slate-900 hover:bg-slate-800 text-white rounded-lg text-xs font-semibold flex items-center justify-center shadow transition">
              <i class="fa-solid fa-play text-teal-400 mr-2"></i> Run Regulatory Pipeline
            </button>
          </div>
        </div>

        <!-- Human Review Sign-Off Action Card -->
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5" id="reviewConsoleCard">
          <h2 class="text-sm font-bold text-slate-900 uppercase tracking-wider mb-2 flex items-center">
            <i class="fa-solid fa-signature text-amber-600 mr-2"></i> 3. Human Review Station
          </h2>
          <p class="text-xs text-slate-600 mb-3">
            In compliance with FDA guidelines, AI-generated safety reports cannot self-approve. An authorized medical officer must explicitly review and sign off.
          </p>

          <div class="space-y-3 text-xs">
            <div>
              <label class="block text-slate-700 font-medium mb-1">Reviewer Name & Credentials</label>
              <input type="text" id="reviewerName" value="Dr. J. Doe, Medical Safety Officer" class="w-full border border-slate-300 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 focus:outline-none">
            </div>
            <div>
              <label class="block text-slate-700 font-medium mb-1">Regulatory Sign-Off Decision</label>
              <select id="reviewDecisionSelect" class="w-full border border-slate-300 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 focus:outline-none">
                <option value="APPROVED">APPROVED (Authorize PADER Submission)</option>
                <option value="NEEDS_REVISION">NEEDS_REVISION (Request Medical Clarifications)</option>
                <option value="REJECTED">REJECTED (Invalid or Inconsistent Data)</option>
              </select>
            </div>
            <div>
              <label class="block text-slate-700 font-medium mb-1">Audit Notes / Comments</label>
              <textarea id="reviewerNotes" rows="2" placeholder="Verified case statistics against deterministic tables..." class="w-full border border-slate-300 rounded-md px-2.5 py-1.5 text-xs focus:ring-1 focus:ring-teal-500 focus:outline-none"></textarea>
            </div>
            <button onclick="submitHumanReview()" id="btnSubmitReview" class="w-full py-2 px-3 bg-amber-600 hover:bg-amber-700 text-white rounded-lg text-xs font-semibold flex items-center justify-center transition disabled:opacity-50" disabled>
              <i class="fa-solid fa-stamp mr-2"></i> Record Reviewer Decision
            </button>
          </div>
        </div>

      </div>

      <!-- RIGHT REPORT & AUDIT VIEWER (8 Cols) -->
      <div class="lg:col-span-8 space-y-6">
        
        <!-- Status & Compliance Header Banner -->
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
          <div class="flex flex-wrap items-center justify-between gap-3">
            <div>
              <div class="flex items-center space-x-2">
                <h2 class="text-base font-bold text-slate-900" id="currentReportTitle">PADER-BISOPROLOL-ANNUAL-REPORT</h2>
                <span id="statusBadge" class="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200">
                  DRAFT_PENDING_REVIEW
                </span>
              </div>
              <p class="text-xs text-slate-500 mt-0.5" id="reportSubheader">No active report generated. Click "Run Regulatory Pipeline" to generate.</p>
            </div>
            
            <div class="flex items-center space-x-2">
              <button onclick="downloadMarkdown()" id="btnDownload" class="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded border border-slate-300 text-xs font-medium transition disabled:opacity-50" disabled>
                <i class="fa-solid fa-download mr-1"></i> Export .MD
              </button>
              <button onclick="downloadJsonAudit()" id="btnAuditJson" class="px-3 py-1.5 bg-slate-100 hover:bg-slate-200 text-slate-700 rounded border border-slate-300 text-xs font-medium transition disabled:opacity-50" disabled>
                <i class="fa-solid fa-file-code mr-1"></i> Audit JSON
              </button>
            </div>
          </div>

          <!-- Evaluation Score Bar -->
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 mt-4 pt-3 border-t border-slate-100 text-center">
            <div class="bg-slate-50 p-2.5 rounded-lg border border-slate-100">
              <span class="text-[11px] text-slate-500 font-medium block">Factual Consistency</span>
              <span class="text-base font-bold text-emerald-600" id="scoreFactual">--%</span>
            </div>
            <div class="bg-slate-50 p-2.5 rounded-lg border border-slate-100">
              <span class="text-[11px] text-slate-500 font-medium block">Grounding Score</span>
              <span class="text-base font-bold text-emerald-600" id="scoreGrounding">--%</span>
            </div>
            <div class="bg-slate-50 p-2.5 rounded-lg border border-slate-100">
              <span class="text-[11px] text-slate-500 font-medium block">Required Sections</span>
              <span class="text-base font-bold text-slate-800" id="scoreSections">-- / 8</span>
            </div>
            <div class="bg-slate-50 p-2.5 rounded-lg border border-slate-100">
              <span class="text-[11px] text-slate-500 font-medium block">Automated Audit</span>
              <span class="text-base font-bold text-slate-600" id="scoreAudit">--</span>
            </div>
          </div>
        </div>

        <!-- Tabbed Report Display -->
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
          <div class="border-b border-slate-200 bg-slate-50 px-4 flex space-x-6 text-xs font-semibold">
            <button onclick="switchTab('reportView')" id="tabBtnReport" class="py-3 text-teal-700 border-b-2 border-teal-600">
              <i class="fa-solid fa-file-lines mr-1.5"></i> Formatted PADER Report
            </button>
            <button onclick="switchTab('auditView')" id="tabBtnAudit" class="py-3 text-slate-500 hover:text-slate-800">
              <i class="fa-solid fa-microscope mr-1.5"></i> Grounding Verification Details
            </button>
            <button onclick="switchTab('rawMdView')" id="tabBtnRaw" class="py-3 text-slate-500 hover:text-slate-800">
              <i class="fa-brands fa-markdown mr-1.5"></i> Raw Markdown Source
            </button>
          </div>

          <!-- Tab 1: Rendered Document -->
          <div id="tabReport" class="p-6">
            <div id="reportLoadingSpinner" class="hidden text-center py-12">
              <i class="fa-solid fa-circle-notch fa-spin text-3xl text-teal-600 mb-3"></i>
              <p class="text-sm font-medium text-slate-700">Running Deterministic Aggregation & Grounded LLM Generation...</p>
              <p class="text-xs text-slate-400 mt-1">Collecting evidence packets & validating hallucination guards</p>
            </div>
            <div id="reportEmptyState" class="text-center py-16 text-slate-400">
              <i class="fa-solid fa-clipboard-check text-4xl mb-3 text-slate-300"></i>
              <p class="text-sm font-medium text-slate-600">No PADER Report Generated Yet</p>
              <p class="text-xs text-slate-400 max-w-sm mx-auto mt-1">Click "Run Regulatory Pipeline" in the control panel to generate an audit-ready PADER safety report.</p>
            </div>
            <div id="reportRenderedContent" class="prose max-w-none text-slate-800 text-sm hidden"></div>
          </div>

          <!-- Tab 2: Grounding & Audit Verification -->
          <div id="tabAudit" class="p-6 hidden">
            <div class="mb-4">
              <h3 class="text-sm font-bold text-slate-900">Hallucination & Number Extraction Audit</h3>
              <p class="text-xs text-slate-500">Every single numeric figure in the LLM-generated narrative is cross-checked against deterministic evidence.</p>
            </div>
            <div id="auditCardsContainer" class="space-y-3">
              <p class="text-xs text-slate-400 text-center py-8">Generate a report to inspect per-section grounding verification tables.</p>
            </div>
          </div>

          <!-- Tab 3: Raw Markdown -->
          <div id="tabRaw" class="p-6 hidden">
            <div class="flex justify-between items-center mb-2">
              <span class="text-xs font-semibold text-slate-500 uppercase tracking-wider">Raw Regulatory Markdown Text</span>
              <button onclick="copyRawMarkdown()" class="text-xs text-teal-600 hover:text-teal-700 font-medium">
                <i class="fa-regular fa-copy mr-1"></i> Copy
              </button>
            </div>
            <pre id="rawMarkdownContent" class="bg-slate-900 text-slate-200 p-4 rounded-lg text-xs overflow-x-auto whitespace-pre-wrap max-h-[600px]">/* Raw markdown will appear here after generation */</pre>
          </div>
        </div>

      </div>

    </div>
  </main>

  <script>
    let currentReportId = null;
    let currentReportData = null;
    let currentMarkdown = "";
    let uploadedFilePath = null;

    function toggleApiKeyField() {
      const prov = document.getElementById("llmProvider").value;
      const grp = document.getElementById("apiKeyGroup");
      if (prov === "mock") {
        grp.classList.add("hidden");
      } else {
        grp.classList.remove("hidden");
      }
    }

    async function loadSampleData() {
      try {
        const res = await fetch("/api/sample-data");
        const data = await res.json();
        document.getElementById("statDatasetName").innerText = data.dataset_name;
        document.getElementById("statCaseCount").innerText = `${data.total_cases} cases`;
        document.getElementById("statSeriousCount").innerText = `${data.serious_percentage}% (${data.serious_cases})`;
        document.getElementById("statAlertCount").innerText = `${data.expedited_alerts} alerts`;
        uploadedFilePath = null;
        alert(`Loaded sample dataset: ${data.dataset_name} (${data.total_cases} unique cases, ${data.total_rows} rows). Ready for generation.`);
      } catch (err) {
        alert("Error loading sample dataset: " + err);
      }
    }

    async function handleFileUpload(e) {
      const file = e.target.files[0];
      if (!file) return;

      const fd = new FormData();
      fd.append("file", file);

      try {
        const res = await fetch("/api/upload", { method: "POST", body: fd });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();
        uploadedFilePath = data.stored_path;
        document.getElementById("statDatasetName").innerText = data.filename;
        document.getElementById("statCaseCount").innerText = `${data.unique_cases} cases`;
        document.getElementById("statSeriousCount").innerText = `${data.serious_cases} serious`;
        document.getElementById("datasetBadge").innerText = "Custom File Loaded";
        alert(`File uploaded: ${data.filename} (${data.unique_cases} cases)`);
      } catch (err) {
        alert("Upload error: " + err);
      }
    }

    async function triggerPipeline() {
      const btn = document.getElementById("btnGenerate");
      const spinner = document.getElementById("reportLoadingSpinner");
      const emptyState = document.getElementById("reportEmptyState");
      const renderedContent = document.getElementById("reportRenderedContent");

      btn.disabled = true;
      spinner.classList.remove("hidden");
      emptyState.classList.add("hidden");
      renderedContent.classList.add("hidden");

      const provider = document.getElementById("llmProvider").value;
      const apiKey = document.getElementById("apiKey").value;
      const model = document.getElementById("modelName").value;

      const payload = {
        file_path: uploadedFilePath,
        llm_provider: provider,
        api_key: apiKey || null,
        model_name: model || "gpt-4o-mini"
      };

      try {
        const res = await fetch("/api/generate", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload)
        });

        if (!res.ok) {
          const err = await res.json();
          throw new Error(err.detail || "Generation failed.");
        }

        const data = await res.json();
        currentReportId = data.report_id;
        currentReportData = data.report;

        // Fetch full markdown
        const mdRes = await fetch(`/api/reports/${currentReportId}/markdown`);
        currentMarkdown = await mdRes.text();

        updateReportUI(data);
      } catch (err) {
        alert("Generation error: " + err.message);
        emptyState.classList.remove("hidden");
      } finally {
        btn.disabled = false;
        spinner.classList.add("hidden");
      }
    }

    function updateReportUI(data) {
      const ev = data.evaluation;
      document.getElementById("currentReportTitle").innerText = data.report_id;
      document.getElementById("reportSubheader").innerText = `Reporting Period: ${currentReportData.metadata.reporting_period_start} to ${currentReportData.metadata.reporting_period_end}`;
      
      const badge = document.getElementById("statusBadge");
      badge.innerText = data.report_status;
      if (data.report_status === "HUMAN_APPROVED") {
        badge.className = "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200";
      } else if (data.report_status === "NEEDS_REVISION") {
        badge.className = "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200";
      } else if (data.report_status === "REJECTED") {
        badge.className = "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-200";
      } else {
        badge.className = "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-100 text-blue-800 border border-blue-200";
      }

      document.getElementById("scoreFactual").innerText = `${ev.factual_consistency_score}%`;
      document.getElementById("scoreGrounding").innerText = `${ev.grounding_score}%`;
      document.getElementById("scoreSections").innerText = `${ev.required_sections_present} / ${ev.required_sections_total}`;
      document.getElementById("scoreAudit").innerText = ev.automated_evaluation_status;

      // Render Markdown HTML
      const renderedContent = document.getElementById("reportRenderedContent");
      renderedContent.innerHTML = marked.parse(currentMarkdown);
      renderedContent.classList.remove("hidden");

      // Raw Markdown tab
      document.getElementById("rawMarkdownContent").innerText = currentMarkdown;

      // Populate Audit Cards
      renderAuditDetails(ev);

      // Enable export buttons & review button
      document.getElementById("btnDownload").disabled = false;
      document.getElementById("btnAuditJson").disabled = false;
      document.getElementById("btnSubmitReview").disabled = false;
    }

    function renderAuditDetails(ev) {
      const container = document.getElementById("auditCardsContainer");
      let html = "";

      for (const [secName, details] of Object.entries(ev.section_details)) {
        const isPass = details.status === "PASS";
        const badgeColor = isPass ? "bg-emerald-100 text-emerald-800 border-emerald-200" : "bg-rose-100 text-rose-800 border-rose-200";
        
        html += `
          <div class="border border-slate-200 rounded-lg p-3 bg-white text-xs">
            <div class="flex items-center justify-between mb-1">
              <span class="font-bold text-slate-800">${secName}</span>
              <span class="px-2 py-0.5 rounded-full text-[10px] font-semibold ${badgeColor} border">${details.status}</span>
            </div>
            <div class="text-[11px] text-slate-500 space-y-0.5">
              <p>Type: <span class="font-mono text-slate-700">${details.type}</span> &bull; Evidence IDs: ${details.evidence_ids_count}</p>
              ${details.warnings && details.warnings.length ? `<p class="text-amber-600 font-medium">Warnings: ${details.warnings.join(", ")}</p>` : `<p class="text-emerald-600">Zero unsupported claims detected.</p>`}
            </div>
          </div>
        `;
      }

      container.innerHTML = html;
    }

    async function submitHumanReview() {
      if (!currentReportId) {
        alert("Please generate a report first.");
        return;
      }

      const reviewer = document.getElementById("reviewerName").value;
      const decision = document.getElementById("reviewDecisionSelect").value;
      const notes = document.getElementById("reviewerNotes").value;

      try {
        const res = await fetch(`/api/reports/${currentReportId}/review`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            decision: decision,
            reviewer_name: reviewer,
            notes: notes
          })
        });

        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();

        // Refresh markdown
        const mdRes = await fetch(`/api/reports/${currentReportId}/markdown`);
        currentMarkdown = await mdRes.text();
        document.getElementById("reportRenderedContent").innerHTML = marked.parse(currentMarkdown);
        document.getElementById("rawMarkdownContent").innerText = currentMarkdown;

        const badge = document.getElementById("statusBadge");
        badge.innerText = data.new_status;
        if (data.new_status === "HUMAN_APPROVED") {
          badge.className = "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-100 text-emerald-800 border border-emerald-200";
        } else if (data.new_status === "NEEDS_REVISION") {
          badge.className = "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-200";
        } else {
          badge.className = "px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-200";
        }

        alert(`Human review recorded: ${data.new_status}`);
      } catch (err) {
        alert("Review sign-off error: " + err.message);
      }
    }

    function switchTab(tabId) {
      document.getElementById("tabReport").classList.add("hidden");
      document.getElementById("tabAudit").classList.add("hidden");
      document.getElementById("tabRaw").classList.add("hidden");

      document.getElementById("tabBtnReport").className = "py-3 text-slate-500 hover:text-slate-800";
      document.getElementById("tabBtnAudit").className = "py-3 text-slate-500 hover:text-slate-800";
      document.getElementById("tabBtnRaw").className = "py-3 text-slate-500 hover:text-slate-800";

      if (tabId === "reportView") {
        document.getElementById("tabReport").classList.remove("hidden");
        document.getElementById("tabBtnReport").className = "py-3 text-teal-700 border-b-2 border-teal-600";
      } else if (tabId === "auditView") {
        document.getElementById("tabAudit").classList.remove("hidden");
        document.getElementById("tabBtnAudit").className = "py-3 text-teal-700 border-b-2 border-teal-600";
      } else {
        document.getElementById("tabRaw").classList.remove("hidden");
        document.getElementById("tabBtnRaw").className = "py-3 text-teal-700 border-b-2 border-teal-600";
      }
    }

    function downloadMarkdown() {
      if (!currentReportId) return;
      window.location.href = `/api/reports/${currentReportId}/download`;
    }

    function downloadJsonAudit() {
      if (!currentReportData) return;
      const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(currentReportData, null, 2));
      const dlAnchor = document.createElement("a");
      dlAnchor.setAttribute("href", dataStr);
      dlAnchor.setAttribute("download", `${currentReportId}_audit.json`);
      dlAnchor.click();
    }

    function copyRawMarkdown() {
      navigator.clipboard.writeText(currentMarkdown);
      alert("Raw markdown copied to clipboard.");
    }
  </script>
</body>
</html>
"""


if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
