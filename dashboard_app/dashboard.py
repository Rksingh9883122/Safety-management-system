import os
import sqlite3

import streamlit as st

try:
    import plotly.express as px  # type: ignore[import-not-found]
except ModuleNotFoundError:
    px = None

import common
from queries import (
    get_incidents_data,
    get_inspections_data,
    get_monthly_statistics_data,
    get_observations_data,
    get_training_records_data,
)

st.set_page_config(page_title="HSE Live Dashboard", layout="wide")

db_path = common.DB_PATH
access = common.require_access()

st.title("HSE Compliance Dashboard")
common.sidebar_header(access)
st.caption("Dashboard metrics are refreshed from saved submissions each time this page loads.")

# Fetch data
incidents_df = get_incidents_data(access["organization_id"])
obs_df = get_observations_data(access["organization_id"])
inspections_df = get_inspections_data(access["organization_id"])
monthly_df = get_monthly_statistics_data(access["organization_id"])
training_df = get_training_records_data(access["organization_id"])

# Scope filter: whole organization, a contractor with its subcontractors, or one company
scope_conn = sqlite3.connect(db_path)
scope_conn.row_factory = sqlite3.Row
org_contractors = scope_conn.execute(
    """
    SELECT contractor_id, company_name, contractor_type, parent_contractor_id
    FROM contractors WHERE organization_id = ? ORDER BY company_name
    """,
    (access["organization_id"],),
).fetchall()
scope_conn.close()
scope_options = {"Entire organization": None}
for row in org_contractors:
    if row["contractor_type"] == "Contractor":
        names = [row["company_name"]] + [
            sub["company_name"] for sub in org_contractors
            if sub["parent_contractor_id"] == row["contractor_id"]
        ]
        scope_options[f"{row['company_name']} + its subcontractors"] = names
for row in org_contractors:
    label = row["company_name"] + (
        " (subcontractor)" if row["contractor_type"] == "Subcontractor" else " (contractor only)"
    )
    scope_options[label] = [row["company_name"]]
selected_scope = st.sidebar.selectbox("View data for", list(scope_options))
selected_names = scope_options[selected_scope]
if selected_names is not None:
    st.info(f"Showing data for: {selected_scope}")

    def scope(df):
        if df.empty or "company_name" not in df:
            return df
        return df[df["company_name"].isin(selected_names)]

    incidents_df = scope(incidents_df)
    obs_df = scope(obs_df)
    inspections_df = scope(inspections_df)
    monthly_df = scope(monthly_df)
    training_df = scope(training_df)

# Top Level Metrics
col1, col2, col3 = st.columns(3)
with col1:
    st.metric("Total Incidents Logged", len(incidents_df))
with col2:
    open_incidents = len(incidents_df[incidents_df['status'] == 'Open']) if not incidents_df.empty else 0
    st.metric("Open Investigations", open_incidents)
with col3:
    st.metric("Total Safety Observations", len(obs_df))

col4, col5, col6 = st.columns(3)
with col4:
    st.metric("Site Inspections", len(inspections_df))
with col5:
    st.metric("Monthly Statistics Reports", len(monthly_df))
with col6:
    completed_training = (
        int((training_df["status"] == "Completed").sum())
        if not training_df.empty and "status" in training_df else 0
    )
    st.metric("Completed Training Records", completed_training)

st.markdown("---")

# Visualizations
col_chart1, col_chart2 = st.columns(2)

with col_chart1:
    st.subheader("Incidents by Type")
    if not incidents_df.empty:
        fig_inc = px.pie(incidents_df, names='incident_type', hole=0.4, 
                         color_discrete_sequence=['#FF8F00', '#1565C0', '#00A8C6'])
        st.plotly_chart(fig_inc, use_container_width=True)
    else:
        st.info("No incident data available yet.")

with col_chart2:
    st.subheader("Observations by Risk Level")
    if not obs_df.empty:
        fig_obs = px.bar(obs_df, x='risk_level', color='category',
                         color_discrete_sequence=['#FFC107', '#00A8C6', '#1565C0'])
        st.plotly_chart(fig_obs, use_container_width=True)
    else:
        st.info("No observation data available yet.")

st.subheader("Recent Safety Observations")
if not obs_df.empty:
    st.dataframe(obs_df.head(20), use_container_width=True, hide_index=True)
else:
    st.info("No safety observations have been submitted yet.")

st.subheader("Recent Site Inspections")
if not inspections_df.empty:
    st.dataframe(inspections_df.head(20), use_container_width=True, hide_index=True)
else:
    st.info("No site inspections have been submitted yet.")

st.subheader("Monthly Statistics")
if not monthly_df.empty:
    st.dataframe(monthly_df.head(20), use_container_width=True, hide_index=True)
else:
    st.info("No monthly statistics have been submitted yet.")

st.subheader("Training Performance")
if not training_df.empty:
    training_columns = [
        column for column in (
            "employee", "module", "status", "completionDate",
            "company_name", "updated_at",
        ) if column in training_df.columns
    ]
    st.dataframe(
        training_df[training_columns].head(50),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.info("No training records have been submitted yet.")
