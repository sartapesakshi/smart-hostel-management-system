"""Dashboard: every number and chart comes from live SQL queries (nothing hard-coded)."""
from datetime import date, timedelta

from flask import Blueprint, render_template

import db
import helpers

bp = Blueprint("dashboard", __name__)


@bp.route("/dashboard")
def index():
    today = helpers.today()
    stats = {}
    stats["students"] = db.scalar("SELECT COUNT(*) FROM students")
    stats["active_students"] = db.scalar("SELECT COUNT(*) FROM students WHERE status = 'Active'")
    rooms = db.query_one(
        "SELECT COUNT(*) AS rooms, COALESCE(SUM(capacity),0) AS beds, COALESCE(SUM(occupied),0) AS occupied, "
        "COALESCE(SUM(available),0) AS available FROM room_overview")
    stats.update(rooms=rooms["rooms"], beds=rooms["beds"], occupied=rooms["occupied"], available=rooms["available"])
    fee = db.query_one(
        "SELECT COALESCE(SUM(balance),0) AS pending_amount, "
        "COALESCE(SUM(CASE WHEN status <> 'Paid' THEN 1 ELSE 0 END),0) AS pending_count, "
        "COALESCE(SUM(CASE WHEN status = 'Paid' THEN 1 ELSE 0 END),0) AS paid_count, "
        "COALESCE(SUM(CASE WHEN status = 'Overdue' THEN 1 ELSE 0 END),0) AS overdue_count FROM fee_overview")
    stats.update(fee)
    stats["collection"] = db.scalar("SELECT COALESCE(SUM(amount),0) FROM payments")
    stats["pending_complaints"] = db.scalar("SELECT COUNT(*) FROM complaints WHERE status <> 'Resolved'")
    stats["visitors_today"] = db.scalar("SELECT COUNT(*) FROM visitors WHERE visit_date = ?", (today,))
    att = db.query_one(
        "SELECT COALESCE(SUM(status='Present'),0) AS present, COALESCE(SUM(status='Absent'),0) AS absent "
        "FROM attendance WHERE att_date = ?", (today,))
    stats["att_present"], stats["att_absent"] = att["present"], att["absent"]
    stats["att_unmarked"] = max(stats["active_students"] - att["present"] - att["absent"], 0)

    # ---------- chart data (plain dictionaries, converted to JSON in the template) ----------
    by_type = db.query_all("SELECT room_type, SUM(occupied) AS occ, SUM(available) AS av FROM room_overview "
                           "GROUP BY room_type ORDER BY capacity")
    occupancy_chart = {"labels": [r["room_type"] for r in by_type],
                       "occupied": [r["occ"] for r in by_type], "available": [r["av"] for r in by_type]}

    # last 6 months of collections (months with no payments show 0)
    months, first = [], date.today().replace(day=1)
    for _ in range(6):
        months.insert(0, first.strftime("%Y-%m"))
        first = (first - timedelta(days=1)).replace(day=1)
    paid_by_month = {r["m"]: r["total"] for r in db.query_all(
        "SELECT substr(payment_date,1,7) AS m, SUM(amount) AS total FROM payments GROUP BY m")}
    fee_chart = {"labels": [date.fromisoformat(m + "-01").strftime("%b %Y") for m in months],
                 "values": [round(paid_by_month.get(m, 0), 2) for m in months]}

    courses = db.query_all("SELECT course, COUNT(*) AS n FROM students WHERE status='Active' "
                           "GROUP BY course ORDER BY n DESC, course")
    course_chart = {"labels": [r["course"] for r in courses], "values": [r["n"] for r in courses]}

    days = [(date.today() - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    att_rows = {(r["att_date"], r["status"]): r["n"] for r in db.query_all(
        "SELECT att_date, status, COUNT(*) AS n FROM attendance WHERE att_date >= ? GROUP BY att_date, status",
        (days[0],))}
    attendance_chart = {"labels": [date.fromisoformat(d).strftime("%d %b") for d in days],
                        "present": [att_rows.get((d, "Present"), 0) for d in days],
                        "absent": [att_rows.get((d, "Absent"), 0) for d in days]}

    # ---------- small "needs attention" lists ----------
    recent_complaints = db.query_all(
        "SELECT c.id, c.category, c.priority, c.status, s.full_name FROM complaints c "
        "JOIN students s ON s.id = c.student_id WHERE c.status <> 'Resolved' "
        "ORDER BY CASE c.priority WHEN 'High' THEN 0 WHEN 'Medium' THEN 1 ELSE 2 END, c.complaint_date LIMIT 5")
    overdue = db.query_all("SELECT * FROM fee_overview WHERE status = 'Overdue' ORDER BY due_date LIMIT 5")
    inside = db.query_all(
        "SELECT v.id, v.visitor_name, v.entry_time, s.full_name AS student_name FROM visitors v "
        "JOIN students s ON s.id = v.student_id WHERE v.exit_time IS NULL AND v.visit_date = ? "
        "ORDER BY v.entry_time", (today,))
    return render_template("dashboard.html", stats=stats, occupancy_chart=occupancy_chart, fee_chart=fee_chart,
                           course_chart=course_chart, attendance_chart=attendance_chart,
                           recent_complaints=recent_complaints, overdue=overdue, inside=inside)
