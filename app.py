import os
import pandas as pd
import numpy as np
import requests
import urllib.parse
from io import StringIO
import io
import streamlit as st

# --- 1. Page Configuration ---
st.set_page_config(page_title="INSPIRES Study: Anthropometry Tracker", layout="wide")
st.title("INSPIRES Study: Height & Weight Dashboard")

# --- 2. Data Fetching Logic ---
@st.cache_data(ttl=43200)
def fetch_odk_data(form_id):
    """Fetches CSV submission data for a given form ID using the proven session token method."""
    if "api_credentials" in st.secrets:
        creds = st.secrets["api_credentials"]
        ODK_URL = "https://odk.thsti.in"
        ODK_PROJECT_ID = "17"
        ODK_EMAIL = creds.get("username", "")
        ODK_PASSWORD = creds.get("password", "")
    else:
        ODK_URL = os.environ.get("ODK_URL", "https://odk.thsti.in").rstrip('/')
        ODK_PROJECT_ID = os.environ.get("ODK_PROJECT_ID", "17")
        ODK_EMAIL = os.environ.get("ODK_USERNAME", "")
        ODK_PASSWORD = os.environ.get("ODK_PASSWORD", "")
    
    if not all([ODK_EMAIL, ODK_PASSWORD]):
        st.sidebar.error("⚠️ Missing ODK_USERNAME or ODK_PASSWORD credentials.")
        return pd.DataFrame()

    try:
        session_resp = requests.post(
            f"{ODK_URL}/v1/sessions",
            json={"email": ODK_EMAIL, "password": ODK_PASSWORD}
        )
        session_resp.raise_for_status()
        token = session_resp.json().get("token")
        
        clean_form_id = urllib.parse.unquote(form_id)
        encoded_form_id = urllib.parse.quote(clean_form_id)
        
        csv_resp = requests.get(
            f"{ODK_URL}/v1/projects/{ODK_PROJECT_ID}/forms/{encoded_form_id}/submissions.csv",
            headers={"Authorization": f"Bearer {token}"}
        )
        csv_resp.raise_for_status()
        
        return pd.read_csv(StringIO(csv_resp.text))
    except Exception as e:
        st.sidebar.error(f"❌ Error fetching '{form_id}': {str(e)}")
        return pd.DataFrame()

# --- 3. Data Processing ---
def process_anthropometry_data(enr_df, out_df):
    if enr_df.empty:
        return pd.DataFrame()

    id_col_enr = 'ENR_BINFO-C_8' if 'ENR_BINFO-C_8' in enr_df.columns else 'ENR_BINFO-C.8'
    site_col_enr = 'ENR_BINFO-Q1_2' if 'ENR_BINFO-Q1_2' in enr_df.columns else 'ENR_BINFO-Q1.2'
    ht_col_enr = 'ENR_FAHA-Q3_5_1' if 'ENR_FAHA-Q3_5_1' in enr_df.columns else 'ENR_FAHA-Q3.5.1'
    wt_col_enr = 'ENR_FAHA-Q3_6_1' if 'ENR_FAHA-Q3_6_1' in enr_df.columns else 'ENR_FAHA-Q3.6.1'
    
    date_col_enr = next((c for c in enr_df.columns if c.lower() == 'today'), 'SubmissionDate')

    std_enr = pd.DataFrame()
    std_enr['Participant ID'] = enr_df[id_col_enr].astype(str).str.strip().str.upper() if id_col_enr in enr_df.columns else pd.Series(dtype=str)
    std_enr['Site_Code'] = enr_df[site_col_enr] if site_col_enr in enr_df.columns else np.nan
    std_enr['ENR_Height'] = pd.to_numeric(enr_df[ht_col_enr], errors='coerce') if ht_col_enr in enr_df.columns else np.nan
    std_enr['ENR_Weight'] = pd.to_numeric(enr_df[wt_col_enr], errors='coerce') if wt_col_enr in enr_df.columns else np.nan
    std_enr['today'] = enr_df[date_col_enr] if date_col_enr in enr_df.columns else np.nan

    site_mapping = {
        "NC": "NCT DELHI", "JO": "JODHPUR", "GU": "GUWAHATI",
        "KO": "KOLKATA", "CH": "CHENNAI", "PU": "PUNE"
    }
    std_enr['City'] = std_enr['Site_Code'].map(site_mapping)

    std_out = pd.DataFrame()
    if not out_df.empty:
        id_col_out = 'OUT-P_ID' if 'OUT-P_ID' in out_df.columns else 'OUT-P.ID'
        ht_col_out = 'OUT-Q1_11_1a' if 'OUT-Q1_11_1a' in out_df.columns else 'OUT-Q1.11.1a'
        wt_col_out = 'OUT-Q1_12_1a' if 'OUT-Q1_12_1a' in out_df.columns else 'OUT-Q1.12.1a'
        date_col_out = next((c for c in out_df.columns if c.lower() == 'today'), 'SubmissionDate')

        std_out['Participant ID'] = out_df[id_col_out].astype(str).str.strip().str.upper() if id_col_out in out_df.columns else pd.Series(dtype=str)
        std_out['OUT_Height'] = pd.to_numeric(out_df[ht_col_out], errors='coerce') if ht_col_out in out_df.columns else np.nan
        std_out['OUT_Weight'] = pd.to_numeric(out_df[wt_col_out], errors='coerce') if wt_col_out in out_df.columns else np.nan
        std_out['OUT_Date'] = out_df[date_col_out] if date_col_out in out_df.columns else np.nan

    std_enr = std_enr.dropna(subset=['Participant ID'])
    if not std_out.empty:
        std_out = std_out.dropna(subset=['Participant ID'])
        merged_df = pd.merge(std_enr, std_out, on="Participant ID", how="left")
    else:
        merged_df = std_enr.copy()
        for col in ['OUT_Height', 'OUT_Weight', 'OUT_Date']:
            merged_df[col] = np.nan

    # Resolve Final Values
    merged_df['Height Recorded'] = merged_df['ENR_Height'].fillna(merged_df['OUT_Height'])
    merged_df['Weight Recorded'] = merged_df['ENR_Weight'].fillna(merged_df['OUT_Weight'])

    merged_df['Source_Height'] = np.where(merged_df['ENR_Height'].notna(), 'Enrolment', 
                                 np.where(merged_df['OUT_Height'].notna(), 'Outcome', 'Missing'))
    
    merged_df['Source_Weight'] = np.where(merged_df['ENR_Weight'].notna(), 'Enrolment', 
                                 np.where(merged_df['OUT_Weight'].notna(), 'Outcome', 'Missing'))

    # Resolve Date of Recording (Enrolment takes priority if data exists there, else Outcome)
    merged_df['Date Recorded'] = np.where(
        (merged_df['Source_Height'] == 'Enrolment') | (merged_df['Source_Weight'] == 'Enrolment'), 
        merged_df['today'], 
        np.where(
            (merged_df['Source_Height'] == 'Outcome') | (merged_df['Source_Weight'] == 'Outcome'), 
            merged_df['OUT_Date'], 
            np.nan
        )
    )

    merged_df['Height_Missing'] = merged_df['Height Recorded'].isna()
    merged_df['Weight_Missing'] = merged_df['Weight Recorded'].isna()
    merged_df['MISSING Ht/wt'] = merged_df['Height_Missing'] | merged_df['Weight_Missing']

    return merged_df

# --- 4. Helper Function for Excel Export ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Anthropometry_Data')
    return output.getvalue()


# --- 5. Main Application UI ---
if st.sidebar.button("🔄 Sync with ODK Central", type="primary", use_container_width=True):
    st.cache_data.clear()
    st.sidebar.success("Cache Cleared! Syncing fresh datasets...")
    st.rerun()

with st.spinner("Fetching and processing data..."):
    raw_enr = fetch_odk_data("ENR_2024")
    raw_out = fetch_odk_data("OUT_2024")
    df = process_anthropometry_data(raw_enr, raw_out)

if df.empty:
    st.warning("No submission data found on the ODK Server or data is empty.")
    st.stop()

# Sidebar Filters
st.sidebar.header("Filters")
available_cities = df['City'].dropna().unique()
selected_cities = st.sidebar.multiselect(
    "Select Site (City):",
    options=available_cities,
    default=available_cities
)

filtered_df = df[df['City'].isin(selected_cities)]

st.subheader("Data Quality: Missing Anthropometry Metrics")
st.markdown("Displays counts and percentages of participants where height or weight is missing.")

# Dynamic Summary Table
if not selected_cities:
    st.info("Please select at least one site from the sidebar.")
else:
    summary_data = []
    for city in selected_cities:
        city_data = filtered_df[filtered_df['City'] == city]
        total_enrolments = len(city_data)
        missing_ht = int(city_data['Height_Missing'].sum())
        missing_wt = int(city_data['Weight_Missing'].sum())
        missing_either = int(city_data['MISSING Ht/wt'].sum())
        pct_missing = (missing_either / total_enrolments * 100) if total_enrolments > 0 else 0
        
        summary_data.append({
            "Site (City)": city,
            "Total Enrolments": total_enrolments,
            "Missing Height": missing_ht,
            "Missing Weight": missing_wt,
            "Missing Either (Ht/Wt)": missing_either,
            "% Missing": f"{pct_missing:.1f}%"
        })
    
    summary_df = pd.DataFrame(summary_data)
    
    if not summary_df.empty:
        # Calculate Totals
        tot_enrol = summary_df["Total Enrolments"].sum()
        tot_miss_ht = summary_df["Missing Height"].sum()
        tot_miss_wt = summary_df["Missing Weight"].sum()
        tot_miss_either = summary_df["Missing Either (Ht/Wt)"].sum()
        tot_pct = (tot_miss_either / tot_enrol * 100) if tot_enrol > 0 else 0
        
        total_row = pd.DataFrame([{
            "Site (City)": "TOTAL",
            "Total Enrolments": tot_enrol,
            "Missing Height": tot_miss_ht,
            "Missing Weight": tot_miss_wt,
            "Missing Either (Ht/Wt)": tot_miss_either,
            "% Missing": f"{tot_pct:.1f}%"
        }])
        
        summary_df = pd.concat([summary_df, total_row], ignore_index=True)
        
        # Apply styling to highlight the Total row
        def style_total_row(row):
            if row['Site (City)'] == 'TOTAL':
                return ['background-color: #f0f2f6; font-weight: bold'] * len(row)
            return [''] * len(row)
            
        styled_summary = summary_df.style.apply(style_total_row, axis=1)
        
        st.dataframe(styled_summary, use_container_width=True, hide_index=True)

st.divider()

# Data Table Display
st.subheader("Extracted Participant Data")

columns_to_display = [
    'Participant ID', 'City', 'Height Recorded', 'Weight Recorded', 
    'Source_Height', 'Source_Weight', 'Date Recorded', 'MISSING Ht/wt'
]

display_cols = [c for c in columns_to_display if c in filtered_df.columns]
st.dataframe(filtered_df[display_cols], use_container_width=True)

# Excel Download
st.subheader("Export Data")
excel_data = convert_df_to_excel(filtered_df[display_cols])
st.download_button(
    label="📥 Download Data as Excel",
    data=excel_data,
    file_name="INSPIRES_Height_Weight_Data.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)
