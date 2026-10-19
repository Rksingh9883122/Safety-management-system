import pandas as pd
import plotly.express as px
import streamlit as st

import common
from queries import get_training_records_data

st.set_page_config(page_title="Training Dashboard", page_icon="🎓", layout="wide")
access = common.require_access()
common.sidebar_header(access)
common.hero("Training Program Dashboard", "Completion, coverage and competency gaps across modules and teams",
            ("#2E7D32", "#00A8C6"))

df = get_training_records_data(access["organization_id"])
st.sidebar.header("Filters")
df = common.filter_companies(df, common.company_scope(access))
if df.empty:
    st.info("No training records have been submitted yet.")
    st.stop()

for column in ("module", "department", "role", "status", "employee", "completionDate", "vertical"):
    if column not in df:
        df[column] = None
df["completionDate"] = pd.to_datetime(df["completionDate"].replace("", None), errors="coerce")
df = common.multiselect_filter(df, "module", "Training module")
df = common.multiselect_filter(df, "department", "Department")
df = common.multiselect_filter(df, "role", "Role")
df = common.multiselect_filter(df, "status", "Status")
df = common.multiselect_filter(df, "company_name", "Company")
search = st.sidebar.text_input("Search employee")
if search:
    df = df[df["employee"].fillna("").str.contains(search, case=False)]
if df.empty:
    st.warning("No records match the selected filters.")
    st.stop()

total = len(df)
completed = int((df["status"] == "Completed").sum())
pending = total - completed
trained = df.loc[df["status"] == "Completed", "employee"].nunique()
c1, c2, c3, c4, c5 = st.columns(5)
common.kpi(c1, "Training records", total, "in current view", "#1565C0")
common.kpi(c2, "Completed", completed, f"{completed / total:.0%} completion", "#43A047")
common.kpi(c3, "Outstanding", pending, "not completed", "#D32F2F" if pending else "#43A047")
common.kpi(c4, "Employees trained", trained, f"of {df['employee'].nunique()} people", "#00A8C6")
common.kpi(c5, "Modules covered", df["module"].nunique(), "distinct programs", "#8E24AA")
st.write("")

tab_overview, tab_gap, tab_trend, tab_records = st.tabs(
    ["Overview", "Gaps & compliance", "Completion trend", "Records"]
)

with tab_overview:
    left, right = st.columns(2)
    status_counts = df["status"].fillna("Unknown").value_counts().reset_index()
    status_counts.columns = ["status", "records"]
    fig = px.pie(status_counts, names="status", values="records", hole=0.55,
                 color="status", color_discrete_map={"Completed": "#43A047", "Not Started": "#D32F2F",
                                                     "In Progress": "#FFB300"})
    left.subheader("Status split")
    left.plotly_chart(common.style_figure(fig), use_container_width=True)
    by_module = df.groupby("module").size().reset_index(name="records").sort_values("records")
    fig = px.bar(by_module, x="records", y="module", orientation="h", text="records",
                 color_discrete_sequence=[common.PALETTE[0]])
    right.subheader("Records by module")
    right.plotly_chart(common.style_figure(fig), use_container_width=True)
    dept = df.groupby(["department", "status"]).size().reset_index(name="records")
    fig = px.bar(dept, x="department", y="records", color="status", barmode="stack",
                 color_discrete_map={"Completed": "#43A047", "Not Started": "#D32F2F"})
    st.subheader("Department progress")
    st.plotly_chart(common.style_figure(fig), use_container_width=True)

with tab_gap:
    rate = (
        df.assign(done=df["status"] == "Completed")
        .groupby("module")["done"].agg(["mean", "sum", "count"]).reset_index()
    )
    rate.columns = ["module", "completion_rate", "completed", "records"]
    rate = rate.sort_values("completion_rate")
    fig = px.bar(rate, x="completion_rate", y="module", orientation="h",
                 text=rate["completion_rate"].map("{:.0%}".format),
                 color="completion_rate", color_continuous_scale=["#D32F2F", "#FFB300", "#43A047"],
                 range_color=(0, 1))
    fig.update_xaxes(tickformat=".0%", range=[0, 1.05])
    st.subheader("Completion rate by module")
    st.plotly_chart(common.style_figure(fig, 380), use_container_width=True)
    matrix = df.assign(done=(df["status"] == "Completed").astype(int)).pivot_table(
        index="module", columns="department", values="done", aggfunc="mean"
    )
    if not matrix.empty:
        fig = px.imshow(matrix, text_auto=".0%", aspect="auto", zmin=0, zmax=1,
                        color_continuous_scale=["#D32F2F", "#FFB300", "#43A047"])
        st.subheader("Module × department completion heatmap")
        st.plotly_chart(common.style_figure(fig, 380), use_container_width=True)
    st.subheader("Outstanding training")
    outstanding = df[df["status"] != "Completed"][["employee", "role", "department", "module", "status", "company_name"]]
    st.dataframe(outstanding, use_container_width=True, hide_index=True)

with tab_trend:
    dated = df.dropna(subset=["completionDate"])
    if dated.empty:
        st.info("No completion dates recorded for the selected records.")
    else:
        monthly = dated.groupby(dated["completionDate"].dt.to_period("M").dt.to_timestamp()).size()
        monthly = monthly.reset_index(name="completions")
        monthly.columns = ["month", "completions"]
        monthly["cumulative"] = monthly["completions"].cumsum()
        fig = px.bar(monthly, x="month", y="completions", color_discrete_sequence=["#00A8C6"])
        fig.add_scatter(x=monthly["month"], y=monthly["cumulative"], name="Cumulative", mode="lines+markers",
                        line=dict(color="#1565C0", width=3))
        st.subheader("Training completions per month")
        st.plotly_chart(common.style_figure(fig), use_container_width=True)

with tab_records:
    cols = [c for c in ("employee", "role", "department", "module", "status", "completionDate",
                        "company_name", "updated_at") if c in df]
    st.dataframe(df[cols], use_container_width=True, hide_index=True)
    common.download_button(df[cols], "training_records")
