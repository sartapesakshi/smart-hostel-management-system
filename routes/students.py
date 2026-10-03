"""Student management: add, list/search/filter, details, edit, delete."""
import re
import sqlite3

from flask import (Blueprint, abort, flash, redirect, render_template, request, url_for)

import db
import helpers
from helpers import clean
from routes.rooms import assign_student, room_choices, vacate_student

bp = Blueprint("students", __name__, url_prefix="/students")

UNIQUE_FIELD_MESSAGES = {
    "students.phone": ("phone", "Another student already uses this phone number."),
    "students.email": ("email", "Another student already uses this email address."),
    "students.student_code": ("student_code", "This student ID is already taken."),
}


def validate_student(form, student_id=None):
    """Check every field. Returns (cleaned values, {field: error message})."""
    f = {k: clean(form.get(k)) for k in (
        "student_code", "full_name", "gender", "dob", "phone", "email", "address", "guardian_name",
        "guardian_phone", "course", "department", "year", "room_id", "admission_date", "status")}
    errors = {}

    # ---- identity ----
    if not student_id and f["student_code"]:
        if not re.fullmatch(r"[A-Za-z0-9\-]{3,20}", f["student_code"]):
            errors["student_code"] = "Use 3-20 letters, numbers or '-'."
        elif db.query_one("SELECT 1 FROM students WHERE student_code = ?", (f["student_code"],)):
            errors["student_code"] = "This student ID is already taken."

    if not helpers.valid_person_name(f["full_name"]):
        errors["full_name"] = "Enter the full name (2-100 characters, no digits)."
    if f["gender"] not in helpers.GENDERS:
        errors["gender"] = "Select a gender."

    dob = helpers.parse_date(f["dob"])
    if not dob:
        errors["dob"] = "Enter a valid date of birth."
    else:
        age = helpers.calc_age(f["dob"])
        if dob > helpers.parse_date(helpers.today()):
            errors["dob"] = "Date of birth cannot be in the future."
        elif not 14 <= age <= 70:
            errors["dob"] = f"Age works out to {age}; it must be between 14 and 70."

    # ---- contact ----
    phone = helpers.normalize_phone(f["phone"])
    if not phone:
        errors["phone"] = "Enter a valid 10-digit mobile number (starting with 6-9)."
    else:
        f["phone"] = phone
        if db.query_one("SELECT 1 FROM students WHERE phone = ? AND id <> ?", (phone, student_id or -1)):
            errors["phone"] = "Another student already uses this phone number."

    if f["email"]:
        if not helpers.valid_email(f["email"]):
            errors["email"] = "Enter a valid email address."
        elif db.query_one("SELECT 1 FROM students WHERE email = ? AND id <> ?", (f["email"], student_id or -1)):
            errors["email"] = "Another student already uses this email address."

    if not helpers.valid_person_name(f["guardian_name"]):
        errors["guardian_name"] = "Enter the parent/guardian's name."
    guardian_phone = helpers.normalize_phone(f["guardian_phone"])
    if not guardian_phone:
        errors["guardian_phone"] = "Enter a valid 10-digit guardian phone number."
    else:
        f["guardian_phone"] = guardian_phone

    if len(f["address"]) > 300:
        errors["address"] = "Address is too long (maximum 300 characters)."

    # ---- academic ----
    if not f["course"] or len(f["course"]) > 50:
        errors["course"] = "Enter the course (e.g. MCA)."
    if len(f["department"]) > 80:
        errors["department"] = "Department name is too long."
    if helpers.parse_int(f["year"], 1, 6) is None:
        errors["year"] = "Select the year of study (1-6)."

    admission = helpers.parse_date(f["admission_date"])
    if not admission:
        errors["admission_date"] = "Enter a valid admission date."
    elif admission > helpers.parse_date(helpers.today()):
        errors["admission_date"] = "Admission date cannot be in the future."

    if f["status"] not in helpers.STUDENT_STATUSES:
        errors["status"] = "Select a status."

    # ---- duplicate person (same name + same birth date) ----
    if "full_name" not in errors and "dob" not in errors and db.query_one(
            "SELECT 1 FROM students WHERE lower(full_name) = lower(?) AND dob = ? AND id <> ?",
            (f["full_name"], f["dob"], student_id or -1)):
        errors["full_name"] = "A student with this name and date of birth is already registered."

    if f["room_id"] and helpers.parse_int(f["room_id"], 1) is None:
        errors["room_id"] = "Select a valid room."
    return f, errors


def friendly_integrity_error(error):
    """Turn 'UNIQUE constraint failed: students.phone' into a message for the right field."""
    for key, (field, message) in UNIQUE_FIELD_MESSAGES.items():
        if key in str(error):
            return {field: message}
    return {"__all__": "The record violates a database rule and was not saved."}


def student_form_context(student, data, errors):
    current_room = student["room_id"] if student else None
    return dict(student=student, data=data, errors=errors, rooms=room_choices(current_room),
                courses=helpers.COURSES, departments=helpers.DEPARTMENTS,
                statuses=helpers.STUDENT_STATUSES)


# ---------------------------------------------------------------- list
@bp.route("/")
def list_students():
    q = clean(request.args.get("q"))
    course = clean(request.args.get("course"))
    year = clean(request.args.get("year"))
    room = clean(request.args.get("room"))
    status = clean(request.args.get("status"))

    conditions, params = [], []
    if q:
        clause, like_params = helpers.search_clause(
            ["s.full_name", "s.student_code", "s.phone", "s.email"], q)
        conditions.append(clause)
        params += like_params
    if course:
        conditions.append("s.course = ?")
        params.append(course)
    if helpers.parse_int(year, 1, 6):
        conditions.append("s.year = ?")
        params.append(int(year))
    if room == "none":
        conditions.append("s.room_id IS NULL")
    elif helpers.parse_int(room, 1):
        conditions.append("s.room_id = ?")
        params.append(int(room))
    if status in helpers.STUDENT_STATUSES:
        conditions.append("s.status = ?")
        params.append(status)

    sql = ("SELECT s.id, s.student_code, s.full_name, s.gender, s.dob, s.age, s.phone, s.course, "
           "s.year, s.status, r.room_no FROM students s LEFT JOIN rooms r ON r.id = s.room_id"
           + helpers.where(conditions) + " ORDER BY s.full_name COLLATE NOCASE")
    rows, pager = helpers.paginate(sql, params, helpers.page_number())

    return render_template(
        "students.html", students=rows, pager=pager,
        courses=[r[0] for r in db.query_all("SELECT DISTINCT course FROM students ORDER BY course")],
        rooms=db.query_all("SELECT id, room_no FROM rooms ORDER BY floor, room_no"),
        statuses=helpers.STUDENT_STATUSES,
        filters={"q": q, "course": course, "year": year, "room": room, "status": status})


# ----------------------------------------------------------------- add
@bp.route("/add", methods=["GET", "POST"])
def add_student():
    data, errors = {}, {}
    if request.method == "POST":
        data, errors = validate_student(request.form)
        if data["status"] != "Active" and data["room_id"]:
            errors["room_id"] = "Only Active students can be given a room."
        if not errors:
            database = db.get_db()
            try:
                code = data["student_code"] or db.next_code(database, "students", "student_code", "STU")
                cursor = database.execute(
                    "INSERT INTO students (student_code, full_name, gender, dob, age, phone, email, address, "
                    "guardian_name, guardian_phone, course, department, year, admission_date, status) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (code, data["full_name"], data["gender"], data["dob"], helpers.calc_age(data["dob"]),
                     data["phone"], data["email"] or None, data["address"] or None, data["guardian_name"],
                     data["guardian_phone"], data["course"], data["department"] or None,
                     int(data["year"]), data["admission_date"], data["status"]))
                new_id = cursor.lastrowid
                if data["room_id"]:
                    assign_student(database, new_id, int(data["room_id"]))   # same rules as everywhere
                database.commit()
                flash(f"Student {data['full_name']} ({code}) added successfully.", "success")
                return redirect(url_for("students.student_details", student_id=new_id))
            except ValueError as error:
                database.rollback()
                errors["room_id"] = str(error)
            except sqlite3.IntegrityError as error:
                database.rollback()
                errors.update(friendly_integrity_error(error))
        flash("Please correct the highlighted fields.", "danger")
    else:
        data = {"admission_date": helpers.today(), "status": "Active", "year": "1"}
        preselect = helpers.parse_int(request.args.get("room"), 1)
        if preselect:
            data["room_id"] = str(preselect)
    return render_template("student_form.html", **student_form_context(None, data, errors))


# ---------------------------------------------------------------- edit
@bp.route("/<int:student_id>/edit", methods=["GET", "POST"])
def edit_student(student_id):
    student = db.query_one("SELECT * FROM students WHERE id = ?", (student_id,))
    if student is None:
        abort(404)
    data, errors = dict(student), {}
    data["room_id"] = str(student["room_id"] or "")
    data["year"] = str(student["year"] or "")

    if request.method == "POST":
        data, errors = validate_student(request.form, student_id)
        if not errors:
            database = db.get_db()
            try:
                database.execute(
                    "UPDATE students SET full_name=?, gender=?, dob=?, age=?, phone=?, email=?, address=?, "
                    "guardian_name=?, guardian_phone=?, course=?, department=?, year=?, admission_date=? "
                    "WHERE id=?",
                    (data["full_name"], data["gender"], data["dob"], helpers.calc_age(data["dob"]),
                     data["phone"], data["email"] or None, data["address"] or None, data["guardian_name"],
                     data["guardian_phone"], data["course"], data["department"] or None,
                     int(data["year"]), data["admission_date"], student_id))

                # Status first: a student who is not Active must give up the bed.
                note = ""
                if data["status"] != "Active":
                    if student["room_id"]:
                        vacate_student(database, student_id)
                        note = " The bed was released because the student is no longer Active."
                    database.execute("UPDATE students SET status=? WHERE id=?", (data["status"], student_id))
                else:
                    database.execute("UPDATE students SET status=? WHERE id=?", (data["status"], student_id))
                    wanted = int(data["room_id"]) if data["room_id"] else None
                    if wanted != student["room_id"]:
                        if wanted is None:
                            vacate_student(database, student_id)
                        else:
                            assign_student(database, student_id, wanted)
                database.commit()
                flash(f"Student {data['full_name']} updated." + note, "success")
                return redirect(url_for("students.student_details", student_id=student_id))
            except ValueError as error:
                database.rollback()
                errors["room_id"] = str(error)
            except sqlite3.IntegrityError as error:
                database.rollback()
                errors.update(friendly_integrity_error(error))
        flash("Please correct the highlighted fields.", "danger")
    return render_template("student_form.html", **student_form_context(student, data, errors))


# ------------------------------------------------------------- details
@bp.route("/<int:student_id>")
def student_details(student_id):
    student = db.query_one(
        "SELECT s.*, r.room_no, r.floor AS room_floor, r.room_type FROM students s "
        "LEFT JOIN rooms r ON r.id = s.room_id WHERE s.id = ?", (student_id,))
    if student is None:
        abort(404)

    fees = db.query_all("SELECT * FROM fee_overview WHERE student_id = ? ORDER BY due_date DESC", (student_id,))
    fee_totals = {"amount": sum(f["amount"] for f in fees), "paid": sum(f["paid"] for f in fees),
                  "balance": sum(f["balance"] for f in fees)}
    attendance = db.query_one(
        "SELECT COUNT(*) AS total, COALESCE(SUM(status='Present'),0) AS present, "
        "COALESCE(SUM(status='Absent'),0) AS absent FROM attendance WHERE student_id = ?", (student_id,))
    percentage = round(100 * attendance["present"] / attendance["total"], 1) if attendance["total"] else None
    recent_attendance = db.query_all(
        "SELECT att_date, status FROM attendance WHERE student_id = ? ORDER BY att_date DESC LIMIT 7",
        (student_id,))
    complaints = db.query_all(
        "SELECT id, category, priority, status, complaint_date FROM complaints "
        "WHERE student_id = ? ORDER BY complaint_date DESC, id DESC LIMIT 10", (student_id,))
    visitors = db.query_all(
        "SELECT visitor_name, relationship, visit_date, entry_time, exit_time FROM visitors "
        "WHERE student_id = ? ORDER BY visit_date DESC, entry_time DESC LIMIT 10", (student_id,))
    return render_template("student_details.html", student=student, fees=fees, fee_totals=fee_totals,
                           attendance=attendance, percentage=percentage, recent_attendance=recent_attendance,
                           complaints=complaints, visitors=visitors,
                           rooms=room_choices() if student["status"] == "Active" and not student["room_id"] else [])


# -------------------------------------------------------------- delete
@bp.route("/<int:student_id>/delete", methods=["POST"])
def delete_student(student_id):
    student = db.query_one("SELECT * FROM students WHERE id = ?", (student_id,))
    if student is None:
        abort(404)
    database = db.get_db()
    try:
        database.execute("DELETE FROM students WHERE id = ?", (student_id,))
        database.commit()
        flash(f"Student {student['full_name']} deleted (the bed was released automatically).", "success")
        return redirect(url_for("students.list_students"))
    except sqlite3.IntegrityError:
        database.rollback()
        flash(f"{student['full_name']} has fee records, so the student cannot be deleted. "
              "Set the status to 'Left' instead to keep the financial history.", "danger")
        return redirect(url_for("students.student_details", student_id=student_id))
