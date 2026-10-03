"""Complaint management: register, track, resolve."""
from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

import db
import helpers
from helpers import clean

bp = Blueprint("complaints", __name__, url_prefix="/complaints")


def validate_complaint(form):
    data = {k: clean(form.get(k)) for k in ("student_id", "category", "description", "priority", "complaint_date")}
    errors = {}
    student = db.query_one("SELECT status FROM students WHERE id = ?", (helpers.parse_int(data["student_id"], 1) or -1,))
    if student is None:
        errors["student_id"] = "Select the student who is complaining."
    if data["category"] not in helpers.COMPLAINT_CATEGORIES:
        errors["category"] = "Select a category."
    if not 10 <= len(data["description"]) <= 500:
        errors["description"] = "Describe the problem in 10-500 characters."
    if data["priority"] not in helpers.PRIORITIES:
        errors["priority"] = "Select a priority."
    raised = helpers.parse_date(data["complaint_date"])
    if not raised:
        errors["complaint_date"] = "Enter a valid date."
    elif raised > helpers.parse_date(helpers.today()):
        errors["complaint_date"] = "Complaint date cannot be in the future."
    return data, errors


@bp.route("/")
def list_complaints():
    f = {k: clean(request.args.get(k)) for k in ("q", "status", "priority", "category", "date_from", "date_to")}
    conditions, params = [], []
    if f["q"]:
        clause, like_params = helpers.search_clause(
            ["s.full_name", "s.student_code", "c.description", "c.category"], f["q"])
        conditions.append(clause)
        params += like_params
    if f["status"] in helpers.COMPLAINT_STATUSES:
        conditions.append("c.status = ?")
        params.append(f["status"])
    if f["priority"] in helpers.PRIORITIES:
        conditions.append("c.priority = ?")
        params.append(f["priority"])
    if f["category"] in helpers.COMPLAINT_CATEGORIES:
        conditions.append("c.category = ?")
        params.append(f["category"])
    if helpers.parse_date(f["date_from"]):
        conditions.append("c.complaint_date >= ?")
        params.append(f["date_from"])
    if helpers.parse_date(f["date_to"]):
        conditions.append("c.complaint_date <= ?")
        params.append(f["date_to"])

    sql = ("SELECT c.id, c.category, c.description, c.complaint_date, c.priority, c.status, c.resolved_date, "
           "s.id AS student_id, s.full_name, s.student_code FROM complaints c "
           "JOIN students s ON s.id = c.student_id" + helpers.where(conditions) +
           " ORDER BY CASE c.status WHEN 'Resolved' THEN 1 ELSE 0 END, "
           "CASE c.priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, c.complaint_date DESC")
    rows, pager = helpers.paginate(sql, params, helpers.page_number())
    counts = {r["status"]: r["n"] for r in db.query_all("SELECT status, COUNT(*) AS n FROM complaints GROUP BY status")}
    return render_template("complaints.html", complaints=rows, pager=pager, filters=f, counts=counts,
                           statuses=helpers.COMPLAINT_STATUSES, priorities=helpers.PRIORITIES,
                           categories=helpers.COMPLAINT_CATEGORIES)


@bp.route("/add", methods=["GET", "POST"])
def add_complaint():
    data, errors = {}, {}
    if request.method == "POST":
        data, errors = validate_complaint(request.form)
        if not errors:
            database = db.get_db()
            cursor = database.execute(
                "INSERT INTO complaints (student_id, category, description, complaint_date, priority) "
                "VALUES (?,?,?,?,?)",
                (int(data["student_id"]), data["category"], data["description"], data["complaint_date"],
                 data["priority"]))
            database.commit()
            flash("Complaint registered.", "success")
            return redirect(url_for("complaints.complaint_details", complaint_id=cursor.lastrowid))
        flash("Please correct the highlighted fields.", "danger")
    else:
        data = {"complaint_date": helpers.today(), "priority": "Medium", "student_id": request.args.get("student", "")}
    return render_template("complaint_form.html", data=data, errors=errors,
                           students=db.query_all("SELECT id, student_code, full_name FROM students "
                                                 "WHERE status <> 'Left' ORDER BY full_name COLLATE NOCASE"),
                           categories=helpers.COMPLAINT_CATEGORIES, priorities=helpers.PRIORITIES)


def _load(complaint_id):
    row = db.query_one(
        "SELECT c.*, s.full_name, s.student_code, s.phone, r.room_no FROM complaints c "
        "JOIN students s ON s.id = c.student_id LEFT JOIN rooms r ON r.id = s.room_id WHERE c.id = ?",
        (complaint_id,))
    if row is None:
        abort(404)
    return row


@bp.route("/<int:complaint_id>")
def complaint_details(complaint_id):
    return render_template("complaint_details.html", c=_load(complaint_id), errors={},
                           statuses=helpers.COMPLAINT_STATUSES)


@bp.route("/<int:complaint_id>/update", methods=["POST"])
def update_complaint(complaint_id):
    c = _load(complaint_id)
    status = clean(request.form.get("status"))
    resolution = clean(request.form.get("resolution"))
    errors = {}
    if status not in helpers.COMPLAINT_STATUSES:
        errors["status"] = "Select a valid status."
    if status == "Resolved" and len(resolution) < 5:
        errors["resolution"] = "Write what was done to resolve the complaint (at least 5 characters)."
    if len(resolution) > 500:
        errors["resolution"] = "Resolution is too long (maximum 500 characters)."
    if errors:
        flash("The complaint was not updated. Please check the form.", "danger")
        c = dict(c)
        c["status"], c["resolution"] = status or c["status"], resolution
        return render_template("complaint_details.html", c=c, errors=errors, statuses=helpers.COMPLAINT_STATUSES)

    resolved_date = (c["resolved_date"] or helpers.today()) if status == "Resolved" else None
    database = db.get_db()
    database.execute("UPDATE complaints SET status=?, resolution=?, resolved_date=? WHERE id=?",
                     (status, resolution or None, resolved_date, complaint_id))
    database.commit()
    flash(f"Complaint marked as {status}.", "success")
    return redirect(url_for("complaints.complaint_details", complaint_id=complaint_id))


@bp.route("/<int:complaint_id>/delete", methods=["POST"])
def delete_complaint(complaint_id):
    _load(complaint_id)
    database = db.get_db()
    database.execute("DELETE FROM complaints WHERE id = ?", (complaint_id,))
    database.commit()
    flash("Complaint deleted.", "success")
    return redirect(url_for("complaints.list_complaints"))
