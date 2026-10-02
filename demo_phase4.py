"""
Demonstration of Phase 4 Grounded LLM Generation.
Loads local dataset -> runs deterministic analysis -> collects evidence ->
builds context packets -> generates sections via LLMClient -> validates grounding.
"""

import sys
sys.path.insert(0, '.')
import os
import json
from src.data_loader import load_and_normalize_data
from src.analysis_engine import AnalysisEngine
from src.evidence_collector import collect_evidence
from src.context_builder import ContextBuilder
from src.report_config import PADER_CONFIG
from src.llm_client import create_llm_client, MockLLMClient
from src.section_generator import SectionGenerator
from src.grounding_validator import GroundingValidator


def run_demo():
    print("=" * 70)
    print("PHASE 4: GROUNDED LLM SECTION GENERATION & VALIDATION DEMO")
    print("=" * 70)

    # 1. Load Dataset & Deterministic Analysis
    file_path = "Bisoprolol_icsr_sample_1068rows.xlsx"
    if not os.path.exists(file_path):
        file_path = "sample_data/sample_icsr_dataset.xlsx"
    print(f"\n[1] Loading dataset: {file_path}")
    df = load_and_normalize_data(file_path)
    engine = AnalysisEngine(df)

    # 2. Collect Evidence
    print("[2] Running Phase 2 deterministic analysis and Phase 3 evidence collection...")
    evidence_list = collect_evidence(
        period=engine.get_reporting_period(),
        volume=engine.get_case_volume(),
        age=engine.get_age_distribution(),
        sex=engine.get_sex_distribution(),
        country=engine.get_country_distribution(),
        reactions=engine.get_reactions(top_n=20),
        serious_reactions=engine.get_serious_reactions(top_n=20),
        outcomes=engine.get_outcomes(),
        trends=engine.get_time_trends(),
        alerts=engine.get_alert_cases(),
        history=engine.get_history_of_actions(),
        expectedness=engine.get_expectedness(),
        case_index=engine.get_case_index(limit=10)
    )

    # 3. Build Context Packets
    print("[3] Building section-specific context packets...")
    builder = ContextBuilder(PADER_CONFIG, evidence_list)
    packets = builder.build_all_packets()

    # 4. Initialize LLM Client
    client = create_llm_client()
    is_mock = isinstance(client, MockLLMClient)
    print(f"[4] LLM Client initialized: {'MOCK (Offline Mode)' if is_mock else 'LIVE API Client'}")

    generator = SectionGenerator(client)
    validator = GroundingValidator()

    # Target demo sections
    demo_sections = ["Narrative Summary", "Reaction Analysis"]

    for sec_name in demo_sections:
        print("\n" + "-" * 70)
        print(f"GENERATING SECTION: {sec_name.upper()}")
        print("-" * 70)

        packet = [p for p in packets if p.section_name == sec_name][0]

        # Generate
        print(f"Context Packet Evidence Count: {len(packet.evidence)}")
        print(f"Available Evidence IDs: {[e.evidence_id for e in packet.evidence]}")
        
        generated = generator.generate(packet)

        # Validate
        val_result = validator.validate_section(generated, packet)

        print("\n>>> GENERATED STRUCTURED OUTPUT:")
        print(json.dumps(generated.model_dump(), indent=2))

        print("\n>>> GROUNDING VALIDATION REPORT:")
        print(f"Is Grounded: {'PASSED [YES]' if val_result.is_grounded else 'FAILED [NO]'}")
        print(f"Extracted Numbers: {val_result.extracted_numbers}")
        print(f"Supported Numbers: {val_result.supported_numbers}")
        print(f"Unsupported Numbers: {val_result.unsupported_numbers}")
        print(f"Flagged Claims: {val_result.flagged_claims}")
        print(f"Warnings: {val_result.warnings}")

    print("\n" + "=" * 70)
    print("PHASE 4 DEMONSTRATION COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    run_demo()
