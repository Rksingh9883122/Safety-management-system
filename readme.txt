HSE Management System
=====================

Local development
-----------------
    .\.venv\Scripts\Activate.ps1
    pip install -r requirements.txt
    python run.py

Portal:    http://localhost:5000
Dashboard: http://localhost:8501

Organization registration
-------------------------
Open /register in the portal. Registration collects organization and project
details, a named administrator, a work email address, and a password. The
administrator account remains inactive until the work email is verified. The
verification link expires after 30 minutes and is single-use. A resend page is
available from the sign-in page.

An organization administrator can send a password-reset link to any active,
email-verified account in that organization from the Organization User Access
table. The single-use link expires after 30 minutes; the user chooses their own
new password. Up to three reset emails can be sent to a user per hour.
Password-reset email uses the configured SMTP sender.

The portal loads a root-level `.env` file when it starts. For local development,
the existing Flask-Mail settings (`MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`,
`MAIL_PASSWORD`, and `MAIL_DEFAULT_SENDER`) are supported. The local activation
URL defaults to `http://127.0.0.1:5000`; keep the portal running on that address
while testing links. Environment variables take precedence over `.env`.

For deployment, configure these application settings through the environment
or a protected `.env` file:

    HSE_SMTP_HOST=smtp.gmail.com
    HSE_SMTP_PORT=587
    HSE_SMTP_USER=rksingh9883122@gmail.com
    HSE_SMTP_PASSWORD=<Google App Password>
    HSE_EMAIL_FROM=rksingh9883122@gmail.com
    HSE_PUBLIC_URL=https://hse.example.com
    HSE_DASHBOARD_URL=https://dashboard.example.com

Gmail SMTP uses STARTTLS on port 587. Create a Google App Password for the
sender account and supply it only through a protected environment secret or
secret manager. Do not commit the password to source control or paste it into
chat. The sender address defaults to rksingh9883122@gmail.com. In production,
registration and subcontractor invitations remain unavailable unless the
sender password and public HTTPS URL are configured.

Production deployment
---------------------
Use a unique generated secret key and an HTTPS reverse proxy. In production,
the application checks the required settings and refuses to start with an
insecure or incomplete configuration:

    HSE_ENV=production
    HSE_SECRET_KEY=<long random secret>
    HSE_COOKIE_SECURE=true
    HSE_SMTP_STARTTLS=true

Set HSE_HOST=127.0.0.1 and HSE_PORT=5000 to bind the Waitress portal to a
private interface behind the reverse proxy. Configure the proxy and Streamlit
deployment so both public URLs use HTTPS. Set HSE_PUBLIC_URL and
HSE_DASHBOARD_URL to those externally reachable addresses. Keep SMTP, database
files, and application secrets outside the public web root.

Organizations have tenant-scoped project data, contractors, dashboard settings,
and dashboard grants. Passwords are stored as Werkzeug scrypt hashes. Email
verification tokens and dashboard access tokens are stored as hashes. Existing
single-workspace records are preserved under an isolated legacy workspace by
the database migration. If upgrading a deployment that used the previous
shared administrator password, it can temporarily access only that isolated
legacy workspace by setting HSE_ADMIN_PASSWORD and HSE_ADMIN_EMAIL. New
organization workspaces must use their verified email/password accounts.

The administrator can add contractors and subcontractors, invite named users
for a subcontractor, select their allowed modules (incident logging, safety
observations, site inspections, monthly statistics, and training performance),
change those permissions later, or revoke the account. Activation links are
single-use and expire after 30 minutes. Subcontractor submissions are recorded
against their assigned company and are scoped to the administrator's
organization. Training records are stored centrally; the training-hours
reference mapping remains in the browser for local workbook calculations.
The administrator can generate an organization-specific public safety
observation QR code. Scanning it opens the observation form without sign-in and
allows submissions only to that organization's observation records; it does
not grant dashboard or administrative access. The code is a bearer link:
anyone who obtains it can submit reports. Regenerating it invalidates the
previous code. Set `HSE_PUBLIC_URL` to the externally reachable HTTPS portal
URL before generating a code for a deployed site.
Dashboard links issued by the administrator show incidents, observations,
inspections (including checklist results and compliance score), monthly
statistics, and training records for that organization. Observation locations
and the contractor/subcontractor attribution on inspections and observations
are stored with each submission.

Dashboard invitation URLs are bearer credentials: anyone with a link can use
it until it expires or is revoked. Share links privately. Because this project
currently uses SQLite and runs the dashboard separately in Streamlit, deploy
as a single application node with protected persistent storage and backups.
For multi-node/high-availability production, migrate the database to a
server-grade database and place both applications behind an authenticated
reverse proxy. Review data-retention, privacy, backup, and incident-response
requirements before handling real worker information.
