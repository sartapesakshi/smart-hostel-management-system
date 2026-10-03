"""
Smart Hostel Management System - application entry point.

Run with:   python app.py
The app is built with the "application factory" pattern: create_app() builds a
Flask object, wires the database, security checks, blueprints (one per module)
and error pages together. Tests call create_app() with a temporary database.
"""
import os
import secrets
import sqlite3
from datetime import timedelta

from flask import (Flask, flash, g, redirect, render_template, request, session,
                   url_for)

import db
import helpers

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Pages that may be opened without logging in.
PUBLIC_ENDPOINTS = {"auth.login", "auth.setup", "auth.index"}

# Sidebar: (blueprint name, endpoint, label, icon)
NAVIGATION = [
    ("dashboard", "dashboard.index", "Dashboard", "home"),
    ("students", "students.list_students", "Students", "users"),
    ("rooms", "rooms.list_rooms", "Rooms & Beds", "bed"),
    ("fees", "fees.list_fees", "Fees", "card"),
    ("attendance", "attendance.mark", "Attendance", "check-square"),
    ("complaints", "complaints.list_complaints", "Complaints", "alert"),
    ("visitors", "visitors.list_visitors", "Visitors", "login"),
    ("staff", "staff.list_staff", "Staff", "briefcase"),
    ("reports", "reports.index", "Reports", "chart"),
    ("profile", "profile.view", "Profile & Settings", "sliders"),
]


def load_secret_key(instance_dir):
    """Secret key for signing session cookies: env variable, else a random key saved once."""
    env_key = os.environ.get("HOSTEL_SECRET_KEY")
    if env_key:
        return env_key
    os.makedirs(instance_dir, exist_ok=True)
    key_file = os.path.join(instance_dir, "secret.key")
    if os.path.exists(key_file):
        with open(key_file, encoding="utf-8") as fh:
            return fh.read().strip()
    key = secrets.token_hex(32)
    with open(key_file, "w", encoding="utf-8") as fh:
        fh.write(key)
    return key


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        DATABASE=os.path.join(BASE_DIR, "hostel.db"),
        SECRET_KEY=None,
        PERMANENT_SESSION_LIFETIME=timedelta(days=7),   # used by "Remember me"
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        MAX_CONTENT_LENGTH=1024 * 1024,
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = load_secret_key(os.path.join(BASE_DIR, "instance"))

    # --- database ---
    db.init_app(app)
    for note in db.init_db(app.config["DATABASE"]):
        print("[migration]", note)

    # --- templates helpers, security hooks, pages ---
    helpers.init_app(app)
    register_security(app)
    register_blueprints(app)
    register_error_pages(app)
    register_legacy_redirects(app)
    return app


# ------------------------------------------------------------------ security
def register_security(app):
    @app.before_request
    def protect_pages():
        """Runs before EVERY request: CSRF check, then 'is the user logged in?'."""
        endpoint = request.endpoint
        if endpoint is None or endpoint == "static":
            return None
        if request.method == "POST":
            helpers.check_csrf()

        g.user = None
        if session.get("user_id"):
            g.user = db.query_one("SELECT * FROM users WHERE id = ?", (session["user_id"],))
            if g.user is None:                       # account was deleted: drop the session
                session.clear()

        if endpoint in PUBLIC_ENDPOINTS:
            return None
        if db.scalar("SELECT COUNT(*) FROM users") == 0:
            return redirect(url_for("auth.setup"))   # first run: create the admin account
        if g.user is None:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("auth.login", next=request.full_path.rstrip("?")))
        return None

    @app.after_request
    def no_cache(response):
        """Stop browsers caching private pages (the Back button after logout shows nothing)."""
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        return response

    @app.context_processor
    def inject_layout_data():
        """Variables available in every template (sidebar, hostel name, badges)."""
        data = {"navigation": NAVIGATION, "current_user": getattr(g, "user", None)}
        if getattr(g, "user", None):
            data["hostel_name"] = db.get_setting("hostel_name")
            data["open_complaints"] = db.scalar(
                "SELECT COUNT(*) FROM complaints WHERE status <> 'Resolved'")
            data["visitors_inside"] = db.scalar(
                "SELECT COUNT(*) FROM visitors WHERE exit_time IS NULL AND visit_date = ?",
                (helpers.today(),))
        else:
            data["hostel_name"] = "Smart Hostel"
        return data


# --------------------------------------------------------------- blueprints
def register_blueprints(app):
    from routes import (attendance, auth, complaints, dashboard, fees, profile,
                        reports, rooms, staff, students, visitors)
    for module in (auth, dashboard, students, rooms, fees, attendance, complaints,
                   visitors, staff, reports, profile):
        app.register_blueprint(module.bp)


# ------------------------------------------------------------- error pages
def register_error_pages(app):
    def show(code, title, message):
        return render_template("error.html", code=code, title=title, message=message), code

    @app.errorhandler(400)
    def bad_request(error):
        return show(400, "Request could not be processed", getattr(error, "description", "Bad request."))

    @app.errorhandler(403)
    def forbidden(error):
        return show(403, "Access denied", "You do not have permission to open this page.")

    @app.errorhandler(404)
    def not_found(error):
        return show(404, "Page not found", "The page or record you asked for does not exist (it may have been deleted).")

    @app.errorhandler(405)
    def wrong_method(error):
        return show(405, "Action not allowed", "That action cannot be performed this way. Please use the buttons in the application.")

    @app.errorhandler(sqlite3.Error)
    def database_error(error):
        app.logger.exception("Database error")
        return show(500, "Database problem",
                    "The database could not complete your request. No changes were saved. Please try again.")

    @app.errorhandler(500)
    def server_error(error):
        return show(500, "Something went wrong",
                    "An unexpected error occurred. The details were written to the server log.")


# Old URLs from the first version of the project still work.
def register_legacy_redirects(app):
    @app.route("/add_student")
    def legacy_add_student():
        return redirect(url_for("students.add_student"), 301)


if __name__ == "__main__":
    # debug=False so normal users never see Python tracebacks. Use HOSTEL_DEBUG=1 while developing.
    create_app().run(host="127.0.0.1", port=5000, debug=os.environ.get("HOSTEL_DEBUG") == "1")
