import sys
sys.path.insert(0, '.')
import json
from src.data_loader import load_and_normalize_data
from src.analysis_engine import AnalysisEngine
from src.evidence_collector import collect_evidence
from src.context_builder import ContextBuilder
from src.report_config import PADER_CONFIG

import os

def run_demo():
    file_path = "Bisoprolol_icsr_sample_1068rows.xlsx"
    if not os.path.exists(file_path):
        file_path = "sample_data/sample_icsr_dataset.xlsx"
    df = load_and_normalize_data(file_path)
    engine = AnalysisEngine(df)

    # 1. Deterministic Analysis
    period = engine.get_reporting_period()
    volume = engine.get_case_volume()
    age = engine.get_age_distribution()
    sex = engine.get_sex_distribution()
    country = engine.get_country_distribution()
    reactions = engine.get_reactions(top_n=20)
    serious_reactions = engine.get_serious_reactions(top_n=20)
    outcomes = engine.get_outcomes()
    trends = engine.get_time_trends()
    alerts = engine.get_alert_cases()
    history = engine.get_history_of_actions()
    expectedness = engine.get_expectedness()
    case_index = engine.get_case_index(limit=10) # limit to 10 for demonstration

    # 2. Collect Evidence
    evidence_list = collect_evidence(
        period=period, volume=volume, age=age, sex=sex, country=country,
        reactions=reactions, serious_reactions=serious_reactions,
        outcomes=outcomes, trends=trends, alerts=alerts, history=history,
        expectedness=expectedness, case_index=case_index
    )

    all_evidence_ids = {e.evidence_id for e in evidence_list}

    # 3. Context Builder
    builder = ContextBuilder(PADER_CONFIG, evidence_list)
    errors = builder.validate()
    assert len(errors) == 0, f"Validation errors: {errors}"

    packets = builder.build_all_packets()

    target_sections = [
        "Narrative Summary",
        "Summary Analysis of Cases",
        "Reaction Analysis",
        "15-Day Alert Reports",
        "Trends and Important Observations",
        "History of Actions",
        "Case Listing"
    ]

    print("================ PHASE 3 DEMONSTRATION ================\n")

    for p in packets:
        if p.section_name in target_sections:
            sec_eids = [e.evidence_id for e in p.evidence]
            excluded_eids = list(all_evidence_ids - set(sec_eids))
            
            print(f"--- Section: {p.section_name} ---")
            print(f"Purpose: {p.section_purpose}")
            print(f"Included Evidence IDs ({len(sec_eids)}): {sec_eids}")
            print(f"Excluded Evidence IDs ({len(excluded_eids)} count): {len(excluded_eids)} items excluded")
            print("Key Evidence Items:")
            for e in p.evidence:
                val_repr = e.value
                if isinstance(val_repr, list) and len(val_repr) > 2:
                    val_repr = f"List of {len(val_repr)} items (first item: {val_repr[0]})"
                elif isinstance(val_repr, dict) and len(val_repr) > 5:
                    sample = {k: val_repr[k] for k in list(val_repr.keys())[:3]}
                    val_repr = f"Dict of {len(val_repr)} entries (sample: {sample}...)"
                print(f"  * [{e.evidence_id}] ({e.evidence_type.value}) {e.metric}: {val_repr}")
            print(f"Grounding Instructions Count: {len(p.grounding_instructions)}")
            print()

    # Dump full JSON examples for requested sections
    print("\n================ JSON CONTEXT PACKET EXAMPLES ================\n")
    for name in ["Narrative Summary", "Reaction Analysis", "15-Day Alert Reports"]:
        pkt = [p for p in packets if p.section_name == name][0]
        print(f"*** FULL CONTEXT PACKET: {name} ***")
        print(json.dumps(pkt.model_dump(), indent=2))
        print("\n" + "="*50 + "\n")

if __name__ == "__main__":
    run_demo()
