import os
import csv
import pandas as pd
from typing import Tuple, Dict, Any, List
from pathlib import Path

# Comprehensive mapping of common ICSR column aliases to standardized internal names
COLUMN_ALIASES = {
    "safetyreportid": [
        "safetyreportid", "safety_report_id", "reportid", "report_id",
        "caseid", "case_id", "casenumber", "case_number", "icsr_id", "icsrid",
        "id", "patient_id", "patientid", "record_id", "safety_report_number"
    ],
    "serious": [
        "serious", "serious_bool", "seriousness", "is_serious", "serious_case",
        "severity", "is_severe", "serious_criteria"
    ],
    "fulfillexpeditecriteria": [
        "fulfillexpeditecriteria", "expedited", "expedited_bool", "is_expedited",
        "alert", "15_day_alert", "15day_alert", "expedited_report", "expedite",
        "alert_case"
    ],
    "occurcountry": [
        "occurcountry", "occur_country", "country", "primarysource_reportercountry",
        "reportercountry", "reporter_country", "location", "patient_country",
        "reporting_country"
    ],
    "patient_patientonsetage": [
        "patient_patientonsetage", "patientonsetage", "patient_age", "age",
        "onset_age", "patient_onset_age", "age_in_years"
    ],
    "patient_patientsex": [
        "patient_patientsex", "patientsex", "patient_gender", "sex", "gender",
        "patient_sex"
    ],
    "patient_reaction_reactionmeddrapt": [
        "patient_reaction_reactionmeddrapt", "reactionmeddrapt", "meddra_pt",
        "meddrapt", "reaction_pt", "reaction", "adverse_event", "adverse_reaction",
        "preferred_term", "event_pt", "pt_name", "pt", "event", "ae",
        "reaction_name", "symptom", "adverse_effect"
    ],
    "patient_reaction_reactionoutcome": [
        "patient_reaction_reactionoutcome", "reactionoutcome", "outcome",
        "patient_outcome", "event_outcome", "reaction_outcome", "event_result",
        "fatal", "death"
    ],
    "receivedate": [
        "receivedate", "receive_date", "receipt_date", "receiptdate",
        "event_date", "report_date", "date", "adverse_event_date", "onset_date",
        "date_received"
    ],
    "medicinalproduct": [
        "patient_drug_medicinalproduct", "medicinalproduct", "medicinal_product",
        "drugname", "drug_name", "product_name", "productname", "product", "drug",
        "active_substance", "active_ingredient", "suspect_drug", "substance"
    ]
}


def load_and_normalize_data(file_path: str) -> pd.DataFrame:
    """Loads the ICSR dataset, handling both CSV and Excel with intelligent column mapping and robust validation."""
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Dataset file not found: {file_path}")

    # Check file size
    if os.path.getsize(file_path) == 0:
        raise ValueError("The uploaded dataset is empty (0 bytes). Please provide a dataset with at least one record.")

    is_csv = file_path.lower().endswith(".csv")

    df = None
    if is_csv:
        # Multi-encoding attempt for CSV datasets
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        last_error = None

        for enc in encodings:
            try:
                # Try standard comma first
                df = pd.read_csv(file_path, encoding=enc, low_memory=False)
                # If parsed as single column with semicolons or tabs, sniff delimiter
                if df is not None and len(df.columns) == 1 and len(df) > 0:
                    first_col = str(df.columns[0])
                    if ";" in first_col or "\t" in first_col:
                        df = pd.read_csv(file_path, encoding=enc, sep=None, engine="python")
                break
            except pd.errors.EmptyDataError:
                raise ValueError("The uploaded dataset contains no data rows (empty dataset).")
            except (pd.errors.ParserError, csv.Error) as pe:
                last_error = pe
                continue
            except UnicodeDecodeError as ue:
                last_error = ue
                continue
            except Exception as ex:
                last_error = ex
                continue

        if df is None:
            raise ValueError(f"Malformed CSV file: unable to parse data structure ({last_error}). Please check delimiters, quotes, and encoding.")
    else:
        try:
            df = pd.read_excel(file_path)
        except Exception as e:
            raise ValueError(f"Malformed Excel file: unable to parse spreadsheet ({str(e)}).")

    if df is None or df.empty or len(df) == 0:
        raise ValueError("The uploaded dataset contains no data rows (empty dataset). Please provide an ICSR dataset with at least one record.")

    # Initial column cleaning
    df.columns = df.columns.astype(str).str.lower().str.strip()

    # Verify that the dataset contains recognizable ICSR safety columns
    # At least one column must match known ICSR safety concepts
    raw_cols = set(df.columns)
    all_known_aliases = {alias for aliases in COLUMN_ALIASES.values() for alias in aliases}
    matched_aliases = raw_cols.intersection(all_known_aliases)

    if not matched_aliases:
        # Check partial token match (e.g. contains 'reaction', 'drug', 'report', 'case', 'patient', 'adverse', 'event')
        safety_keywords = {"case", "report", "patient", "reaction", "adverse", "event", "drug", "product", "outcome", "serious"}
        has_safety_concept = any(
            any(kw in col for kw in safety_keywords)
            for col in raw_cols
        )
        if not has_safety_concept:
            raise ValueError(
                "Missing required ICSR fields. The dataset must contain safety report columns such as case ID ('safety_report_id' / 'case_id'), adverse event/reaction ('adverse_event' / 'reactionmeddrapt'), or drug product ('medicinal_product' / 'drug_name')."
            )

    # Map aliases to standard internal column names if not already present
    rename_map = {}
    for standard_col, aliases in COLUMN_ALIASES.items():
        if standard_col not in df.columns:
            for alias in aliases:
                if alias in df.columns:
                    rename_map[alias] = standard_col
                    break
    if rename_map:
        df = df.rename(columns=rename_map)

    # Fallback synthesize safetyreportid if completely absent
    if "safetyreportid" not in df.columns:
        df["safetyreportid"] = [f"ICSR-{i+1:05d}" for i in range(len(df))]

    # Fallback synthesize receivedate if completely absent
    if "receivedate" not in df.columns:
        df["receivedate"] = "20240101"

    # Fallback reaction term if absent
    if "patient_reaction_reactionmeddrapt" not in df.columns:
        df["patient_reaction_reactionmeddrapt"] = "Adverse event unclassified"

    # Normalize seriousness flags to boolean (1/yes/true -> True, else False)
    if "serious" in df.columns:
        df["serious_bool"] = df["serious"].astype(str).str.lower().isin(["1", "yes", "true", "serious", "y"])
    else:
        df["serious_bool"] = False

    # Normalize expedited flag
    if "fulfillexpeditecriteria" in df.columns:
        df["expedited_bool"] = df["fulfillexpeditecriteria"].astype(str).str.lower().isin(["1", "yes", "true", "y", "expedited"])
    else:
        df["expedited_bool"] = False

    # Normalize country
    if "occurcountry" in df.columns:
        df["standard_country"] = df["occurcountry"].fillna("UNKNOWN").astype(str).str.upper()
    elif "primarysource_reportercountry" in df.columns:
        df["standard_country"] = df["primarysource_reportercountry"].fillna("UNKNOWN").astype(str).str.upper()
    else:
        df["standard_country"] = "UNKNOWN"

    # Normalize age
    if "patient_patientonsetage" in df.columns:
        df["numeric_age"] = pd.to_numeric(df["patient_patientonsetage"], errors="coerce")
    else:
        df["numeric_age"] = None

    # Normalize sex if present
    if "patient_patientsex" in df.columns:
        df["patient_patientsex"] = df["patient_patientsex"].astype(str).replace({"1": "Male", "2": "Female", "nan": "Unknown"})
    else:
        df["patient_patientsex"] = "Unknown"

    return df


def validate_data(df: pd.DataFrame) -> dict:
    """Validates the dataframe and returns a summary of data quality."""
    issues = {}

    # Missing values
    missing = df.isnull().sum()
    issues["missing_counts"] = missing[missing > 0].to_dict()

    # Duplicates
    issues["duplicate_rows"] = int(df.duplicated().sum())

    # Ensure required columns
    required_cols = ["safetyreportid", "receivedate", "patient_reaction_reactionmeddrapt"]
    missing_req = [c for c in required_cols if c not in df.columns]
    issues["missing_required_columns"] = missing_req

    return issues
