import importlib

try:
    qrcode = importlib.import_module('qrcode')
    svg_image = importlib.import_module('qrcode.image.svg')
    dotenv = importlib.import_module('dotenv')
    flask = importlib.import_module('flask')
except ModuleNotFoundError as exc:
    if exc.name == 'qrcode':
        raise RuntimeError(
            "qrcode is required to create observation QR codes. "
            "Install it with: python -m pip install -r requirements.txt"
        ) from exc
    if exc.name == 'dotenv':
        raise RuntimeError(
            "python-dotenv is required to load local mail settings. "
            "Install it with: python -m pip install -r requirements.txt"
        ) from exc
    if exc.name != 'flask':
        raise
    raise RuntimeError(
        "Flask is required to run this app. Install it with: python -m pip install Flask"
    ) from exc

import os
import base64
from io import BytesIO

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
dotenv.load_dotenv(os.path.join(PROJECT_ROOT, '.env'), override=False)

for app_setting, local_setting in (
    ('HSE_SMTP_HOST', 'MAIL_SERVER'),
    ('HSE_SMTP_PORT', 'MAIL_PORT'),
    ('HSE_SMTP_USER', 'MAIL_USERNAME'),
    ('HSE_SMTP_PASSWORD', 'MAIL_PASSWORD'),
    ('HSE_EMAIL_FROM', 'MAIL_DEFAULT_SENDER'),
):
    if not os.environ.get(app_setting) and os.environ.get(local_setting):
        setting_value = os.environ[local_setting]
        if app_setting == 'HSE_SMTP_PASSWORD':
            setting_value = setting_value.replace(' ', '')
        os.environ[app_setting] = setting_value

if (
    not os.environ.get('HSE_PUBLIC_URL')
    and os.environ.get('HSE_ENV', '').lower() != 'production'
):
    os.environ['HSE_PUBLIC_URL'] = 'http://127.0.0.1:5000'

Flask = flask.Flask
render_template = flask.render_template
request = flask.request
redirect = flask.redirect
url_for = flask.url_for
session = flask.session
abort = flask.abort
flash = flask.flash
import sqlite3
import json
import hashlib
import hmac
import math
import re
import secrets
import smtplib
import ssl
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps
from urllib.parse import urlencode, urlsplit
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
DEFAULT_EMAIL_FROM = 'rksingh9883122@gmail.com'
DEFAULT_SMTP_HOST = 'smtp.gmail.com'

OBSERVATION_TAXONOMY = {
    'Oil & Gas': {
        'Hot work and welding': [
            'Hot-work permit, gas test, or fire watch',
            'Combustibles, ignition sources, or fire protection',
            'Welding equipment, cylinders, or hoses',
            'Welding fume, screens, or PPE',
        ],
        'Process operations and line breaking': [
            'Permit, isolation, or lockout/tagout',
            'Gas detection, leak, or process alarm',
            'Pressure release, line of fire, or stored energy',
            'Chemical exposure, spill, or containment',
        ],
        'Confined-space entry': [
            'Entry permit, isolation, or atmospheric testing',
            'Ventilation, gas monitoring, or communication',
            'Attendant, rescue readiness, or retrieval equipment',
            'PPE, access, or unauthorized entry',
        ],
        'Drilling and well servicing': [
            'Well control, barriers, or pressure equipment',
            'Red zone, line of fire, or dropped objects',
            'Rig floor, tubular handling, or lifting',
            'Gas detection, alarms, or emergency escape',
        ],
        'Lifting and crane operations': [
            'Lift plan, load rating, or ground setup',
            'Rigging gear, lifting points, or load security',
            'Suspended load, exclusion zone, or signaling',
            'Weather, visibility, or overhead obstruction',
        ],
        'Pipeline and excavation': [
            'Utility locating, ground disturbance, or excavation permit',
            'Trench support, edge protection, or safe access',
            'Pipe handling, lifting, or stored energy',
            'Pressure test, leak, spill, or environmental control',
        ],
        'Electrical work and LOTO': [
            'Isolation, lockout/tagout, or test-before-touch',
            'Arc-flash boundary, electrical PPE, or live work',
            'Temporary power, cable condition, or grounding',
            'Electrical equipment, panel access, or unauthorized work',
        ],
        'Working at height and scaffolding': [
            'Fall protection, anchor, or edge/opening protection',
            'Scaffold tag, platform, access, or structural condition',
            'Ladder use, dropped objects, or exclusion zone',
            'Weather, rescue plan, or unsafe access',
        ],
    },
    'Construction': {
        'Earthworks and excavation': [
            'Utility locating, permit, or safe digging',
            'Trench protection, access/egress, or competent inspection',
            'Excavation edge, spoil placement, or falling materials',
            'Plant/pedestrian interface, reversing, or traffic control',
        ],
        'Lifting, rigging, and material handling': [
            'Lift plan, equipment capacity, or ground conditions',
            'Rigging inspection, load security, or competent signaling',
            'Suspended load, line of fire, or exclusion zone',
            'Manual handling, pinch points, or unstable materials',
        ],
        'Scaffolding and work at height': [
            'Fall arrest, guardrail, or unprotected edge/opening',
            'Scaffold condition, inspection tag, or safe access',
            'Ladder, mobile platform, or work positioning',
            'Dropped objects, tool tethering, or area below',
        ],
        'Concrete, formwork, and rebar': [
            'Formwork/falsework stability or inspection release',
            'Pump hose, coupling, pressure, or exclusion zone',
            'Rebar impalement, trip hazard, or access',
            'Cement exposure, wet work, or PPE',
        ],
        'Structural steel and mechanical erection': [
            'Erection sequence, temporary bracing, or structural stability',
            'Lifting point, rigging, or suspended load',
            'Working at height, fall protection, or dropped objects',
            'Hot work, connection quality, or fire prevention',
        ],
        'Roadworks and mobile plant': [
            'Traffic plan, barriers, or live-road exposure',
            'Plant inspection, operator authorization, or seat belt',
            'Blind spot, reversing, or pedestrian separation',
            'Ground stability, overhead services, or safe visibility',
        ],
        'Electrical installation': [
            'Isolation, lockout/tagout, or electrical testing',
            'Temporary power, RCD/GFCI, or damaged leads',
            'Exposed conductor, panel access, or guarding',
            'Cable routing, trip hazard, or work near other trades',
        ],
        'Demolition and dismantling': [
            'Demolition sequence, structural stability, or exclusion zone',
            'Utility isolation, hazardous material, or unexpected service',
            'Falling debris, dust, vibration, or public protection',
            'Plant operation, access, or emergency response',
        ],
    },
    'Manufacturing': {
        'Machine operation and production': [
            'Machine guarding, interlock, or emergency stop',
            'Entanglement, pinch point, or unsafe machine access',
            'Operating procedure, authorization, or unsafe bypass',
            'Noise, dust, fumes, or required PPE',
        ],
        'Maintenance and lockout/tagout': [
            'Energy isolation, personal lock, or zero-energy verification',
            'Stored energy, blocking, or unexpected startup',
            'Guard restoration, test run, or return to service',
            'Permit, group lockout, or shift handover',
        ],
        'Forklift and material handling': [
            'Vehicle condition, load capacity, or operator authorization',
            'Pedestrian separation, blind spot, or reversing',
            'Unstable load, stacking, racking, or dock edge',
            'Speed, seat belt, charging, or refueling',
        ],
        'Conveyor and automated equipment': [
            'Nip-point guarding, interlock, or emergency stop',
            'Jam clearing, isolation, or unexpected restart',
            'Robot/cobot cell access, light curtain, or exclusion zone',
            'Conveyor condition, housekeeping, or pedestrian crossing',
        ],
        'Welding and hot work': [
            'Hot-work authorization, fire watch, or extinguisher',
            'Welding leads, gas cylinders, or equipment condition',
            'Fume extraction, welding screen, or PPE',
            'Combustibles, sparks, or post-work fire check',
        ],
        'Chemical and process handling': [
            'Chemical identification, labeling, or safety data',
            'Transfer connection, leak, or secondary containment',
            'Ventilation, exposure controls, or chemical PPE',
            'Eyewash, shower, spill response, or incompatible storage',
        ],
        'Electrical and control panel work': [
            'Electrical isolation, lockout/tagout, or absence-of-voltage test',
            'Arc-flash boundary, electrical PPE, or exposed live parts',
            'Panel access, labeling, or unauthorized adjustment',
            'Temporary leads, grounding, or testing equipment',
        ],
        'Manual handling and ergonomics': [
            'Lifting posture, load weight, or mechanical aid',
            'Repetitive motion, workstation layout, or reach',
            'Team lift, carrying route, or obstruction',
            'Fatigue, task rotation, or ergonomic equipment',
        ],
    },
    'Other': {
        'General site activities': [
            'Permit, authorization, or task risk assessment',
            'PPE, training, or unsafe behavior',
            'Equipment, tools, guarding, or maintenance',
            'Work at height, lifting, or dropped objects',
            'Vehicle movement, access, or housekeeping',
            'Chemical, environmental, or emergency controls',
        ],
    },
}
configured_secret = os.environ.get('HSE_SECRET_KEY')
if os.environ.get('HSE_ENV', '').lower() == 'production' and not configured_secret:
    raise RuntimeError('HSE_SECRET_KEY must be set in production.')
if os.environ.get('HSE_ENV', '').lower() == 'production':
    required_production_settings = (
        'HSE_PUBLIC_URL', 'HSE_SMTP_PASSWORD',
    )
    missing_settings = [
        setting for setting in required_production_settings
        if not os.environ.get(setting)
    ]
    if missing_settings:
        raise RuntimeError(
            'Production configuration is missing: ' + ', '.join(missing_settings)
        )
    if not os.environ['HSE_PUBLIC_URL'].startswith('https://'):
        raise RuntimeError('HSE_PUBLIC_URL must use HTTPS in production.')
    if os.environ.get('HSE_COOKIE_SECURE', '').lower() != 'true':
        raise RuntimeError('Set HSE_COOKIE_SECURE=true in production.')
def load_persistent_secret_key():
    # Reuse one key across restarts so signed-in sessions and forms stay valid.
    key_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'database', '.flask_secret_key',
    )
    try:
        with open(key_path, encoding='utf-8') as key_file:
            stored = key_file.read().strip()
        if len(stored) >= 32:
            return stored
    except OSError:
        pass
    generated = secrets.token_hex(32)
    try:
        with open(key_path, 'w', encoding='utf-8') as key_file:
            key_file.write(generated)
    except OSError:
        pass
    return generated

app.secret_key = configured_secret or load_persistent_secret_key()
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=os.environ.get('HSE_COOKIE_SECURE', '').lower() == 'true',
    PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
    MAX_CONTENT_LENGTH=4 * 1024 * 1024,
)
if os.environ.get('HSE_ENV', '').lower() == 'production':
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# Path to the SQLite database
DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'database', 'hse_data.db')

def get_db_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    return conn

def current_organization_id():
    organization_id = session.get('organization_id')
    if not organization_id:
        return None
    return int(organization_id)

def resolve_contractor_id(submitted_id=None):
    organization_id = current_organization_id()
    if session.get('is_admin') or session.get('is_legacy_admin'):
        if not submitted_id:
            return None
        conn = get_db_connection()
        contractor = conn.execute('''
            SELECT contractor_id FROM contractors
            WHERE contractor_id = ? AND organization_id = ?
        ''', (submitted_id, organization_id)).fetchone()
        conn.close()
        if not contractor:
            abort(400, description='Select a contractor from your organization.')
        return contractor['contractor_id']

    conn = get_db_connection()
    user = conn.execute('''
        SELECT contractor_id FROM users
        WHERE user_id = ? AND organization_id = ? AND is_active = 1
    ''', (session.get('user_id'), organization_id)).fetchone()
    conn.close()
    if not user or user['contractor_id'] is None:
        abort(403, description='Your account is not linked to an active subcontractor.')
    if submitted_id and str(user['contractor_id']) != str(submitted_id):
        abort(400, description='You can only submit records for your assigned subcontractor.')
    return user['contractor_id']

def get_available_contractors():
    organization_id = current_organization_id()
    conn = get_db_connection()
    if session.get('is_admin') or session.get('is_legacy_admin'):
        contractors = conn.execute('''
            SELECT contractor_id, company_name, contractor_type
            FROM contractors WHERE organization_id = ? ORDER BY company_name
        ''', (organization_id,)).fetchall()
    else:
        contractors = conn.execute('''
            SELECT c.contractor_id, c.company_name, c.contractor_type
            FROM users u JOIN contractors c ON c.contractor_id = u.contractor_id
            WHERE u.user_id = ? AND u.organization_id = ? AND c.organization_id = ?
        ''', (
            session.get('user_id'), organization_id, organization_id,
        )).fetchall()
    conn.close()
    return contractors

def organization_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user_id = session.get('user_id')
        organization_id = current_organization_id()
        if not user_id or not organization_id:
            return redirect(url_for('admin_login', next=request.path))
        conn = get_db_connection()
        if session.get('is_legacy_admin'):
            user = conn.execute('''
                SELECT organization_id FROM organizations
                WHERE organization_id = ? AND is_legacy = 1
            ''', (organization_id,)).fetchone()
        else:
            user = conn.execute('''
                SELECT user_id FROM users
                WHERE user_id = ? AND organization_id = ?
                  AND email_verified_at IS NOT NULL AND is_active = 1
            ''', (user_id, organization_id)).fetchone()
        conn.close()
        if not user:
            session.clear()
            return redirect(url_for('admin_login', next=request.path))
        return view(*args, **kwargs)
    return wrapped

def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('is_admin'):
            return redirect(url_for('admin_login', next=request.path))
        return organization_required(view)(*args, **kwargs)
    return wrapped

def module_required(module_name):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get('user_id') or not current_organization_id():
                return redirect(url_for('admin_login', next=request.path))
            if session.get('is_admin') or session.get('is_legacy_admin'):
                return organization_required(view)(*args, **kwargs)
            @wraps(view)
            def permission_checked(*view_args, **view_kwargs):
                conn = get_db_connection()
                user = conn.execute('''
                    SELECT module_access FROM users
                    WHERE user_id = ? AND organization_id = ?
                      AND role = 'subcontractor' AND is_active = 1
                ''', (
                    session.get('user_id'), current_organization_id(),
                )).fetchone()
                conn.close()
                if not user or module_name not in json.loads(user['module_access'] or '[]'):
                    abort(403, description='Your account is not assigned to this module.')
                return view(*view_args, **view_kwargs)

            return organization_required(permission_checked)(*args, **kwargs)
        return wrapped
    return decorate

def csrf_token():
    token = session.get('_csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['_csrf_token'] = token
    return token

@app.context_processor
def inject_csrf_token():
    modules = {
        'incident_logging': 'incident',
        'safety_observations': 'observation',
        'site_inspections': 'inspection',
        'monthly_statistics': 'monthly_stats',
        'training_performance': 'training_performance',
    }
    if session.get('is_admin') or session.get('is_legacy_admin'):
        accessible = set(modules)
    else:
        accessible = set(session.get('module_access', []))
    return {
        'csrf_token': csrf_token,
        'accessible_modules': accessible,
        'module_endpoints': modules,
        'is_admin': bool(session.get('is_admin')),
        'authenticated': bool(session.get('user_id')),
    }

def require_valid_csrf():
    supplied = request.form.get('_csrf_token') or request.headers.get('X-CSRF-Token', '')
    expected = session.get('_csrf_token', '')
    if not expected or not hmac.compare_digest(supplied, expected):
        abort(400, description='Invalid or missing form security token.')

@app.before_request
def enforce_post_csrf():
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        if not session.get('_csrf_token') and request.endpoint != 'admin_login':
            flash('Your session expired. Please sign in again.', 'error')
            return redirect(url_for('admin_login'))
        require_valid_csrf()

@app.after_request
def add_security_headers(response):
    response.headers.setdefault('X-Content-Type-Options', 'nosniff')
    response.headers.setdefault('X-Frame-Options', 'DENY')
    response.headers.setdefault('Referrer-Policy', 'strict-origin-when-cross-origin')
    response.headers.setdefault('Permissions-Policy', 'camera=(), microphone=(), geolocation=()')
    if request.is_secure:
        response.headers.setdefault(
            'Strict-Transport-Security', 'max-age=31536000; includeSubDomains'
        )
    return response

def issue_dashboard_token(display_name, email, role, expires_in_hours):
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    expires_at = (now + timedelta(hours=expires_in_hours)).isoformat()
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO dashboard_access (
            organization_id, display_name, email, role, token_hash,
            expires_at, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    ''', (
        current_organization_id(),
        display_name,
        email,
        role,
        hashlib.sha256(token.encode('utf-8')).hexdigest(),
        expires_at,
        now.isoformat(),
    ))
    conn.commit()
    conn.close()
    dashboard_url = os.environ.get(
        'HSE_DASHBOARD_URL', 'http://127.0.0.1:8501'
    ).rstrip('/')
    return f'{dashboard_url}/?{urlencode({"access": token})}'

def send_account_email(
    email, full_name, token, invited=False, password_reset=False
):
    smtp_host = os.environ.get('HSE_SMTP_HOST', DEFAULT_SMTP_HOST)
    sender = os.environ.get('HSE_EMAIL_FROM', DEFAULT_EMAIL_FROM)
    public_url = os.environ.get('HSE_PUBLIC_URL', '').rstrip('/')
    if not smtp_host or not sender or not public_url or not os.environ.get('HSE_SMTP_PASSWORD'):
        raise RuntimeError(
            'Email delivery is not configured. Set HSE_PUBLIC_URL and '
            'HSE_SMTP_PASSWORD; Gmail SMTP is used by default.'
        )
    if not public_url_is_valid(public_url):
        raise RuntimeError('HSE_PUBLIC_URL must use HTTPS.')

    if password_reset:
        endpoint = 'reset_password'
        subject = 'Reset your HSE Management System password'
        instruction = 'Choose a new password for your HSE Management System account'
    elif invited:
        endpoint = 'activate_account'
        subject = 'You have been invited to your HSE project workspace'
        instruction = 'Set a password and activate your subcontractor access'
    else:
        endpoint = 'verify_email'
        subject = 'Verify your HSE Management System account'
        instruction = 'Verify your organization administrator email address'
    action_url = f'{public_url}{url_for(endpoint, token=token)}'
    message = EmailMessage()
    message['Subject'] = subject
    message['From'] = sender
    message['To'] = email
    message.set_content(
        f'Hello {full_name},\n\n'
        f'{instruction} by opening this '
        f'link:\n{action_url}\n\n'
        'The link expires in 30 minutes and can only be used once. '
        'If you did not register, ignore this message.'
    )

    smtp_port = int(os.environ.get('HSE_SMTP_PORT', '587'))
    with smtplib.SMTP(smtp_host, smtp_port, timeout=15) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp_user = os.environ.get('HSE_SMTP_USER', sender)
        smtp_password = os.environ.get('HSE_SMTP_PASSWORD')
        if not smtp_password:
            raise RuntimeError('HSE_SMTP_PASSWORD is required for Gmail SMTP.')
        smtp.login(smtp_user, smtp_password)
        smtp.send_message(message)

def public_url_is_valid(public_url=None):
    public_url = (public_url or os.environ.get('HSE_PUBLIC_URL', '')).rstrip('/')
    parsed_url = urlsplit(public_url)
    if parsed_url.scheme == 'https':
        return bool(parsed_url.hostname)
    local_development_url = (
        os.environ.get('HSE_ENV', '').lower() != 'production'
        and parsed_url.scheme == 'http'
        and parsed_url.hostname in {'localhost', '127.0.0.1', '::1'}
    )
    test_http_url = app.config['TESTING'] and parsed_url.scheme == 'http'
    return local_development_url or test_http_url

def email_delivery_configured():
    return bool(
        os.environ.get('HSE_SMTP_PASSWORD')
        and os.environ.get('HSE_PUBLIC_URL')
        and public_url_is_valid()
    )

@app.route('/')
def index():
    return render_template('home.html')

@app.route('/register', methods=['GET', 'POST'])
def register_organization():
    if request.method == 'GET':
        return render_template(
            'register.html',
            csrf_token=csrf_token(),
            registration_enabled=email_delivery_configured(),
        )

    ip_hash = hmac.new(
        app.secret_key.encode('utf-8'),
        request.remote_addr.encode('utf-8') if request.remote_addr else b'unknown',
        hashlib.sha256,
    ).hexdigest()
    now = datetime.now(timezone.utc)
    conn = get_db_connection()
    attempt = conn.execute(
        'SELECT failure_count, updated_at FROM login_attempts WHERE email = ?',
        ('registration:' + ip_hash,),
    ).fetchone()
    if attempt and datetime.fromisoformat(attempt['updated_at']) > now - timedelta(hours=1) and attempt['failure_count'] >= 5:
        conn.close()
        return render_template(
            'register.html', csrf_token=csrf_token(),
            registration_enabled=email_delivery_configured(),
            errors=['Registration limit reached. Try again later.'],
        ), 429
    if not attempt or datetime.fromisoformat(attempt['updated_at']) <= now - timedelta(hours=1):
        conn.execute('''
            INSERT INTO login_attempts (email, failure_count, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(email) DO UPDATE SET
                failure_count = 1, locked_until = NULL, updated_at = excluded.updated_at
        ''', ('registration:' + ip_hash, now.isoformat()))
    else:
        conn.execute(
            'UPDATE login_attempts SET failure_count = failure_count + 1, updated_at = ? WHERE email = ?',
            (now.isoformat(), 'registration:' + ip_hash),
        )
    conn.commit()
    conn.close()
    form = {
        'organization_name': request.form.get('organization_name', '').strip(),
        'organization_type': request.form.get('organization_type', ''),
        'industry': request.form.get('industry', ''),
        'project_name': request.form.get('project_name', '').strip(),
        'project_type': request.form.get('project_type', '').strip(),
        'project_location': request.form.get('project_location', '').strip(),
        'project_start_date': request.form.get('project_start_date', '').strip(),
        'project_end_date': request.form.get('project_end_date', '').strip(),
        'website': request.form.get('website', '').strip(),
        'full_name': request.form.get('full_name', '').strip(),
        'email': request.form.get('email', '').strip().lower(),
    }
    password = request.form.get('password', '')
    password_confirm = request.form.get('password_confirm', '')
    errors = []
    if not form['organization_name'] or len(form['organization_name']) > 160:
        errors.append('Organization name is required (maximum 160 characters).')
    if form['organization_type'] not in {'Company', 'Contractor', 'Client', 'Other'}:
        errors.append('Select a valid organization type.')
    if form['industry'] not in {'Oil & Gas', 'Construction', 'Manufacturing', 'Other'}:
        errors.append('Select a valid industry.')
    for field, label, limit in (
        ('project_name', 'Project name', 160),
        ('project_type', 'Project type', 120),
        ('project_location', 'Project location', 200),
        ('full_name', 'Administrator name', 120),
    ):
        if not form[field] or len(form[field]) > limit:
            errors.append(f'{label} is required (maximum {limit} characters).')
    if not re.fullmatch(r'[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+', form['email']) or len(form['email']) > 254:
        errors.append('Enter a valid administrator email address.')
    if len(password) < 12 or len(password) > 128:
        errors.append('Password must be between 12 and 128 characters.')
    if password.strip() != password:
        errors.append('Password must not start or end with whitespace.')
    if password != password_confirm:
        errors.append('Passwords do not match.')
    project_start = None
    project_end = None
    for date_field, label in (
        ('project_start_date', 'Project start date'),
        ('project_end_date', 'Project end date'),
    ):
        if form[date_field]:
            try:
                parsed_date = datetime.strptime(form[date_field], '%Y-%m-%d')
                if date_field == 'project_start_date':
                    project_start = parsed_date
                else:
                    project_end = parsed_date
            except ValueError:
                errors.append(f'Enter a valid {label.lower()}.')
    if project_start and project_end:
        if project_end < project_start:
            errors.append('Project end date cannot be earlier than its start date.')
    if form['website']:
        try:
            website = urlsplit(form['website'])
            if website.scheme.lower() != 'https' or not website.hostname or website.username or website.password:
                errors.append('Website must be a valid HTTPS URL.')
        except ValueError:
            errors.append('Website must be a valid HTTPS URL.')
    if errors:
        return render_template(
            'register.html', csrf_token=csrf_token(), form=form,
            registration_enabled=email_delivery_configured(), errors=errors
        ), 400

    # Fail explicitly before creating an account that cannot receive verification.
    try:
        if not email_delivery_configured():
            raise RuntimeError(
                'Email verification is not configured. Contact the service '
                'administrator to configure email delivery.'
            )
        if not public_url_is_valid(os.environ['HSE_PUBLIC_URL']):
            raise RuntimeError('HSE_PUBLIC_URL must use HTTPS.')
    except RuntimeError as exc:
        return render_template(
            'register.html', csrf_token=csrf_token(), form=form,
            registration_enabled=email_delivery_configured(),
            errors=[str(exc)],
        ), 503

    now = datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(32)
    conn = get_db_connection()
    try:
        with conn:
            existing_user = conn.execute(
                'SELECT 1 FROM users WHERE email = ? COLLATE NOCASE',
                (form['email'],),
            ).fetchone()
            if existing_user:
                conn.close()
                return render_template(
                    'registration_pending.html', csrf_token=csrf_token()
                ), 200
            cursor = conn.execute('''
                INSERT INTO organizations (
                    organization_name, organization_type, industry, project_name,
                    project_type, project_location, project_start_date,
                    project_end_date, website, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                form['organization_name'], form['organization_type'], form['industry'],
                form['project_name'], form['project_type'], form['project_location'],
                form['project_start_date'] or None, form['project_end_date'] or None,
                form['website'] or None, now.isoformat(),
            ))
            organization_id = cursor.lastrowid
            cursor = conn.execute('''
                INSERT INTO users (
                    organization_id, full_name, email, password_hash, role, created_at
                ) VALUES (?, ?, ?, ?, 'admin', ?)
            ''', (
                organization_id, form['full_name'], form['email'],
                generate_password_hash(password, method='scrypt'), now.isoformat(),
            ))
            user_id = cursor.lastrowid
            conn.execute('''
                INSERT INTO organization_settings (
                    organization_id, setting_key, setting_value
                ) VALUES (?, 'dashboard_enabled', 'true')
            ''', (organization_id,))
            conn.execute('''
                INSERT INTO email_verification_tokens (
                    user_id, token_hash, expires_at, created_at
                ) VALUES (?, ?, ?, ?)
            ''', (
                user_id, hashlib.sha256(raw_token.encode()).hexdigest(),
                (now + timedelta(minutes=30)).isoformat(), now.isoformat(),
            ))
    except sqlite3.IntegrityError:
        conn.close()
        return render_template(
            'registration_pending.html', csrf_token=csrf_token()
        ), 200
    conn.close()

    try:
        send_account_email(form['email'], form['full_name'], raw_token)
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        conn = get_db_connection()
        with conn:
            conn.execute('DELETE FROM email_verification_tokens WHERE user_id = ?', (user_id,))
            conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
            conn.execute(
                'DELETE FROM organization_settings WHERE organization_id = ?',
                (organization_id,),
            )
            conn.execute('DELETE FROM organizations WHERE organization_id = ?', (organization_id,))
        conn.close()
        app.logger.error('Failed to send account verification email: %s', exc)
        return render_template(
            'register.html',
            csrf_token=csrf_token(),
            form=form,
            registration_enabled=email_delivery_configured(),
            errors=['We could not send the verification email. Please try again later.'],
        ), 503

    return render_template(
        'registration_pending.html', csrf_token=csrf_token()
    ), 200

@app.route('/resend-verification', methods=['GET', 'POST'])
def resend_verification():
    if request.method == 'GET':
        return render_template('resend_verification.html', csrf_token=csrf_token())

    email = request.form.get('email', '').strip().lower()
    now = datetime.now(timezone.utc)
    conn = get_db_connection()
    attempt_key = 'resend:' + email
    attempt = conn.execute(
        'SELECT failure_count, updated_at FROM login_attempts WHERE email = ?',
        (attempt_key,),
    ).fetchone()
    allowed = not (
        attempt
        and datetime.fromisoformat(attempt['updated_at']) > now - timedelta(hours=1)
        and attempt['failure_count'] >= 3
    )
    if allowed:
        conn.execute('''
            INSERT INTO login_attempts (email, failure_count, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(email) DO UPDATE SET
                failure_count = CASE
                    WHEN updated_at <= ? THEN 1 ELSE failure_count + 1
                END,
                updated_at = excluded.updated_at
        ''', (attempt_key, now.isoformat(), (now - timedelta(hours=1)).isoformat()))
        pending_user = conn.execute('''
            SELECT user_id, full_name FROM users
            WHERE email = ? COLLATE NOCASE
              AND email_verified_at IS NULL AND is_active = 1
        ''', (email,)).fetchone()
    else:
        pending_user = None
    raw_token = secrets.token_urlsafe(32)
    new_token_id = None
    if pending_user:
        with conn:
            cursor = conn.execute('''
                INSERT INTO email_verification_tokens (
                    user_id, token_hash, expires_at, created_at
                ) VALUES (?, ?, ?, ?)
            ''', (
                pending_user['user_id'],
                hashlib.sha256(raw_token.encode()).hexdigest(),
                (now + timedelta(minutes=30)).isoformat(),
                now.isoformat(),
            ))
            new_token_id = cursor.lastrowid
    conn.close()
    if pending_user:
        try:
            send_account_email(email, pending_user['full_name'], raw_token)
            conn = get_db_connection()
            with conn:
                conn.execute('''
                    UPDATE email_verification_tokens SET used_at = ?
                    WHERE user_id = ? AND used_at IS NULL AND token_id != ?
                ''', (now.isoformat(), pending_user['user_id'], new_token_id))
            conn.close()
        except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
            conn = get_db_connection()
            with conn:
                conn.execute(
                    'DELETE FROM email_verification_tokens WHERE token_id = ?',
                    (new_token_id,),
                )
            conn.close()
            app.logger.error('Failed to resend account verification email: %s', exc)
    return render_template(
        'registration_pending.html', csrf_token=csrf_token()
    ), 200

@app.route('/verify-email/<token>', methods=['GET', 'POST'])
def verify_email(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    if request.method == 'GET':
        conn = get_db_connection()
        record = conn.execute('''
            SELECT token_id FROM email_verification_tokens
            WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?
        ''', (token_hash, datetime.now(timezone.utc).isoformat())).fetchone()
        conn.close()
        if not record:
            abort(400, description='This verification link is invalid or expired.')
        return render_template('verify_email.html', token=token, csrf_token=csrf_token())

    require_valid_csrf()
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    conn.execute('BEGIN IMMEDIATE')
    token_row = conn.execute('''
        SELECT token_id, user_id FROM email_verification_tokens
        WHERE token_hash = ? AND used_at IS NULL AND expires_at > ?
    ''', (token_hash, now)).fetchone()
    if not token_row:
        conn.rollback()
        conn.close()
        abort(400, description='This verification link is invalid or expired.')
    consumed = conn.execute('''
        UPDATE email_verification_tokens SET used_at = ?
        WHERE token_id = ? AND used_at IS NULL AND expires_at > ?
    ''', (now, token_row['token_id'], now))
    if consumed.rowcount != 1:
        conn.rollback()
        conn.close()
        abort(400, description='This verification link is invalid or expired.')
    conn.execute(
        'UPDATE users SET email_verified_at = ? WHERE user_id = ?',
        (now, token_row['user_id']),
    )
    user = conn.execute('''
        SELECT user_id, organization_id, role, module_access
        FROM users WHERE user_id = ?
    ''', (token_row['user_id'],)).fetchone()
    conn.commit()
    conn.close()
    session.clear()
    session['user_id'] = user['user_id']
    session['organization_id'] = user['organization_id']
    session['is_admin'] = user['role'] == 'admin'
    session['module_access'] = json.loads(user['module_access'] or '[]')
    session.permanent = True
    csrf_token()
    return redirect(url_for('admin'))

@app.route('/activate-account/<token>', methods=['GET', 'POST'])
def activate_account(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    invitation = conn.execute('''
        SELECT t.token_id, u.user_id, u.organization_id, u.role, u.module_access
        FROM email_verification_tokens t
        JOIN users u ON u.user_id = t.user_id
        WHERE t.token_hash = ? AND t.used_at IS NULL AND t.expires_at > ?
          AND u.role = 'subcontractor' AND u.is_active = 0
    ''', (token_hash, now)).fetchone()
    conn.close()
    if not invitation:
        abort(400, description='This activation link is invalid, expired, or already used.')
    if request.method == 'GET':
        return render_template(
            'activate_account.html', token=token, csrf_token=csrf_token()
        )

    password = request.form.get('password', '')
    password_confirm = request.form.get('password_confirm', '')
    if len(password) < 12 or len(password) > 128 or password.strip() != password:
        return render_template(
            'activate_account.html',
            token=token,
            csrf_token=csrf_token(),
            error='Choose a password between 12 and 128 characters with no leading or trailing spaces.',
        ), 400
    if password != password_confirm:
        return render_template(
            'activate_account.html',
            token=token,
            csrf_token=csrf_token(),
            error='Passwords do not match.',
        ), 400

    conn = get_db_connection()
    conn.execute('BEGIN IMMEDIATE')
    current = conn.execute('''
        SELECT t.token_id, u.user_id FROM email_verification_tokens t
        JOIN users u ON u.user_id = t.user_id
        WHERE t.token_hash = ? AND t.used_at IS NULL AND t.expires_at > ?
          AND u.role = 'subcontractor' AND u.is_active = 0
    ''', (token_hash, datetime.now(timezone.utc).isoformat())).fetchone()
    if not current:
        conn.rollback()
        conn.close()
        abort(400, description='This activation link is invalid, expired, or already used.')
    consumed = conn.execute('''
        UPDATE email_verification_tokens SET used_at = ?
        WHERE token_id = ? AND used_at IS NULL
    ''', (datetime.now(timezone.utc).isoformat(), current['token_id']))
    if consumed.rowcount != 1:
        conn.rollback()
        conn.close()
        abort(400, description='This activation link has already been used.')
    conn.execute('''
        UPDATE users SET password_hash = ?, email_verified_at = ?, is_active = 1
        WHERE user_id = ? AND role = 'subcontractor' AND is_active = 0
    ''', (
        generate_password_hash(password, method='scrypt'),
        datetime.now(timezone.utc).isoformat(),
        current['user_id'],
    ))
    user = conn.execute('''
        SELECT user_id, organization_id, module_access
        FROM users WHERE user_id = ?
    ''', (current['user_id'],)).fetchone()
    conn.commit()
    conn.close()
    session.clear()
    session['user_id'] = user['user_id']
    session['organization_id'] = user['organization_id']
    session['is_admin'] = False
    session['module_access'] = json.loads(user['module_access'] or '[]')
    session.permanent = True
    csrf_token()
    return redirect(url_for('index'))

@app.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    token_row = conn.execute('''
        SELECT t.token_id, u.user_id
        FROM password_reset_tokens t
        JOIN users u ON u.user_id = t.user_id
        WHERE t.token_hash = ? AND t.used_at IS NULL AND t.expires_at > ?
          AND u.email_verified_at IS NOT NULL AND u.is_active = 1
    ''', (token_hash, now)).fetchone()
    conn.close()
    if not token_row:
        abort(400, description='This password reset link is invalid or expired.')
    if request.method == 'GET':
        return render_template(
            'reset_password.html', token=token, csrf_token=csrf_token()
        )

    password = request.form.get('password', '')
    password_confirm = request.form.get('password_confirm', '')
    if len(password) < 12 or len(password) > 128 or password.strip() != password:
        return render_template(
            'reset_password.html',
            token=token,
            csrf_token=csrf_token(),
            error='Choose a password between 12 and 128 characters with no leading or trailing spaces.',
        ), 400
    if password != password_confirm:
        return render_template(
            'reset_password.html',
            token=token,
            csrf_token=csrf_token(),
            error='Passwords do not match.',
        ), 400

    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    conn.execute('BEGIN IMMEDIATE')
    token_row = conn.execute('''
        SELECT t.token_id, u.user_id, u.email
        FROM password_reset_tokens t
        JOIN users u ON u.user_id = t.user_id
        WHERE t.token_hash = ? AND t.used_at IS NULL AND t.expires_at > ?
          AND u.email_verified_at IS NOT NULL AND u.is_active = 1
    ''', (token_hash, now)).fetchone()
    if not token_row:
        conn.rollback()
        conn.close()
        abort(400, description='This password reset link is invalid or expired.')
    consumed = conn.execute('''
        UPDATE password_reset_tokens SET used_at = ?
        WHERE token_id = ? AND used_at IS NULL AND expires_at > ?
    ''', (now, token_row['token_id'], now))
    if consumed.rowcount != 1:
        conn.rollback()
        conn.close()
        abort(400, description='This password reset link is invalid or expired.')
    updated = conn.execute('''
        UPDATE users SET password_hash = ?
        WHERE user_id = ? AND email_verified_at IS NOT NULL AND is_active = 1
    ''', (
        generate_password_hash(password, method='scrypt'), token_row['user_id'],
    ))
    if updated.rowcount != 1:
        conn.rollback()
        conn.close()
        abort(400, description='This password reset link is invalid or expired.')
    conn.execute('''
        UPDATE password_reset_tokens SET used_at = ?
        WHERE user_id = ? AND used_at IS NULL
    ''', (now, token_row['user_id']))
    conn.execute(
        'DELETE FROM login_attempts WHERE email = ?', (token_row['email'],)
    )
    conn.commit()
    conn.close()
    session.clear()
    flash('Your password has been reset. Sign in with your new password.', 'success')
    return redirect(url_for('admin_login'))

@app.route('/incident')
@module_required('incident_logging')
def incident():
    organization_id = current_organization_id()
    conn = get_db_connection()
    if session.get('is_admin') or session.get('is_legacy_admin'):
        contractors = conn.execute('''
            SELECT contractor_id, company_name, contractor_type
            FROM contractors WHERE organization_id = ? ORDER BY company_name
        ''', (organization_id,)).fetchall()
    else:
        contractors = conn.execute('''
            SELECT c.contractor_id, c.company_name, c.contractor_type
            FROM users u JOIN contractors c ON c.contractor_id = u.contractor_id
            WHERE u.user_id = ? AND u.organization_id = ?
        ''', (session['user_id'], organization_id)).fetchall()
    conn.close()
    return render_template('incident_report.html', contractors=contractors)

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        require_valid_csrf()
        email = request.form.get('email', '').strip().lower()
        supplied_password = request.form.get('password', '')
        now = datetime.now(timezone.utc)
        conn = get_db_connection()
        attempt = conn.execute(
            'SELECT failure_count, locked_until FROM login_attempts WHERE email = ?',
            (email,),
        ).fetchone()
        locked = bool(
            attempt and attempt['locked_until']
            and datetime.fromisoformat(attempt['locked_until']) > now
        )
        user = None
        legacy_password = os.environ.get('HSE_ADMIN_PASSWORD')
        legacy_email = os.environ.get(
            'HSE_ADMIN_EMAIL', 'legacy-admin@local'
        ).strip().lower()
        if (
            not locked
            and legacy_password
            and hmac.compare_digest(email, legacy_email)
            and hmac.compare_digest(supplied_password, legacy_password)
        ):
            legacy_organization = conn.execute(
                'SELECT organization_id FROM organizations WHERE is_legacy = 1'
            ).fetchone()
            if legacy_organization:
                conn.execute('DELETE FROM login_attempts WHERE email = ?', (email,))
                conn.commit()
                conn.close()
                session.clear()
                session['user_id'] = -1
                session['organization_id'] = legacy_organization['organization_id']
                session['is_admin'] = True
                session['is_legacy_admin'] = True
                csrf_token()
                session.permanent = True
                next_path = request.args.get('next', '')
                if not next_path.startswith('/') or next_path.startswith('//'):
                    next_path = url_for('admin')
                return redirect(next_path)
        if not locked:
            user = conn.execute('''
                SELECT user_id, organization_id, password_hash, email_verified_at,
                       is_active, role, module_access
                FROM users WHERE email = ? COLLATE NOCASE
            ''', (email,)).fetchone()
        password_matches = bool(
            user and check_password_hash(user['password_hash'], supplied_password)
        )
        if (
            user and password_matches
            and user['email_verified_at'] and user['is_active']
        ):
            conn.execute('DELETE FROM login_attempts WHERE email = ?', (email,))
            conn.commit()
            conn.close()
            session.clear()
            session['user_id'] = user['user_id']
            session['organization_id'] = user['organization_id']
            session['is_admin'] = user['role'] == 'admin'
            session['module_access'] = json.loads(user['module_access'] or '[]')
            csrf_token()
            next_path = request.args.get('next', '')
            if not next_path.startswith('/') or next_path.startswith('//'):
                next_path = url_for('admin')
                if user['role'] != 'admin':
                    module_endpoints = (
                        ('incident_logging', 'incident'),
                        ('safety_observations', 'observation'),
                        ('site_inspections', 'inspection'),
                        ('monthly_statistics', 'monthly_stats'),
                        ('training_performance', 'training_performance'),
                    )
                    assigned = set(session['module_access'])
                    next_path = next(
                        (url_for(endpoint) for module, endpoint in module_endpoints
                         if module in assigned),
                        url_for('index'),
                    )
            session.permanent = True
            return redirect(next_path)
        if not locked:
            failure_count = (attempt['failure_count'] if attempt else 0) + 1
            locked_until = (
                (now + timedelta(minutes=15)).isoformat()
                if failure_count >= 5 else None
            )
            conn.execute('''
                INSERT INTO login_attempts (email, failure_count, locked_until, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(email) DO UPDATE SET
                    failure_count = excluded.failure_count,
                    locked_until = excluded.locked_until,
                    updated_at = excluded.updated_at
            ''', (email, failure_count, locked_until, now.isoformat()))
            conn.commit()
        conn.close()
        return render_template(
            'admin_login.html',
            csrf_token=csrf_token(),
            error='Sign-in failed. Check your credentials, verify your email, or try again later.',
        ), 401
    return render_template(
        'admin_login.html',
        csrf_token=csrf_token(),
        registration_enabled=email_delivery_configured(),
    )

@app.route('/admin/logout', methods=['POST'])
def admin_logout():
    require_valid_csrf()
    session.clear()
    return redirect(url_for('index'))

@app.route('/admin')
@admin_required
def admin():
    organization_id = current_organization_id()
    now_iso = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    contractors = conn.execute('''
        SELECT c.contractor_id, c.company_name, c.trade_type, c.contractor_type,
               parent.company_name AS parent_company
        FROM contractors c
        LEFT JOIN contractors parent
            ON parent.contractor_id = c.parent_contractor_id
        WHERE c.organization_id = ? ORDER BY c.company_name
    ''', (organization_id,)).fetchall()
    access_links = conn.execute('''
        SELECT access_id, display_name, email, role, expires_at, revoked_at, created_at
        FROM dashboard_access WHERE organization_id = ?
        ORDER BY created_at DESC
    ''', (organization_id,)).fetchall()
    users = conn.execute('''
        SELECT u.user_id, u.full_name, u.email, u.role, u.module_access,
               u.is_active, u.email_verified_at, c.company_name,
               EXISTS (
                   SELECT 1 FROM email_verification_tokens t
                   WHERE t.user_id = u.user_id AND t.used_at IS NULL
                     AND t.expires_at > ?
               ) AS invitation_pending
        FROM users u
        LEFT JOIN contractors c ON c.contractor_id = u.contractor_id
        WHERE u.organization_id = ?
        ORDER BY u.created_at DESC
    ''', (now_iso, organization_id)).fetchall()
    setting = conn.execute('''
        SELECT setting_value FROM organization_settings
        WHERE organization_id = ? AND setting_key = 'dashboard_enabled'
    ''', (organization_id,)).fetchone()
    organization = conn.execute(
        'SELECT * FROM organizations WHERE organization_id = ?',
        (organization_id,),
    ).fetchone()
    conn.close()
    users = [
        {
            **dict(user),
            'modules_list': json.loads(user['module_access'] or '[]'),
            'module_names': [
                {
                    'incident_logging': 'Incident logging',
                    'safety_observations': 'Safety observations',
                    'site_inspections': 'Site inspections',
                    'monthly_statistics': 'Monthly statistics',
                    'training_performance': 'Training performance',
                }[module]
                for module in json.loads(user['module_access'] or '[]')
                if module in {
                    'incident_logging', 'safety_observations', 'site_inspections',
                    'monthly_statistics', 'training_performance',
                }
            ],
        }
        for user in users
    ]
    new_observation_qr_url = session.pop('new_observation_qr_url', None)
    new_observation_qr = None
    if new_observation_qr_url:
        new_observation_qr = {
            'url': new_observation_qr_url,
            'image': observation_qr_data_uri(new_observation_qr_url),
        }
    return render_template(
        'admin.html',
        csrf_token=csrf_token(),
        contractors=contractors,
        users=users,
        access_links=access_links,
        dashboard_enabled=setting['setting_value'] == 'true' if setting else True,
        new_dashboard_link=session.pop('new_dashboard_link', None),
        now_iso=now_iso,
        organization=organization,
        new_observation_qr=new_observation_qr,
    )

@app.route('/admin/observation-qr', methods=['POST'])
@admin_required
def create_observation_qr():
    require_valid_csrf()
    raw_token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode('utf-8')).hexdigest()
    organization_id = current_organization_id()
    conn = get_db_connection()
    with conn:
        conn.execute('''
            INSERT INTO organization_settings (
                organization_id, setting_key, setting_value
            ) VALUES (?, 'public_observation_token_hash', ?)
            ON CONFLICT (organization_id, setting_key)
            DO UPDATE SET setting_value = excluded.setting_value
        ''', (organization_id, token_hash))
    conn.close()

    public_base_url = os.environ.get('HSE_PUBLIC_URL', '').rstrip('/')
    if not public_base_url:
        public_base_url = request.url_root.rstrip('/')
    observation_url = (
        f'{public_base_url}{url_for("public_observation", token=raw_token)}'
    )
    session['new_observation_qr_url'] = observation_url
    return redirect(url_for('admin'))

@app.route('/admin/users/invite', methods=['POST'])
@admin_required
def invite_subcontractor_user():
    require_valid_csrf()
    organization_id = current_organization_id()
    full_name = request.form.get('full_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    contractor_id = request.form.get('contractor_id', '').strip()
    modules = sorted(set(request.form.getlist('modules')))
    allowed_modules = {
        'incident_logging',
        'safety_observations',
        'site_inspections',
        'monthly_statistics',
        'training_performance',
    }
    if not full_name or len(full_name) > 120:
        abort(400, description='Enter a subcontractor user name (maximum 120 characters).')
    if not re.fullmatch(r'[^@\s]{1,64}@[^@\s.]+(?:\.[^@\s.]+)+', email) or len(email) > 254:
        abort(400, description='Enter a valid subcontractor work email.')
    if not modules or not set(modules).issubset(allowed_modules):
        abort(400, description='Select at least one valid application module.')
    conn = get_db_connection()
    contractor = conn.execute('''
        SELECT contractor_id FROM contractors
        WHERE contractor_id = ? AND organization_id = ?
          AND contractor_type = 'Subcontractor'
    ''', (contractor_id, organization_id)).fetchone()
    if not contractor:
        conn.close()
        abort(400, description='Select a subcontractor in your organization.')
    if conn.execute(
        'SELECT 1 FROM users WHERE email = ? COLLATE NOCASE', (email,)
    ).fetchone():
        conn.close()
        abort(409, description='That email already has an application account.')

    now = datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(32)
    try:
        with conn:
            cursor = conn.execute('''
                INSERT INTO users (
                    organization_id, full_name, email, password_hash, role,
                    contractor_id, module_access, email_verified_at,
                    is_active, created_at
                ) VALUES (?, ?, ?, ?, 'subcontractor', ?, ?, NULL, 0, ?)
            ''', (
                organization_id,
                full_name,
                email,
                generate_password_hash(secrets.token_urlsafe(32), method='scrypt'),
                contractor_id,
                json.dumps(modules),
                now.isoformat(),
            ))
            user_id = cursor.lastrowid
            conn.execute('''
                INSERT INTO email_verification_tokens (
                    user_id, token_hash, expires_at, created_at
                ) VALUES (?, ?, ?, ?)
            ''', (
                user_id,
                hashlib.sha256(raw_token.encode()).hexdigest(),
                (now + timedelta(minutes=30)).isoformat(),
                now.isoformat(),
            ))
    except sqlite3.IntegrityError:
        conn.close()
        abort(409, description='That email already has an application account.')
    conn.close()

    try:
        send_account_email(email, full_name, raw_token, invited=True)
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        conn = get_db_connection()
        with conn:
            conn.execute('DELETE FROM email_verification_tokens WHERE user_id = ?', (user_id,))
            conn.execute('DELETE FROM users WHERE user_id = ?', (user_id,))
        conn.close()
        app.logger.error('Failed to deliver subcontractor invitation: %s', exc)
        abort(503, description='Could not send the activation email. The invitation was not created.')
    return redirect(url_for('admin'))

@app.route('/admin/users/<int:user_id>/revoke', methods=['POST'])
@admin_required
def revoke_subcontractor_user(user_id):
    require_valid_csrf()
    conn = get_db_connection()
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute('''
        UPDATE users SET is_active = 0
        WHERE user_id = ? AND organization_id = ? AND role = 'subcontractor'
    ''', (user_id, current_organization_id()))
    if cursor.rowcount == 1:
        conn.execute('''
            UPDATE email_verification_tokens SET used_at = ?
            WHERE user_id = ? AND used_at IS NULL
        ''', (now, user_id))
        conn.execute('''
            UPDATE password_reset_tokens SET used_at = ?
            WHERE user_id = ? AND used_at IS NULL
        ''', (now, user_id))
    conn.commit()
    conn.close()
    if cursor.rowcount != 1:
        abort(404, description='Subcontractor user not found in your organization.')
    return redirect(url_for('admin'))

@app.route('/admin/users/<int:user_id>/password-reset', methods=['POST'])
@admin_required
def send_user_password_reset(user_id):
    require_valid_csrf()
    organization_id = current_organization_id()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()
    raw_token = secrets.token_urlsafe(32)
    conn = get_db_connection()
    conn.execute('BEGIN IMMEDIATE')
    user = conn.execute('''
        SELECT user_id, full_name, email
        FROM users
        WHERE user_id = ? AND organization_id = ?
          AND role IN ('admin', 'subcontractor')
          AND is_active = 1 AND email_verified_at IS NOT NULL
    ''', (user_id, organization_id)).fetchone()
    if not user:
        conn.rollback()
        conn.close()
        abort(404, description='Active, verified user not found in your organization.')
    recent_requests = conn.execute('''
        SELECT COUNT(*) FROM password_reset_tokens
        WHERE user_id = ? AND created_at > ?
    ''', (user_id, (now - timedelta(hours=1)).isoformat())).fetchone()[0]
    if recent_requests >= 3:
        conn.rollback()
        conn.close()
        flash('Password reset email limit reached for this user. Try again later.', 'error')
        return redirect(url_for('admin'))
    conn.execute('''
        UPDATE password_reset_tokens SET used_at = ?
        WHERE user_id = ? AND used_at IS NULL
    ''', (now_iso, user_id))
    conn.execute('''
        INSERT INTO password_reset_tokens (
            user_id, token_hash, expires_at, created_at
        ) VALUES (?, ?, ?, ?)
    ''', (
        user_id,
        hashlib.sha256(raw_token.encode('utf-8')).hexdigest(),
        (now + timedelta(minutes=30)).isoformat(),
        now_iso,
    ))
    conn.commit()
    conn.close()

    try:
        send_account_email(
            user['email'], user['full_name'], raw_token, password_reset=True
        )
    except (OSError, smtplib.SMTPException, RuntimeError, ValueError) as exc:
        conn = get_db_connection()
        with conn:
            conn.execute('''
                UPDATE password_reset_tokens SET used_at = ?
                WHERE user_id = ? AND token_hash = ? AND used_at IS NULL
            ''', (
                datetime.now(timezone.utc).isoformat(),
                user_id,
                hashlib.sha256(raw_token.encode('utf-8')).hexdigest(),
            ))
        conn.close()
        app.logger.error('Failed to send password reset email: %s', exc)
        flash('Could not send the password reset email. Check email delivery settings and try again.', 'error')
    else:
        flash("Password reset instructions were sent to the user's registered email.", 'success')
    return redirect(url_for('admin'))

@app.route('/admin/users/<int:user_id>/modules', methods=['POST'])
@admin_required
def update_subcontractor_modules(user_id):
    require_valid_csrf()
    allowed_modules = {
        'incident_logging', 'safety_observations', 'site_inspections',
        'monthly_statistics', 'training_performance',
    }
    modules = sorted(set(request.form.getlist('modules')))
    if not modules or not set(modules).issubset(allowed_modules):
        abort(400, description='Select at least one valid application module.')
    conn = get_db_connection()
    cursor = conn.execute('''
        UPDATE users SET module_access = ?
        WHERE user_id = ? AND organization_id = ? AND role = 'subcontractor'
    ''', (
        json.dumps(modules), user_id, current_organization_id(),
    ))
    conn.commit()
    conn.close()
    if cursor.rowcount != 1:
        abort(404, description='Subcontractor user not found in your organization.')
    return redirect(url_for('admin'))

@app.route('/admin/contractors', methods=['POST'])
@admin_required
def add_contractor():
    require_valid_csrf()
    company_name = request.form.get('company_name', '').strip()
    trade_type = request.form.get('trade_type', '').strip()
    contractor_type = request.form.get('contractor_type', '')
    parent_id = request.form.get('parent_contractor_id', '').strip()
    if not company_name or contractor_type not in {'Contractor', 'Subcontractor'}:
        abort(400, description='A company name and valid organization type are required.')
    if contractor_type == 'Subcontractor' and not parent_id:
        abort(400, description='Select the contractor this subcontractor works for.')
    if contractor_type == 'Contractor':
        parent_id = None
    else:
        conn = get_db_connection()
        parent = conn.execute(
            'SELECT contractor_type FROM contractors WHERE contractor_id = ? AND organization_id = ?',
            (parent_id, current_organization_id()),
        ).fetchone()
        conn.close()
        if not parent or parent['contractor_type'] != 'Contractor':
            abort(400, description='Subcontractors must be linked to a valid contractor.')
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO contractors (
            organization_id, company_name, trade_type, contractor_type,
            parent_contractor_id
        ) VALUES (?, ?, ?, ?, ?)
    ''', (
        current_organization_id(), company_name, trade_type, contractor_type, parent_id
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/invitations', methods=['POST'])
@admin_required
def create_dashboard_invitation():
    require_valid_csrf()
    display_name = request.form.get('display_name', '').strip()
    email = request.form.get('email', '').strip().lower()
    if (
        not display_name
        or not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+', email)
    ):
        abort(400, description='Enter a viewer name and valid email address.')
    try:
        expires_in_hours = int(request.form.get('expires_in_hours', ''))
    except ValueError:
        abort(400, description='Select a valid invitation expiry.')
    if expires_in_hours not in {1, 24, 168, 720}:
        abort(400, description='Select a valid invitation expiry.')
    session['new_dashboard_link'] = issue_dashboard_token(
        display_name, email, 'viewer', expires_in_hours
    )
    return redirect(url_for('admin'))

@app.route('/admin/dashboard-link', methods=['POST'])
@admin_required
def create_admin_dashboard_link():
    require_valid_csrf()
    if session.get('is_legacy_admin'):
        display_name = 'Legacy Administrator'
        email = os.environ.get('HSE_ADMIN_EMAIL', 'legacy-admin@local')
    else:
        conn = get_db_connection()
        user = conn.execute(
            'SELECT full_name, email FROM users WHERE user_id = ?',
            (session['user_id'],),
        ).fetchone()
        conn.close()
        display_name = user['full_name']
        email = user['email']
    session['new_dashboard_link'] = issue_dashboard_token(
        display_name, email, 'admin', 12
    )
    return redirect(url_for('admin'))

@app.route('/admin/dashboard-settings', methods=['POST'])
@admin_required
def update_dashboard_settings():
    require_valid_csrf()
    enabled = 'true' if request.form.get('dashboard_enabled') == 'on' else 'false'
    conn = get_db_connection()
    conn.execute('''
        UPDATE organization_settings SET setting_value = ?
        WHERE organization_id = ? AND setting_key = 'dashboard_enabled'
    ''', (enabled, current_organization_id()))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/admin/invitations/<int:access_id>/revoke', methods=['POST'])
@admin_required
def revoke_dashboard_invitation(access_id):
    require_valid_csrf()
    conn = get_db_connection()
    conn.execute('''
        UPDATE dashboard_access SET revoked_at = ?
        WHERE access_id = ? AND organization_id = ? AND revoked_at IS NULL
    ''', (
        datetime.now(timezone.utc).isoformat(), access_id,
        current_organization_id(),
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('admin'))

@app.route('/submit_incident', methods=['POST'])
@module_required('incident_logging')
def submit_incident():
    organization_id = current_organization_id()
    contractor_id = resolve_contractor_id(request.form.get('contractor_id'))
    if not contractor_id:
        abort(400, description='Select a contractor before logging an incident.')
    report_date = request.form['report_date']
    event_time = request.form['event_time']
    incident_type = request.form['incident_type']
    employee_age = request.form['employee_age']
    employment_date = request.form['employment_date']
    employment_type = request.form['employment_type']
    activity_type = request.form['activity_type']
    pre_incident_activity = request.form['pre_incident_activity']
    description = request.form['description']
    injury_details = request.form.get('injury_details', '')
    body_part = request.form.get('body_part', '')
    immediate_causes = request.form.getlist('immediate_causes')
    underlying_causes = request.form.getlist('underlying_causes')
    root_cause = '; '.join(immediate_causes + underlying_causes)
    corrective_action = request.form['corrective_action']

    conn = get_db_connection()
    conn.execute('''
        INSERT INTO incidents (
            organization_id, contractor_id, report_date, event_time, incident_type, employee_age,
            employment_date, employment_type, activity_type, pre_incident_activity,
            description, injury_details, body_part, root_cause, immediate_causes,
            underlying_causes, corrective_action, status
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'Open')
    ''', (
        organization_id, contractor_id, report_date, event_time, incident_type, employee_age,
        employment_date, employment_type, activity_type, pre_incident_activity,
        description, injury_details, body_part, root_cause,
        json.dumps(immediate_causes), json.dumps(underlying_causes), corrective_action
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('incident'))

@app.route('/observation')
@module_required('safety_observations')
def observation():
    conn = get_db_connection()
    organization = conn.execute(
        'SELECT industry FROM organizations WHERE organization_id = ?',
        (current_organization_id(),),
    ).fetchone()
    conn.close()
    return render_template(
        'safety_observation.html',
        contractors=get_available_contractors(),
        industry=organization['industry'] if organization else 'Construction',
        observation_taxonomy=OBSERVATION_TAXONOMY,
        public_access=False,
    )

def get_public_observation_organization(token):
    if not token or len(token) > 128:
        abort(404)
    token_hash = hashlib.sha256(token.encode('utf-8')).hexdigest()
    conn = get_db_connection()
    organization = conn.execute('''
        SELECT o.organization_id, o.organization_name, o.project_name, o.industry
        FROM organizations o
        JOIN organization_settings s
          ON s.organization_id = o.organization_id
         AND s.setting_key = 'public_observation_token_hash'
        WHERE s.setting_value = ?
    ''', (token_hash,)).fetchone()
    conn.close()
    if not organization:
        abort(404)
    return organization

def observation_qr_data_uri(observation_url):
    qr_image = qrcode.make(
        observation_url,
        image_factory=svg_image.SvgPathImage,
        border=4,
    )
    qr_stream = BytesIO()
    qr_image.save(qr_stream)
    return (
        'data:image/svg+xml;base64,'
        + base64.b64encode(qr_stream.getvalue()).decode('ascii')
    )

def render_public_observation_form(token, organization):
    conn = get_db_connection()
    contractors = conn.execute('''
        SELECT contractor_id, company_name, contractor_type
        FROM contractors
        WHERE organization_id = ?
        ORDER BY company_name
    ''', (organization['organization_id'],)).fetchall()
    conn.close()
    return render_template(
        'safety_observation.html',
        contractors=contractors,
        industry=organization['industry'],
        observation_taxonomy=OBSERVATION_TAXONOMY,
        public_access=True,
        public_token=token,
        organization_name=organization['organization_name'],
        project_name=organization['project_name'],
    )

def persist_observation(organization_id, contractor_id, industry):
    date_recorded = request.form.get('date_recorded', '').strip()
    location = request.form.get('location', '').strip()
    activity_type = request.form.get('activity_type', '').strip()
    observation_type = request.form.get('observation_type', '').strip()
    category = request.form.get('category', '').strip()
    risk_level = request.form.get('risk_level', '').strip()
    description = request.form.get('description', '').strip()
    action_taken = request.form.get('action_taken', '').strip()

    allowed_categories = {'Unsafe Act', 'Unsafe Condition', 'Positive Behavior'}
    allowed_risk_levels = {'Low', 'Medium', 'High', 'N/A'}
    industry_taxonomy = OBSERVATION_TAXONOMY.get(industry)
    if (
        not industry_taxonomy
        or activity_type not in industry_taxonomy
        or observation_type not in industry_taxonomy.get(activity_type, [])
    ):
        abort(400, description='Select a valid work activity and observation type.')
    if category not in allowed_categories or risk_level not in allowed_risk_levels:
        abort(400, description='Select a valid observation category and risk level.')
    if (
        not date_recorded
        or not location
        or len(location) > 200
        or not description
        or len(description) > 4000
        or not action_taken
        or len(action_taken) > 2000
    ):
        abort(400, description='Complete all required observation fields within their length limits.')
    try:
        datetime.strptime(date_recorded, '%Y-%m-%d')
    except ValueError:
        abort(400, description='Enter a valid observation date.')

    conn = get_db_connection()
    if contractor_id is not None:
        contractor = conn.execute('''
            SELECT contractor_id FROM contractors
            WHERE contractor_id = ? AND organization_id = ?
        ''', (contractor_id, organization_id)).fetchone()
        if not contractor:
            conn.close()
            abort(400, description='Select a contractor in this organization.')
    conn.execute('''
        INSERT INTO safety_observations (
            organization_id, contractor_id, date_recorded, location, category,
            risk_level, action_taken, activity_type, observation_type, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        organization_id, contractor_id, date_recorded, location, category,
        risk_level, action_taken, activity_type, observation_type, description,
    ))
    conn.commit()
    conn.close()

@app.route('/submit_observation', methods=['POST'])
@module_required('safety_observations')
def submit_observation():
    contractor_id = resolve_contractor_id(request.form.get('contractor_id'))
    if not contractor_id:
        abort(400, description='Select a contractor before submitting an observation.')
    conn = get_db_connection()
    organization = conn.execute(
        'SELECT industry FROM organizations WHERE organization_id = ?',
        (current_organization_id(),),
    ).fetchone()
    conn.close()
    industry = organization['industry'] if organization else ''
    if industry not in OBSERVATION_TAXONOMY:
        industry = 'Construction'
    persist_observation(current_organization_id(), contractor_id, industry)
    return redirect(url_for('observation'))

@app.route('/observe/<token>', methods=['GET', 'POST'])
def public_observation(token):
    organization = get_public_observation_organization(token)
    if request.method == 'GET':
        response = app.make_response(
            render_public_observation_form(token, organization)
        )
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
        return response

    raw_contractor_id = request.form.get('contractor_id', '').strip()
    if raw_contractor_id and not raw_contractor_id.isdigit():
        abort(400, description='Select a valid contractor.')
    contractor_id = int(raw_contractor_id) if raw_contractor_id else None
    industry = organization['industry']
    if industry not in OBSERVATION_TAXONOMY:
        industry = 'Construction'
    persist_observation(
        organization['organization_id'], contractor_id, industry
    )
    return render_template(
        'observation_submitted.html',
        organization_name=organization['organization_name'],
    )

@app.route('/inspection')
@module_required('site_inspections')
def inspection():
    return render_template(
        'inspection_report.html',
        contractors=get_available_contractors(),
        inspection_checkpoints=INSPECTION_CHECKPOINTS,
    )

INSPECTION_CHECKPOINTS = {
    'Oil & Gas': {
        'Hot Work': [
            'Approved hot-work permit and gas test are valid for the work location and duration.',
            'Combustibles are removed or protected; fire watch and suitable extinguishers are present.',
            'Nearby process lines and equipment are isolated or protected against heat, sparks, and ignition.',
            'Gas detector is suitable, in calibration, and bump-tested; readings remain within site limits.',
            'Welding leads, return clamp, torch, hoses, and cylinders are in safe condition and secured.',
            'Area is barricaded and adjacent workers are protected from arc flash, sparks, and fumes.',
            'Required PPE, respiratory controls, and safe access are in place.',
            'Post-work fire watch and permit close-out requirements are understood.',
        ],
        'Confined Space Entry': [
            'Confined-space permit, entry authorization, and task risk assessment are approved.',
            'All energy and process sources are positively isolated, locked, tagged, and verified.',
            'Atmosphere is tested for oxygen, flammable gas, and toxic contaminants before entry.',
            'Continuous or scheduled atmospheric monitoring and effective ventilation are in place.',
            'Dedicated attendant maintains entrant count and reliable communication.',
            'Rescue plan, retrieval equipment, and competent rescue response are ready before entry.',
            'Entry/exit routes are clear and lighting and tools are suitable for the space.',
            'Entrants use required PPE and understand stop-work and evacuation triggers.',
        ],
        'Drilling & Well Servicing': [
            'Well-control equipment is installed, inspected, tested, and suitable for the operation.',
            'Well-control barriers and pressure-control status are confirmed before work starts.',
            'Drilling/workover program, permits, and simultaneous-operations controls are current.',
            'Pressure-rated hoses, connections, lines, and restraints are inspected and secured.',
            'Red zones and line-of-fire areas are identified, barricaded, and kept clear.',
            'Gas detection, alarms, emergency shutdowns, and escape routes are available.',
            'Lifting equipment, handling tools, and tubular restraints are inspected and fit for use.',
            'Crew roles, well-control response, and emergency communications are briefed.',
        ],
        'Pipeline Work': [
            'Line location, ownership, contents, pressure, and isolation limits are positively confirmed.',
            'Depressurization, draining, purging, and zero-energy verification are documented.',
            'Excavation permits, utility locating, support, access, and spoil controls are in place.',
            'Hot-work or cold-cutting controls match the line contents and residual-hazard assessment.',
            'Pressure-test limits, exclusion zone, calibrated gauges, and test boundaries are defined.',
            'Pipe handling, lifting points, rigging, and stored-energy hazards are controlled.',
            'Environmental containment and spill response are ready for the work area.',
            'Tie-in, reinstatement, leak testing, and handover steps are authorized and briefed.',
        ],
        'Process Operations & Line Breaking': [
            'Current process drawings and equipment identity are verified at the worksite.',
            'Permit, isolation certificate, and approved line-break sequence are available.',
            'Correct valves, blinds, locks, and tags are installed and independently verified.',
            'Pressure, temperature, inventory, and trapped-energy hazards are relieved and checked.',
            'Contents and possible toxic, corrosive, flammable, or oxygen-deficient hazards are known.',
            'Gas testing, ventilation, PPE, and exposure controls match the process hazards.',
            'Drainage, containment, emergency shower/eyewash, and spill response are accessible.',
            'Operations coordination, exclusion zone, and safe reinstatement/handover are confirmed.',
        ],
        'Mechanical Erection & Maintenance': [
            'Work permit, task risk assessment, equipment identity, and approved method are confirmed.',
            'Electrical, mechanical, hydraulic, pneumatic, and process energy are isolated and verified.',
            'Equipment is stable, supported, and protected against movement or stored-energy release.',
            'Lifting plan, certified accessories, load path, and exclusion zone are suitable for the task.',
            'Dropped-object controls and secure tool/material handling are in place.',
            'Access, work-at-height protection, and scaffold/platform condition are acceptable.',
            'Fit-for-purpose tools, guards, and required PPE are available and used.',
            'Reassembly checks, guard restoration, testing authorization, and handback are defined.',
        ],
        'Electrical Work & LOTO': [
            'Electrical work permit and approved isolation boundaries match the equipment.',
            'Correct circuit/equipment identity is independently confirmed before isolation.',
            'Lockout/tagout is applied by authorized personnel and absence of voltage is tested.',
            'Test instrument is correctly rated, inspected, and proven before and after use.',
            'Arc-flash/shock boundaries, approach distances, and barriers are established.',
            'Temporary power, cables, grounding, and protective devices are suitable and inspected.',
            'Required electrical PPE, insulated tools, and rescue arrangements are available.',
            'Re-energization, personnel clearance, and authorization to return to service are controlled.',
        ],
        'Lifting & Crane Operations': [
            'Approved lift plan identifies load weight, center of gravity, crane capacity, and lift path.',
            'Crane setup, ground bearing, outriggers, level, and operating limits are verified.',
            'Crane, rigging gear, hooks, and lifting points are inspected and suitable for the load.',
            'Competent operator, rigger, and signaler are assigned with clear communication.',
            'Exclusion zone and suspended-load/line-of-fire controls are maintained.',
            'Nearby power lines, structures, process equipment, and simultaneous work are controlled.',
            'Weather, visibility, and wind are within equipment and site limits.',
            'Trial lift, load control, landing area, and emergency stop arrangements are understood.',
        ],
        'Excavation & Ground Disturbance': [
            'Ground-disturbance permit and current utility locating/mark-out are approved.',
            'Underground services are exposed or protected using the approved safe-dig method.',
            'Soil conditions and excavation protection are assessed by a competent person.',
            'Access/egress, edge protection, and safe separation from mobile equipment are provided.',
            'Spoil, materials, and equipment are kept clear of excavation edges.',
            'Water ingress, hazardous atmosphere, and adjacent structure risks are controlled.',
            'Barriers, signage, lighting, and traffic/pedestrian separation are adequate.',
            'Daily inspection and stop-work triggers after change or adverse conditions are understood.',
        ],
        'Working at Height & Scaffolding': [
            'Work-at-height permit and risk assessment identify fall and dropped-object hazards.',
            'Guardrails or inspected personal fall-arrest systems are suitable and correctly anchored.',
            'Scaffold/platform is inspected, tagged, complete, and within its rated capacity.',
            'Ladders and access points are secured, suitable, and used only for permitted tasks.',
            'Openings, fragile surfaces, edges, and lower-level exposure are protected.',
            'Tools and materials are secured; exclusion zone protects people below.',
            'Rescue plan and equipment for a suspended worker are immediately available.',
            'Weather, lighting, PPE, and worker competency are suitable for the task.',
        ],
    },
    'Construction': {
        'Civil Construction & Excavation': [
            'Approved excavation permit and verified underground-service information are at the worksite.',
            'Protective system is selected for soil/depth and inspected by a competent person.',
            'Safe access/egress is provided and excavation edges are protected.',
            'Spoil, vehicles, and stored materials are kept back from the edge.',
            'Water, adjacent structures, and hazardous atmosphere risks are assessed and controlled.',
            'Plant/pedestrian routes, reversing controls, and spotter arrangements are effective.',
            'Excavation is barricaded, signed, lit, and inspected after changing conditions.',
            'Workers know emergency response, exclusion boundaries, and stop-work triggers.',
        ],
        'Structural Steel & Mechanical Erection': [
            'Approved erection sequence, lift plan, and connection details are available.',
            'Members are stable, correctly identified, and secured against unintended movement.',
            'Cranes, rigging, lifting points, and operators are inspected/authorized for the lift.',
            'Fall protection and safe access are in place for erectors at every work position.',
            'Temporary bracing and stability are maintained until permanent connections are complete.',
            'Dropped-object and suspended-load exclusion zones are enforced.',
            'Bolting, welding, and hot-work permits/fire controls are suitable for the task.',
            'Wind/weather limits, communications, and emergency arrangements are understood.',
        ],
        'Scaffolding & Temporary Works': [
            'Scaffold/temporary-works design and ground support are suitable for intended loading.',
            'Erection, alteration, and dismantling are controlled by competent authorized personnel.',
            'Platforms are fully decked, secured, guarded, and free from unsafe gaps.',
            'Bracing, ties, base plates, access, and scaffold condition pass the required inspection.',
            'Scaffold status tag is current and capacity is not exceeded.',
            'Fall protection and dropped-object controls are used during scaffold work.',
            'Public, vehicle, overhead-line, and adjacent-work interfaces are controlled.',
            'Changes, damage, weather effects, and handover are inspected before use.',
        ],
        'Concrete, Formwork & Rebar': [
            'Formwork/falsework design, supports, ties, and inspection release are verified before pour.',
            'Pour sequence, load limits, pump setup, and exclusion areas are briefed.',
            'Concrete pump, hoses, couplings, restraints, and emergency stop are inspected.',
            'Rebar ends are protected and reinforcement mats are stable with safe access.',
            'Workers are protected from cement burns, splashes, silica, and required exposures.',
            'Work platforms, edge protection, and access are safe during placing and finishing.',
            'Electrical leads, tools, and lighting are suitable for wet conditions.',
            'Pour monitoring, stop criteria, curing barriers, and post-pour inspection are assigned.',
        ],
        'Roadworks & Mobile Plant': [
            'Approved traffic-management plan, signs, barriers, and work-zone limits are in place.',
            'Pedestrians are physically separated from plant and live traffic.',
            'Plant pre-use checks, alarms, cameras, lights, and brakes are satisfactory.',
            'Operators are authorized and seat belts/restraints are used.',
            'Reversing, blind spots, spotters, and exclusion zones are controlled.',
            'Ground stability, slopes, edge protection, and overhead hazards are assessed.',
            'Dust, noise, visibility, and worker high-visibility PPE are controlled.',
            'Emergency access, communications, and vehicle/pedestrian diversion are maintained.',
        ],
        'Demolition': [
            'Current structural survey, demolition sequence, and competent supervision are confirmed.',
            'Utilities are identified, isolated, locked/tagged, and verified before disturbance.',
            'Hazardous materials and unknown substances are assessed before removal.',
            'Collapse zones, exclusion barriers, and adjacent-structure protections are established.',
            'Plant, attachments, operators, and work platforms are suitable for the method.',
            'Dust, noise, vibration, debris, and public exposure are controlled.',
            'Fall protection, dropped-object, and safe access controls are in place.',
            'Emergency plan, ongoing stability checks, and stop-work criteria are briefed.',
        ],
        'Electrical Installation': [
            'Approved electrical drawings, permit, and equipment identification match the installation.',
            'Circuits are isolated and absence of voltage verified before contact.',
            'Temporary power has suitable RCD/GFCI protection, grounding, and inspected leads.',
            'Cables are routed to prevent damage, trip hazards, and contact with water or traffic.',
            'Panels, enclosures, and exposed conductors are guarded and secured.',
            'Safe access, barriers, and separation from other trades are maintained.',
            'Authorized workers use correctly rated tools and electrical PPE.',
            'Testing, labeling, energization authorization, and handover are controlled.',
        ],
        'Roofing & Work at Height': [
            'Roof access permit and assessment identify edges, openings, and fragile surfaces.',
            'Collective edge protection or inspected fall-arrest system is effective and anchored.',
            'Fragile roof areas and skylights are covered, guarded, and clearly marked.',
            'Safe access routes, ladders, platforms, and roof loading limits are confirmed.',
            'Tools/materials are secured and drop zones below are barricaded.',
            'Weather, wind, heat, and surface conditions are suitable for work.',
            'Rescue plan and fall-arrest recovery equipment are ready.',
            'Workers are trained, equipped, and briefed on stop-work triggers.',
        ],
        'Lifting & Crane Operations': [
            'Lift plan confirms load weight, crane capacity, rigging, and travel/landing path.',
            'Crane setup and ground bearing are checked; outrigger limits are respected.',
            'Crane, accessories, and lifting points are inspected and fit for use.',
            'Competent operator, rigger, and signaler use agreed signals/radio protocol.',
            'Suspended-load, swing-radius, and public-access exclusion zones are maintained.',
            'Overhead services, structures, and simultaneous operations are controlled.',
            'Weather and visibility remain within equipment/site limits.',
            'Trial lift, load control, and emergency stop arrangements are understood.',
        ],
        'Mechanical, Plumbing & HVAC': [
            'Permit, drawings, work sequence, and interface hazards are reviewed before work.',
            'Pipes, ducts, and equipment are supported against movement or collapse.',
            'Pressure, electrical, rotating, and stored-energy sources are isolated and verified.',
            'Hot work, brazing, or cutting has suitable permit, gas test, and fire controls.',
            'Lifting/handling aids and manual-handling routes are suitable for the load.',
            'Work-at-height access, scaffold, and dropped-object controls are adequate.',
            'Open pipework/ducts are capped or protected against entry and contamination.',
            'Pressure testing, flushing, guarding, and handover are authorized and controlled.',
        ],
    },
    'Manufacturing': {
        'Machine Operation & Production': [
            'Machine guards, interlocks, and emergency stops are present and functional.',
            'Operators are trained and authorized for the machine and current process.',
            'Point-of-operation, nip, shear, entanglement, and ejection hazards are guarded.',
            'Safe operating procedure and startup/changeover checks are followed.',
            'No bypassed guards, defeated interlocks, or unsafe reaching into equipment.',
            'Work area, walkways, and material staging are clear and stable.',
            'Required PPE, noise, dust, fume, and ergonomic controls are in place.',
            'Abnormal conditions, jam clearing, and stop-work/reporting steps are understood.',
        ],
        'Maintenance & Lockout/Tagout': [
            'Maintenance permit and equipment-specific energy-control procedure are available.',
            'All electrical, mechanical, hydraulic, pneumatic, thermal, and process sources are isolated.',
            'Personal locks/tags are applied and zero-energy state is verified before work.',
            'Stored energy is discharged, blocked, restrained, or otherwise controlled.',
            'Group lockout, shift handover, and affected-worker notifications are managed.',
            'Tools, replacement parts, and access platforms are suitable and inspected.',
            'Guards and safety devices are restored before authorized testing.',
            'Personnel clearance, lock removal, and return-to-service authorization are controlled.',
        ],
        'Forklift & Material Handling': [
            'Vehicle pre-use check, capacity plate, tires, forks, brakes, and restraints are satisfactory.',
            'Operator is trained/authorized and seat belt or restraint is used.',
            'Pedestrian routes are separated; crossings, visibility, and right-of-way are controlled.',
            'Loads are stable, within capacity, secured, and carried at safe travel height.',
            'Speed, reversing, turning, ramps, and blind corners are controlled.',
            'Racking, dock edges, trailers, and floor capacity are protected and inspected.',
            'Charging/fueling, battery, and hazardous-material controls are followed.',
            'Parking, key control, and defect reporting prevent unintended operation.',
        ],
        'Conveyor & Automated Equipment': [
            'Fixed/interlocked guards cover nip points, rollers, drives, and transfer points.',
            'Emergency-stop devices and pull cords are accessible, tested, and unobstructed.',
            'Jam clearing and adjustment follow isolation and zero-energy verification.',
            'Workers cannot reach into running equipment or enter robot/automated cells.',
            'Pedestrian crossings and interaction with mobile equipment are protected.',
            'Conveyor supports, belts, sensors, and guarding are in safe condition.',
            'Authorized access, warning systems, and restart communication are effective.',
            'Housekeeping prevents slips, trips, entanglement, and material buildup.',
        ],
        'Welding & Hot Work': [
            'Hot-work permit, area assessment, and gas test are completed where required.',
            'Combustibles are removed/protected and fire watch/extinguishers are available.',
            'Welding machine, cables, return clamp, torch, hoses, and cylinders are inspected.',
            'Fume extraction and respiratory protection are suitable for the material/process.',
            'Screens protect others from arc flash, sparks, and radiation.',
            'Gas cylinders are upright, secured, capped for movement, and separated as required.',
            'PPE, electrical protection, and safe work positioning are adequate.',
            'Post-work fire check, housekeeping, and permit close-out are completed.',
        ],
        'Chemical & Process Handling': [
            'Chemical identity, current safety data, and task-specific risk controls are available.',
            'Containers, labels, transfer lines, and connections are compatible and in good condition.',
            'Ventilation, closed transfer, and exposure controls are functioning.',
            'Required chemical PPE, eyewash, and safety shower are accessible and serviceable.',
            'Secondary containment, spill kit, and waste segregation are suitable.',
            'Incompatible chemicals and ignition sources are separated and controlled.',
            'Process alarms, pressure controls, guards, and emergency shutdown are available.',
            'Workers know exposure response, spill escalation, and emergency evacuation actions.',
        ],
        'Confined Space Entry': [
            'Entry permit, space identification, and task risk assessment are approved.',
            'All connected energy and process sources are isolated and verified.',
            'Pre-entry atmospheric testing covers oxygen, flammable, and toxic hazards.',
            'Ventilation and ongoing atmospheric monitoring are adequate.',
            'Dedicated attendant, entrant register, and reliable communication are maintained.',
            'Rescue team, retrieval equipment, and rescue plan are ready before entry.',
            'Lighting, access, tools, and PPE are suitable for the space.',
            'Stop-work, evacuation alarms, and emergency response are briefed.',
        ],
        'Electrical & Control Panel Work': [
            'Electrical permit and panel/circuit identity are verified before work.',
            'Isolation, lockout/tagout, and absence-of-voltage test are confirmed.',
            'Test instruments and tools have suitable ratings and are inspected.',
            'Arc-flash/shock assessment, boundaries, barriers, and PPE are appropriate.',
            'Cabinet covers, exposed conductors, and adjacent live equipment are controlled.',
            'Temporary leads, grounding, and work-area access are safe.',
            'Only authorized personnel perform electrical or control-system work.',
            'Testing, panel closure, personnel clearance, and re-energization are authorized.',
        ],
        'Presses, Moulding & Stored Energy': [
            'Point-of-operation guarding and safety interlocks are fitted and functional.',
            'Press/moulding cycle, two-hand controls, light curtains, or presence sensing are verified.',
            'Die/tooling is secured, rated, and changed using an approved procedure.',
            'Hydraulic, pneumatic, thermal, and mechanical stored energy is isolated before access.',
            'Jam clearing and adjustment are performed only under safe isolation.',
            'Hot surfaces, molten material, ejection, and splash hazards are shielded/controlled.',
            'Operator competency, PPE, and safe loading/unloading are confirmed.',
            'Emergency stop, restart prevention, and defect reporting are effective.',
        ],
        'Packaging & Palletizing': [
            'Guards and interlocks protect sealing, cutting, wrapping, and palletizing mechanisms.',
            'Emergency stops are accessible and functional at operator positions.',
            'Jam clearing, blade changes, and adjustments require safe isolation.',
            'Robot/cobot cells, light curtains, and restricted zones prevent unexpected access.',
            'Pallets, loads, and stacking patterns are stable and within equipment limits.',
            'Forklift/pedestrian interfaces and pallet transfer points are controlled.',
            'Manual handling, repetitive motion, and ergonomic risks are reduced.',
            'Housekeeping, packaging waste, and fire-load controls are maintained.',
        ],
    },
}

@app.route('/submit_inspection', methods=['POST'])
@module_required('site_inspections')
def submit_inspection():
    inspection_date = request.form['inspection_date']
    inspector_name = request.form['inspector_name']
    selected_operation = request.form.get('trade_type', '')
    try:
        industry, trade_type = selected_operation.split('::', 1)
    except ValueError:
        abort(400, description='Select a valid inspection operation or trade.')
    major_findings = request.form['major_findings']
    contractor_id = resolve_contractor_id(request.form.get('contractor_id'))
    if not contractor_id:
        abort(400, description='Select a contractor before submitting an inspection.')
    activity_checkpoints = INSPECTION_CHECKPOINTS.get(industry, {}).get(trade_type)
    if activity_checkpoints is None:
        abort(400, description='Select a valid inspection operation or trade.')
    trade_type = f'{industry} - {trade_type}'
    checklist_statuses = [
        request.form.get(f'checkpoint_{index}', '')
        for index in range(1, len(activity_checkpoints) + 1)
    ]
    if any(value not in {'Pass', 'Fail', 'N/A'} for value in checklist_statuses):
        abort(400, description='Complete every inspection checklist item.')
    checklist = {
        label: status
        for label, status in zip(activity_checkpoints, checklist_statuses)
    }
    applicable_items = [
        value for value in checklist_statuses if value != 'N/A'
    ]
    compliance_score = (
        sum(value == 'Pass' for value in applicable_items)
        / len(applicable_items) * 100
        if applicable_items else 0.0
    )

    conn = get_db_connection()
    conn.execute('''
        INSERT INTO hse_inspections (
            organization_id, contractor_id, inspection_date, inspector_name,
            trade_type, checklist_json, major_findings, compliance_score
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        current_organization_id(), contractor_id, inspection_date,
        inspector_name, trade_type, json.dumps(checklist), major_findings,
        compliance_score,
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('inspection'))

@app.route('/monthly_stats')
@module_required('monthly_statistics')
def monthly_stats():
    return render_template(
        'monthly_statistics.html',
        contractors=get_available_contractors(),
    )

def get_monthly_report_counts(organization_id, contractor_id, report_month):
    month_start = datetime.strptime(report_month, '%Y-%m').date()
    next_month = (
        month_start.replace(year=month_start.year + 1, month=1)
        if month_start.month == 12
        else month_start.replace(month=month_start.month + 1)
    )
    start_date = month_start.isoformat()
    end_date = next_month.isoformat()
    conn = get_db_connection()
    incidents = conn.execute('''
        SELECT lower(trim(incident_type)) AS incident_type, COUNT(*) AS case_count
        FROM incidents
        WHERE organization_id = ? AND contractor_id = ?
          AND report_date >= ? AND report_date < ?
        GROUP BY lower(trim(incident_type))
    ''', (organization_id, contractor_id, start_date, end_date)).fetchall()
    counts_by_type = {row['incident_type']: row['case_count'] for row in incidents}
    observations = conn.execute('''
        SELECT COUNT(*) FROM safety_observations
        WHERE organization_id = ? AND contractor_id = ?
          AND date_recorded >= ? AND date_recorded < ?
    ''', (organization_id, contractor_id, start_date, end_date)).fetchone()[0]
    inspections = conn.execute('''
        SELECT COUNT(*) FROM hse_inspections
        WHERE organization_id = ? AND contractor_id = ?
          AND inspection_date >= ? AND inspection_date < ?
    ''', (organization_id, contractor_id, start_date, end_date)).fetchone()[0]
    conn.close()

    fatalities = counts_by_type.get('fatality', 0)
    days_away_cases = counts_by_type.get('lti', 0) + counts_by_type.get(
        'lost time injury', 0
    )
    restricted_cases = counts_by_type.get('restricted work case', 0) + counts_by_type.get(
        'restricted duty', 0
    )
    other_recordables = counts_by_type.get('medical treatment', 0) + counts_by_type.get(
        'medical treatment case', 0
    ) + counts_by_type.get('mtc', 0)
    return {
        'fatalities': fatalities,
        'days_away_cases': days_away_cases,
        'restricted_cases': restricted_cases,
        'other_recordables': other_recordables,
        'near_misses': counts_by_type.get('near miss', 0),
        'observations_recorded': observations,
        'inspections_performed': inspections,
    }

@app.route('/api/monthly-stats/metrics')
@module_required('monthly_statistics')
def monthly_stats_metrics():
    contractor_id = resolve_contractor_id(
        request.args.get('contractor_id', '').strip()
    )
    if not contractor_id:
        abort(400, description='Select a contractor to load automatic counts.')
    report_month = request.args.get('report_month', '').strip()
    try:
        datetime.strptime(report_month, '%Y-%m')
    except ValueError:
        abort(400, description='Select a valid reporting month.')
    return get_monthly_report_counts(
        current_organization_id(), contractor_id, report_month
    )

def calculate_safety_rates(data, base_hours=200000):
    hours = float(data['total_hours'])
    fatalities = int(data['fatalities'])
    days_away = int(data['days_away_cases'])
    restricted = int(data['restricted_cases'])
    recordable_cases = fatalities + days_away + restricted + int(data['other_recordables'])

    def rate(count):
        return round(count * base_hours / hours, 2) if hours > 0 else 0.0

    return {
        'recordable_cases': recordable_cases,
        'trir': rate(recordable_cases),
        'dart_rate': rate(days_away + restricted),
        'dafw_rate': rate(days_away),
        'ltir': rate(days_away),
        'severity_rate': rate(int(data['days_away_total'])),
        'fatality_rate': rate(fatalities),
    }


@app.route('/submit_monthly_stats', methods=['POST'])
@module_required('monthly_statistics')
def submit_monthly_stats():
    contractor_id = resolve_contractor_id(request.form.get('contractor_id'))
    if not contractor_id:
        abort(400, description='Select a contractor before submitting monthly statistics.')
    report_month = request.form.get('report_month', '')
    try:
        datetime.strptime(report_month, '%Y-%m')
    except ValueError:
        abort(400, description='Select a valid reporting month.')
    fields = (
        'avg_employees', 'working_days', 'daily_hours', 'total_hours',
        'safe_hours', 'fatalities', 'days_away_cases',
        'restricted_cases', 'other_recordables', 'days_away_total',
        'days_restricted_total', 'toolboxes_conducted', 'near_misses',
        'observations_recorded', 'inspections_performed',
        'executive_summary',
    )
    data = {field: request.form.get(field, '').strip() for field in fields}
    for field in ('avg_employees', 'working_days', 'toolboxes_conducted'):
        try:
            value = int(data[field])
        except ValueError:
            abort(400, description=f'Enter a whole number for {field.replace("_", " ")}.')
        if value < 0:
            abort(400, description=f'{field.replace("_", " ").title()} cannot be negative.')
        data[field] = value
    if int(data['avg_employees']) <= 0:
        abort(400, description='Number of employees must be greater than zero.')
    if int(data['working_days']) <= 0:
        abort(400, description='Number of working days must be greater than zero.')
    try:
        daily_hours = float(data['daily_hours'])
        safe_hours = float(data['safe_hours'])
    except ValueError:
        abort(400, description='Enter valid daily working hours and total safe hours.')
    if (
        not math.isfinite(daily_hours)
        or not math.isfinite(safe_hours)
        or daily_hours <= 0
        or safe_hours < 0
    ):
        abort(400, description='Daily working hours must be positive and safe hours cannot be negative.')
    data['daily_hours'] = daily_hours
    data['safe_hours'] = safe_hours
    data['total_hours'] = round(
        int(data['avg_employees']) * int(data['working_days']) * daily_hours, 2
    )

    metric_modes = {
        'recordables_mode': ('fatalities', 'days_away_cases', 'restricted_cases', 'other_recordables'),
        'near_misses_mode': ('near_misses',),
        'observations_mode': ('observations_recorded',),
        'inspections_mode': ('inspections_performed',),
    }
    for mode_field in metric_modes:
        data[mode_field] = request.form.get(mode_field, 'manual').strip()
        if data[mode_field] not in {'manual', 'automatic'}:
            abort(400, description='Choose manual or automatic mode for each metric.')
    automatic_counts = get_monthly_report_counts(
        current_organization_id(), contractor_id, report_month
    )
    for mode_field, value_fields in metric_modes.items():
        for field in value_fields:
            if data[mode_field] == 'automatic':
                data[field] = automatic_counts[field]
            else:
                try:
                    value = int(request.form.get(field, '').strip())
                except ValueError:
                    abort(400, description=f'Enter a whole number for {field.replace("_", " ")}.')
                if value < 0:
                    abort(400, description=f'{field.replace("_", " ").title()} cannot be negative.')
                data[field] = value
    for field in ('days_away_total', 'days_restricted_total'):
        try:
            value = int(request.form.get(field, '').strip())
        except ValueError:
            abort(400, description=f'Enter a whole number for {field.replace("_", " ")}.')
        if value < 0:
            abort(400, description=f'{field.replace("_", " ").title()} cannot be negative.')
        data[field] = value
    data.update(calculate_safety_rates(data))
    now = datetime.now(timezone.utc).isoformat()
    conn = get_db_connection()
    conn.execute('''
        INSERT INTO monthly_statistics (
            organization_id, contractor_id, report_month, data_json,
            submitted_by, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (organization_id, contractor_id, report_month)
        DO UPDATE SET data_json = excluded.data_json,
                      submitted_by = excluded.submitted_by,
                      updated_at = excluded.updated_at
    ''', (
        current_organization_id(), contractor_id, report_month,
        json.dumps(data), session.get('user_id'), now, now,
    ))
    conn.commit()
    conn.close()
    return redirect(url_for('monthly_stats'))

@app.route('/training_performance')
@module_required('training_performance')
def training_performance():
    return render_template('training_performance.html')

@app.route('/api/training-records', methods=['GET', 'PUT'])
@module_required('training_performance')
def training_records_api():
    organization_id = current_organization_id()
    contractor_id = resolve_contractor_id()
    is_admin = session.get('is_admin') or session.get('is_legacy_admin')
    conn = get_db_connection()
    if request.method == 'GET':
        query = '''
            SELECT record_json FROM training_records
            WHERE organization_id = ?
        '''
        params = [organization_id]
        if not is_admin:
            query += ' AND contractor_id = ?'
            params.append(contractor_id)
        query += ' ORDER BY updated_at DESC'
        records = conn.execute(query, params).fetchall()
        conn.close()
        return {'records': [json.loads(row['record_json']) for row in records]}

    if not request.is_json:
        conn.close()
        abort(400, description='Training records must be submitted as JSON.')
    payload = request.get_json()
    records = payload.get('records') if isinstance(payload, dict) else None
    deleted_ids = payload.get('deleted_ids', []) if isinstance(payload, dict) else []
    if not isinstance(records, list):
        conn.close()
        abort(400, description='Training records must be submitted as a list.')
    assert isinstance(records, list)
    if len(records) > 500:
        conn.close()
        abort(400, description='Submit at most 500 training records at a time.')
    if not isinstance(deleted_ids, list):
        conn.close()
        abort(400, description='Deleted training record IDs are invalid.')
    assert isinstance(deleted_ids, list)
    if len(deleted_ids) > 500 or not all(
        isinstance(record_id, str) and 0 < len(record_id) <= 100
        for record_id in deleted_ids
    ):
        conn.close()
        abort(400, description='Deleted training record IDs are invalid.')

    allowed_fields = {
        'vertical', 'department', 'role', 'module', 'employee',
        'status', 'completionDate',
    }
    field_limits = {
        'vertical': 80, 'department': 120, 'role': 120, 'module': 160,
        'employee': 120, 'status': 20, 'completionDate': 20,
    }
    normalized_records = []
    seen_ids = set()
    for record in records:
        if not isinstance(record, dict):
            conn.close()
            abort(400, description='Each training record must be an object.')
        record_id = record.get('id')
        if not isinstance(record_id, (str, int)) or not str(record_id) or len(str(record_id)) > 100:
            conn.close()
            abort(400, description='A training record has an invalid ID.')
        record_id = str(record_id)
        if record_id in seen_ids:
            conn.close()
            abort(400, description='Training record IDs must be unique in each request.')
        seen_ids.add(record_id)
        clean_record = {
            field: str(record.get(field, '')).strip()
            for field in allowed_fields
        }
        if (
            any(len(clean_record[field]) > limit for field, limit in field_limits.items())
            or not clean_record['employee']
            or clean_record['status'] not in {'Not Started', 'In Progress', 'Completed'}
            or not clean_record['module']
        ):
            conn.close()
            abort(400, description='Training records require an employee, module, and valid status.')
        clean_record['id'] = record_id
        normalized_records.append(clean_record)
    if not is_admin:
        requested_ids = set(deleted_ids) | {
            record['id'] for record in normalized_records
        }
        for record_id in requested_ids:
            existing = conn.execute('''
                SELECT contractor_id FROM training_records
                WHERE organization_id = ? AND training_record_id = ?
            ''', (organization_id, record_id)).fetchone()
            if existing and existing['contractor_id'] != contractor_id:
                conn.close()
                abort(403, description='You can only manage your subcontractor training records.')
    now = datetime.now(timezone.utc).isoformat()
    with conn:
        for record_id in deleted_ids:
            conn.execute(
                'DELETE FROM training_records WHERE organization_id = ? AND training_record_id = ?',
                (organization_id, record_id),
            )
        for record in normalized_records:
            conn.execute('''
                INSERT INTO training_records (
                    training_record_id, organization_id, contractor_id,
                    record_json, created_by, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (organization_id, training_record_id)
                DO UPDATE SET contractor_id = excluded.contractor_id,
                              record_json = excluded.record_json,
                              created_by = excluded.created_by,
                              updated_at = excluded.updated_at
            ''', (
                record['id'], organization_id, contractor_id,
                json.dumps(record), session.get('user_id'), now,
            ))
    conn.close()
    return {'saved': len(normalized_records), 'deleted': len(deleted_ids)}


if __name__ == '__main__':
    if os.environ.get('HSE_ENV', '').lower() == 'production':
        from waitress import serve
        serve(
            app,
            host=os.environ.get('HSE_HOST', '127.0.0.1'),
            port=int(os.environ.get('HSE_PORT', '5000')),
            threads=int(os.environ.get('HSE_THREADS', '8')),
        )
    else:
        app.run(debug=False, host='0.0.0.0', port=5000)