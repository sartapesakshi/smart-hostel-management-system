"""Visitor management: register visitors, record exit time, history."""
from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import db
import helpers
from helpers import clean

bp = Blueprint("visitors", __name__, url_prefix="/visitors")


def validate_visitor(form):
    data = {k: clean(form.get(k)) for k in (
        "visitor_name", "phone", "student_id", "relationship", "purpose", "visit_date", "entry_time")}
    errors = {}
    if not helpers.valid_person_name(data["visitor_name"]):
        errors["visitor_name"] = "Enter the visitor's name (2-100 characters, no digits)."
    phone = helpers.normalize_phone(data["phone"])
    if not phone:
        errors["phone"] = "Enter a valid 10-digit mobile number."
    else:
        data["phone"] = phone
    student = db.query_one("SELECT status FROM students WHERE id = ?", (helpers.parse_int(data["student_id"], 1) or -1,))
    if student is None:
        errors["student_id"] = "Select the student being visited."
    elif student["status"] != "Active":
        errors["student_id"] = "Visitors can only be registered for Active students."
    if data["relationship"] not in helpers.RELATIONSHIPS:
        errors["relationship"] = "Select the relationship."
    if not 3 <= len(data["purpose"]) <= 200:
        errors["purpose"] = "State the purpose of the visit (3-200 characters)."
    visit = helpers.parse_date(data["visit_date"])
    if not visit:
        errors["visit_date"] = "Enter a valid visit date."
    elif visit > helpers.parse_date(helpers.today()):
        errors["visit_date"] = "Visit date cannot be in the future."
    if not helpers.parse_time(data["entry_time"]):
        errors["entry_time"] = "Enter a valid entry time."
    return data, errors


@bp.route("/")
def list_visitors():
    f = {k: clean(request.args.get(k)) for k in ("q", "date_from", "date_to", "status", "student", "scope")}
    if f["scope"] == "today":                    # the "Today's visitors" tab
        f["date_from"] = f["date_to"] = helpers.today()
    conditions, params = [], []
    if f["q"]:
        clause, like_params = helpers.search_clause(
            ["v.visitor_name", "v.phone", "s.full_name", "s.student_code"], f["q"])
        conditions.append(clause)
        params += like_params
    if helpers.parse_date(f["date_from"]):
        conditions.append("v.visit_date >= ?")
        params.append(f["date_from"])
    if helpers.parse_date(f["date_to"]):
        conditions.append("v.visit_date <= ?")
        params.append(f["date_to"])
    if f["status"] == "Inside":
        conditions.append("v.exit_time IS NULL")
    elif f["status"] == "Exited":
        conditions.append("v.exit_time IS NOT NULL")
    if helpers.parse_int(f["student"], 1):
        conditions.append("v.student_id = ?")
        params.append(int(f["student"]))

    sql = ("SELECT v.*, s.full_name AS student_name, s.student_code, "
           "CASE WHEN v.exit_time IS NULL THEN 'Inside' ELSE 'Exited' END AS status "
           "FROM visitors v JOIN students s ON s.id = v.student_id" + helpers.where(conditions) +
           " ORDER BY v.visit_date DESC, v.entry_time DESC")
    rows, pager = helpers.paginate(sql, params, helpers.page_number())
    summary = db.query_one(
        "SELECT COALESCE(SUM(visit_date = ?),0) AS today, "
        "COALESCE(SUM(exit_time IS NULL AND visit_date = ?),0) AS inside, COUNT(*) AS total FROM visitors",
        (helpers.today(), helpers.today()))
    return render_template("visitors.html", visitors=rows, pager=pager, filters=f, summary=summary,
                           now=datetime.now().strftime("%H:%M"),
                           students=db.query_all("SELECT id, student_code, full_name FROM students "
                                                 "ORDER BY full_name COLLATE NOCASE"))


@bp.route("/add", methods=["GET", "POST"])
def add_visitor():
    data, errors = {}, {}
    if request.method == "POST":
        data, errors = validate_visitor(request.form)
        if not errors:
            database = db.get_db()
            database.execute(
                "INSERT INTO visitors (visitor_name, phone, student_id, relationship, purpose, visit_date, entry_time) "
                "VALUES (?,?,?,?,?,?,?)",
                (data["visitor_name"], data["phone"], int(data["student_id"]), data["relationship"],
                 data["purpose"], data["visit_date"], helpers.parse_time(data["entry_time"])))
            database.commit()
            flash("Visitor registered. Remember to record the exit time.", "success")
            return redirect(url_for("visitors.list_visitors", scope="today"))
        flash("Please correct the highlighted fields.", "danger")
    else:
        data = {"visit_date": helpers.today(), "entry_time": datetime.now().strftime("%H:%M"),
                "student_id": request.args.get("student", "")}
    return render_template("visitor_form.html", data=data, errors=errors,
                           students=db.query_all("SELECT id, student_code, full_name FROM students "
                                                 "WHERE status = 'Active' ORDER BY full_name COLLATE NOCASE"),
                           relationships=helpers.RELATIONSHIPS)


@bp.route("/<int:visitor_id>/exit", methods=["POST"])
def record_exit(visitor_id):
    visitor = db.query_one("SELECT * FROM visitors WHERE id = ?", (visitor_id,))
    if visitor is None:
        abort(404)
    exit_time = helpers.parse_time(request.form.get("exit_time"))
    target = helpers.safe_next_url(request.form.get("next")) or url_for("visitors.list_visitors")
    if visitor["exit_time"]:
        flash("Exit time was already recorded for this visitor.", "warning")
    elif not exit_time:
        flash("Enter a valid exit time.", "danger")
    elif exit_time < visitor["entry_time"]:
        flash(f"Exit time cannot be earlier than the entry time ({helpers.fmt_time(visitor['entry_time'])}).", "danger")
    else:
        database = db.get_db()
        database.execute("UPDATE visitors SET exit_time = ? WHERE id = ?", (exit_time, visitor_id))
        database.commit()
        flash(f"Exit recorded for {visitor['visitor_name']} at {helpers.fmt_time(exit_time)}.", "success")
    return redirect(target)


@bp.route("/<int:visitor_id>/delete", methods=["POST"])
def delete_visitor(visitor_id):
    if db.query_one("SELECT 1 FROM visitors WHERE id = ?", (visitor_id,)) is None:
        abort(404)
    database = db.get_db()
    database.execute("DELETE FROM visitors WHERE id = ?", (visitor_id,))
    database.commit()
    flash("Visitor record deleted.", "success")
    return redirect(url_for("visitors.list_visitors"))
