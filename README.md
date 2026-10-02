# GenAR: Periodic Adverse Drug Experience Report (PADER) Generator

## 1. Project Title
GenAR PADER Regulatory Report Generation Pipeline (Version 0)

## 2. Problem Statement
Regulatory safety reports like PADERs demand absolute factual accuracy and strict adherence to specific sections and guidelines. While Large Language Models (LLMs) are excellent at synthesizing fluent clinical narratives, they are prone to hallucinating numbers, inventing causality, or declaring unverified safety signals. The challenge is to safely harness the generative capabilities of LLMs without compromising the deterministic integrity of the underlying pharmacovigilance data.

## 3. Solution Overview
The GenAR PADER pipeline solves this by implementing a strictly deterministic-first architecture. A robust analytics engine calculates all case volumes, demographic distributions, and reaction frequencies. These facts are wrapped into traceable evidence packets and provided to the LLM to generate narrative sections. A deterministic grounding validator ensures the LLM's output introduces no numerical hallucinations or forbidden clinical claims. Finally, a human-in-the-loop review system ensures qualified regulatory approval before finalizing any report.

## 4. Architecture
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full architectural details and diagrams. The system strictly isolates:
- **Deterministic Analytics:** (Source of Truth)
- **Evidence Context:** (Data boundary protection)
- **LLM Generation:** (Narrative synthesis only)

## 5. Key Design Principles
- **No Raw Data to LLM:** Raw datasets are never exposed to the LLM prompt.
- **Fail Safely:** A failure in LLM generation isolates to the affected section without crashing the pipeline, surfacing a clear `REVIEW_REQUIRED` state.
- **Human in the Loop:** Automated evaluations assess structural completeness and grounding; human review is required for approval.

## 6. Data Flow
Raw Dataset -> Data Validation -> Deterministic Analysis -> Evidence Items -> Section-specific Context Packets -> LLM Generation -> Grounding Validation -> Report Assembly -> Human Review.

## 7. Deterministic Analysis
Performs all row-to-case deduplication, demographic bucketing, and statistical aggregation. It is responsible for 100% of the numerical facts presented in the final report.

## 8. Evidence & Context Engineering
Statistics are packaged into `EvidenceItem` structures with explicit methodologies. A `ContextBuilder` selects only the required subset of evidence for each section, minimizing the LLM context window and preventing cross-contamination.

## 9. Grounded LLM Generation
The LLM receives targeted instructions and a precise evidence packet, tasked solely with synthesizing the provided facts into regulatory-style prose.

## 10. Grounding Validation
Extracts all numbers and targeted phrases (like "causality established" or "safety signal") from the LLM output and validates them against the allowed evidence payload. Hallucinations fail the validation check and flag the section.

## 11. Human Review
Report states advance strictly from `DRAFT_PENDING_REVIEW` to `HUMAN_APPROVED`, `NEEDS_REVISION`, or `REJECTED` via explicit human intervention.

## 12. Evaluation
An automated evaluator ensures all mandatory sections exist, no section failed grounding validation, and limitations are correctly stated. It cannot approve the report, only determine if it is technically ready for human review.

## 13. Safety & Failure Handling
- **Section Isolation:** HTTP 500s or timeouts flag the section as `GENERATION FAILED` without corrupting other sections.
- **Targeted Regeneration:** Individual sections can be regenerated without rebuilding the entire report.

## 14. Version 0 Limitations
- **Expectedness:** Not determinable without an authorized product label or CCDS.
- **History of Actions:** No external regulatory history data is provided in the dataset.
- **System Organ Class (SOC):** Only MedDRA Preferred Terms (PT) are provided; no SOC hierarchy mapping is performed.
- **Causality:** The system does not establish medical causality or confirm safety signals.

## 15. Project Structure
```
GenAR/
├── .env.example
├── .gitignore
├── README.md
├── requirements.txt
├── run_pader.py             # CLI entry point
├── src/                     # Core pipeline modules
├── tests/                   # 115+ automated tests
├── docs/                    # Architecture and documentation
└── outputs/                 # (Git-ignored) Generated artifacts
```

## 16. Setup
Ensure Python 3.10+ is installed.
```bash
python -m venv venv
# Windows: venv\Scripts\activate
# Mac/Linux: source venv/bin/activate
pip install -r requirements.txt
```

## 17. Environment Configuration
Copy `.env.example` to `.env` and configure your API credentials.
```bash
LLM_API_KEY=your_key_here
LLM_MODEL=gpt-4o-mini
```
If no key is provided, the system seamlessly defaults to an offline `MockLLMClient` for testing.

## 18. How to Run Tests
```bash
$env:PYTHONPATH="."
pytest -v
```

## 19. How to Run the PADER Pipeline
```bash
python run_pader.py --data Bisoprolol_icsr_sample_1068rows.xlsx --output-dir outputs
```

## 20. How to Perform Human Review
```bash
python run_pader.py --data Bisoprolol_icsr_sample_1068rows.xlsx --output-dir outputs --review APPROVED
# Or to target a section for regeneration:
python run_pader.py --data Bisoprolol_icsr_sample_1068rows.xlsx --output-dir outputs --review NEEDS_REVISION --target-section "Narrative Summary"
```

## 21. Expected Outputs
Check the `outputs/` folder (which is ignored by Git to protect data):
- `pader_report.md`: The fully assembled PADER report.
- `evaluation.json`: The evaluator's technical assessment.
- `review.json`: The human audit trail (if review was performed).

## 22. Git/GitHub Data Protection
- The raw dataset (`.xlsx`/`.csv`) is ignored.
- The `outputs/` directory is ignored.
- `__pycache__` and virtual environments are ignored.
- Secrets and `.env` files are ignored.

## 23. Future Version 1 Direction
- **Product Label Integration:** RAG or structured ingestion of CCDS documents to automate expectedness evaluation.
- **MedDRA Hierarchy:** API integration to map PTs to SOCs.
- **Richer UI:** A web-based review dashboard for medical writers.
- **Audit Trails:** Cryptographically signed approval logs.

## 24. Engineering Highlights
- strictly deterministic-first architecture.
- evidence-based context packets preventing LLM hallucination.
- strict data boundary: no raw dataset ever sent to the LLM.
- robust grounding validation against numerical hallucination and forbidden claims.
- human-in-the-loop approval workflow.
- targeted regeneration of isolated sections.
- 115 automated tests covering edge cases, failures, and data edge cases.
- offline mock testing support.
- failure isolation preventing full pipeline crashes on LLM timeouts.
