import pandas as pd
from typing import Tuple, Dict, Any
from pathlib import Path

# Mapping of common column aliases to standardized internal names
COLUMN_ALIASES = {
    "safetyreportid": [
        "safetyreportid", "safety_report_id", "reportid", "report_id",
        "caseid", "case_id", "casenumber", "case_number", "icsr_id", "id"
    ],
    "serious": [
        "serious", "serious_bool", "seriousness", "is_serious", "serious_case"
    ],
    "fulfillexpeditecriteria": [
        "fulfillexpeditecriteria", "expedited", "expedited_bool", "is_expedited",
        "alert", "15_day_alert", "expedited_report"
    ],
    "occurcountry": [
        "occurcountry", "occur_country", "country", "primarysource_reportercountry",
        "reportercountry", "reporter_country", "location"
    ],
    "patient_patientonsetage": [
        "patient_patientonsetage", "patientonsetage", "patient_age", "age",
        "onset_age", "patient_onset_age"
    ],
    "patient_patientsex": [
        "patient_patientsex", "patientsex", "patient_gender", "sex", "gender"
    ],
    "patient_reaction_reactionmeddrapt": [
        "patient_reaction_reactionmeddrapt", "reactionmeddrapt", "meddra_pt",
        "meddrapt", "reaction_pt", "reaction", "adverse_event", "adverse_reaction",
        "preferred_term", "event_pt", "pt_name"
    ],
    "patient_reaction_reactionoutcome": [
        "patient_reaction_reactionoutcome", "reactionoutcome", "outcome",
        "patient_outcome", "event_outcome"
    ],
    "receivedate": [
        "receivedate", "receive_date", "receipt_date", "receiptdate",
        "event_date", "report_date", "date"
    ],
    "medicinalproduct": [
        "patient_drug_medicinalproduct", "medicinalproduct", "medicinal_product",
        "drugname", "drug_name", "product_name", "productname", "product", "drug",
        "active_substance", "active_ingredient"
    ]
}


def load_and_normalize_data(file_path: str) -> pd.DataFrame:
    """Loads the ICSR dataset, handling both CSV and Excel with intelligent column mapping."""
    if file_path.endswith('.csv'):
        df = pd.read_csv(file_path, low_memory=False)
    else:
        df = pd.read_excel(file_path)

    # Initial column cleaning
    df.columns = df.columns.astype(str).str.lower().str.strip()

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
    if 'safetyreportid' not in df.columns:
        df['safetyreportid'] = [f"ICSR-{i+1:05d}" for i in range(len(df))]

    # Fallback synthesize receivedate if completely absent
    if 'receivedate' not in df.columns:
        df['receivedate'] = "20240101"

    # Fallback reaction term if absent
    if 'patient_reaction_reactionmeddrapt' not in df.columns:
        df['patient_reaction_reactionmeddrapt'] = "Adverse event unclassified"

    # Normalize seriousness flags to boolean (1/yes/true -> True, else False)
    if 'serious' in df.columns:
        df['serious_bool'] = df['serious'].astype(str).str.lower().isin(['1', 'yes', 'true', 'serious', 'y'])
    else:
        df['serious_bool'] = False

    # Normalize expedited flag
    if 'fulfillexpeditecriteria' in df.columns:
        df['expedited_bool'] = df['fulfillexpeditecriteria'].astype(str).str.lower().isin(['1', 'yes', 'true', 'y', 'expedited'])
    else:
        df['expedited_bool'] = False

    # Normalize country
    if 'occurcountry' in df.columns:
        df['standard_country'] = df['occurcountry'].fillna("UNKNOWN").astype(str).str.upper()
    elif 'primarysource_reportercountry' in df.columns:
        df['standard_country'] = df['primarysource_reportercountry'].fillna("UNKNOWN").astype(str).str.upper()
    else:
        df['standard_country'] = "UNKNOWN"

    # Normalize age
    if 'patient_patientonsetage' in df.columns:
        df['numeric_age'] = pd.to_numeric(df['patient_patientonsetage'], errors='coerce')
    else:
        df['numeric_age'] = None

    # Normalize sex if present
    if 'patient_patientsex' in df.columns:
        df['patient_patientsex'] = df['patient_patientsex'].astype(str).replace({'1': 'Male', '2': 'Female', 'nan': 'Unknown'})
    else:
        df['patient_patientsex'] = "Unknown"

    return df


def validate_data(df: pd.DataFrame) -> dict:
    """Validates the dataframe and returns a summary of data quality."""
    issues = {}
    
    # Missing values
    missing = df.isnull().sum()
    issues['missing_counts'] = missing[missing > 0].to_dict()
    
    # Duplicates
    issues['duplicate_rows'] = int(df.duplicated().sum())

    # Ensure required columns
    required_cols = ['safetyreportid', 'receivedate', 'patient_reaction_reactionmeddrapt']
    missing_req = [c for c in required_cols if c not in df.columns]
    issues['missing_required_columns'] = missing_req

    return issues
