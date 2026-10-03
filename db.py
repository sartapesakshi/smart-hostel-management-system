"""
db.py - all SQLite plumbing lives here.

* get_db()      -> one connection per request (stored in Flask's `g`)
* init_db()     -> creates the tables from schema.sql, migrates an old database
* helper funcs  -> query_all / query_one / next_code (small, easy to explain)
"""
import os
import re
import sqlite3
from datetime import datetime

from flask import current_app, g

SCHEMA_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")

DEFAULT_SETTINGS = {
    "hostel_name": "Smart Hostel",
    "hostel_address": "Pune, Maharashtra",
    "hostel_phone": "",
    "hostel_email": "",
}


# ---------------------------------------------------------------- connections
def connect(path):
    """Open a connection with foreign keys ON (SQLite has them OFF by default)."""
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row          # rows behave like dicts: row["name"]
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db():
    """Return the connection for the current request (created on first use)."""
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_app(app):
    app.teardown_appcontext(close_db)


# -------------------------------------------------------------- small helpers
def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def scalar(sql, params=()):
    row = get_db().execute(sql, params).fetchone()
    return row[0] if row else None


def next_code(db, table, column, prefix, width=4):
    """Generate the next readable ID such as STU-0007 / STF-0003."""
    rows = db.execute(f"SELECT {column} FROM {table} WHERE {column} LIKE ?",
                      (prefix + "-%",)).fetchall()
    highest = 0
    for r in rows:
        m = re.fullmatch(re.escape(prefix) + r"-(\d+)", r[0])
        if m:
            highest = max(highest, int(m.group(1)))
    return f"{prefix}-{highest + 1:0{width}d}"


def get_setting(key, default=""):
    row = query_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else DEFAULT_SETTINGS.get(key, default)


# ------------------------------------------------------------ initialisation
def init_db(path):
    """Create / upgrade the database file at `path`. Returns migration notes."""
    notes = []
    conn = connect(path)
    try:
        legacy = _is_legacy_schema(conn)
        if legacy:
            notes += _archive_legacy_tables(conn, path)

        with open(SCHEMA_FILE, encoding="utf-8") as fh:
            conn.executescript(fh.read())

        if legacy:
            notes += _copy_legacy_data(conn)

        for key, value in DEFAULT_SETTINGS.items():
            conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
        conn.commit()
    finally:
        conn.close()
    return notes


# --------------------------------------------------------------- migration
# The very first version of this project had three loose tables
# (students / rooms / fees) with no relations. If such a database is found we:
#   1. take a safe backup copy of the file,
#   2. rename the old tables to legacy_*  (nothing is deleted),
#   3. create the new schema,
#   4. copy whatever can be copied safely into the new tables.
def _is_legacy_schema(conn):
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(students)")]
    return bool(cols) and "student_code" not in cols


def _archive_legacy_tables(conn, path):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = os.path.splitext(path)[0] + f"_backup_{stamp}.db"
    dest = sqlite3.connect(backup_path)
    conn.backup(dest)                       # consistent copy of the whole file
    dest.close()

    for table in ("students", "rooms", "fees"):
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
        if exists:
            conn.execute(f"ALTER TABLE {table} RENAME TO legacy_{table}")
    conn.commit()
    return [f"Old database backed up to {os.path.basename(backup_path)}",
            "Old tables kept as legacy_students / legacy_rooms / legacy_fees"]


def _table_exists(conn, name):
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (name,)).fetchone() is not None


def _copy_legacy_data(conn):
    notes, today = [], datetime.now().strftime("%Y-%m-%d")
    room_ids = {}

    # --- rooms: floor/type are inferred (the old table had neither) ---
    if _table_exists(conn, "legacy_rooms"):
        for r in conn.execute("SELECT * FROM legacy_rooms ORDER BY id").fetchall():
            capacity = r["capacity"] or 0
            room_type = ("Single" if capacity == 1 else "Double" if capacity == 2
                         else "Triple" if capacity == 3 else "Dormitory")
            m = re.match(r"\d", str(r["room_no"] or ""))
            floor = int(str(r["room_no"])[0]) if m and len(str(r["room_no"])) > 2 else 0
            try:
                cur = conn.execute(
                    "INSERT INTO rooms (room_no, floor, room_type, capacity) VALUES (?,?,?,?)",
                    (str(r["room_no"]).strip(), floor, room_type, capacity))
                room_ids[str(r["room_no"]).strip().lower()] = cur.lastrowid
            except sqlite3.IntegrityError:
                notes.append(f"Room '{r['room_no']}' could not be copied (invalid/duplicate data).")

    # --- students ---
    student_ids = {}
    if _table_exists(conn, "legacy_students"):
        for s in conn.execute("SELECT * FROM legacy_students ORDER BY id").fetchall():
            code = next_code(conn, "students", "student_code", "STU")
            room_id = room_ids.get(str(s["room_no"] or "").strip().lower())
            values = [code, (s["name"] or "").strip(), "Other", s["age"],
                      (s["phone"] or "").strip(), (s["course"] or "").strip() or "Not specified",
                      today]
            sql = ("INSERT INTO students (student_code, full_name, gender, age, phone, course, "
                   "admission_date, room_id) VALUES (?,?,?,?,?,?,?,?)")
            try:
                cur = conn.execute(sql, values + [room_id])
            except sqlite3.IntegrityError:
                try:   # most likely the room is full/invalid: keep the student unassigned
                    cur = conn.execute(sql, values + [None])
                    if s["room_no"]:
                        notes.append(f"Student '{s['name']}' copied without room '{s['room_no']}' "
                                     "(room missing or full). Assign a room manually.")
                except sqlite3.IntegrityError:
                    notes.append(f"Student '{s['name']}' skipped (duplicate or invalid phone).")
                    continue
            student_ids.setdefault((s["name"] or "").strip().lower(), []).append(cur.lastrowid)

    # --- fees: the old table stored the student NAME, so we match by name ---
    if _table_exists(conn, "legacy_fees"):
        for f in conn.execute("SELECT * FROM legacy_fees ORDER BY id").fetchall():
            matches = student_ids.get((f["student_name"] or "").strip().lower(), [])
            if len(matches) != 1 or not f["amount"] or f["amount"] <= 0:
                notes.append(f"Fee #{f['id']} for '{f['student_name']}' not copied "
                             "(no unique matching student). Still available in legacy_fees.")
                continue
            cur = conn.execute(
                "INSERT INTO fees (student_id, fee_type, amount, due_date) VALUES (?,?,?,?)",
                (matches[0], "Hostel Fee", f["amount"], today))
            if (f["status"] or "").strip().lower() == "paid":
                conn.execute(
                    "INSERT INTO payments (fee_id, amount, payment_date, method, receipt_no) "
                    "VALUES (?,?,?,?,?)",
                    (cur.lastrowid, f["amount"], today, "Cash",
                     f"RCPT-{today[:4]}-M{cur.lastrowid:05d}"))
    conn.commit()
    return notes
