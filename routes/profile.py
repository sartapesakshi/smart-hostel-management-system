"""Admin profile, password change and hostel settings."""
from flask import Blueprint, flash, g, redirect, render_template, request, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import db
import helpers
from helpers import clean

bp = Blueprint("profile", __name__, url_prefix="/profile")


def _render(profile_errors=None, password_errors=None, settings_errors=None, profile_data=None, settings_data=None):
    settings = settings_data or {k: db.get_setting(k) for k in
                                 ("hostel_name", "hostel_address", "hostel_phone", "hostel_email")}
    stats = {"students": db.scalar("SELECT COUNT(*) FROM students"),
             "payments": db.scalar("SELECT COUNT(*) FROM payments WHERE received_by = ?", (g.user["id"],)),
             "attendance": db.scalar("SELECT COUNT(*) FROM attendance WHERE marked_by = ?", (g.user["id"],))}
    return render_template("profile.html", profile_errors=profile_errors or {}, password_errors=password_errors or {},
                           settings_errors=settings_errors or {}, profile_data=profile_data or dict(g.user),
                           settings=settings, stats=stats)


@bp.route("/")
def view():
    return _render()


@bp.route("/update", methods=["POST"])
def update_profile():
    data = {k: clean(request.form.get(k)) for k in ("full_name", "email", "phone")}
    errors = {}
    if not helpers.valid_person_name(data["full_name"]):
        errors["full_name"] = "Enter your full name."
    if data["email"] and not helpers.valid_email(data["email"]):
        errors["email"] = "Enter a valid email address."
    if data["phone"]:
        phone = helpers.normalize_phone(data["phone"])
        if phone:
            data["phone"] = phone
        else:
            errors["phone"] = "Enter a valid 10-digit mobile number."
    if errors:
        flash("Profile was not updated. Please check the form.", "danger")
        return _render(profile_errors=errors, profile_data={**dict(g.user), **data})
    database = db.get_db()
    database.execute("UPDATE users SET full_name=?, email=?, phone=? WHERE id=?",
                     (data["full_name"], data["email"] or None, data["phone"] or None, g.user["id"]))
    database.commit()
    flash("Profile updated.", "success")
    return redirect(url_for("profile.view"))


@bp.route("/password", methods=["POST"])
def change_password():
    current = request.form.get("current_password", "")
    new = request.form.get("new_password", "")
    errors = {}
    if not check_password_hash(g.user["password_hash"], current):
        errors["current_password"] = "Current password is incorrect."
    problem = helpers.password_problem(new)
    if problem:
        errors["new_password"] = problem
    elif new == current:
        errors["new_password"] = "The new password must be different from the current one."
    elif new != request.form.get("confirm_password", ""):
        errors["confirm_password"] = "Passwords do not match."
    if errors:
        flash("Password was not changed. Please check the form.", "danger")
        return _render(password_errors=errors)
    database = db.get_db()
    database.execute("UPDATE users SET password_hash = ? WHERE id = ?", (generate_password_hash(new), g.user["id"]))
    database.commit()
    flash("Password changed successfully.", "success")
    return redirect(url_for("profile.view"))


@bp.route("/settings", methods=["POST"])
def update_settings():
    data = {k: clean(request.form.get(k)) for k in ("hostel_name", "hostel_address", "hostel_phone", "hostel_email")}
    errors = {}
    if not 2 <= len(data["hostel_name"]) <= 80:
        errors["hostel_name"] = "Hostel name must be 2-80 characters."
    if len(data["hostel_address"]) > 200:
        errors["hostel_address"] = "Address is too long (maximum 200 characters)."
    if data["hostel_phone"] and not helpers.normalize_phone(data["hostel_phone"]):
        errors["hostel_phone"] = "Enter a valid 10-digit mobile number or leave it empty."
    if data["hostel_email"] and not helpers.valid_email(data["hostel_email"]):
        errors["hostel_email"] = "Enter a valid email address."
    if errors:
        flash("Settings were not saved. Please check the form.", "danger")
        return _render(settings_errors=errors, settings_data=data)
    if data["hostel_phone"]:
        data["hostel_phone"] = helpers.normalize_phone(data["hostel_phone"])
    database = db.get_db()
    for key, value in data.items():
        database.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                         "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, value))
    database.commit()
    flash("Hostel settings saved.", "success")
    return redirect(url_for("profile.view"))
