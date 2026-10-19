import hashlib
import os
import sqlite3
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "database", "hse_data.db"
)

PALETTE = ["#1565C0", "#00A8C6", "#FF8F00", "#D32F2F", "#43A047", "#8E24AA", "#546E7A"]
RISK_COLORS = {"Low": "#43A047", "Medium": "#FFB300", "High": "#D32F2F"}

_CSS = """
<style>
.block-container { padding-top: 1.4rem; }
.dash-hero {
    background: linear-gradient(120deg, %(a)s, %(b)s);
    color: #fff; padding: 20px 26px; border-radius: 14px; margin-bottom: 18px;
}
.dash-hero h1 { margin: 0; font-size: 1.7rem; color: #fff; }
.dash-hero p { margin: 4px 0 0; opacity: .9; }
.kpi {
    background: #fff; border-radius: 12px; padding: 14px 16px;
    border: 1px solid #e3e8ee; border-top: 4px solid var(--c);
    box-shadow: 0 2px 6px rgba(20, 40, 80, .06);
}
.kpi .label { color: #667085; font-size: .78rem; text-transform: uppercase; letter-spacing: .04em; }
.kpi .value { font-size: 1.9rem; font-weight: 700; color: #1d2939; line-height: 1.2; }
.kpi .hint { color: #98a2b3; font-size: .78rem; }
</style>
"""


def kpi(column, label, value, hint="", color="#1565C0"):
    column.markdown(
        f'<div class="kpi" style="--c:{color}"><div class="label">{label}</div>'
        f'<div class="value">{value}</div><div class="hint">{hint}&nbsp;</div></div>',
        unsafe_allow_html=True,
    )


def hero(title, subtitle, colors=("#1565C0", "#00A8C6")):
    st.markdown(_CSS % {"a": colors[0], "b": colors[1]}, unsafe_allow_html=True)
    st.markdown(
        f'<div class="dash-hero"><h1>{title}</h1><p>{subtitle}</p></div>',
        unsafe_allow_html=True,
    )


def require_access():
    """Validate the administrator-issued token and keep it for page navigation."""
    token = str(st.query_params.get("access", "")) or st.session_state.get("access_token", "")
    if not token:
        st.error("Dashboard access requires a valid administrator-issued link.")
        st.stop()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    access = conn.execute(
        """
        SELECT organization_id, display_name, email, role, expires_at, revoked_at
        FROM dashboard_access
        WHERE token_hash = ? AND organization_id IS NOT NULL
        """,
        (hashlib.sha256(token.encode("utf-8")).hexdigest(),),
    ).fetchone()
    setting = conn.execute(
        """
        SELECT setting_value FROM organization_settings
        WHERE organization_id = ? AND setting_key = 'dashboard_enabled'
        """,
        (access["organization_id"] if access else -1,),
    ).fetchone()
    conn.close()
    if not access:
        st.error("This dashboard access link is invalid or has been revoked.")
        st.stop()
    if access["revoked_at"]:
        st.error("This dashboard access link has been revoked.")
        st.stop()
    if datetime.fromisoformat(access["expires_at"]) <= datetime.now(timezone.utc):
        st.error("This dashboard access link has expired.")
        st.stop()
    if (not setting or setting["setting_value"] != "true") and access["role"] != "admin":
        st.error("Dashboard access has been disabled by the administrator.")
        st.stop()
    st.session_state["access_token"] = token
    return access


def sidebar_header(access):
    st.sidebar.caption(f"Signed in as {access['display_name']} ({access['role']})")
    if st.sidebar.button("Refresh data", use_container_width=True):
        st.rerun()


def company_scope(access):
    """Sidebar scope selector. Returns a list of company names, or None for all."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT contractor_id, company_name, contractor_type, parent_contractor_id
        FROM contractors WHERE organization_id = ? ORDER BY company_name
        """,
        (access["organization_id"],),
    ).fetchall()
    conn.close()
    options = {"Entire organization": None}
    for row in rows:
        if row["contractor_type"] == "Contractor":
            options[f"{row['company_name']} + its subcontractors"] = [row["company_name"]] + [
                sub["company_name"] for sub in rows
                if sub["parent_contractor_id"] == row["contractor_id"]
            ]
    for row in rows:
        suffix = " (subcontractor)" if row["contractor_type"] == "Subcontractor" else " (contractor only)"
        options[row["company_name"] + suffix] = [row["company_name"]]
    choice = st.sidebar.selectbox("Company scope", list(options))
    return options[choice]


def filter_companies(df, names):
    if names is None or df.empty or "company_name" not in df:
        return df
    return df[df["company_name"].isin(names)]


def date_range_filter(df, column, label="Date range"):
    """Sidebar date filter. Adds a parsed datetime column and returns the filtered frame."""
    if df.empty or column not in df:
        return df
    df = df.copy()
    df[column] = pd.to_datetime(df[column], errors="coerce")
    valid = df[column].dropna()
    if valid.empty:
        return df
    low, high = valid.min().date(), valid.max().date()
    picked = st.sidebar.date_input(label, (low, high), min_value=low, max_value=high)
    if isinstance(picked, tuple) and len(picked) == 2:
        start, end = pd.Timestamp(picked[0]), pd.Timestamp(picked[1])
        df = df[(df[column] >= start) & (df[column] <= end + pd.Timedelta(days=1))]
    return df


def multiselect_filter(df, column, label):
    if df.empty or column not in df:
        return df
    options = sorted(df[column].dropna().astype(str).unique())
    chosen = st.sidebar.multiselect(label, options)
    return df[df[column].astype(str).isin(chosen)] if chosen else df


def style_figure(fig, height=360):
    fig.update_layout(
        height=height, margin=dict(l=10, r=10, t=40, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        legend=dict(orientation="h", y=-0.2),
        font=dict(family="Segoe UI, Arial", size=13),
    )
    return fig


def download_button(df, name):
    st.download_button(
        "Download filtered data (CSV)", df.to_csv(index=False).encode("utf-8"),
        file_name=f"{name}.csv", mime="text/csv",
    )
