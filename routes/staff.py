"""Hostel staff management."""
import sqlite3

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import db
import helpers
from helpers import clean

bp = Blueprint("staff", __name__, url_prefix="/staff")


def validate_staff(form, staff_id=None):
    data = {k: clean(form.get(k)) for k in ("full_name", "role", "phone", "email", "joining_date", "salary", "status")}
    errors = {}
    if not helpers.valid_person_name(data["full_name"]):
        errors["full_name"] = "Enter the full name (2-100 characters, no digits)."
    if data["role"] not in helpers.STAFF_ROLES:
        errors["role"] = "Select a role."
    phone = helpers.normalize_phone(data["phone"])
    if not phone:
        errors["phone"] = "Enter a valid 10-digit mobile number."
    else:
        data["phone"] = phone
        if db.query_one("SELECT 1 FROM staff WHERE phone = ? AND id <> ?", (phone, staff_id or -1)):
            errors["phone"] = "Another staff member already uses this phone number."
    if data["email"]:
        if not helpers.valid_email(data["email"]):
            errors["email"] = "Enter a valid email address."
        elif db.query_one("SELECT 1 FROM staff WHERE email = ? AND id <> ?", (data["email"], staff_id or -1)):
            errors["email"] = "Another staff member already uses this email."
    joined = helpers.parse_date(data["joining_date"])
    if not joined:
        errors["joining_date"] = "Enter a valid joining date."
    elif joined > helpers.parse_date(helpers.today()):
        errors["joining_date"] = "Joining date cannot be in the future."
    if helpers.parse_amount(data["salary"], allow_zero=True) is None:
        errors["salary"] = "Enter the monthly salary as a number (0 or more)."
    if data["status"] not in helpers.STAFF_STATUSES:
        errors["status"] = "Select a status."
    return data, errors


@bp.route("/")
def list_staff():
    f = {k: clean(request.args.get(k)) for k in ("q", "role", "status")}
    conditions, params = [], []
    if f["q"]:
        clause, like_params = helpers.search_clause(["full_name", "staff_code", "phone", "email"], f["q"])
        conditions.append(clause)
        params += like_params
    if f["role"] in helpers.STAFF_ROLES:
        conditions.append("role = ?")
        params.append(f["role"])
    if f["status"] in helpers.STAFF_STATUSES:
        conditions.append("status = ?")
        params.append(f["status"])
    sql = "SELECT * FROM staff" + helpers.where(conditions) + " ORDER BY full_name COLLATE NOCASE"
    rows, pager = helpers.paginate(sql, params, helpers.page_number())
    payroll = db.scalar("SELECT COALESCE(SUM(salary),0) FROM staff WHERE status = 'Active'")
    return render_template("staff.html", staff=rows, pager=pager, filters=f, payroll=payroll,
                           roles=helpers.STAFF_ROLES, statuses=helpers.STAFF_STATUSES)


def _save(data, staff_id=None):
    database = db.get_db()
    values = (data["full_name"], data["role"], data["phone"], data["email"] or None, data["joining_date"],
              helpers.parse_amount(data["salary"], allow_zero=True), data["status"])
    if staff_id is None:
        code = db.next_code(database, "staff", "staff_code", "STF")
        cursor = database.execute(
            "INSERT INTO staff (full_name, role, phone, email, joining_date, salary, status, staff_code) "
            "VALUES (?,?,?,?,?,?,?,?)", values + (code,))
        staff_id = cursor.lastrowid
    else:
        database.execute("UPDATE staff SET full_name=?, role=?, phone=?, email=?, joining_date=?, salary=?, "
                         "status=? WHERE id=?", values + (staff_id,))
    database.commit()
    return staff_id


@bp.route("/add", methods=["GET", "POST"])
def add_staff():
    data, errors = {}, {}
    if request.method == "POST":
        data, errors = validate_staff(request.form)
        if not errors:
            try:
                new_id = _save(data)
                flash(f"Staff member {data['full_name']} added.", "success")
                return redirect(url_for("staff.staff_details", staff_id=new_id))
            except sqlite3.IntegrityError:
                db.get_db().rollback()
                errors["phone"] = "Phone number or email is already in use."
        flash("Please correct the highlighted fields.", "danger")
    else:
        data = {"joining_date": helpers.today(), "status": "Active"}
    return render_template("staff_form.html", staff=None, data=data, errors=errors,
                           roles=helpers.STAFF_ROLES, statuses=helpers.STAFF_STATUSES)


@bp.route("/<int:staff_id>/edit", methods=["GET", "POST"])
def edit_staff(staff_id):
    member = db.query_one("SELECT * FROM staff WHERE id = ?", (staff_id,))
    if member is None:
        abort(404)
    data, errors = dict(member), {}
    data["salary"] = f"{member['salary']:.2f}"
    if request.method == "POST":
        data, errors = validate_staff(request.form, staff_id)
        if not errors:
            try:
                _save(data, staff_id)
                flash("Staff details updated.", "success")
                return redirect(url_for("staff.staff_details", staff_id=staff_id))
            except sqlite3.IntegrityError:
                db.get_db().rollback()
                errors["phone"] = "Phone number or email is already in use."
        flash("Please correct the highlighted fields.", "danger")
    return render_template("staff_form.html", staff=member, data=data, errors=errors,
                           roles=helpers.STAFF_ROLES, statuses=helpers.STAFF_STATUSES)


@bp.route("/<int:staff_id>")
def staff_details(staff_id):
    member = db.query_one("SELECT * FROM staff WHERE id = ?", (staff_id,))
    if member is None:
        abort(404)
    return render_template("staff_details.html", s=member)


@bp.route("/<int:staff_id>/delete", methods=["POST"])
def delete_staff(staff_id):
    member = db.query_one("SELECT * FROM staff WHERE id = ?", (staff_id,))
    if member is None:
        abort(404)
    database = db.get_db()
    database.execute("DELETE FROM staff WHERE id = ?", (staff_id,))
    database.commit()
    flash(f"Staff member {member['full_name']} deleted.", "success")
    return redirect(url_for("staff.list_staff"))
