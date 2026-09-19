import streamlit as st
import pandas as pd
import numpy as np
import requests
import io

# --- 1. Page Configuration ---
st.set_page_config(page_title="INSPIRES Study: Anthropometry Tracker", layout="wide")
st.title("INSPIRES Study: Height & Weight Dashboard")

# --- 2. Data Fetching & Processing ---
@st.cache_data(ttl=600)
def fetch_and_process_data():
    creds = st.secrets["api_credentials"]
    auth = (creds["username"], creds["password"])
    
    # Construct OData API endpoints for ODK Central forms
    enr_url = f"{creds['base_url']}/forms/ENR_2024.svc/Submissions?$expand=*"
    out_url = f"{creds['base_url']}/forms/OUT_2024.svc/Submissions?$expand=*"
    
    # Fetch Data
    with st.spinner("Fetching data from ODK server..."):
        enr_resp = requests.get(enr_url, auth=auth)
        out_resp = requests.get(out_url, auth=auth)
    
    if enr_resp.status_code != 200 or out_resp.status_code != 200:
        st.error(f"Failed to fetch data. Server responded with ENR: {enr_resp.status_code}, OUT: {out_resp.status_code}")
        st.stop()
        
    enr_data = enr_resp.json().get('value', [])
    out_data = out_resp.json().get('value', [])
    
    # Create DataFrames natively
    enr_df = pd.json_normalize(enr_data) if enr_data else pd.DataFrame()
    out_df = pd.json_normalize(out_data) if out_data else pd.DataFrame()

    # ---------------------------------------------------------
    # ROBUST EXTRACTION LOGIC
    # Always returns a pandas Series of the correct length, 
    # even if the column is missing, preventing KeyErrors.
    # ---------------------------------------------------------
    def extract_col(df, target_str):
        if df.empty:
            return pd.Series(dtype=object)
        matches = [c for c in df.columns if target_str in c]
        if matches:
            return df[matches[0]]
        return pd.Series(np.nan, index=df.index)

    # 1. Build Standardized ENR DataFrame
    std_enr = pd.DataFrame(index=enr_df.index)
    std_enr['Participant_ID'] = extract_col(enr_df, 'ENR_BINFO-C_8')
    std_enr['Site_Code'] = extract_col(enr_df, 'ENR_BINFO-Q1_2')
    std_enr['ENR_FAHA-Q3_5_1'] = extract_col(enr_df, 'ENR_FAHA-Q3_5_1')
    std_enr['ENR_FAHA-Q3_6_1'] = extract_col(enr_df, 'ENR_FAHA-Q3_6_1')
    
    # Try finding specific 'SubmitterName', fallback to system submitterName
    sub_enr = extract_col(enr_df, 'SubmitterName')
    if sub_enr.isna().all():
        sub_enr = extract_col(enr_df, 'submitterName')
    std_enr['SubmitterName'] = sub_enr
    
    # Try finding specific 'today', fallback to system submissionDate
    date_enr = extract_col(enr_df, 'today')
    if date_enr.isna().all():
        date_enr = extract_col(enr_df, 'submissionDate')
    std_enr['today'] = date_enr

    # Map Sites
    site_mapping = {
        "NC": "NCT DELHI", "JO": "JODHPUR", "GU": "GUWAHATI",
        "KO": "KOLKATA", "CH": "CHENNAI", "PU": "PUNE"
    }
    std_enr['City'] = std_enr['Site_Code'].map(site_mapping)

    # 2. Build Standardized OUT DataFrame
    std_out = pd.DataFrame(index=out_df.index)
    std_out['Participant_ID'] = extract_col(out_df, 'OUT-P_ID')
    std_out['OUT_Height'] = extract_col(out_df, 'OUT-Q1_11_1a')
    std_out['OUT_Weight'] = extract_col(out_df, 'OUT-Q1_12_1a')
    std_out['OUT_Submitter'] = extract_col(out_df, 'submitterName')
    std_out['OUT_Date'] = extract_col(out_df, 'submissionDate')

    # Ensure no entirely blank rows merge
    std_enr = std_enr.dropna(subset=['Participant_ID'])
    std_out = std_out.dropna(subset=['Participant_ID'])

    # 3. Merge and Process DataFrames
    if std_enr.empty:
        # Failsafe if forms have 0 records with a valid ID
        merged_df = std_enr.copy()
        merged_df['Final_Height_cm'] = np.nan
        merged_df['Final_Weight_kg'] = np.nan
        merged_df['Height_Source'] = 'Missing'
        merged_df['Weight_Source'] = 'Missing'
        merged_df['Height_Missing'] = True
        merged_df['Weight_Missing'] = True
        return merged_df

    merged_df = pd.merge(std_enr, std_out, on="Participant_ID", how="left")

    # Enforce numeric types just in case ODK returned strings
    merged_df['ENR_FAHA-Q3_5_1'] = pd.to_numeric(merged_df['ENR_FAHA-Q3_5_1'], errors='coerce')
    merged_df['OUT_Height'] = pd.to_numeric(merged_df['OUT_Height'], errors='coerce')
    merged_df['ENR_FAHA-Q3_6_1'] = pd.to_numeric(merged_df['ENR_FAHA-Q3_6_1'], errors='coerce')
    merged_df['OUT_Weight'] = pd.to_numeric(merged_df['OUT_Weight'], errors='coerce')

    # Resolve Final Values
    merged_df['Final_Height_cm'] = merged_df['ENR_FAHA-Q3_5_1'].fillna(merged_df['OUT_Height'])
    merged_df['Final_Weight_kg'] = merged_df['ENR_FAHA-Q3_6_1'].fillna(merged_df['OUT_Weight'])

    merged_df['Height_Source'] = np.where(merged_df['ENR_FAHA-Q3_5_1'].notna(), 'Enrolment', 
                                 np.where(merged_df['OUT_Height'].notna(), 'Outcome', 'Missing'))
    
    merged_df['Weight_Source'] = np.where(merged_df['ENR_FAHA-Q3_6_1'].notna(), 'Enrolment', 
                                 np.where(merged_df['OUT_Weight'].notna(), 'Outcome', 'Missing'))

    merged_df['Height_Missing'] = merged_df['Final_Height_cm'].isna()
    merged_df['Weight_Missing'] = merged_df['Final_Weight_kg'].isna()

    return merged_df

# --- 3. Helper Function for Excel Export ---
def convert_df_to_excel(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Anthropometry_Data')
    return output.getvalue()

# --- 4. Main Application UI ---
try:
    df = fetch_and_process_data()
except Exception as e:
    st.error(f"An unexpected error occurred during data processing: {e}")
    st.stop()

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

# Apply Filter
filtered_df = df[df['City'].isin(selected_cities)]

st.subheader("Data Quality: Missing Anthropometry Metrics")
st.markdown("Displays counts of participants where height or weight is missing in **both** Enrolment and Outcome forms.")

# Dynamic Metric Cards per selected site
if not selected_cities:
    st.info("Please select at least one site from the sidebar.")
else:
    cols = st.columns(len(selected_cities))
    for idx, city in enumerate(selected_cities):
        city_data = filtered_df[filtered_df['City'] == city]
        missing_height = city_data['Height_Missing'].sum()
        missing_weight = city_data['Weight_Missing'].sum()
        
        with cols[idx]:
            st.metric(label=f"{city} - Missing Height", value=int(missing_height))
            st.metric(label=f"{city} - Missing Weight", value=int(missing_weight))

st.divider()

# Data Table Display
st.subheader("Extracted Participant Data")
columns_to_display = [
    'Participant_ID', 'City', 'SubmitterName', 'today', 
    'Final_Height_cm', 'Height_Source', 
    'Final_Weight_kg', 'Weight_Source'
]
st.dataframe(filtered_df[columns_to_display], use_container_width=True)

# Excel Download Button
st.subheader("Export Data")
excel_data = convert_df_to_excel(filtered_df)

st.download_button(
    label="📥 Download Data as Excel",
    data=excel_data,
    file_name="INSPIRES_Height_Weight_Data.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)