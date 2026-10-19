import sqlite3
import os

# Ensure the database is created in the same directory as this script
db_path = os.path.join(os.path.dirname(__file__), 'hse_data.db')

def initialize_database():
    # Connect to the SQLite database (this creates the file if it doesn't exist)
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Execute the SQL commands to create the tables
    cursor.executescript('''
        CREATE TABLE IF NOT EXISTS organizations (
            organization_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_name TEXT NOT NULL,
            organization_type TEXT NOT NULL,
            industry TEXT NOT NULL,
            project_name TEXT NOT NULL,
            project_type TEXT NOT NULL,
            project_location TEXT NOT NULL,
            project_start_date DATE,
            project_end_date DATE,
            website TEXT,
            created_at TEXT NOT NULL,
            is_legacy INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            full_name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'subcontractor')),
            contractor_id INTEGER,
            module_access TEXT NOT NULL DEFAULT '[]',
            email_verified_at TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (organization_id) REFERENCES organizations (organization_id)
        );

        CREATE TABLE IF NOT EXISTS email_verification_tokens (
            token_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS password_reset_tokens (
            token_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            used_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            email TEXT PRIMARY KEY COLLATE NOCASE,
            failure_count INTEGER NOT NULL DEFAULT 0,
            locked_until TEXT,
            updated_at TEXT NOT NULL
        );

        -- Contractors Table
        CREATE TABLE IF NOT EXISTS contractors (
            contractor_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER,
            company_name TEXT NOT NULL,
            trade_type TEXT,
            contractor_type TEXT NOT NULL DEFAULT 'Contractor',
            parent_contractor_id INTEGER,
            FOREIGN KEY (parent_contractor_id) REFERENCES contractors (contractor_id)
        );

        -- Incidents & Near Misses
        CREATE TABLE IF NOT EXISTS incidents (
            incident_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER,
            contractor_id INTEGER,
            report_date DATE,
            event_time TEXT,
            incident_type TEXT, -- 'LTI', 'Medical Treatment', 'First Aid', 'Near Miss'
            employee_age INTEGER,
            employment_date DATE,
            employment_type TEXT,
            activity_type TEXT,
            pre_incident_activity TEXT,
            ptw_reference TEXT, -- Link to Permit-to-Work if applicable
            description TEXT,
            injury_details TEXT,
            body_part TEXT,
            root_cause TEXT,
            immediate_causes TEXT,
            underlying_causes TEXT,
            corrective_action TEXT,
            status TEXT, -- 'Open', 'Closed'
            FOREIGN KEY (contractor_id) REFERENCES contractors (contractor_id)
        );

        -- Safety Observations
        CREATE TABLE IF NOT EXISTS safety_observations (
            observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER,
            contractor_id INTEGER,
            date_recorded DATE,
            location TEXT,
            category TEXT, -- 'Unsafe Act', 'Unsafe Condition', 'Positive Behavior'
            description TEXT,
            risk_level TEXT, -- 'High', 'Medium', 'Low'
            action_taken TEXT,
            FOREIGN KEY (contractor_id) REFERENCES contractors (contractor_id)
        );

        -- Inspections & Walkthroughs
        CREATE TABLE IF NOT EXISTS hse_inspections (
            inspection_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER,
            contractor_id INTEGER,
            inspection_date DATE,
            location TEXT,
            inspector_name TEXT,
            trade_type TEXT,
            checklist_json TEXT,
            compliance_score REAL, -- Percentage score from the walkthrough
            major_findings TEXT,
            FOREIGN KEY (contractor_id) REFERENCES contractors (contractor_id)
        );

        CREATE TABLE IF NOT EXISTS dashboard_access (
            access_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER,
            display_name TEXT NOT NULL,
            email TEXT NOT NULL,
            role TEXT NOT NULL CHECK (role IN ('admin', 'viewer')),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            revoked_at TEXT,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS dashboard_settings (
            setting_key TEXT PRIMARY KEY,
            setting_value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS organization_settings (
            organization_id INTEGER NOT NULL,
            setting_key TEXT NOT NULL,
            setting_value TEXT NOT NULL,
            PRIMARY KEY (organization_id, setting_key),
            FOREIGN KEY (organization_id) REFERENCES organizations (organization_id)
        );

        CREATE TABLE IF NOT EXISTS monthly_statistics (
            statistics_id INTEGER PRIMARY KEY AUTOINCREMENT,
            organization_id INTEGER NOT NULL,
            contractor_id INTEGER,
            report_month TEXT NOT NULL,
            data_json TEXT NOT NULL,
            submitted_by INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (organization_id, contractor_id, report_month),
            FOREIGN KEY (organization_id) REFERENCES organizations (organization_id),
            FOREIGN KEY (contractor_id) REFERENCES contractors (contractor_id)
        );

        CREATE TABLE IF NOT EXISTS training_records (
            training_record_id TEXT NOT NULL,
            organization_id INTEGER NOT NULL,
            contractor_id INTEGER,
            record_json TEXT NOT NULL,
            created_by INTEGER,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (organization_id, training_record_id),
            FOREIGN KEY (organization_id) REFERENCES organizations (organization_id),
            FOREIGN KEY (contractor_id) REFERENCES contractors (contractor_id)
        );
    ''')

    users_schema = cursor.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'users'"
    ).fetchone()
    if users_schema and "('admin')" in users_schema[0]:
        cursor.execute('PRAGMA foreign_keys = OFF')
        cursor.execute('''
            CREATE TABLE users_new (
                user_id INTEGER PRIMARY KEY AUTOINCREMENT,
                organization_id INTEGER NOT NULL,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL CHECK (role IN ('admin', 'subcontractor')),
                contractor_id INTEGER,
                module_access TEXT NOT NULL DEFAULT '[]',
                email_verified_at TEXT,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                FOREIGN KEY (organization_id) REFERENCES organizations (organization_id),
                FOREIGN KEY (contractor_id) REFERENCES contractors (contractor_id)
            )
        ''')
        cursor.execute('''
            INSERT INTO users_new (
                user_id, organization_id, full_name, email, password_hash, role,
                email_verified_at, is_active, created_at
            )
            SELECT user_id, organization_id, full_name, email, password_hash, role,
                   email_verified_at, is_active, created_at
            FROM users
        ''')
        cursor.execute('DROP TABLE users')
        cursor.execute('ALTER TABLE users_new RENAME TO users')
        cursor.execute('PRAGMA foreign_keys = ON')

    def add_missing_columns(table, columns):
        existing = {row[1] for row in cursor.execute(f'PRAGMA table_info({table})')}
        for column, column_type in columns.items():
            if column not in existing:
                cursor.execute(
                    f'ALTER TABLE {table} ADD COLUMN {column} {column_type}'
                )

    contractor_columns = {
        row[1] for row in cursor.execute('PRAGMA table_info(contractors)')
    }
    for column, column_type in {
        'contractor_type': "TEXT NOT NULL DEFAULT 'Contractor'",
        'parent_contractor_id': 'INTEGER',
    }.items():
        if column not in contractor_columns:
            cursor.execute(
                f'ALTER TABLE contractors ADD COLUMN {column} {column_type}'
            )
    add_missing_columns('contractors', {'organization_id': 'INTEGER'})

    # Add incident-report fields to databases initialized by older versions.
    incident_columns = {
        'event_time': 'TEXT',
        'employee_age': 'INTEGER',
        'employment_date': 'DATE',
        'employment_type': 'TEXT',
        'activity_type': 'TEXT',
        'pre_incident_activity': 'TEXT',
        'injury_details': 'TEXT',
        'body_part': 'TEXT',
        'immediate_causes': 'TEXT',
        'underlying_causes': 'TEXT',
    }
    existing_columns = {
        row[1] for row in cursor.execute('PRAGMA table_info(incidents)')
    }
    for column, column_type in incident_columns.items():
        if column not in existing_columns:
            cursor.execute(
                f'ALTER TABLE incidents ADD COLUMN {column} {column_type}'
            )

    add_missing_columns('incidents', {'organization_id': 'INTEGER'})
    add_missing_columns('safety_observations', {'organization_id': 'INTEGER'})
    add_missing_columns('safety_observations', {'location': 'TEXT'})
    add_missing_columns('safety_observations', {
        'activity_type': 'TEXT',
        'observation_type': 'TEXT',
    })
    add_missing_columns('hse_inspections', {
        'organization_id': 'INTEGER',
        'trade_type': 'TEXT',
        'checklist_json': 'TEXT',
    })
    add_missing_columns('dashboard_access', {'organization_id': 'INTEGER'})
    add_missing_columns('users', {
        'contractor_id': 'INTEGER',
        'module_access': "TEXT NOT NULL DEFAULT '[]'",
    })

    # Preserve existing single-workspace records in an isolated legacy tenant.
    cursor.execute('''
        INSERT INTO organizations (
            organization_name, organization_type, industry, project_name,
            project_type, project_location, created_at, is_legacy
        )
        SELECT 'Legacy workspace', 'Other', 'Other', 'Existing project data',
               'Other', 'Not specified', CURRENT_TIMESTAMP, 1
        WHERE NOT EXISTS (SELECT 1 FROM organizations WHERE is_legacy = 1)
    ''')
    legacy_organization_id = cursor.execute(
        'SELECT organization_id FROM organizations WHERE is_legacy = 1'
    ).fetchone()[0]
    for table in (
        'contractors', 'incidents', 'safety_observations',
        'hse_inspections', 'dashboard_access',
    ):
        cursor.execute(
            f'UPDATE {table} SET organization_id = ? WHERE organization_id IS NULL',
            (legacy_organization_id,),
        )

    cursor.execute('''
        INSERT OR IGNORE INTO dashboard_settings (setting_key, setting_value)
        VALUES ('dashboard_enabled', 'true')
    ''')
    legacy_setting = cursor.execute('''
        SELECT setting_value FROM dashboard_settings
        WHERE setting_key = 'dashboard_enabled'
    ''').fetchone()
    cursor.execute('''
        INSERT OR IGNORE INTO organization_settings (
            organization_id, setting_key, setting_value
        ) VALUES (?, 'dashboard_enabled', ?)
    ''', (legacy_organization_id, legacy_setting[0]))

    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_contractors_organization
        ON contractors (organization_id, company_name)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_incidents_organization
        ON incidents (organization_id, report_date)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_dashboard_access_organization
        ON dashboard_access (organization_id, token_hash)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_users_organization
        ON users (organization_id, role, is_active)
    ''')
    cursor.execute('''
        CREATE INDEX IF NOT EXISTS idx_training_records_organization
        ON training_records (organization_id, updated_at)
    ''')

    # Save changes and close the connection
    conn.commit()
    conn.close()
    print(f"Database successfully initialized at: {db_path}")

if __name__ == '__main__':
    initialize_database()