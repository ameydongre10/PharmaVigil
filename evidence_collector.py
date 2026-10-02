"""
Evidence Collector — transforms Phase 2 AnalysisResult objects into
traceable EvidenceItem objects.

Key principle: this module does NOT recalculate any statistics.
It consumes the authoritative values from AnalysisEngine and wraps
them in the evidence schema so they can be selected per-section.
"""

from typing import List, Optional
from .models import AnalysisResult
from .evidence_models import EvidenceItem, EvidenceType, AggregationLevel


def _ev(evidence_id: str, analysis: AnalysisResult, section: str,
        metric: str, value, *, evidence_type=EvidenceType.FACT,
        aggregation=AggregationLevel.CASE, unit=None, notes=None):
    """Shorthand factory for building an EvidenceItem from an AnalysisResult."""
    return EvidenceItem(
        evidence_id=evidence_id,
        analysis_id=analysis.analysis_id,
        section=section,
        evidence_type=evidence_type,
        metric=metric,
        value=value,
        unit=unit,
        aggregation_level=aggregation,
        source_fields=analysis.source_fields,
        methodology=analysis.methodology,
        notes=notes,
    )


def collect_evidence(
    period: AnalysisResult,
    volume: AnalysisResult,
    age: AnalysisResult,
    sex: AnalysisResult,
    country: AnalysisResult,
    reactions: AnalysisResult,
    serious_reactions: AnalysisResult,
    outcomes: AnalysisResult,
    trends: AnalysisResult,
    alerts: AnalysisResult,
    history: AnalysisResult,
    expectedness: AnalysisResult,
    case_index: AnalysisResult,
) -> List[EvidenceItem]:
    """
    Convert all Phase 2 AnalysisResults into a flat list of EvidenceItems.

    Every value used here comes directly from a Phase 2 AnalysisResult.
    No independent calculations are performed.
    """
    evidence: List[EvidenceItem] = []

    # --- Reporting Period ---
    evidence.append(_ev(
        "EV_PERIOD_START", period, "Reporting Period",
        "Reporting period start date", period.value["start_date"],
    ))
    evidence.append(_ev(
        "EV_PERIOD_END", period, "Reporting Period",
        "Reporting period end date", period.value["end_date"],
    ))

    # --- Case Volume ---
    v = volume.value
    evidence.append(_ev("EV_CASE_TOTAL", volume, "Narrative Summary",
                        "Total unique cases", v["total_cases"]))
    evidence.append(_ev("EV_CASE_SERIOUS", volume, "Narrative Summary",
                        "Serious cases", v["serious_cases"]))
    evidence.append(_ev("EV_CASE_NON_SERIOUS", volume, "Narrative Summary",
                        "Non-serious cases", v["non_serious_cases"]))
    evidence.append(_ev("EV_CASE_SERIOUS_PCT", volume, "Narrative Summary",
                        "Serious case percentage", v["serious_pct"], unit="%"))
    evidence.append(_ev("EV_CASE_NON_SERIOUS_PCT", volume, "Narrative Summary",
                        "Non-serious case percentage", v["non_serious_pct"], unit="%"))

    # --- Demographics: Age ---
    evidence.append(_ev(
        "EV_AGE_DISTRIBUTION", age, "Summary Analysis of Cases",
        "Age group distribution", age.value,
    ))

    # --- Demographics: Sex ---
    evidence.append(_ev(
        "EV_SEX_DISTRIBUTION", sex, "Summary Analysis of Cases",
        "Sex distribution", sex.value,
    ))

    # --- Demographics: Country ---
    evidence.append(_ev(
        "EV_COUNTRY_DISTRIBUTION", country, "Summary Analysis of Cases",
        "Country distribution", country.value,
    ))

    # --- Outcomes ---
    evidence.append(_ev(
        "EV_OUTCOMES", outcomes, "Summary Analysis of Cases",
        "Reaction outcome distribution", outcomes.value,
        aggregation=AggregationLevel.REACTION,
        notes="Outcome field contains comma-separated multi-values per row; "
              "counts reflect raw row-level values.",
    ))

    # --- Reactions ---
    evidence.append(_ev(
        "EV_TOP_REACTIONS", reactions, "Reaction Analysis",
        "Most frequently reported reactions (MedDRA PT)", reactions.value,
        evidence_type=EvidenceType.FACT,
        aggregation=AggregationLevel.REACTION,
    ))
    # Observation: identify the single most common reaction
    top_rx_name = next(iter(reactions.value)) if reactions.value else None
    top_rx_count = reactions.value.get(top_rx_name, 0) if top_rx_name else 0
    if top_rx_name:
        evidence.append(_ev(
            "EV_MOST_COMMON_REACTION", reactions, "Narrative Summary",
            "Most frequently reported reaction",
            {"reaction": top_rx_name, "count": top_rx_count},
            evidence_type=EvidenceType.OBSERVATION,
            aggregation=AggregationLevel.REACTION,
        ))

    # --- Serious Reactions ---
    evidence.append(_ev(
        "EV_TOP_SERIOUS_REACTIONS", serious_reactions, "Reaction Analysis",
        "Most frequently reported serious reactions (MedDRA PT)",
        serious_reactions.value,
        aggregation=AggregationLevel.REACTION,
    ))

    # --- Trends ---
    evidence.append(_ev(
        "EV_MONTHLY_TRENDS", trends, "Trends and Important Observations",
        "Monthly case volume", trends.value,
    ))

    # --- Alerts ---
    a = alerts.value
    evidence.append(EvidenceItem(
        evidence_id="EV_ALERT_TOTAL",
        analysis_id=alerts.analysis_id,
        section="15-Day Alert Reports",
        evidence_type=EvidenceType.FACT,
        metric="Total expedited / 15-day alert cases",
        value=a["total_alerts"],
        unit=None,
        aggregation_level=AggregationLevel.CASE,
        source_fields=["fulfillexpeditecriteria"],
        methodology="Count of cases where fulfillexpeditecriteria is true",
        notes=None,
    ))
    evidence.append(EvidenceItem(
        evidence_id="EV_ALERT_SERIOUS",
        analysis_id=alerts.analysis_id,
        section="15-Day Alert Reports",
        evidence_type=EvidenceType.FACT,
        metric="Serious alert cases",
        value=a["serious_alerts"],
        unit=None,
        aggregation_level=AggregationLevel.CASE,
        source_fields=["fulfillexpeditecriteria", "serious"],
        methodology="Count of cases where fulfillexpeditecriteria is true AND serious is true",
        notes=None,
    ))

    # --- History of Actions ---
    evidence.append(_ev(
        "EV_HISTORY", history, "History of Actions",
        "History of actions status", history.value,
        evidence_type=EvidenceType.NOT_AVAILABLE,
    ))

    # --- Expectedness ---
    evidence.append(_ev(
        "EV_EXPECTEDNESS", expectedness, "Expectedness",
        "Expectedness determination status", expectedness.value,
        evidence_type=EvidenceType.NOT_AVAILABLE,
    ))

    # --- Case Index ---
    evidence.append(_ev(
        "EV_CASE_INDEX", case_index, "Case Listing",
        "Structured case listing", case_index.value,
        notes="Limited to first N cases for context size management.",
    ))

    return evidence
