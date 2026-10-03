"""Reports: eight reports built from the same pattern.

Every report is a small function returning  (column names, rows, summary lines).
One generic page, one CSV exporter and one PDF exporter then work for all of them.
Amounts in reports are plain numbers in rupees (so they open correctly in Excel).
"""
import csv
import io
from xml.sax.saxutils import escape

from flask import Blueprint, Response, abort, render_template, request

import db
import helpers
from helpers import clean
from routes.attendance import attendance_summary
from routes.rooms import ROOM_STATUSES

try:                                     # PDF export is optional: needs `pip install reportlab`
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    PDF_AVAILABLE = True
except ImportError:                      # pragma: no cover
    PDF_AVAILABLE = False

bp = Blueprint("reports", __name__, url_prefix="/reports")


def money(value):
    return f"{float(value or 0):.2f}"


def date_range(args, default_from=None, default_to=None):
    """Read ?date_from & ?date_to; ignore invalid values."""
    start = clean(args.get("date_from")) or default_from or ""
    end = clean(args.get("date_to")) or default_to or ""
    start = start if helpers.parse_date(start) else ""
    end = end if helpers.parse_date(end) else ""
    if start and end and start > end:
        start, end = end, start
    return start, end


def add_range(conditions, params, column, start, end):
    if start:
        conditions.append(f"{column} >= ?")
        params.append(start)
    if end:
        conditions.append(f"{column} <= ?")
        params.append(end)


# ----------------------------------------------------------- the 8 reports
def students_report(args):
    conditions, params = [], []
    if clean(args.get("course")):
        conditions.append("s.course = ?")
        params.append(clean(args.get("course")))
    if clean(args.get("status")) in helpers.STUDENT_STATUSES:
        conditions.append("s.status = ?")
        params.append(clean(args.get("status")))
    if helpers.parse_int(args.get("year"), 1, 6):
        conditions.append("s.year = ?")
        params.append(int(args.get("year")))
    add_range(conditions, params, "s.admission_date", *date_range(args))
    rows = db.query_all(
        "SELECT s.*, r.room_no FROM students s LEFT JOIN rooms r ON r.id = s.room_id" + helpers.where(conditions) +
        " ORDER BY s.student_code", params)
    data = [[s["student_code"], s["full_name"], s["gender"], helpers.student_age(s) or "", s["phone"], s["course"],
             s["year"] or "", s["room_no"] or "Unassigned", s["admission_date"], s["status"]] for s in rows]
    cols = ["Student ID", "Name", "Gender", "Age", "Phone", "Course", "Year", "Room", "Admission Date", "Status"]
    return cols, data, [("Total students", len(rows)),
                        ("Active", sum(1 for s in rows if s["status"] == "Active")),
                        ("Without a room", sum(1 for s in rows if s["status"] == "Active" and not s["room_no"]))]


def occupancy_report(args):
    conditions, params = [], []
    if helpers.parse_int(args.get("floor"), 0, 50) is not None and clean(args.get("floor")) != "":
        conditions.append("floor = ?")
        params.append(int(args.get("floor")))
    if clean(args.get("room_type")) in helpers.ROOM_TYPES:
        conditions.append("room_type = ?")
        params.append(clean(args.get("room_type")))
    if clean(args.get("status")) in ROOM_STATUSES:
        conditions.append("status = ?")
        params.append(clean(args.get("status")))
    rows = db.query_all("SELECT * FROM room_overview" + helpers.where(conditions) + " ORDER BY floor, room_no", params)
    data = [[r["room_no"], r["floor"], r["room_type"], r["capacity"], r["occupied"], r["available"], r["status"]]
            for r in rows]
    beds, occupied = sum(r["capacity"] for r in rows), sum(r["occupied"] for r in rows)
    return (["Room No", "Floor", "Type", "Capacity", "Occupied", "Available", "Status"], data,
            [("Rooms", len(rows)), ("Total beds", beds), ("Occupied beds", occupied),
             ("Available beds", sum(r["available"] for r in rows)),
             ("Occupancy", f"{round(100 * occupied / beds, 1) if beds else 0}%")])


def fee_collection_report(args):
    start, end = date_range(args)
    conditions, params = [], []
    add_range(conditions, params, "p.payment_date", start, end)
    if clean(args.get("method")) in helpers.PAYMENT_METHODS:
        conditions.append("p.method = ?")
        params.append(clean(args.get("method")))
    if clean(args.get("fee_type")) in helpers.FEE_TYPES:
        conditions.append("f.fee_type = ?")
        params.append(clean(args.get("fee_type")))
    rows = db.query_all(
        "SELECT p.*, f.fee_type, s.student_code, s.full_name FROM payments p JOIN fees f ON f.id = p.fee_id "
        "JOIN students s ON s.id = f.student_id" + helpers.where(conditions) +
        " ORDER BY p.payment_date, p.id", params)
    data = [[p["receipt_no"], p["payment_date"], p["student_code"], p["full_name"], p["fee_type"], p["method"],
             p["transaction_ref"] or "", money(p["amount"])] for p in rows]
    summary = [("Payments", len(rows)), ("Total collected (Rs)", money(sum(p["amount"] for p in rows)))]
    for method in helpers.PAYMENT_METHODS:
        part = sum(p["amount"] for p in rows if p["method"] == method)
        if part:
            summary.append((f"{method} (Rs)", money(part)))
    return (["Receipt No", "Date", "Student ID", "Student", "Fee Type", "Method", "Reference", "Amount (Rs)"],
            data, summary)


def pending_fee_report(args):
    conditions, params = ["status <> 'Paid'"], []
    if clean(args.get("status")) in ("Pending", "Partial", "Overdue"):
        conditions.append("status = ?")
        params.append(clean(args.get("status")))
    add_range(conditions, params, "due_date", *date_range(args))
    rows = db.query_all("SELECT * FROM fee_overview" + helpers.where(conditions) + " ORDER BY due_date, id", params)
    data = [[f"FEE-{r['id']:04d}", r["student_code"], r["student_name"], r["fee_type"], r["due_date"],
             money(r["amount"]), money(r["paid"]), money(r["balance"]), r["status"]] for r in rows]
    return (["Fee ID", "Student ID", "Student", "Fee Type", "Due Date", "Amount (Rs)", "Paid (Rs)",
             "Balance (Rs)", "Status"], data,
            [("Unpaid fees", len(rows)), ("Total balance due (Rs)", money(sum(r["balance"] for r in rows))),
             ("Overdue", sum(1 for r in rows if r["status"] == "Overdue"))])


def attendance_report(args):
    today = helpers.today()
    start, end = date_range(args, today[:8] + "01", today)
    student_id = helpers.parse_int(args.get("student"), 1)
    rows = attendance_summary(start or "0000-01-01", end or "9999-12-31", student_id)
    data = [[r["student_code"], r["full_name"], r["course"], r["total"], r["present"], r["absent"],
             f"{r['percentage']}%"] for r in rows]
    total = sum(r["total"] for r in rows)
    present = sum(r["present"] for r in rows)
    return (["Student ID", "Name", "Course", "Days Recorded", "Present", "Absent", "Attendance %"], data,
            [("Students", len(rows)), ("Overall attendance", f"{round(100 * present / total, 1) if total else 0}%"),
             ("Below 75%", sum(1 for r in rows if r["percentage"] < 75))])


def complaint_report(args):
    conditions, params = [], []
    add_range(conditions, params, "c.complaint_date", *date_range(args))
    for field, allowed in (("status", helpers.COMPLAINT_STATUSES), ("priority", helpers.PRIORITIES),
                           ("category", helpers.COMPLAINT_CATEGORIES)):
        if clean(args.get(field)) in allowed:
            conditions.append(f"c.{field} = ?")
            params.append(clean(args.get(field)))
    rows = db.query_all(
        "SELECT c.*, s.student_code, s.full_name FROM complaints c JOIN students s ON s.id = c.student_id" +
        helpers.where(conditions) + " ORDER BY c.complaint_date, c.id", params)
    data = [[f"CMP-{c['id']:04d}", c["full_name"], c["category"], c["priority"], c["status"], c["complaint_date"],
             c["resolved_date"] or "", c["description"]] for c in rows]
    return (["Complaint ID", "Student", "Category", "Priority", "Status", "Date", "Resolved On", "Description"],
            data, [("Complaints", len(rows)),
                   ("Pending", sum(1 for c in rows if c["status"] == "Pending")),
                   ("In progress", sum(1 for c in rows if c["status"] == "In Progress")),
                   ("Resolved", sum(1 for c in rows if c["status"] == "Resolved"))])


def visitor_report(args):
    conditions, params = [], []
    add_range(conditions, params, "v.visit_date", *date_range(args))
    status = clean(args.get("status"))
    if status == "Inside":
        conditions.append("v.exit_time IS NULL")
    elif status == "Exited":
        conditions.append("v.exit_time IS NOT NULL")
    rows = db.query_all(
        "SELECT v.*, s.full_name AS student_name FROM visitors v JOIN students s ON s.id = v.student_id" +
        helpers.where(conditions) + " ORDER BY v.visit_date, v.entry_time", params)
    data = [[f"VIS-{v['id']:04d}", v["visitor_name"], v["phone"], v["student_name"], v["relationship"],
             v["purpose"], v["visit_date"], v["entry_time"], v["exit_time"] or "Inside"] for v in rows]
    return (["Visitor ID", "Visitor", "Phone", "Student Visited", "Relationship", "Purpose", "Date", "Entry", "Exit"],
            data, [("Visits", len(rows)), ("Still inside", sum(1 for v in rows if not v["exit_time"]))])


def staff_report(args):
    conditions, params = [], []
    if clean(args.get("role")) in helpers.STAFF_ROLES:
        conditions.append("role = ?")
        params.append(clean(args.get("role")))
    if clean(args.get("status")) in helpers.STAFF_STATUSES:
        conditions.append("status = ?")
        params.append(clean(args.get("status")))
    rows = db.query_all("SELECT * FROM staff" + helpers.where(conditions) + " ORDER BY staff_code", params)
    data = [[s["staff_code"], s["full_name"], s["role"], s["phone"], s["email"] or "", s["joining_date"],
             money(s["salary"]), s["status"]] for s in rows]
    return (["Staff ID", "Name", "Role", "Phone", "Email", "Joining Date", "Salary (Rs)", "Status"], data,
            [("Staff members", len(rows)),
             ("Monthly payroll, active staff (Rs)", money(sum(s["salary"] for s in rows if s["status"] == "Active")))])


# --------------------------------------------------------------- registry
# Filter descriptions drive the form shown on top of each report page.
DATE_FILTERS = [("date_from", "From", "date", None), ("date_to", "To", "date", None)]


def _students_filters():
    return [("course", "Course", "select", [r[0] for r in db.query_all("SELECT DISTINCT course FROM students ORDER BY course")]),
            ("year", "Year", "select", ["1", "2", "3", "4", "5", "6"]),
            ("status", "Status", "select", helpers.STUDENT_STATUSES),
            ("date_from", "Admitted from", "date", None), ("date_to", "Admitted to", "date", None)]


REPORTS = {
    "students": ("Student Report", "All students with course, room and status.", students_report, _students_filters),
    "occupancy": ("Room Occupancy Report", "Beds occupied and available in every room.", occupancy_report,
                  lambda: [("floor", "Floor", "select", [str(r[0]) for r in db.query_all("SELECT DISTINCT floor FROM rooms ORDER BY floor")]),
                           ("room_type", "Type", "select", list(helpers.ROOM_TYPES)),
                           ("status", "Status", "select", ROOM_STATUSES)]),
    "fee-collection": ("Fee Collection Report", "Payments received in a period.", fee_collection_report,
                       lambda: [("method", "Method", "select", helpers.PAYMENT_METHODS),
                                ("fee_type", "Fee type", "select", helpers.FEE_TYPES),
                                ("date_from", "Paid from", "date", None), ("date_to", "Paid to", "date", None)]),
    "pending-fees": ("Pending Fee Report", "Fees that are not fully paid.", pending_fee_report,
                     lambda: [("status", "Status", "select", ["Pending", "Partial", "Overdue"]),
                              ("date_from", "Due from", "date", None), ("date_to", "Due to", "date", None)]),
    "attendance": ("Attendance Report", "Student-wise attendance percentage for a period.", attendance_report,
                   lambda: [("student", "Student", "student", None)] + DATE_FILTERS),
    "complaints": ("Complaint Report", "Complaints with priority and resolution status.", complaint_report,
                   lambda: [("status", "Status", "select", helpers.COMPLAINT_STATUSES),
                            ("priority", "Priority", "select", helpers.PRIORITIES),
                            ("category", "Category", "select", helpers.COMPLAINT_CATEGORIES)] + DATE_FILTERS),
    "visitors": ("Visitor Report", "Visitor log with entry and exit times.", visitor_report,
                 lambda: [("status", "Status", "select", ["Inside", "Exited"])] + DATE_FILTERS),
    "staff": ("Staff Report", "Hostel staff, roles and salaries.", staff_report,
              lambda: [("role", "Role", "select", helpers.STAFF_ROLES), ("status", "Status", "select", helpers.STAFF_STATUSES)]),
}


@bp.route("/")
def index():
    return render_template("reports.html", reports=REPORTS)


def csv_response(slug, title, columns, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(columns)
    writer.writerows(rows)
    # the BOM (utf-8-sig) lets Excel open names with accents correctly
    return Response("\ufeff" + buffer.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={slug}-report.csv"})


def pdf_response(slug, title, columns, rows, summary, applied):
    buffer = io.BytesIO()
    document = SimpleDocTemplate(buffer, pagesize=landscape(A4), leftMargin=24, rightMargin=24,
                                 topMargin=28, bottomMargin=28, title=title)
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=7.5, leading=9)
    head = styles["BodyText"].clone("head", fontSize=8, leading=10, textColor=colors.white)
    story = [Paragraph(escape(db.get_setting("hostel_name")), styles["Title"]),
             Paragraph(escape(title), styles["Heading2"])]
    if applied:
        story.append(Paragraph("Filters: " + escape("; ".join(applied)), styles["Normal"]))
    story.append(Paragraph("Generated on " + helpers.today(), styles["Normal"]))
    story.append(Spacer(1, 8))
    story.append(Paragraph(escape("   |   ".join(f"{k}: {v}" for k, v in summary)), styles["Normal"]))
    story.append(Spacer(1, 8))
    table_data = [[Paragraph(escape(str(c)), head) for c in columns]]
    table_data += [[Paragraph(escape(str(cell)), small) for cell in row] for row in rows]
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#17324d")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f2f5f8")]),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#c9d2db")),
        ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.append(table)
    document.build(story)
    return Response(buffer.getvalue(), mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment; filename={slug}-report.pdf"})


@bp.route("/<slug>")
def show(slug):
    if slug not in REPORTS:
        abort(404)
    title, description, builder, filter_factory = REPORTS[slug]
    filters = filter_factory()
    columns, rows, summary = builder(request.args)

    export = clean(request.args.get("export"))
    if export == "csv":
        return csv_response(slug, title, columns, rows)
    if export == "pdf":
        if not PDF_AVAILABLE:
            abort(400, "PDF export needs the 'reportlab' package. Run: pip install reportlab")
        applied = [f"{label} = {request.args.get(name)}" for name, label, _, _ in filters if clean(request.args.get(name))]
        return pdf_response(slug, title, columns, rows, summary, applied)

    students = db.query_all("SELECT id, student_code, full_name FROM students ORDER BY full_name COLLATE NOCASE") \
        if any(f[2] == "student" for f in filters) else []
    values = {name: clean(request.args.get(name)) for name, *_ in filters}
    if slug == "attendance":                         # show the default month in the date boxes
        values["date_from"] = values["date_from"] or helpers.today()[:8] + "01"
        values["date_to"] = values["date_to"] or helpers.today()
    return render_template("report.html", slug=slug, title=title, description=description, columns=columns,
                           rows=rows, summary=summary, filters=filters, values=values, students=students,
                           pdf_available=PDF_AVAILABLE, hostel=db.get_setting("hostel_name"))
