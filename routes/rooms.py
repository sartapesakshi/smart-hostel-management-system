"""Rooms & Beds: CRUD for rooms, assigning students to beds, vacating beds.

Occupancy is NOT stored in the rooms table. It is counted from students.room_id
by the `room_overview` view, so it always matches reality. Database triggers
additionally refuse to put a student into a full / maintenance room.
"""
import re
import sqlite3

from flask import (Blueprint, abort, flash, redirect, render_template, request, url_for)

import db
import helpers
from helpers import clean

bp = Blueprint("rooms", __name__, url_prefix="/rooms")

ROOM_STATUSES = ["Available", "Partially Occupied", "Full", "Maintenance"]


# ------------------------------------------------- shared business rules
def assign_student(database, student_id, room_id):
    """Move a student into a room. Raises ValueError with a friendly message if not allowed.
    (The caller commits.) Used by the room page, the student page and the student form."""
    student = database.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if student is None:
        raise ValueError("That student does not exist.")
    if student["status"] != "Active":
        raise ValueError("Only students with status Active can be given a bed.")
    room = database.execute("SELECT * FROM room_overview WHERE id = ?", (room_id,)).fetchone()
    if room is None:
        raise ValueError("That room does not exist.")
    if student["room_id"] == room["id"]:
        raise ValueError(f"{student['full_name']} is already in room {room['room_no']}.")
    if room["under_maintenance"]:
        raise ValueError(f"Room {room['room_no']} is under maintenance.")
    if room["available"] <= 0:
        raise ValueError(f"Room {room['room_no']} is full ({room['occupied']} of {room['capacity']} beds taken).")
    try:
        database.execute("UPDATE students SET room_id = ? WHERE id = ?", (room_id, student_id))
    except sqlite3.IntegrityError as error:      # trigger safety net
        raise ValueError(str(error))
    return room


def vacate_student(database, student_id):
    student = database.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if student is None:
        raise ValueError("That student does not exist.")
    if student["room_id"] is None:
        raise ValueError(f"{student['full_name']} does not have a bed assigned.")
    database.execute("UPDATE students SET room_id = NULL WHERE id = ?", (student_id,))
    return student


def room_choices(include_room_id=None):
    """Rooms that can take another student (plus the student's current room when editing)."""
    return db.query_all(
        "SELECT * FROM room_overview WHERE (available > 0 AND under_maintenance = 0) OR id = ? "
        "ORDER BY floor, room_no", (include_room_id or -1,))


# ------------------------------------------------------------ validation
def validate_room(form, room_id=None):
    data = {
        "room_no": clean(form.get("room_no")),
        "floor": clean(form.get("floor")),
        "room_type": clean(form.get("room_type")),
        "capacity": clean(form.get("capacity")),
        "under_maintenance": 1 if form.get("under_maintenance") == "on" else 0,
        "notes": clean(form.get("notes")),
    }
    errors = {}

    if not data["room_no"]:
        errors["room_no"] = "Room number is required."
    elif not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 \-/]{0,19}", data["room_no"]):
        errors["room_no"] = "Use up to 20 letters, numbers, spaces, '-' or '/'."
    elif db.query_one("SELECT 1 FROM rooms WHERE room_no = ? AND id <> ?",
                      (data["room_no"], room_id or -1)):
        errors["room_no"] = f"Room {data['room_no']} already exists."

    floor = helpers.parse_int(data["floor"], 0, 50)
    if floor is None:
        errors["floor"] = "Enter a floor number between 0 (ground) and 50."

    if data["room_type"] not in helpers.ROOM_TYPES:
        errors["room_type"] = "Choose a room type."

    capacity = helpers.parse_int(data["capacity"], 1, 50)
    if capacity is None:
        errors["capacity"] = "Capacity must be a whole number between 1 and 50."
    elif data["room_type"] in helpers.ROOM_TYPES:
        beds = helpers.ROOM_TYPES[data["room_type"]]
        if data["room_type"] == "Dormitory" and capacity < beds:
            errors["capacity"] = "A dormitory needs at least 4 beds."
        elif data["room_type"] != "Dormitory" and capacity != beds:
            errors["capacity"] = f"A {data['room_type']} room has exactly {beds} bed(s)."

    if room_id and "capacity" not in errors and capacity is not None:
        occupied = db.scalar("SELECT COUNT(*) FROM students WHERE room_id = ?", (room_id,))
        if capacity < occupied:
            errors["capacity"] = f"{occupied} students already live here. Vacate beds before reducing capacity."
        if data["under_maintenance"] and occupied:
            errors["under_maintenance"] = "Vacate all students before marking the room as under maintenance."

    data["floor_value"], data["capacity_value"] = floor, capacity
    return data, errors


# ---------------------------------------------------------------- views
@bp.route("/")
def list_rooms():
    q = clean(request.args.get("q"))
    floor = clean(request.args.get("floor"))
    room_type = clean(request.args.get("type"))
    status = clean(request.args.get("status"))

    conditions, params = [], []
    if q:
        conditions.append("room_no LIKE ? ESCAPE '\\'")
        params.append(helpers.like(q))
    if floor != "" and helpers.parse_int(floor, 0, 50) is not None:
        conditions.append("floor = ?")
        params.append(int(floor))
    if room_type in helpers.ROOM_TYPES:
        conditions.append("room_type = ?")
        params.append(room_type)
    if status in ROOM_STATUSES:
        conditions.append("status = ?")
        params.append(status)

    sql = "SELECT * FROM room_overview" + helpers.where(conditions) + " ORDER BY floor, room_no"
    rows, pager = helpers.paginate(sql, params, helpers.page_number())

    totals = db.query_one(
        "SELECT COUNT(*) AS rooms, COALESCE(SUM(capacity),0) AS beds, COALESCE(SUM(occupied),0) AS occupied, "
        "COALESCE(SUM(available),0) AS available, "
        "COALESCE(SUM(CASE WHEN status='Maintenance' THEN 1 ELSE 0 END),0) AS maintenance FROM room_overview")
    floors = [r[0] for r in db.query_all("SELECT DISTINCT floor FROM rooms ORDER BY floor")]
    return render_template("rooms.html", rooms=rows, pager=pager, totals=totals, floors=floors,
                           statuses=ROOM_STATUSES, filters={"q": q, "floor": floor, "type": room_type,
                                                            "status": status})


@bp.route("/add", methods=["GET", "POST"])
def add_room():
    data, errors = {}, {}
    if request.method == "POST":
        data, errors = validate_room(request.form)
        if not errors:
            try:
                database = db.get_db()
                database.execute(
                    "INSERT INTO rooms (room_no, floor, room_type, capacity, under_maintenance, notes) "
                    "VALUES (?,?,?,?,?,?)",
                    (data["room_no"], data["floor_value"], data["room_type"], data["capacity_value"],
                     data["under_maintenance"], data["notes"] or None))
                database.commit()
                flash(f"Room {data['room_no']} added.", "success")
                return redirect(url_for("rooms.list_rooms"))
            except sqlite3.IntegrityError:
                errors["room_no"] = f"Room {data['room_no']} already exists."
        flash("Please correct the highlighted fields.", "danger")
    return render_template("room_form.html", room=None, data=data, errors=errors,
                           room_types=helpers.ROOM_TYPES)


@bp.route("/<int:room_id>/edit", methods=["GET", "POST"])
def edit_room(room_id):
    room = db.query_one("SELECT * FROM room_overview WHERE id = ?", (room_id,))
    if room is None:
        abort(404)
    data, errors = dict(room), {}
    data["under_maintenance"] = room["under_maintenance"]
    if request.method == "POST":
        data, errors = validate_room(request.form, room_id)
        if not errors:
            try:
                database = db.get_db()
                database.execute(
                    "UPDATE rooms SET room_no=?, floor=?, room_type=?, capacity=?, under_maintenance=?, notes=? "
                    "WHERE id=?",
                    (data["room_no"], data["floor_value"], data["room_type"], data["capacity_value"],
                     data["under_maintenance"], data["notes"] or None, room_id))
                database.commit()
                flash(f"Room {data['room_no']} updated.", "success")
                return redirect(url_for("rooms.room_details", room_id=room_id))
            except sqlite3.IntegrityError as error:
                errors["room_no"] = f"Could not save: {error}"
        flash("Please correct the highlighted fields.", "danger")
    return render_template("room_form.html", room=room, data=data, errors=errors,
                           room_types=helpers.ROOM_TYPES)


@bp.route("/<int:room_id>")
def room_details(room_id):
    room = db.query_one("SELECT * FROM room_overview WHERE id = ?", (room_id,))
    if room is None:
        abort(404)
    occupants = db.query_all(
        "SELECT id, student_code, full_name, course, year, phone FROM students "
        "WHERE room_id = ? ORDER BY full_name", (room_id,))
    candidates = []
    if room["available"] > 0:
        candidates = db.query_all(
            "SELECT id, student_code, full_name, course FROM students "
            "WHERE status = 'Active' AND room_id IS NULL ORDER BY full_name")
    return render_template("room_details.html", room=room, occupants=occupants, candidates=candidates)


@bp.route("/<int:room_id>/delete", methods=["POST"])
def delete_room(room_id):
    room = db.query_one("SELECT * FROM room_overview WHERE id = ?", (room_id,))
    if room is None:
        abort(404)
    if room["occupied"] > 0:
        flash(f"Room {room['room_no']} still has {room['occupied']} student(s). Vacate them first.", "danger")
        return redirect(url_for("rooms.room_details", room_id=room_id))
    try:
        database = db.get_db()
        database.execute("DELETE FROM rooms WHERE id = ?", (room_id,))
        database.commit()
        flash(f"Room {room['room_no']} deleted.", "success")
    except sqlite3.IntegrityError:
        flash("This room is still referenced by other records and cannot be deleted.", "danger")
    return redirect(url_for("rooms.list_rooms"))


# ------------------------------------------------------- assign / vacate
def _return_target(default_endpoint, **values):
    return helpers.safe_next_url(request.form.get("next")) or url_for(default_endpoint, **values)


@bp.route("/assign", methods=["POST"])
def assign():
    student_id = helpers.parse_int(request.form.get("student_id"), 1)
    room_id = helpers.parse_int(request.form.get("room_id"), 1)
    target = _return_target("rooms.list_rooms")
    if student_id is None or room_id is None:
        flash("Please choose both a student and a room.", "danger")
        return redirect(target)
    database = db.get_db()
    try:
        room = assign_student(database, student_id, room_id)
        database.commit()
        flash(f"Student assigned to room {room['room_no']}.", "success")
    except ValueError as error:
        database.rollback()
        flash(str(error), "danger")
    return redirect(target)


@bp.route("/vacate", methods=["POST"])
def vacate():
    student_id = helpers.parse_int(request.form.get("student_id"), 1)
    target = _return_target("rooms.list_rooms")
    if student_id is None:
        abort(400, "Missing student.")
    database = db.get_db()
    try:
        student = vacate_student(database, student_id)
        database.commit()
        flash(f"{student['full_name']} has been vacated from the room.", "success")
    except ValueError as error:
        database.rollback()
        flash(str(error), "danger")
    return redirect(target)
