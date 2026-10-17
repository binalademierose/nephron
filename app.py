"""
app.py - creates and configures the Flask application.

Run it with:   python app.py
"""
import logging
import os
from datetime import date, datetime
from logging.handlers import RotatingFileHandler

from flask import Flask, g, request

import db
from config import Config, validate_config
from routes.account_routes import account_bp
from routes.auth_hooks import register_auth_hooks
from routes.auth_routes import auth_bp
from routes.authorization_routes import authorization_bp
from routes.design_routes import design_bp
from routes.history_routes import history_bp
from routes.lab_routes import lab_bp
from routes.report_routes import reports_bp
from routes.resource_routes import resource_bp
from routes.followup_routes import followup_bp
from routes.patient_records_routes import patient_records_bp
from routes.admin_routes import admin_bp
from routes.notification_routes import notification_bp
from routes.screening_routes import screening_bp
from routes.error_handlers import register_error_handlers
from routes.main_routes import main_bp
from services import notifications, security, visuals
from services import clock, lab_contract, screening_contract
from services.assessment_store import MemoryAssessmentStore, MySQLAssessmentStore
from services.authorization_store import MemoryAuthorizationStore, MySQLAuthorizationStore
from services.clinical_review_store import MemoryClinicalReviewStore, MySQLClinicalReviewStore
from services.followup_store import MemoryFollowUpStore, MySQLFollowUpStore
from services.checklist_store import MemoryChecklistStore, MySQLChecklistStore
from services.activity_store import MemoryActivityStore, MySQLActivityStore
from services.consent_store import MemoryConsentStore, MySQLConsentStore
from services.followup_appointment_store import MemoryFollowUpAppointmentStore, MySQLFollowUpAppointmentStore
from services.notification_store import MemoryNotificationStore, MySQLNotificationStore
from services.patient_records_store import MemoryPatientRecordsStore, MySQLPatientRecordsStore
from services.screening_draft_store import MemoryScreeningDraftStore, MySQLScreeningDraftStore
from services.lab_document_store import MemoryLabDocumentStore, MySQLLabDocumentStore
from services.model_service import ModelService
from services.model_service_stage2 import Stage2ModelService
from services.reassessment_store import MemoryReassessmentStore, MySQLReassessmentStore
from services.user_store import MySQLUserStore


def create_app(overrides=None, user_store=None, assessment_store=None, model_service=None,
              lab_document_store=None, model_service_stage2=None, authorization_store=None,
              clinical_review_store=None, followup_store=None, screening_draft_store=None, notification_store=None,
              followup_appointment_store=None, checklist_store=None, consent_store=None, patient_records_store=None,
              reassessment_store=None):
    """
    Build the app. The automated tests use `overrides` (settings) and `user_store` / `assessment_store`
    (in-memory stores, so they need no database) and `model_service` (a stand-in model). A test that supplies an
    in-memory user store and no model service gets "no model installed", so the tests never depend on a real model file.
    """
    app = Flask(__name__)
    app.config.from_object(Config)
    if overrides:
        app.config.update(overrides)
    validate_config(app.config)

    # Behind a trusted reverse proxy (Vercel, nginx, ...), read the real scheme/host/client IP from its forwarded
    # headers, so request.is_secure is true for HTTPS traffic (HSTS and secure cookies then behave correctly) and
    # the logged client IP is the real one. Only enabled when TRUSTED_PROXY_COUNT says a proxy is really there -
    # otherwise these headers are ignored so a direct client cannot spoof them (see config.py).
    hops = app.config.get("TRUSTED_PROXY_HOPS", 0)
    if hops:
        from werkzeug.middleware.proxy_fix import ProxyFix
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    _setup_logging(app)

    # Close the database connection after every request.
    app.teardown_appcontext(db.close_db)

    # Where user accounts are kept, and the code that knows who is signed in (runs on every request).
    app.extensions["user_store"] = user_store or MySQLUserStore()
    if assessment_store is None:
        # A test that supplies an in-memory user store gets an in-memory assessment store that checks against it.
        assessment_store = MemoryAssessmentStore(app.extensions["user_store"]) if user_store else MySQLAssessmentStore()
    app.extensions["assessment_store"] = assessment_store
    if authorization_store is None:
        authorization_store = MemoryAuthorizationStore(app.extensions["user_store"]) if user_store else MySQLAuthorizationStore()
    app.extensions["authorization_store"] = authorization_store
    if clinical_review_store is None:
        clinical_review_store = MemoryClinicalReviewStore(assessment_store) if user_store else MySQLClinicalReviewStore()
    app.extensions["clinical_review_store"] = clinical_review_store
    if followup_store is None:
        followup_store = MemoryFollowUpStore(app.extensions["user_store"]) if user_store else MySQLFollowUpStore()
    app.extensions["followup_store"] = followup_store
    if screening_draft_store is None:
        screening_draft_store = MemoryScreeningDraftStore() if user_store else MySQLScreeningDraftStore()
    app.extensions["screening_draft_store"] = screening_draft_store
    if notification_store is None:
        notification_store = MemoryNotificationStore() if user_store else MySQLNotificationStore()
    app.extensions["notification_store"] = notification_store
    if followup_appointment_store is None:
        followup_appointment_store = MemoryFollowUpAppointmentStore() if user_store else MySQLFollowUpAppointmentStore()
    app.extensions["followup_appointment_store"] = followup_appointment_store
    if checklist_store is None:
        checklist_store = MemoryChecklistStore() if user_store else MySQLChecklistStore()
    app.extensions["checklist_store"] = checklist_store
    app.extensions["activity_store"] = MemoryActivityStore() if user_store else MySQLActivityStore()
    if reassessment_store is None:
        reassessment_store = MemoryReassessmentStore(app.extensions["user_store"]) if user_store else MySQLReassessmentStore()
    app.extensions["reassessment_store"] = reassessment_store
    if patient_records_store is None:
        patient_records_store = MemoryPatientRecordsStore(app.extensions["user_store"]) if user_store else MySQLPatientRecordsStore()
    app.extensions["patient_records_store"] = patient_records_store
    if consent_store is None:
        consent_store = MemoryConsentStore() if user_store else MySQLConsentStore()
    app.extensions["consent_store"] = consent_store
    if lab_document_store is None:
        lab_document_store = MemoryLabDocumentStore(app.extensions["user_store"]) if user_store else MySQLLabDocumentStore()
    app.extensions["lab_document_store"] = lab_document_store

    # The screening model. It is loaded ONCE here and checked strictly (services/model_service.py). If it fails any check
    # the app still runs, screening says it is unavailable, and the reason is written to the log.
    catalog = screening_contract.load_catalog()
    app.extensions["catalog"] = catalog
    if model_service is None:
        folder = os.path.join(app.config["MODEL_DIR"], "__none__") if user_store else app.config["MODEL_DIR"]
        model_service = ModelService(folder, catalog)
        model_service.load()
    app.extensions["model_service"] = model_service
    if model_service.ready:
        app.logger.info("Screening model ready: %s, version %s", model_service.metadata["model_name"], model_service.version)
    else:
        app.logger.warning("Screening is UNAVAILABLE: %s", model_service.reason)

    # The Stage 2 (Enhanced Screening) model. Same idea: loaded once, checked strictly (services/model_service_stage2.py),
    # and the app keeps running with Enhanced Screening unavailable if it fails any check. See ml/model_stage2/README.md.
    lab_catalog = lab_contract.load_lab_catalog()
    app.extensions["lab_catalog"] = lab_catalog
    if model_service_stage2 is None:
        folder = os.path.join(app.config["MODEL_STAGE2_DIR"], "__none__") if user_store else app.config["MODEL_STAGE2_DIR"]
        model_service_stage2 = Stage2ModelService(folder, lab_catalog)
        model_service_stage2.load()
    app.extensions["model_service_stage2"] = model_service_stage2
    if model_service_stage2.ready:
        app.logger.info("Enhanced Screening model ready: %s, version %s", model_service_stage2.metadata["model_name"], model_service_stage2.version)
    else:
        app.logger.warning("Enhanced Screening is UNAVAILABLE: %s", model_service_stage2.reason)
    register_auth_hooks(app)

    # Routes (one blueprint per area of the system; more are added phase by phase).
    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(account_bp)
    app.register_blueprint(screening_bp)
    app.register_blueprint(history_bp)
    app.register_blueprint(lab_bp)
    app.register_blueprint(authorization_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(resource_bp)
    app.register_blueprint(notification_bp)
    sweetalert_file = os.path.join(app.static_folder, "vendor", "sweetalert2", "sweetalert2.all.min.js")
    app.jinja_env.globals["has_sweetalert"] = os.path.exists(sweetalert_file)    # see static/vendor/sweetalert2/README.txt
    if app.jinja_env.globals["has_sweetalert"]:
        app.logger.info("SweetAlert2: found at %s - pop-ups use it.", sweetalert_file)
    else:
        app.logger.warning("SweetAlert2: NOT found at %s - pop-ups use the built-in dialog. See static/vendor/sweetalert2/README.txt "
                           "(restart the app after adding the file).", sweetalert_file)
    # Is OCR of an uploaded lab report actually possible here? It needs the Tesseract program (not a Python
    # package). When it is absent - for example on a serverless host that cannot install system programs - the
    # photo/PDF upload would read nothing, so the Enhanced Screening pages hide the upload control and point to
    # manual entry instead (templates/lab/upload.html, templates/lab/confirm.html). Images need Tesseract; PDFs
    # also need Poppler's pdftoppm. Checked once here.
    import shutil
    tesseract = app.config.get("TESSERACT_CMD") or shutil.which("tesseract")
    app.jinja_env.globals["ocr_available"] = bool(tesseract)
    app.jinja_env.globals["ocr_pdf_available"] = bool(tesseract and shutil.which("pdftoppm"))
    if not tesseract:
        app.logger.info("OCR (Tesseract) not found - Enhanced Screening offers manual lab entry only.")

    from services.validation import COUNTRY_OPTIONS, GENDER_OPTIONS
    app.jinja_env.globals["country_options"] = COUNTRY_OPTIONS        # registration, patient records and the screening share one list
    app.jinja_env.globals["gender_options"] = GENDER_OPTIONS          # the patient-record form and the screening share one list
    from services import ph_locations
    app.jinja_env.globals.update(location_provinces=ph_locations.provinces(), location_municipalities=ph_locations.municipalities(),
                                 location_barangays=ph_locations.barangays, pangasinan_code=ph_locations.PANGASINAN,
                                 describe_location=ph_locations.describe)
    from routes.location_routes import location_bp
    app.register_blueprint(location_bp)
    app.register_blueprint(followup_bp)
    app.register_blueprint(patient_records_bp)
    app.register_blueprint(admin_bp)
    if app.debug:
        # Design previews (sample layouts of screens built in later phases).
        # They exist only while FLASK_DEBUG=1 and are not registered otherwise.
        app.register_blueprint(design_bp)
    register_error_handlers(app)

    # Chart geometry and date wording, so templates can draw real data (see services/visuals.py).
    app.jinja_env.globals.update(
        ring_geometry=visuals.ring_geometry,
        donut_geometry=visuals.donut_geometry,
        sparkline_geometry=visuals.sparkline_geometry,
        trend_frame=visuals.trend_frame,
        level_label=visuals.level_label,
        format_date=visuals.format_date,
        format_datetime=visuals.format_datetime,
        percent_text=visuals.percent_text,
        short_date=visuals.short_date,
        relative_day_text=visuals.relative_day_text,
        today=date.today,
        csrf_token=security.csrf_token,
        local_date=lambda moment: clock.to_local_date(moment, app.config["APP_TIMEZONE"]),
    )

    @app.context_processor
    def inject_template_values():
        """Values every template can use without being passed in."""
        values = {
            "APP_NAME": app.config["APP_NAME"],
            "MEDICAL_DISCLAIMER": app.config["MEDICAL_DISCLAIMER"],
            "current_year": datetime.now().year,
        }
        if getattr(g, "user", None):
            store = app.extensions["notification_store"]
            values["unread_notification_count"] = notifications.unread_count(store, g.user["user_id"])
            values["header_notifications"] = notifications.recent_for_header(store, g.user["user_id"], app.config["APP_TIMEZONE"])
        return values

    @app.after_request
    def add_security_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        # A content security policy is the main backstop against cross-site scripting: it tells the browser to run
        # and load only this site's own resources. Nephron uses NO inline <script> and NO inline event handlers
        # (every script is a file under /static), so 'self' is enough for scripts. Inline style ATTRIBUTES are used
        # (e.g. style="--i: 1"), and SweetAlert2 injects its own <style>, so styles allow 'unsafe-inline'; that does
        # not weaken the script protection, which is what matters for XSS. Everything (images, fonts, fetches) is
        # same-origin, and the app is never framed.
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; "
            "font-src 'self'; connect-src 'self'; form-action 'self'; base-uri 'self'; frame-ancestors 'none'; "
            "object-src 'none'"
        )
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), interest-cohort=()"
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        # HTTP Strict Transport Security: once a browser has seen this over HTTPS, it refuses to talk to the site
        # over plain HTTP for a year. Only sent on a secure request, so local HTTP development is unaffected. Behind
        # Vercel's proxy, request.is_secure is true because of ProxyFix (see create_app) reading X-Forwarded-Proto.
        if request.is_secure:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response

    _report_database_status(app)
    _block_until_migrated(app)
    return app


def _setup_logging(app):
    """Technical errors go to logs/nephron.log. Users only see friendly pages.

    On a host with a read-only file system (for example a serverless platform such as Vercel, where only /tmp is
    writable), the log file cannot be created. That must NOT stop the app from starting - the whole application is
    built here, at import time, so an unhandled error would make every page fail. So the file handler is attempted,
    and if the log location cannot be written the app logs to the standard error stream instead (which the platform
    captures) and keeps running. A normal server with a writable logs/ folder is unaffected.
    """
    if any(isinstance(handler, (RotatingFileHandler, logging.StreamHandler)) for handler in app.logger.handlers):
        return  # already set up (happens when tests, or a reload, create the app more than once)
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    try:
        os.makedirs(app.config["LOG_DIR"], exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(app.config["LOG_DIR"], "nephron.log"),
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        # Read-only file system (or no permission): fall back to stderr so the app still starts and still logs.
        handler = logging.StreamHandler()
        handler.setFormatter(formatter)
        app.logger.addHandler(handler)
        app.logger.setLevel(logging.INFO)
        app.logger.warning("Log directory is not writable (%s); logging to standard error instead.", app.config["LOG_DIR"])
        return
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)


def _report_database_status(app):
    """Print whether MySQL is reachable when the app starts - and whether the database is as new as the code."""
    # In debug mode Flask starts the app twice; only report from the real one.
    if app.debug and os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        return
    with app.app_context():
        is_connected, _ = db.check_database_connection()
        if not is_connected:
            app.logger.warning(
                "MySQL connection: FAILED. Check the DB_* values in .env and run "
                "'python init_db.py'. Details are in logs/nephron.log."
            )
            return
        app.logger.info("MySQL connection: OK (database '%s')", app.config["DB_NAME"])
        # Is the DATABASE as new as the CODE? New code reads tables and columns that only a newer migration adds; a
        # database without it would fail those requests with a bare "Error 500". Say so plainly instead - here at
        # startup, and on every page (see _block_until_migrated) - until 'python init_db.py' has been run.
        migrations_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "database", "migrations")
        applied = db.applied_migrations()
        pending = db.migration_files(migrations_dir) if applied is None else db.pending_migrations(applied, migrations_dir)
        app.extensions["pending_migrations"] = pending
        if pending:
            app.logger.error("DATABASE IS OLDER THAN THE CODE: %d migration(s) not applied yet (%s). "
                             "Stop the app, run 'python init_db.py', then start it again.", len(pending), ", ".join(pending))


def _block_until_migrated(app):
    """While the database is missing migrations, every page explains exactly that (a 503 that names the fix)
    instead of failing somewhere deep inside with a bare 500. Static files still load so the page is styled."""
    @app.before_request
    def database_out_of_date():
        from flask import render_template, request
        pending = app.extensions.get("pending_migrations")
        if not pending or request.endpoint == "static":
            return None
        return render_template("errors/database_update.html", page_title="Database update needed", pending=pending), 503

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=app.config["DEBUG"])
