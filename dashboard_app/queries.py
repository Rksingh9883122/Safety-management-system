import sqlite3
import pandas as pd
import json
import os

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'hse_data.db')

def get_incidents_data(organization_id):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    query = """
    SELECT i.report_date, i.event_time, i.incident_type, i.status,
           i.employment_type, i.activity_type, i.body_part, i.root_cause,
           i.employee_age, i.description, i.corrective_action,
           c.company_name
    FROM incidents i
    JOIN contractors c ON i.contractor_id = c.contractor_id
    WHERE i.organization_id = ?
    """
    df = pd.read_sql_query(query, conn, params=(organization_id,))
    conn.close()
    return df

def get_observations_data(organization_id):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    query = """
    SELECT o.date_recorded, o.location, o.activity_type, o.observation_type,
           o.category, o.risk_level, o.description, o.action_taken,
           c.company_name
    FROM safety_observations o
    LEFT JOIN contractors c ON o.contractor_id = c.contractor_id
    WHERE o.organization_id = ?
    ORDER BY o.date_recorded DESC
    """
    df = pd.read_sql_query(query, conn, params=(organization_id,))
    conn.close()
    return df

def get_inspections_data(organization_id):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    query = """
    SELECT h.inspection_date, h.trade_type, h.inspector_name,
           h.compliance_score, h.checklist_json, h.major_findings,
           c.company_name
    FROM hse_inspections h
    LEFT JOIN contractors c ON h.contractor_id = c.contractor_id
    WHERE h.organization_id = ?
    ORDER BY h.inspection_date DESC
    """
    df = pd.read_sql_query(query, conn, params=(organization_id,))
    conn.close()
    return df

def get_monthly_statistics_data(organization_id):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    query = """
    SELECT m.report_month, m.data_json, c.company_name
    FROM monthly_statistics m
    LEFT JOIN contractors c ON m.contractor_id = c.contractor_id
    WHERE m.organization_id = ?
    ORDER BY m.report_month DESC
    """
    rows = pd.read_sql_query(query, conn, params=(organization_id,))
    conn.close()
    reports = []
    for row in rows.to_dict(orient="records"):
        report = json.loads(row.pop("data_json"))
        reports.append({**row, **report})
    return pd.DataFrame(reports)

def get_training_records_data(organization_id):
    conn = sqlite3.connect(DB_PATH, timeout=30)
    query = """
    SELECT t.record_json, t.updated_at, c.company_name
    FROM training_records t
    LEFT JOIN contractors c ON t.contractor_id = c.contractor_id
    WHERE t.organization_id = ?
    ORDER BY t.updated_at DESC
    """
    rows = pd.read_sql_query(query, conn, params=(organization_id,))
    conn.close()
    records = []
    for row in rows.to_dict(orient="records"):
        record = json.loads(row.pop("record_json"))
        records.append({**row, **record})
    return pd.DataFrame(records)