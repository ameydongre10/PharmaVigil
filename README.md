# Deterministic Analysis Layer

## Overview
This layer provides the factual, math-based foundation for the GenAR AI Engineering Challenge. The LLM does **not** calculate any statistics. Instead, `analysis_engine.py` aggregates data and provides structured outputs via the `models.AnalysisResult` schema.

## Data Flow
1. **Raw Data:** ICSR line-listing (Excel or CSV).
2. **Data Loader (`data_loader.py`):** Loads the dataset, normalizes columns to lowercase, standardizes boolean flags (e.g., `1`/`yes` -> `True`), buckets countries, and outputs a normalized Pandas DataFrame.
3. **Analysis Engine (`analysis_engine.py`):** Takes the normalized DataFrame and produces `AnalysisResult` objects.

## Case vs. Row vs. Reaction
*   **Row:** A single line in the source dataset.
*   **Case:** Uniquely identified by `safetyreportid`. 
*   **Reaction:** Specific adverse event associated with a case (`patient_reaction_reactionmeddrapt`). 
*   **Implementation:** The engine maintains `self.df` (row-level, used for reaction frequency) and builds `self.cases_df` (case-level deduplicated by `safetyreportid`, used for volume, demographics, and outcomes).

## Important Transformations
*   **Seriousness:** Any indication of "1", "yes", or "serious" in the `serious` column sets `serious_bool` to `True`.
*   **Expedited:** Handled identically to seriousness.
*   **Country Fallback:** Maps `occurcountry` first, falling back to `primarysource_reportercountry`.
*   **Age Bucketing:** Converts numeric ages into `<18`, `18-64`, `65+`, and `Unknown`.

## Known Limitations
*   No "History of Actions" or product label data exists, so these modules return hardcoded "Out of scope / No data provided" strings.
*   Deduplication of reactions assumes the combination of `safetyreportid` and `patient_reaction_reactionmeddrapt` uniquely identifies a reaction occurrence per patient.
