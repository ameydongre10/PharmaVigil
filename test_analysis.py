import pytest
import pandas as pd
from src.data_loader import validate_data, load_and_normalize_data
from src.analysis_engine import AnalysisEngine

@pytest.fixture
def mock_dataset():
    data = [
        # Case 1: 2 reactions, serious, female, 65, UK
        {"safetyreportid": "C1", "receivedate": "20250101", "serious": "1", "fulfillexpeditecriteria": "yes", 
         "patient_patientonsetage": 65, "patient_patientsex": "female", "occurcountry": "GB",
         "patient_reaction_reactionmeddrapt": "Headache", "patient_reaction_reactionoutcome": "recovered"},
        {"safetyreportid": "C1", "receivedate": "20250101", "serious": "1", "fulfillexpeditecriteria": "yes", 
         "patient_patientonsetage": 65, "patient_patientsex": "female", "occurcountry": "GB",
         "patient_reaction_reactionmeddrapt": "Nausea", "patient_reaction_reactionoutcome": "unknown"},
        
        # Case 2: 1 reaction, non-serious, male, 12, FR
        {"safetyreportid": "C2", "receivedate": "20250215", "serious": "2", "fulfillexpeditecriteria": "no", 
         "patient_patientonsetage": 12, "patient_patientsex": "male", "occurcountry": "FR",
         "patient_reaction_reactionmeddrapt": "Rash", "patient_reaction_reactionoutcome": "recovering"},
         
        # Case 3: 1 reaction, serious, missing age/sex, US
        {"safetyreportid": "C3", "receivedate": "20250320", "serious": "yes", "fulfillexpeditecriteria": "yes", 
         "patient_patientonsetage": None, "patient_patientsex": None, "primarysource_reportercountry": "US",
         "patient_reaction_reactionmeddrapt": "Headache", "patient_reaction_reactionoutcome": "fatal"},
    ]
    df = pd.DataFrame(data)
    
    # Normalize mimicking data_loader
    df['serious_bool'] = df['serious'].astype(str).str.lower().isin(['1', 'yes', 'true', 'serious'])
    df['expedited_bool'] = df['fulfillexpeditecriteria'].astype(str).str.lower().isin(['1', 'yes', 'true'])
    
    df['standard_country'] = df['occurcountry'].fillna(df.get('primarysource_reportercountry')).astype(str).str.upper()
    df['numeric_age'] = pd.to_numeric(df['patient_patientonsetage'], errors='coerce')
    
    return df

def test_validation(mock_dataset):
    issues = validate_data(mock_dataset)
    assert issues['duplicate_rows'] == 0
    assert len(issues['missing_required_columns']) == 0

def test_case_volume(mock_dataset):
    engine = AnalysisEngine(mock_dataset)
    res = engine.get_case_volume()
    assert res.value['total_cases'] == 3
    assert res.value['serious_cases'] == 2
    assert res.value['non_serious_cases'] == 1

def test_age_bucketing(mock_dataset):
    engine = AnalysisEngine(mock_dataset)
    res = engine.get_age_distribution()
    assert res.value['counts']['65+'] == 1
    assert res.value['counts']['<18'] == 1
    assert res.value['counts']['Unknown'] == 1

def test_country_fallback(mock_dataset):
    engine = AnalysisEngine(mock_dataset)
    res = engine.get_country_distribution()
    assert res.value['counts']['US'] == 1
    assert res.value['counts']['GB'] == 1

def test_top_reactions(mock_dataset):
    engine = AnalysisEngine(mock_dataset)
    res = engine.get_reactions()
    assert res.value['Headache'] == 2
    assert res.value['Nausea'] == 1
    assert res.value['Rash'] == 1

def test_serious_reactions(mock_dataset):
    engine = AnalysisEngine(mock_dataset)
    res = engine.get_serious_reactions()
    # Rash is in the non-serious case C2, so it shouldn't be here
    assert 'Rash' not in res.value
    assert res.value['Headache'] == 2

def test_reporting_period(mock_dataset):
    engine = AnalysisEngine(mock_dataset)
    res = engine.get_reporting_period()
    assert res.value['start_date'] == '2025-01-01'
    assert res.value['end_date'] == '2025-03-20'

def test_alert_cases(mock_dataset):
    engine = AnalysisEngine(mock_dataset)
    res = engine.get_alert_cases()
    assert res.value['total_alerts'] == 2
    assert res.value['serious_alerts'] == 2

def test_alert_cases_with_expedited_non_serious():
    """Regression test proving expedited but non-serious cases are NOT counted as serious alerts."""
    data = [
        # Case 1: serious=True, expedited=True -> counts in total_alerts AND serious_alerts
        {"safetyreportid": "C1", "serious": "1", "fulfillexpeditecriteria": "yes", "patient_reaction_reactionmeddrapt": "Headache"},
        # Case 2: serious=False (non-serious), expedited=True -> counts in total_alerts ONLY
        {"safetyreportid": "C2", "serious": "2", "fulfillexpeditecriteria": "yes", "patient_reaction_reactionmeddrapt": "Nausea"},
        # Case 3: serious=True, expedited=False -> counts in NEITHER
        {"safetyreportid": "C3", "serious": "1", "fulfillexpeditecriteria": "no", "patient_reaction_reactionmeddrapt": "Dizziness"},
        # Case 4: serious=False, expedited=False -> counts in NEITHER
        {"safetyreportid": "C4", "serious": "2", "fulfillexpeditecriteria": "no", "patient_reaction_reactionmeddrapt": "Rash"},
    ]
    df = pd.DataFrame(data)
    df['serious_bool'] = df['serious'].astype(str).str.lower().isin(['1', 'yes', 'true', 'serious'])
    df['expedited_bool'] = df['fulfillexpeditecriteria'].astype(str).str.lower().isin(['1', 'yes', 'true'])
    df['standard_country'] = "UNKNOWN"
    df['numeric_age'] = None
    df['patient_patientsex'] = "Unknown"
    df['receivedate'] = "20250101"

    engine = AnalysisEngine(df)
    res = engine.get_alert_cases()
    assert res.value['total_alerts'] == 2
    assert res.value['serious_alerts'] == 1, "Expedited non-serious case must NOT be counted in serious_alerts"

