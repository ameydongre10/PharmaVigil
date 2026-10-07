import pandas as pd
from typing import Dict, Any, List, Optional
from .models import AnalysisResult


class AnalysisEngine:
    def __init__(self, df: pd.DataFrame):
        self.df = df
        
        # Build a case-level dataframe deduplicated by safetyreportid
        if 'safetyreportid' in df.columns:
            agg_dict = {
                'serious_bool': 'max',
                'expedited_bool': 'max',
                'numeric_age': 'first',
                'patient_patientsex': 'first',
                'standard_country': 'first',
                'receivedate': 'first'
            }
            # Only aggregate columns present in df
            agg_dict = {k: v for k, v in agg_dict.items() if k in df.columns}
            self.cases_df = df.groupby('safetyreportid').agg(agg_dict).reset_index()
        else:
            self.cases_df = pd.DataFrame()

    @staticmethod
    def parse_dates(series: pd.Series) -> pd.Series:
        """Robustly parses date series, supporting FAERS integer YYYYMMDD, ISO YYYY-MM-DD, or Excel dates."""
        if series.empty:
            return pd.Series(dtype='datetime64[ns]')
        s_clean = series.astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
        # 1. Try FAERS format %Y%m%d (e.g. 20230512)
        parsed_ymd = pd.to_datetime(s_clean, format='%Y%m%d', errors='coerce')
        valid_inputs = s_clean.replace(['nan', 'None', '', 'NaT'], None).dropna()
        if len(valid_inputs) > 0 and parsed_ymd.notna().sum() >= len(valid_inputs) * 0.5:
            return parsed_ymd
        # 2. Try general parser
        parsed_gen = pd.to_datetime(series, errors='coerce')
        if parsed_gen.notna().sum() > 0:
            return parsed_gen
        return parsed_ymd

    def get_reporting_period(self) -> AnalysisResult:
        if self.cases_df.empty or 'receivedate' not in self.cases_df.columns:
            return AnalysisResult(
                analysis_id="period_001",
                analysis_name="Reporting Period",
                metric="Date Range",
                value={"start_date": None, "end_date": None},
                methodology="Min and Max of receivedate across all unique cases",
                case_level=True,
                source_fields=["receivedate"]
            )
        dates = self.parse_dates(self.cases_df['receivedate'])
        min_date = dates.min()
        max_date = dates.max()
        return AnalysisResult(
            analysis_id="period_001",
            analysis_name="Reporting Period",
            metric="Date Range",
            value={"start_date": min_date.strftime('%Y-%m-%d') if pd.notnull(min_date) else None,
                   "end_date": max_date.strftime('%Y-%m-%d') if pd.notnull(max_date) else None},
            methodology="Min and Max of receivedate across all unique cases",
            case_level=True,
            source_fields=["receivedate"]
        )

    def get_case_volume(self) -> AnalysisResult:
        if self.cases_df.empty:
            return AnalysisResult(
                analysis_id="vol_001",
                analysis_name="Case Volume",
                metric="Counts",
                value={"total_cases": 0, "serious_cases": 0, "non_serious_cases": 0,
                       "serious_pct": 0, "non_serious_pct": 0},
                methodology="Deduplicated safetyreportid. Max of serious flag per case.",
                case_level=True,
                source_fields=["safetyreportid", "serious"]
            )
        total = len(self.cases_df)
        serious = int(self.cases_df['serious_bool'].sum()) if 'serious_bool' in self.cases_df.columns else 0
        non_serious = total - serious
        return AnalysisResult(
            analysis_id="vol_001",
            analysis_name="Case Volume",
            metric="Counts",
            value={
                "total_cases": total,
                "serious_cases": serious,
                "non_serious_cases": non_serious,
                "serious_pct": round((serious / total) * 100, 2) if total > 0 else 0,
                "non_serious_pct": round((non_serious / total) * 100, 2) if total > 0 else 0
            },
            methodology="Deduplicated safetyreportid. Max of serious flag per case.",
            case_level=True,
            source_fields=["safetyreportid", "serious"]
        )
        
    def get_age_distribution(self) -> AnalysisResult:
        def bucket_age(age):
            if pd.isnull(age): return "Unknown"
            if age < 0 or age > 150: return "Unknown"
            if age < 18: return "<18"
            if age < 65: return "18-64"
            return "65+"

        if 'numeric_age' not in self.cases_df.columns:
            return AnalysisResult(
                analysis_id="demo_age_001",
                analysis_name="Age Distribution",
                metric="Counts and Percentages",
                value={"counts": {"Unknown": len(self.cases_df)}, "percentages": {"Unknown": 100.0}},
                methodology="Bucket numeric_age field into <18, 18-64, 65+, Unknown",
                case_level=True,
                source_fields=["patient_patientonsetage"]
            )

        ages = self.cases_df['numeric_age'].apply(bucket_age)
        counts = ages.value_counts().to_dict()
        total = len(self.cases_df)
        pcts = {k: round((v/total)*100, 2) for k, v in counts.items()} if total > 0 else {}
        
        return AnalysisResult(
            analysis_id="demo_age_001",
            analysis_name="Age Distribution",
            metric="Counts and Percentages",
            value={"counts": counts, "percentages": pcts},
            methodology="Bucket numeric_age field into <18, 18-64, 65+, Unknown",
            case_level=True,
            source_fields=["patient_patientonsetage"]
        )

    def get_sex_distribution(self) -> AnalysisResult:
        if 'patient_patientsex' not in self.cases_df.columns:
            return AnalysisResult(
                analysis_id="demo_sex_001",
                analysis_name="Sex Distribution",
                metric="Counts and Percentages",
                value={"counts": {"Unknown": len(self.cases_df)}, "percentages": {"Unknown": 100.0}},
                methodology="Case-level count of patient_patientsex",
                case_level=True,
                source_fields=["patient_patientsex"]
            )

        sex = self.cases_df['patient_patientsex'].fillna("Unknown").astype(str).str.title()
        counts = sex.value_counts().to_dict()
        total = len(self.cases_df)
        pcts = {k: round((v/total)*100, 2) for k, v in counts.items()} if total > 0 else {}
        
        return AnalysisResult(
            analysis_id="demo_sex_001",
            analysis_name="Sex Distribution",
            metric="Counts and Percentages",
            value={"counts": counts, "percentages": pcts},
            methodology="Case-level count of patient_patientsex",
            case_level=True,
            source_fields=["patient_patientsex"]
        )

    def get_country_distribution(self) -> AnalysisResult:
        if 'standard_country' not in self.cases_df.columns:
            return AnalysisResult(
                analysis_id="demo_country_001",
                analysis_name="Country Distribution",
                metric="Counts and Percentages",
                value={"counts": {"UNKNOWN": len(self.cases_df)}, "percentages": {"UNKNOWN": 100.0}},
                methodology="Case-level count of occurcountry",
                case_level=True,
                source_fields=["occurcountry"]
            )

        counts = self.cases_df['standard_country'].value_counts().to_dict()
        total = len(self.cases_df)
        pcts = {k: round((v/total)*100, 2) for k, v in counts.items()} if total > 0 else {}
        
        return AnalysisResult(
            analysis_id="demo_country_001",
            analysis_name="Country Distribution",
            metric="Counts and Percentages",
            value={"counts": counts, "percentages": pcts},
            methodology="Case-level count of occurcountry (fallback to primarysource_reportercountry)",
            case_level=True,
            source_fields=["occurcountry", "primarysource_reportercountry"]
        )
        
    def get_reactions(self, top_n: int = 20) -> Optional[AnalysisResult]:
        if 'patient_reaction_reactionmeddrapt' not in self.df.columns:
            return None
        rx_df = self.df[['safetyreportid', 'patient_reaction_reactionmeddrapt']].drop_duplicates()
        counts = rx_df['patient_reaction_reactionmeddrapt'].value_counts().head(top_n).to_dict()
        
        return AnalysisResult(
            analysis_id="rx_001",
            analysis_name="Top Reactions",
            metric=f"Top {top_n} Counts",
            value=counts,
            methodology="Count of unique PTs per case",
            case_level=False,
            source_fields=["patient_reaction_reactionmeddrapt"]
        )

    def get_serious_reactions(self, top_n: int = 20) -> Optional[AnalysisResult]:
        if 'patient_reaction_reactionmeddrapt' not in self.df.columns:
            return None
            
        serious_case_ids = self.cases_df[self.cases_df['serious_bool'] == True]['safetyreportid']
        rx_df = self.df[self.df['safetyreportid'].isin(serious_case_ids)]
        rx_df = rx_df[['safetyreportid', 'patient_reaction_reactionmeddrapt']].drop_duplicates()
        counts = rx_df['patient_reaction_reactionmeddrapt'].value_counts().head(top_n).to_dict()
        
        return AnalysisResult(
            analysis_id="rx_002",
            analysis_name="Top Serious Reactions",
            metric=f"Top {top_n} Counts in Serious Cases",
            value=counts,
            methodology="Count of unique PTs per serious case",
            case_level=False,
            source_fields=["patient_reaction_reactionmeddrapt", "serious"]
        )
        
    def get_outcomes(self) -> Optional[AnalysisResult]:
        if 'patient_reaction_reactionoutcome' not in self.df.columns:
            return None
        counts = self.df['patient_reaction_reactionoutcome'].fillna("Unknown").value_counts().to_dict()
        
        return AnalysisResult(
            analysis_id="out_001",
            analysis_name="Reaction Outcomes",
            metric="Counts",
            value=counts,
            methodology="Row-level count of reaction outcomes",
            case_level=False,
            source_fields=["patient_reaction_reactionoutcome"]
        )

    def get_time_trends(self) -> AnalysisResult:
        if self.cases_df.empty or 'receivedate' not in self.cases_df.columns:
            return AnalysisResult(
                analysis_id="trend_001",
                analysis_name="Monthly Case Volume",
                metric="Counts per Month",
                value={},
                methodology="Group cases by receivedate month",
                case_level=True,
                source_fields=["receivedate"]
            )

        dates = self.parse_dates(self.cases_df['receivedate'])
        valid_dates = dates.dropna()
        if not valid_dates.empty:
            months = valid_dates.dt.to_period('M').astype(str)
            counts = months.value_counts().sort_index().to_dict()
        else:
            counts = {}
        
        return AnalysisResult(
            analysis_id="trend_001",
            analysis_name="Monthly Case Volume",
            metric="Counts per Month",
            value=counts,
            methodology="Group cases by receivedate month",
            case_level=True,
            source_fields=["receivedate"]
        )

    def get_alert_cases(self) -> AnalysisResult:
        total_alerts = int(self.cases_df['expedited_bool'].sum()) if 'expedited_bool' in self.cases_df.columns else 0
        if 'expedited_bool' in self.cases_df.columns and 'serious_bool' in self.cases_df.columns:
            serious_alerts = int(self.cases_df[(self.cases_df['expedited_bool'] == True) & (self.cases_df['serious_bool'] == True)].shape[0])
        else:
            serious_alerts = 0
        
        return AnalysisResult(
            analysis_id="alert_001",
            analysis_name="15-Day / Alert Cases",
            metric="Counts",
            value={"total_alerts": total_alerts, "serious_alerts": serious_alerts},
            methodology="Count of cases where fulfillexpeditecriteria is true (total_alerts) and fulfillexpeditecriteria is true AND serious is true (serious_alerts)",
            case_level=True,
            source_fields=["fulfillexpeditecriteria", "serious"]
        )

    def get_history_of_actions(self) -> AnalysisResult:
        return AnalysisResult(
            analysis_id="hist_001",
            analysis_name="History of Actions",
            metric="Status",
            value="No history-of-actions data was provided.",
            methodology="Hardcoded per assignment requirements.",
            case_level=False,
            source_fields=[]
        )
        
    def get_expectedness(self) -> AnalysisResult:
        return AnalysisResult(
            analysis_id="exp_001",
            analysis_name="Expectedness",
            metric="Status",
            value="OUT OF SCOPE / NOT DETERMINABLE FROM SUPPLIED DATA",
            methodology="Hardcoded per assignment requirements.",
            case_level=False,
            source_fields=[]
        )
        
    def get_case_index(self, limit: int = 100) -> AnalysisResult:
        listing = []
        for _, case in self.cases_df.head(limit).iterrows():
            cid = case['safetyreportid']
            rx_col = 'patient_reaction_reactionmeddrapt'
            if rx_col in self.df.columns:
                rx = self.df[self.df['safetyreportid'] == cid][rx_col].dropna().unique().tolist()
            else:
                rx = []
            raw_date = case.get('receivedate', '')
            try:
                parsed = self.parse_dates(pd.Series([raw_date]))
                if not parsed.isna().iloc[0]:
                    date_str = parsed.iloc[0].strftime('%Y-%m-%d')
                else:
                    date_str = str(raw_date)
            except Exception:
                date_str = str(raw_date)

            listing.append({
                "safetyreportid": str(cid),
                "reactions": ", ".join(str(r) for r in rx) if rx else "Unknown",
                "serious": "Yes" if case.get('serious_bool', False) else "No",
                "date": date_str,
                "country": str(case.get('standard_country', 'UNKNOWN'))
            })
            
        return AnalysisResult(
            analysis_id="idx_001",
            analysis_name="Case Index",
            metric="Structured Listing",
            value=listing,
            methodology="Join case-level data with concatenated reactions",
            case_level=True,
            source_fields=["safetyreportid", "patient_reaction_reactionmeddrapt", "serious", "receivedate", "occurcountry"]
        )
