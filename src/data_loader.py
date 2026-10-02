import pandas as pd
from typing import Tuple

def load_and_normalize_data(file_path: str) -> pd.DataFrame:
    """Loads the ICSR dataset, handling both CSV and Excel."""
    if file_path.endswith('.csv'):
        df = pd.read_csv(file_path, low_memory=False)
    else:
        df = pd.read_excel(file_path)

    # Normalization
    df.columns = df.columns.str.lower().str.strip()

    # Normalize seriousness flags to boolean (1/yes/true -> True, else False)
    if 'serious' in df.columns:
        df['serious_bool'] = df['serious'].astype(str).str.lower().isin(['1', 'yes', 'true', 'serious'])
    else:
        df['serious_bool'] = False

    # Normalize expedited flag
    if 'fulfillexpeditecriteria' in df.columns:
        df['expedited_bool'] = df['fulfillexpeditecriteria'].astype(str).str.lower().isin(['1', 'yes', 'true'])
    else:
        df['expedited_bool'] = False

    # Normalize country
    if 'occurcountry' in df.columns:
        df['standard_country'] = df['occurcountry'].astype(str).str.upper()
    elif 'primarysource_reportercountry' in df.columns:
        df['standard_country'] = df['primarysource_reportercountry'].astype(str).str.upper()
    else:
        df['standard_country'] = "UNKNOWN"

    # Normalize age
    if 'patient_patientonsetage' in df.columns:
        df['numeric_age'] = pd.to_numeric(df['patient_patientonsetage'], errors='coerce')
    else:
        df['numeric_age'] = None

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
