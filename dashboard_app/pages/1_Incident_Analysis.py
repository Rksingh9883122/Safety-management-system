import pandas as pd
import plotly.express as px
import streamlit as st

import common
from queries import get_incidents_data, get_monthly_statistics_data

st.set_page_config(page_title="Incident Analysis", page_icon="🚨", layout="wide")
access = common.require_access()
common.sidebar_header(access)
common.hero("HSE Incident Analysis & Trend Monitoring", "Severity mix, root causes, hotspots and rate trends",
            ("#B71C1C", "#FF8F00"))

df = get_incidents_data(access["organization_id"])
monthly = get_monthly_statistics_data(access["organization_id"])
st.sidebar.header("Filters")
names = common.company_scope(access)
df = common.filter_companies(df, names)
monthly = common.filter_companies(monthly, names)
if df.empty and monthly.empty:
    st.info("No incidents or monthly statistics have been submitted yet.")
    st.stop()

df = common.date_range_filter(df, "report_date", "Incident date")
df = common.multiselect_filter(df, "incident_type", "Incident type")
df = common.multiselect_filter(df, "status", "Status")
df = common.multiselect_filter(df, "employment_type", "Employment type")
df = common.multiselect_filter(df, "body_part", "Body part")
df = common.multiselect_filter(df, "activity_type", "Activity")
df = common.multiselect_filter(df, "company_name", "Company")

SEVERE = {"LTI", "Fatality", "Restricted Work Case", "Medical Treatment"}
total = len(df)
open_cases = int((df["status"] == "Open").sum()) if total else 0
severe = int(df["incident_type"].isin(SEVERE).sum()) if total else 0
near_miss = int((df["incident_type"] == "Near Miss").sum()) if total else 0
lti = int((df["incident_type"] == "LTI").sum()) if total else 0
c1, c2, c3, c4, c5 = st.columns(5)
common.kpi(c1, "Incidents", total, "in current view", "#1565C0")
common.kpi(c2, "Open investigations", open_cases, "awaiting closure", "#D32F2F" if open_cases else "#43A047")
common.kpi(c3, "Recordable / severe", severe, "LTI, RWC, MTC, fatality", "#FF8F00")
common.kpi(c4, "Lost-time injuries", lti, "LTI cases", "#B71C1C")
common.kpi(c5, "Near misses", near_miss, "leading indicator", "#00A8C6")
st.write("")

tab_overview, tab_cause, tab_trend, tab_rates, tab_log = st.tabs(
    ["Overview", "Root causes & people", "Incident trend", "Safety rates (TRIR/LTIR)", "Incident log"]
)

with tab_overview:
    if df.empty:
        st.info("No incidents match the selected filters.")
    else:
        left, right = st.columns(2)
        typ = df["incident_type"].value_counts().reset_index()
        typ.columns = ["incident_type", "count"]
        fig = px.pie(typ, names="incident_type", values="count", hole=0.55,
                     color_discrete_sequence=common.PALETTE)
        left.subheader("Incident types")
        left.plotly_chart(common.style_figure(fig), use_container_width=True)
        comp = df.groupby(["company_name", "incident_type"]).size().reset_index(name="count")
        fig = px.bar(comp, x="company_name", y="count", color="incident_type",
                     color_discrete_sequence=common.PALETTE)
        right.subheader("Incidents by company")
        right.plotly_chart(common.style_figure(fig), use_container_width=True)
        act = df.groupby(df["activity_type"].fillna("Not specified")).size().reset_index(name="count")
        fig = px.treemap(act, path=["activity_type"], values="count", color="count",
                         color_continuous_scale=["#FFCCBC", "#B71C1C"])
        st.subheader("Where incidents happen (activity)")
        st.plotly_chart(common.style_figure(fig, 340), use_container_width=True)

with tab_cause:
    if df.empty:
        st.info("No incidents match the selected filters.")
    else:
        left, right = st.columns(2)
        body = df.groupby(df["body_part"].fillna("Not specified")).size().reset_index(name="count")
        body = body.sort_values("count")
        fig = px.bar(body, x="count", y="body_part", orientation="h", text="count",
                     color_discrete_sequence=["#D32F2F"])
        left.subheader("Body part affected")
        left.plotly_chart(common.style_figure(fig), use_container_width=True)
        emp = df.groupby(df["employment_type"].fillna("Not specified")).size().reset_index(name="count")
        fig = px.pie(emp, names="employment_type", values="count", hole=0.55,
                     color_discrete_sequence=common.PALETTE)
        right.subheader("Employment type")
        right.plotly_chart(common.style_figure(fig), use_container_width=True)
        cause = df["root_cause"].fillna("").str.split(";").explode().str.strip()
        cause = cause[cause != ""].value_counts().reset_index()
        cause.columns = ["cause", "count"]
        if not cause.empty:
            fig = px.bar(cause.sort_values("count"), x="count", y="cause", orientation="h", text="count",
                         color_discrete_sequence=["#FF8F00"])
            st.subheader("Root & contributing causes")
            st.plotly_chart(common.style_figure(fig, 380), use_container_width=True)
        ages = df["employee_age"].dropna()
        if not ages.empty:
            fig = px.histogram(df, x="employee_age", nbins=10, color_discrete_sequence=["#1565C0"])
            st.subheader("Age of injured / involved workers")
            st.plotly_chart(common.style_figure(fig, 300), use_container_width=True)

with tab_trend:
    dated = df.dropna(subset=["report_date"])
    if dated.empty:
        st.info("No dated incidents in the selected range.")
    else:
        granularity = st.radio("Group by", ["Week", "Month"], horizontal=True, index=1)
        freq = "W" if granularity == "Week" else "M"
        series = (
            dated.groupby([dated["report_date"].dt.to_period(freq).dt.start_time, "incident_type"])
            .size().reset_index(name="count")
        )
        series.columns = ["period", "incident_type", "count"]
        fig = px.bar(series, x="period", y="count", color="incident_type",
                     color_discrete_sequence=common.PALETTE)
        totals = series.groupby("period")["count"].sum().reset_index()
        if len(totals) >= 3:
            totals["rolling"] = totals["count"].rolling(3, min_periods=1).mean()
            fig.add_scatter(x=totals["period"], y=totals["rolling"], mode="lines+markers",
                            name="3-period average", line=dict(color="#1D2939", width=3))
        st.subheader(f"Incidents per {granularity.lower()}")
        st.plotly_chart(common.style_figure(fig), use_container_width=True)
        hours = pd.to_datetime(dated["event_time"], format="%H:%M", errors="coerce").dt.hour.dropna()
        if not hours.empty:
            by_hour = hours.value_counts().sort_index().reset_index()
            by_hour.columns = ["hour", "count"]
            fig = px.bar(by_hour, x="hour", y="count", color_discrete_sequence=["#8E24AA"])
            st.subheader("Time of day")
            st.plotly_chart(common.style_figure(fig, 300), use_container_width=True)

with tab_rates:
    if monthly.empty:
        st.info("No monthly statistics have been submitted yet.")
    else:
        rate_names = {
            "trir": "TRIR", "dart_rate": "DART", "dafw_rate": "DAFW",
            "ltir": "LTIR", "severity_rate": "Severity", "fatality_rate": "Fatality",
        }
        present = [c for c in rate_names if c in monthly]
        if not present:
            st.info("Rates are calculated for monthly statistics submitted after the rate formulae were added.")
        else:
            data = monthly.copy()
            data["report_month"] = pd.to_datetime(data["report_month"], format="%Y-%m", errors="coerce")
            for column in present:
                data[column] = pd.to_numeric(data[column], errors="coerce")
            chosen = st.multiselect("Rates to plot", [rate_names[c] for c in present],
                                    default=[rate_names[c] for c in present[:2]])
            reverse = {v: k for k, v in rate_names.items()}
            long = (
                data.melt(id_vars=["report_month", "company_name"], value_vars=[reverse[c] for c in chosen],
                          var_name="rate", value_name="value")
                .dropna(subset=["value"])
            )
            long["rate"] = long["rate"].map(rate_names)
            if long.empty:
                st.info("No calculated rates available for the current selection.")
            else:
                line = long.groupby(["report_month", "rate"], as_index=False)["value"].mean()
                fig = px.line(line.sort_values("report_month"), x="report_month", y="value", color="rate",
                              markers=True, color_discrete_sequence=common.PALETTE)
                st.subheader("Monthly rate trend (per 200,000 hours worked)")
                st.plotly_chart(common.style_figure(fig), use_container_width=True)
                by_company = long.groupby(["company_name", "rate"], as_index=False)["value"].mean()
                fig = px.bar(by_company, x="company_name", y="value", color="rate", barmode="group",
                             color_discrete_sequence=common.PALETTE)
                st.subheader("Average rate by company")
                st.plotly_chart(common.style_figure(fig), use_container_width=True)

with tab_log:
    cols = ["report_date", "company_name", "incident_type", "status", "activity_type", "body_part",
            "employment_type", "root_cause", "description", "corrective_action"]
    st.dataframe(df[cols] if not df.empty else df, use_container_width=True, hide_index=True)
    if not df.empty:
        common.download_button(df[cols], "incidents")
