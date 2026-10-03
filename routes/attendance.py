"""Attendance: mark a day's sheet, browse history, monthly report.

UNIQUE(student_id, att_date) in the database makes duplicates impossible.
Saving a day again simply UPDATES the earlier mark (an 'upsert').
"""
import calendar
import sqlite3
from datetime import date

from flask import Blueprint, flash, g, redirect, render_template, request, url_for

import db
import helpers
from helpers import clean

bp = Blueprint("attendance", __name__, url_prefix="/attendance")


def attendance_summary(date_from, date_to, student_id=None):
    """Student-wise present / absent / percentage between two dates (also used by Reports)."""
    conditions, params = ["a.att_date BETWEEN ? AND ?"], [date_from, date_to]
    if student_id:
        conditions.append("a.student_id = ?")
        params.append(student_id)
    return db.query_all(
        "SELECT s.id, s.student_code, s.full_name, s.course, COUNT(*) AS total, "
        "SUM(a.status = 'Present') AS present, SUM(a.status = 'Absent') AS absent, "
        "ROUND(100.0 * SUM(a.status = 'Present') / COUNT(*), 1) AS percentage "
        "FROM attendance a JOIN students s ON s.id = a.student_id" + helpers.where(conditions) +
        " GROUP BY s.id ORDER BY percentage, s.full_name", params)


# ---------------------------------------------------------- daily sheet
@bp.route("/")
def mark():
    chosen = helpers.parse_date(request.args.get("date"))
    if chosen is None or chosen > date.today():
        if request.args.get("date"):
            flash("Choose a valid date that is not in the future. Showing today instead.", "warning")
        chosen = date.today()
    day = chosen.isoformat()
    q, course = clean(request.args.get("q")), clean(request.args.get("course"))

    conditions, params = ["s.status = 'Active'"], [day]
    if q:
        clause, like_params = helpers.search_clause(["s.full_name", "s.student_code", "r.room_no"], q)
        conditions.append(clause)
        params += like_params
    if course:
        conditions.append("s.course = ?")
        params.append(course)
    students = db.query_all(
        "SELECT s.id, s.student_code, s.full_name, s.course, r.room_no, a.status AS marked "
        "FROM students s LEFT JOIN rooms r ON r.id = s.room_id "
        "LEFT JOIN attendance a ON a.student_id = s.id AND a.att_date = ?" + helpers.where(conditions) +
        " ORDER BY s.full_name COLLATE NOCASE", params)

    counts = db.query_one(
        "SELECT COUNT(*) AS active, COALESCE(SUM(a.status='Present'),0) AS present, "
        "COALESCE(SUM(a.status='Absent'),0) AS absent FROM students s "
        "LEFT JOIN attendance a ON a.student_id = s.id AND a.att_date = ? WHERE s.status = 'Active'", (day,))
    return render_template(
        "attendance.html", students=students, day=day, filters={"q": q, "course": course},
        counts=counts, not_marked=counts["active"] - counts["present"] - counts["absent"],
        courses=[r[0] for r in db.query_all("SELECT DISTINCT course FROM students WHERE status='Active' ORDER BY course")])


@bp.route("/save", methods=["POST"])
def save():
    chosen = helpers.parse_date(request.form.get("date"))
    back = url_for("attendance.mark", date=request.form.get("date", ""), q=clean(request.form.get("q")),
                   course=clean(request.form.get("course")))
    if chosen is None or chosen > date.today():
        flash("Attendance can only be saved for a valid date that is not in the future.", "danger")
        return redirect(back)

    marks = []
    for key, value in request.form.items():
        if key.startswith("status_") and value in ("Present", "Absent"):
            student_id = helpers.parse_int(key[len("status_"):], 1)
            if student_id:
                marks.append((student_id, value))
    if not marks:
        flash("Nothing to save: mark at least one student as Present or Absent.", "warning")
        return redirect(back)

    database = db.get_db()
    saved = 0
    try:
        for student_id, status in marks:
            student = database.execute("SELECT status FROM students WHERE id = ?", (student_id,)).fetchone()
            if student is None or student["status"] != "Active":
                continue                                    # ignore tampered / inactive students
            database.execute(
                "INSERT INTO attendance (student_id, att_date, status, marked_by) VALUES (?,?,?,?) "
                "ON CONFLICT(student_id, att_date) DO UPDATE SET status = excluded.status, "
                "marked_by = excluded.marked_by",
                (student_id, chosen.isoformat(), status, g.user["id"]))
            saved += 1
        database.commit()
        flash(f"Attendance saved for {saved} student(s) on {helpers.fmt_date(chosen.isoformat())}.", "success")
    except sqlite3.Error:
        database.rollback()
        raise
    return redirect(back)


# ---------------------------------------------------------------- history
@bp.route("/history")
def history():
    t = date.today()
    f = {"student": clean(request.args.get("student")),
         "date_from": clean(request.args.get("date_from")) or t.replace(day=1).isoformat(),
         "date_to": clean(request.args.get("date_to")) or t.isoformat(),
         "status": clean(request.args.get("status"))}
    if not helpers.parse_date(f["date_from"]) or not helpers.parse_date(f["date_to"]):
        flash("Invalid date range. Showing the current month.", "warning")
        f["date_from"], f["date_to"] = t.replace(day=1).isoformat(), t.isoformat()
    elif f["date_from"] > f["date_to"]:
        flash("'From' date is after 'To' date. The dates were swapped.", "warning")
        f["date_from"], f["date_to"] = f["date_to"], f["date_from"]

    student_id = helpers.parse_int(f["student"], 1)
    conditions, params = ["a.att_date BETWEEN ? AND ?"], [f["date_from"], f["date_to"]]
    if student_id:
        conditions.append("a.student_id = ?")
        params.append(student_id)
    if f["status"] in ("Present", "Absent"):
        conditions.append("a.status = ?")
        params.append(f["status"])
    sql = ("SELECT a.id, a.att_date, a.status, s.id AS student_id, s.student_code, s.full_name, s.course "
           "FROM attendance a JOIN students s ON s.id = a.student_id" + helpers.where(conditions) +
           " ORDER BY a.att_date DESC, s.full_name COLLATE NOCASE")
    rows, pager = helpers.paginate(sql, params, helpers.page_number())
    return render_template(
        "attendance_history.html", records=rows, pager=pager, filters=f,
        summary=attendance_summary(f["date_from"], f["date_to"], student_id),
        students=db.query_all("SELECT id, student_code, full_name FROM students ORDER BY full_name COLLATE NOCASE"))


# ---------------------------------------------------------- monthly report
@bp.route("/monthly")
def monthly():
    month = clean(request.args.get("month")) or date.today().strftime("%Y-%m")
    try:
        year_no, month_no = (int(x) for x in month.split("-"))
        days_in_month = calendar.monthrange(year_no, month_no)[1]
    except (ValueError, calendar.IllegalMonthError):
        flash("Invalid month. Showing the current month.", "warning")
        today = date.today()
        year_no, month_no, month = today.year, today.month, today.strftime("%Y-%m")
        days_in_month = calendar.monthrange(year_no, month_no)[1]

    first, last = f"{month}-01", f"{month}-{days_in_month:02d}"
    records = db.query_all("SELECT student_id, att_date, status FROM attendance WHERE att_date BETWEEN ? AND ?",
                           (first, last))
    grid = {(r["student_id"], int(r["att_date"][8:10])): r["status"] for r in records}
    students = db.query_all(
        "SELECT id, student_code, full_name FROM students WHERE status = 'Active' "
        "OR id IN (SELECT student_id FROM attendance WHERE att_date BETWEEN ? AND ?) "
        "ORDER BY full_name COLLATE NOCASE", (first, last))

    rows = []
    for s in students:
        marks = [grid.get((s["id"], d)) for d in range(1, days_in_month + 1)]
        present, absent = marks.count("Present"), marks.count("Absent")
        total = present + absent
        rows.append({"student": s, "marks": marks, "present": present, "absent": absent,
                     "percentage": round(100 * present / total, 1) if total else None})
    return render_template("attendance_monthly.html", rows=rows, month=month,
                           days=range(1, days_in_month + 1),
                           title=date(year_no, month_no, 1).strftime("%B %Y"))
