import pandas as pd
import plotly.express as px
import streamlit as st

import common
from queries import get_observations_data

st.set_page_config(page_title="Safety Observations", page_icon="👁️", layout="wide")
access = common.require_access()
common.sidebar_header(access)
common.hero("Safety Observation Dashboard", "Unsafe acts, unsafe conditions and positive behaviours observed on site",
            ("#EF6C00", "#FFB300"))

df = get_observations_data(access["organization_id"])
st.sidebar.header("Filters")
df = common.filter_companies(df, common.company_scope(access))
if df.empty:
    st.info("No safety observations have been submitted yet.")
    st.stop()

df = common.date_range_filter(df, "date_recorded", "Observation date")
df = common.multiselect_filter(df, "risk_level", "Risk level")
df = common.multiselect_filter(df, "category", "Category")
df = common.multiselect_filter(df, "observation_type", "Observation type")
df = common.multiselect_filter(df, "location", "Location")
df = common.multiselect_filter(df, "activity_type", "Activity")
df = common.multiselect_filter(df, "company_name", "Company")
if df.empty:
    st.warning("No observations match the selected filters.")
    st.stop()

df["date_recorded"] = pd.to_datetime(df["date_recorded"], errors="coerce")
df["risk_level"] = df["risk_level"].fillna("Unspecified")
total = len(df)
high = int((df["risk_level"] == "High").sum())
open_actions = int(df["action_taken"].fillna("").str.strip().eq("").sum())
unsafe = int(df["category"].fillna("").str.startswith("Unsafe").sum())
c1, c2, c3, c4, c5 = st.columns(5)
common.kpi(c1, "Observations", total, "in current view", "#1565C0")
common.kpi(c2, "High risk", high, f"{high / total:.0%} of total", "#D32F2F")
common.kpi(c3, "Unsafe acts/conditions", unsafe, f"{unsafe / total:.0%} of total", "#FF8F00")
common.kpi(c4, "No action recorded", open_actions, "follow-up needed", "#8E24AA")
common.kpi(c5, "Locations", df["location"].nunique(), "observed", "#00A8C6")
st.write("")

tab_overview, tab_where, tab_trend, tab_records = st.tabs(
    ["Overview", "Hotspots", "Trend", "Observation log"]
)

with tab_overview:
    left, right = st.columns(2)
    risk = df["risk_level"].value_counts().reset_index()
    risk.columns = ["risk_level", "count"]
    fig = px.pie(risk, names="risk_level", values="count", hole=0.55, color="risk_level",
                 color_discrete_map=common.RISK_COLORS)
    left.subheader("Risk level")
    left.plotly_chart(common.style_figure(fig), use_container_width=True)
    cat = df.groupby(["category", "risk_level"]).size().reset_index(name="count")
    fig = px.bar(cat, x="category", y="count", color="risk_level", color_discrete_map=common.RISK_COLORS)
    right.subheader("Category by risk level")
    right.plotly_chart(common.style_figure(fig), use_container_width=True)
    act = df.groupby(df["activity_type"].fillna("Not specified")).size().reset_index(name="count")
    fig = px.treemap(act, path=["activity_type"], values="count", color="count",
                     color_continuous_scale=["#FFE082", "#EF6C00"])
    st.subheader("Observations by activity")
    st.plotly_chart(common.style_figure(fig, 340), use_container_width=True)

with tab_where:
    left, right = st.columns(2)
    loc = df.groupby(df["location"].fillna("Not specified")).size().reset_index(name="count")
    loc = loc.sort_values("count")
    fig = px.bar(loc, x="count", y="location", orientation="h", text="count",
                 color_discrete_sequence=["#EF6C00"])
    left.subheader("Top locations")
    left.plotly_chart(common.style_figure(fig), use_container_width=True)
    comp = df.groupby(["company_name", "risk_level"]).size().reset_index(name="count")
    fig = px.bar(comp, x="company_name", y="count", color="risk_level", color_discrete_map=common.RISK_COLORS)
    right.subheader("Observations by company")
    right.plotly_chart(common.style_figure(fig), use_container_width=True)
    heat = df.pivot_table(index="location", columns="risk_level", values="description",
                          aggfunc="count", fill_value=0)
    if not heat.empty:
        fig = px.imshow(heat, text_auto=True, aspect="auto", color_continuous_scale="YlOrRd")
        st.subheader("Location × risk heatmap")
        st.plotly_chart(common.style_figure(fig, 340), use_container_width=True)

with tab_trend:
    dated = df.dropna(subset=["date_recorded"])
    granularity = st.radio("Group by", ["Week", "Month"], horizontal=True, index=1)
    freq = "W" if granularity == "Week" else "M"
    series = (
        dated.groupby([dated["date_recorded"].dt.to_period(freq).dt.start_time, "risk_level"])
        .size().reset_index(name="count")
    )
    series.columns = ["period", "risk_level", "count"]
    fig = px.bar(series, x="period", y="count", color="risk_level", color_discrete_map=common.RISK_COLORS)
    st.subheader(f"Observations per {granularity.lower()}")
    st.plotly_chart(common.style_figure(fig), use_container_width=True)

with tab_records:
    st.caption("Click a column header to sort. Use the sidebar filters to narrow the log.")
    cols = ["date_recorded", "company_name", "location", "category", "risk_level", "observation_type",
            "activity_type", "description", "action_taken"]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    common.download_button(df[cols], "safety_observations")
