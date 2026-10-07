"""
Report Assembler ?" combines deterministic tables, LLM narratives, evidence metadata, and review status into Markdown.
"""

from typing import List, Dict, Any, Optional
from .models import AnalysisResult
from .generation_models import GeneratedSection, ValidationResult
from .report_models import (
    PADERReport, ReportMetadata, SectionOutput, SectionType, SectionStatus, ReportStatus
)


class ReportAssembler:
    """
    Assembles structured report models and formats them into a regulatory Markdown document.
    """

    def assemble_report(
        self,
        metadata: ReportMetadata,
        analyses: Dict[str, AnalysisResult],
        generated_sections: Dict[str, GeneratedSection],
        validations: Dict[str, ValidationResult]
    ) -> PADERReport:
        sections: List[SectionOutput] = []

        # 1. Reporting Period (Deterministic Required Section)
        period_res = analyses.get("period_001")
        sections.append(SectionOutput(
            section_name="Reporting Period",
            section_type=SectionType.DETERMINISTIC,
            is_required_by_assignment=True,
            structured_tables={"period": period_res.value if period_res else {}},
            evidence_ids=["EV_PERIOD_START", "EV_PERIOD_END"],
            validation_status=SectionStatus.PASS
        ))

        # 2. Narrative Summary (LLM Generated Required Section)
        narrative_gen = generated_sections.get("Narrative Summary")
        narrative_val = validations.get("Narrative Summary")
        sections.append(SectionOutput(
            section_name="Narrative Summary",
            section_type=SectionType.LLM_GENERATED,
            is_required_by_assignment=True,
            narrative=narrative_gen.narrative if narrative_gen else "Generation failed.",
            evidence_ids=narrative_gen.evidence_ids if narrative_gen else [],
            limitations=narrative_gen.limitations if narrative_gen else [],
            validation_status=SectionStatus.PASS if (narrative_val and narrative_val.is_grounded) else SectionStatus.REVIEW_REQUIRED,
            validation_warnings=narrative_val.warnings if narrative_val else [],
            generation_metadata=narrative_gen.generation_metadata if narrative_gen else None
        ))

        # 3. Summary Analysis of Cases (LLM Narrative + Deterministic Tables Required Section)
        case_gen = generated_sections.get("Summary Analysis of Cases")
        case_val = validations.get("Summary Analysis of Cases")
        sections.append(SectionOutput(
            section_name="Summary Analysis of Cases",
            section_type=SectionType.LLM_GENERATED,
            is_required_by_assignment=True,
            narrative=case_gen.narrative if case_gen else None,
            structured_tables={
                "volume": analyses["vol_001"].value if "vol_001" in analyses else {},
                "age": analyses["demo_age_001"].value if "demo_age_001" in analyses else {},
                "sex": analyses["demo_sex_001"].value if "demo_sex_001" in analyses else {},
                "country": analyses["demo_country_001"].value if "demo_country_001" in analyses else {},
            },
            evidence_ids=case_gen.evidence_ids if case_gen else [],
            limitations=case_gen.limitations if case_gen else [],
            validation_status=SectionStatus.PASS if (case_val and case_val.is_grounded) else SectionStatus.REVIEW_REQUIRED,
            validation_warnings=case_val.warnings if case_val else []
        ))

        # 4. Reaction / Adverse Event Analysis (LLM Narrative + Deterministic Tables Required Section)
        rx_gen = generated_sections.get("Reaction Analysis")
        rx_val = validations.get("Reaction Analysis")
        sections.append(SectionOutput(
            section_name="Reaction Analysis",
            section_type=SectionType.LLM_GENERATED,
            is_required_by_assignment=True,
            narrative=rx_gen.narrative if rx_gen else None,
            structured_tables={
                "top_reactions": analyses["rx_001"].value if "rx_001" in analyses else {},
                "top_serious_reactions": analyses["rx_002"].value if "rx_002" in analyses else {},
            },
            evidence_ids=rx_gen.evidence_ids if rx_gen else [],
            limitations=rx_gen.limitations if rx_gen else [],
            validation_status=SectionStatus.PASS if (rx_val and rx_val.is_grounded) else SectionStatus.REVIEW_REQUIRED,
            validation_warnings=rx_val.warnings if rx_val else []
        ))

        # 5. Serious Cases / 15-Day Alerts (LLM Narrative + Deterministic Table Required Section)
        alert_gen = generated_sections.get("15-Day Alert Reports")
        alert_val = validations.get("15-Day Alert Reports")
        sections.append(SectionOutput(
            section_name="15-Day Alert Reports",
            section_type=SectionType.LLM_GENERATED,
            is_required_by_assignment=True,
            narrative=alert_gen.narrative if alert_gen else None,
            structured_tables={"alerts": analyses["alert_001"].value if "alert_001" in analyses else {}},
            evidence_ids=alert_gen.evidence_ids if alert_gen else [],
            limitations=alert_gen.limitations if alert_gen else [],
            validation_status=SectionStatus.PASS if (alert_val and alert_val.is_grounded) else SectionStatus.REVIEW_REQUIRED,
            validation_warnings=alert_val.warnings if alert_val else []
        ))

        # 6. Trends and Important Observations (LLM Narrative + Deterministic Monthly Table Required Section)
        trend_gen = generated_sections.get("Trends and Important Observations")
        trend_val = validations.get("Trends and Important Observations")
        sections.append(SectionOutput(
            section_name="Trends and Important Observations",
            section_type=SectionType.LLM_GENERATED,
            is_required_by_assignment=True,
            narrative=trend_gen.narrative if trend_gen else None,
            structured_tables={"trends": analyses["trend_001"].value if "trend_001" in analyses else {}},
            evidence_ids=trend_gen.evidence_ids if trend_gen else [],
            limitations=trend_gen.limitations if trend_gen else [],
            validation_status=SectionStatus.PASS if (trend_val and trend_val.is_grounded) else SectionStatus.REVIEW_REQUIRED,
            validation_warnings=trend_val.warnings if trend_val else []
        ))

        # 7. History of Actions (Deterministic Required Section)
        hist_res = analyses.get("hist_001")
        sections.append(SectionOutput(
            section_name="History of Actions",
            section_type=SectionType.DETERMINISTIC,
            is_required_by_assignment=True,
            narrative=str(hist_res.value) if hist_res else "No history-of-actions data was provided.",
            evidence_ids=["EV_HISTORY"],
            validation_status=SectionStatus.PASS
        ))

        # 8. Expectedness (Additional Limitation Statement - Not an independent required section)
        exp_res = analyses.get("exp_001")
        sections.append(SectionOutput(
            section_name="Expectedness",
            section_type=SectionType.LIMITATION_STATEMENT,
            is_required_by_assignment=False,
            narrative=str(exp_res.value) if exp_res else "OUT OF SCOPE / NOT DETERMINABLE FROM SUPPLIED DATA",
            evidence_ids=["EV_EXPECTEDNESS"],
            validation_status=SectionStatus.PASS
        ))

        # 9. Case Index / Listing (Deterministic Required Section)
        idx_res = analyses.get("idx_001")
        sections.append(SectionOutput(
            section_name="Case Listing",
            section_type=SectionType.DETERMINISTIC,
            is_required_by_assignment=True,
            structured_tables={"case_listing": idx_res.value if idx_res else []},
            evidence_ids=["EV_CASE_INDEX"],
            validation_status=SectionStatus.PASS
        ))

        return PADERReport(
            metadata=metadata,
            sections=sections,
            status=ReportStatus.DRAFT_PENDING_REVIEW
        )

    def to_markdown(self, report: PADERReport, max_case_index_rows: int = 50) -> str:
        """Render the complete PADERReport into formatted Markdown."""
        m = report.metadata
        md = []

        # Document Header
        md.append(f"# Periodic Adverse Drug Experience Report (PADER)")
        md.append(f"**Product:** {m.product_name} | **Application No:** {m.application_number} | **Sponsor:** {m.sponsor_name}")
        md.append(f"**Reporting Period:** {m.reporting_period_start} to {m.reporting_period_end}  ")
        md.append(f"**Report Generated (UTC):** {m.generated_at_utc} | **Status:** `{report.status.value}`")
        md.append("\n---\n")

        # Table of Contents
        md.append("## Table of Contents")
        req_num = 1
        for sec in report.sections:
            anchor = sec.section_name.lower().replace(" ", "-").replace("/", "").replace(",", "")
            if sec.is_required_by_assignment:
                md.append(f"{req_num}. [{sec.section_name}](#{anchor})")
                req_num += 1
            else:
                md.append(f"* [{sec.section_name} (Limitation Notice)](#{anchor})")
        md.append("\n---\n")

        # Render each section
        req_idx = 1
        for sec in report.sections:
            if sec.is_required_by_assignment:
                md.append(f"## {req_idx}. {sec.section_name}\n")
                req_idx += 1
            else:
                md.append(f"## Appendix: {sec.section_name} (Limitation Notice)\n")

            # Review / Validation Flag Badge
            if sec.validation_status != SectionStatus.PASS:
                md.append(f"> **Validation Alert:** `{sec.validation_status.value}` - Review Required")
                for w in sec.validation_warnings:
                    md.append(f"> - {w}")
                md.append("\n")

            # Narrative Text
            if sec.narrative:
                md.append(f"{sec.narrative}\n")

            # Structured Tables per Section
            st = sec.structured_tables or {}

            if sec.section_name == "Reporting Period" and "period" in st:
                p = st["period"]
                md.append(f"| Attribute | Value |")
                md.append(f"|---|---|")
                md.append(f"| **Start Date** | {p.get('start_date')} |")
                md.append(f"| **End Date** | {p.get('end_date')} |")
                md.append(f"| **Report Type** | PADER (Annual) |")
                md.append("\n")

            elif sec.section_name == "Summary Analysis of Cases":
                # Case Volume
                vol = st.get("volume", {})
                if vol:
                    md.append("### Case Volume Summary\n")
                    md.append("| Metric | Count | Percentage |")
                    md.append("|---|---|---|")
                    md.append(f"| **Total Cases** | {vol.get('total_cases', 0):,} | 100.0% |")
                    md.append(f"| **Serious Cases** | {vol.get('serious_cases', 0):,} | {vol.get('serious_pct', 0)}% |")
                    md.append(f"| **Non-Serious Cases** | {vol.get('non_serious_cases', 0):,} | {vol.get('non_serious_pct', 0)}% |\n")

                # Age Distribution
                age = st.get("age", {})
                if age:
                    md.append("### Patient Age Breakdown\n")
                    md.append("| Age Group | Count | Percentage |")
                    md.append("|---|---|---|")
                    counts = age.get("counts", {})
                    pcts = age.get("percentages", {})
                    for grp, cnt in counts.items():
                        md.append(f"| {grp} | {cnt:,} | {pcts.get(grp, 0)}% |")
                    md.append("\n")

                # Sex Distribution
                sex = st.get("sex", {})
                if sex:
                    md.append("### Patient Sex Breakdown\n")
                    md.append("| Sex | Count | Percentage |")
                    md.append("|---|---|---|")
                    counts = sex.get("counts", {})
                    pcts = sex.get("percentages", {})
                    for s_val, cnt in counts.items():
                        md.append(f"| {s_val} | {cnt:,} | {pcts.get(s_val, 0)}% |")
                    md.append("\n")

                # Top Countries
                country = st.get("country", {})
                if country:
                    md.append("### Geographic Distribution (Top Countries)\n")
                    md.append("| Country / Region | Case Count | Percentage |")
                    md.append("|---|---|---|")
                    counts = country.get("counts", {})
                    pcts = country.get("percentages", {})
                    for c_val, cnt in list(counts.items())[:10]:
                        md.append(f"| {c_val} | {cnt:,} | {pcts.get(c_val, 0)}% |")
                    md.append("\n")

            elif sec.section_name == "Reaction Analysis":
                top_rx = st.get("top_reactions", {})
                top_srx = st.get("top_serious_reactions", {})
                if top_rx:
                    md.append("### Top Reported Adverse Reactions (MedDRA PT)\n")
                    md.append("| Rank | Preferred Term (PT) | Total Reports | Serious Reports |")
                    md.append("|---|---|---|---|")
                    for r_idx, (pt, cnt) in enumerate(list(top_rx.items())[:15], 1):
                        s_cnt = top_srx.get(pt, 0)
                        md.append(f"| {r_idx} | {pt} | {cnt} | {s_cnt} |")
                    md.append("\n")

            elif sec.section_name == "15-Day Alert Reports":
                alerts = st.get("alerts", {})
                if alerts:
                    md.append("### Expedited Alert Summary\n")
                    md.append("| Reporting Category | Case Count |")
                    md.append("|---|---|")
                    md.append(f"| **15-Day Expedited Alerts (Total)** | {alerts.get('total_alerts', 0):,} |")
                    md.append(f"| **15-Day Expedited Alerts (Serious)** | {alerts.get('serious_alerts', 0):,} |")
                    md.append("\n")

            elif sec.section_name == "Trends and Important Observations":
                trends = st.get("trends", {})
                if trends:
                    md.append("### Monthly Reporting Trends\n")
                    md.append("| Reporting Month | Received Cases |")
                    md.append("|---|---|")
                    for m_val, cnt in trends.items():
                        md.append(f"| {m_val} | {cnt:,} |")
                    md.append("\n")

            elif sec.section_name == "Case Listing":
                listing = st.get("case_listing", [])
                if listing:
                    display_count = min(len(listing), max_case_index_rows)
                    md.append(f"*(Displaying first {display_count} of {len(listing):,} cases for summary listing)*\n")
                    md.append("| Safety Report ID | Reported Reactions | Serious | Received Date | Country |")
                    md.append("|---|---|---|---|---|")
                    for row in listing[:display_count]:
                        md.append(f"| `{row.get('safetyreportid')}` | {row.get('reactions')} | {row.get('serious')} | {row.get('date')} | {row.get('country')} |")
                    md.append("\n")

            # Limitations & Evidence Traceability
            if sec.limitations:
                md.append("**Acknowledged Limitations:**")
                for lim in sec.limitations:
                    md.append(f"- *{lim}*")
                md.append("")

            if sec.evidence_ids:
                eids_str = ", ".join([f"`{e}`" for e in sec.evidence_ids])
                md.append(f"<small>**Traceable Evidence IDs:** {eids_str}</small>\n")

            md.append("---\n")

        # Appendix: Evaluation & Review Sign-off
        if report.review_record:
            rec = report.review_record
            sim_notice = " *(Simulated Automated Test Fixture)*" if rec.is_simulated else ""
            md.append("## Human Review & Medical Verification Sign-Off")
            md.append(f"- **Reviewer / Medical Officer:** {rec.reviewer_name}{sim_notice}")
            if rec.doctor_license:
                md.append(f"- **Medical Registration / License:** `{rec.doctor_license}`")
            if rec.specialty:
                md.append(f"- **Clinical Specialty:** {rec.specialty}")
            if rec.affiliation:
                md.append(f"- **Affiliation / Institution:** {rec.affiliation}")
            md.append(f"- **Decision:** `{rec.reviewer_decision.value}`")
            md.append(f"- **Verification Timestamp (UTC):** {rec.reviewed_at_utc}")
            if rec.verification_id:
                md.append(f"- **Audit Verification ID:** `{rec.verification_id}`")
            if rec.signature_hash:
                md.append(f"- **Cryptographic Verification Signature:** `{rec.signature_hash}`")
            if rec.reviewer_notes:
                md.append(f"- **Clinical Review Notes:** {rec.reviewer_notes}")
            md.append("\n---\n")

        return "\n".join(md)
