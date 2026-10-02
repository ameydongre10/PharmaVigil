"""
Report type configurations.

Each report type defines its sections, the Phase 2 analysis_ids each
section depends on, and any extra grounding instructions. Adding a new
report type (e.g. PSUR) requires only a new config object here — no
changes to the evidence collector or context builder.
"""

from .evidence_models import ReportTypeConfig, ReportSectionConfig


PADER_CONFIG = ReportTypeConfig(
    report_type="PADER",
    display_name="Periodic Adverse Drug Experience Report",
    sections=[
        ReportSectionConfig(
            section_name="Reporting Period",
            section_purpose="State the date range covered by this report.",
            required_analysis_ids=["period_001"],
        ),
        ReportSectionConfig(
            section_name="Narrative Summary",
            section_purpose=(
                "Provide a high-level executive summary of the reporting period, "
                "including total cases, seriousness breakdown, and the most "
                "frequently reported reactions."
            ),
            required_analysis_ids=["period_001", "vol_001", "rx_001"],
            optional_analysis_ids=["demo_age_001", "demo_sex_001"],
            extra_grounding_instructions=[
                "Keep the summary concise (1-2 paragraphs).",
                "Do NOT list every reaction; highlight only the top findings.",
            ],
        ),
        ReportSectionConfig(
            section_name="Summary Analysis of Cases",
            section_purpose=(
                "Present a detailed demographic and case-characteristic breakdown "
                "of the cases received during the reporting period."
            ),
            required_analysis_ids=[
                "vol_001", "demo_age_001", "demo_sex_001",
                "demo_country_001", "out_001",
            ],
            extra_grounding_instructions=[
                "Present counts and percentages.",
                "Acknowledge unknown/missing demographics explicitly.",
            ],
        ),
        ReportSectionConfig(
            section_name="Reaction Analysis",
            section_purpose=(
                "Analyse the most frequently reported adverse reactions, "
                "including serious reactions."
            ),
            required_analysis_ids=["rx_001", "rx_002"],
            extra_grounding_instructions=[
                "Do NOT invent System Organ Class (SOC) groupings; "
                "the dataset does not contain SOC data.",
                "Present reactions by MedDRA Preferred Term only.",
            ],
        ),
        ReportSectionConfig(
            section_name="15-Day Alert Reports",
            section_purpose=(
                "Summarise expedited / 15-day alert cases submitted during "
                "the reporting period."
            ),
            required_analysis_ids=["alert_001", "vol_001"],
            extra_grounding_instructions=[
                "Base alert status solely on the fulfillexpeditecriteria field.",
            ],
        ),
        ReportSectionConfig(
            section_name="Trends and Important Observations",
            section_purpose=(
                "Describe temporal trends in case volume and reaction reporting."
            ),
            required_analysis_ids=["trend_001"],
            optional_analysis_ids=["vol_001"],
            extra_grounding_instructions=[
                "Report only observed numerical trends.",
                "Do NOT automatically label any trend as a safety signal.",
            ],
        ),
        ReportSectionConfig(
            section_name="History of Actions",
            section_purpose=(
                "Document any regulatory or safety actions taken during "
                "the reporting period."
            ),
            required_analysis_ids=["hist_001"],
            extra_grounding_instructions=[
                "If no data is provided, state that explicitly.",
            ],
        ),
        ReportSectionConfig(
            section_name="Expectedness",
            section_purpose=(
                "Assess whether reported reactions are expected based on "
                "the approved product label."
            ),
            required_analysis_ids=["exp_001"],
            extra_grounding_instructions=[
                "State that expectedness cannot be determined without "
                "a product label / CCDS.",
            ],
        ),
        ReportSectionConfig(
            section_name="Case Listing",
            section_purpose=(
                "Provide a structured tabular listing of individual cases "
                "for traceability."
            ),
            required_analysis_ids=["idx_001"],
            extra_grounding_instructions=[
                "Format as a table.",
                "Do NOT add narrative interpretation to the case listing.",
            ],
        ),
    ],
)

# Registry of all available report types
REPORT_CONFIGS: dict[str, ReportTypeConfig] = {
    "PADER": PADER_CONFIG,
}
