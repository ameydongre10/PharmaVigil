"""
Command Line Interface (CLI) for running the end-to-end PADER Generation Pipeline.

Usage:
    # 1. Generate Draft Report (Status: DRAFT_PENDING_REVIEW)
    python run_pader.py --data Bisoprolol_icsr_sample_1068rows.xlsx --output-dir outputs

    # 2. Perform Explicit Human Review Sign-Off
    python run_pader.py --data Bisoprolol_icsr_sample_1068rows.xlsx --sign-off APPROVED --reviewer "Dr. J. Doe, MD" --notes "Verified all statistics."

    # 3. Run Simulated Review for Testing / Demo
    python run_pader.py --data Bisoprolol_icsr_sample_1068rows.xlsx --simulate-review APPROVED
"""

import sys
sys.path.insert(0, '.')
import argparse
import os
from src.orchestrator import PADEROrchestrator
from src.llm_client import create_llm_client
from src.report_models import ReviewDecision, ReportStatus


def main():
    parser = argparse.ArgumentParser(description="Generate Grounded PADER Safety Report")
    parser.add_argument(
        "--data",
        type=str,
        default="Bisoprolol_icsr_sample_1068rows.xlsx",
        help="Path to source ICSR Excel or CSV dataset (default: Bisoprolol_icsr_sample_1068rows.xlsx)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="outputs",
        help="Directory to save generated report and artifacts (default: outputs)"
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Force offline Mock LLM client even if LLM_API_KEY is present"
    )
    parser.add_argument(
        "--sign-off",
        type=str,
        choices=["APPROVED", "NEEDS_REVISION", "REJECTED"],
        default=None,
        help="Perform explicit human reviewer sign-off"
    )
    parser.add_argument(
        "--simulate-review",
        type=str,
        choices=["APPROVED", "NEEDS_REVISION", "REJECTED"],
        default=None,
        help="Run simulated review decision for automated testing / demo fixtures"
    )
    parser.add_argument(
        "--reviewer",
        type=str,
        default="Qualified Safety Reviewer",
        help="Name/Title of the human reviewer"
    )
    parser.add_argument(
        "--notes",
        type=str,
        default=None,
        help="Human reviewer comments/sign-off notes"
    )

    args = parser.parse_args()

    dataset_path = args.data
    if not os.path.exists(dataset_path):
        if os.path.exists("sample_data/sample_icsr_dataset.xlsx"):
            dataset_path = "sample_data/sample_icsr_dataset.xlsx"
            print(f"[!] Dataset '{args.data}' not found. Using bundled sample: {dataset_path}")
        elif os.path.exists("sample_data/sample_icsr_dataset.csv"):
            dataset_path = "sample_data/sample_icsr_dataset.csv"
            print(f"[!] Dataset '{args.data}' not found. Using bundled sample: {dataset_path}")

    print("========================================================================")
    print("GENAR PADER REGULATORY REPORT GENERATION PIPELINE")
    print("========================================================================")
    print(f"Input Dataset    : {dataset_path}")
    print(f"Output Directory : {args.output_dir}")
    print(f"LLM Provider Mode: {'MOCK (Offline)' if args.mock or not os.getenv('LLM_API_KEY') else 'LIVE API'}")

    # Determine Review Action
    is_simulated = False
    if args.sign_off:
        review_decision = ReviewDecision(args.sign_off)
        print(f"Workflow Action  : EXPLICIT HUMAN REVIEW SIGN-OFF -> `{review_decision.value}`")
    elif args.simulate_review:
        review_decision = ReviewDecision(args.simulate_review)
        is_simulated = True
        print(f"Workflow Action  : SIMULATED HUMAN REVIEW (Test Fixture) -> `{review_decision.value}`")
    else:
        review_decision = ReviewDecision.PENDING_REVIEW
        print(f"Workflow Action  : DRAFT GENERATION (Status: PENDING_REVIEW)")

    print("------------------------------------------------------------------------")

    client = create_llm_client(force_mock=args.mock)
    orchestrator = PADEROrchestrator(llm_client=client)

    report = orchestrator.run(
        file_path=dataset_path,
        output_dir=args.output_dir,
        review_decision=review_decision,
        reviewer_name=args.reviewer,
        reviewer_notes=args.notes or ("Simulated test approval." if is_simulated else "Reviewed against source metrics."),
        is_simulated_review=is_simulated
    )

    print("\n[+] Pipeline execution completed successfully!")
    print(f"[+] Total Sections Rendered : {len(report.sections)}")
    print(f"[+] Required Assignment Sections : {report.evaluation.required_sections_present}/{report.evaluation.required_sections_total} (Complete: {report.evaluation.required_sections_complete})")
    print(f"[+] Additional Limitation Notices: {report.evaluation.additional_limitation_sections_present}")
    print(f"[+] Automated Evaluation Status : {report.evaluation.automated_evaluation_status.value} (Factual: {report.evaluation.factual_consistency_score}%, Grounding: {report.evaluation.grounding_score}%)")
    print(f"[+] Final Report Status         : {report.status.value}")
    print(f"[+] Human Approved              : {report.evaluation.is_human_approved}")
    print(f"[+] Artifacts written to: {args.output_dir}/")
    print(f"    - {args.output_dir}/pader_report.md")
    print(f"    - {args.output_dir}/evaluation.json")
    if report.review_record:
        print(f"    - {args.output_dir}/review.json")
    print("========================================================================")


if __name__ == "__main__":
    main()
