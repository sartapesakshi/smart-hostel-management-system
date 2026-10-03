-- =====================================================================
--  Smart Hostel Management System - database schema (SQLite 3)
--  Executed on every start-up. Every statement is IF NOT EXISTS, so it
--  is safe to run repeatedly and never touches existing data.
--  Foreign keys are switched on per connection in db.py
--  (PRAGMA foreign_keys = ON), SQLite does not enforce them otherwise.
-- =====================================================================

-- ---------- users: administrator accounts (passwords are hashed) ----------
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    full_name     TEXT NOT NULL,
    email         TEXT,
    phone         TEXT,
    role          TEXT NOT NULL DEFAULT 'Administrator',
    created_at    TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_login    TEXT
);

-- ---------- settings: key/value pairs (hostel name, address ...) ----------
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------- rooms ----------
CREATE TABLE IF NOT EXISTS rooms (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    room_no           TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    floor             INTEGER NOT NULL CHECK (floor BETWEEN 0 AND 50),
    room_type         TEXT    NOT NULL CHECK (room_type IN ('Single','Double','Triple','Dormitory')),
    capacity          INTEGER NOT NULL CHECK (capacity BETWEEN 1 AND 50),
    under_maintenance INTEGER NOT NULL DEFAULT 0 CHECK (under_maintenance IN (0,1)),
    notes             TEXT,
    created_at        TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    -- the room type decides the capacity (Dormitory = 4 or more beds)
    CHECK (   (room_type = 'Single'    AND capacity = 1)
           OR (room_type = 'Double'    AND capacity = 2)
           OR (room_type = 'Triple'    AND capacity = 3)
           OR (room_type = 'Dormitory' AND capacity >= 4))
);

-- ---------- students ----------
CREATE TABLE IF NOT EXISTS students (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_code   TEXT NOT NULL UNIQUE,                 -- e.g. STU-0001
    full_name      TEXT NOT NULL,
    gender         TEXT NOT NULL CHECK (gender IN ('Male','Female','Other')),
    dob            TEXT,                                 -- YYYY-MM-DD
    age            INTEGER CHECK (age IS NULL OR age BETWEEN 10 AND 100),
    phone          TEXT NOT NULL UNIQUE,
    email          TEXT UNIQUE COLLATE NOCASE,           -- NULL allowed, duplicates not
    address        TEXT,
    guardian_name  TEXT,
    guardian_phone TEXT,
    course         TEXT NOT NULL,
    department     TEXT,
    year           INTEGER CHECK (year IS NULL OR year BETWEEN 1 AND 6),
    room_id        INTEGER REFERENCES rooms(id) ON DELETE RESTRICT,
    admission_date TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Inactive','Left')),
    created_at     TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    -- only an Active student may hold a bed
    CHECK (status = 'Active' OR room_id IS NULL)
);
CREATE INDEX IF NOT EXISTS idx_students_room   ON students(room_id);
CREATE INDEX IF NOT EXISTS idx_students_course ON students(course);

-- ---------- fees (what a student owes) and payments (what was paid) ----------
-- Status (Paid / Pending / Partial / Overdue) is NEVER stored. It is derived
-- from these two tables by the fee_overview view, so it cannot go out of sync.
CREATE TABLE IF NOT EXISTS fees (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
    fee_type   TEXT    NOT NULL,
    amount     REAL    NOT NULL CHECK (amount > 0),
    due_date   TEXT    NOT NULL,
    notes      TEXT,
    created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_fees_student ON fees(student_id);

CREATE TABLE IF NOT EXISTS payments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    fee_id          INTEGER NOT NULL REFERENCES fees(id) ON DELETE RESTRICT,
    amount          REAL    NOT NULL CHECK (amount > 0),
    payment_date    TEXT    NOT NULL,
    method          TEXT    NOT NULL CHECK (method IN ('Cash','UPI','Card','Bank Transfer','Cheque')),
    transaction_ref TEXT,
    receipt_no      TEXT    NOT NULL UNIQUE,
    received_by     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at      TEXT    NOT NULL DEFAULT (datetime('now','localtime'))
);
CREATE INDEX IF NOT EXISTS idx_payments_fee ON payments(fee_id);

-- ---------- attendance (one row per student per day) ----------
CREATE TABLE IF NOT EXISTS attendance (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    att_date   TEXT    NOT NULL,
    status     TEXT    NOT NULL CHECK (status IN ('Present','Absent')),
    marked_by  INTEGER REFERENCES users(id) ON DELETE SET NULL,
    created_at TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE (student_id, att_date)                 -- no duplicate attendance
);
CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(att_date);

-- ---------- complaints ----------
CREATE TABLE IF NOT EXISTS complaints (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id     INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    category       TEXT    NOT NULL,
    description    TEXT    NOT NULL,
    complaint_date TEXT    NOT NULL,
    priority       TEXT    NOT NULL DEFAULT 'Medium' CHECK (priority IN ('Low','Medium','High')),
    status         TEXT    NOT NULL DEFAULT 'Pending' CHECK (status IN ('Pending','In Progress','Resolved')),
    resolution     TEXT,
    resolved_date  TEXT,
    created_at     TEXT    NOT NULL DEFAULT (datetime('now','localtime')),
    -- a complaint has a resolved date if, and only if, it is Resolved
    CHECK ((status = 'Resolved' AND resolved_date IS NOT NULL)
        OR (status <> 'Resolved' AND resolved_date IS NULL))
);

-- ---------- visitors ----------
CREATE TABLE IF NOT EXISTS visitors (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    visitor_name TEXT NOT NULL,
    phone        TEXT NOT NULL,
    student_id   INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    relationship TEXT NOT NULL,
    purpose      TEXT NOT NULL,
    visit_date   TEXT NOT NULL,
    entry_time   TEXT NOT NULL,                   -- HH:MM
    exit_time    TEXT,                            -- NULL = still inside
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    CHECK (exit_time IS NULL OR exit_time >= entry_time)
);
CREATE INDEX IF NOT EXISTS idx_visitors_date ON visitors(visit_date);

-- ---------- staff ----------
CREATE TABLE IF NOT EXISTS staff (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    staff_code   TEXT NOT NULL UNIQUE,            -- e.g. STF-0001
    full_name    TEXT NOT NULL,
    role         TEXT NOT NULL,
    phone        TEXT NOT NULL UNIQUE,
    email        TEXT UNIQUE COLLATE NOCASE,
    joining_date TEXT NOT NULL,
    salary       REAL NOT NULL CHECK (salary >= 0),
    status       TEXT NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Inactive')),
    created_at   TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

-- =====================================================================
--  TRIGGERS - the database itself refuses impossible occupancy, even if
--  a bug in the Python code tried to allow it.
-- =====================================================================
CREATE TRIGGER IF NOT EXISTS trg_room_capacity_on_insert
BEFORE INSERT ON students
FOR EACH ROW WHEN NEW.room_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Room is under maintenance')
     WHERE (SELECT under_maintenance FROM rooms WHERE id = NEW.room_id) = 1;
    SELECT RAISE(ABORT, 'Room is full')
     WHERE (SELECT COUNT(*) FROM students WHERE room_id = NEW.room_id)
        >= (SELECT capacity FROM rooms WHERE id = NEW.room_id);
END;

CREATE TRIGGER IF NOT EXISTS trg_room_capacity_on_update
BEFORE UPDATE OF room_id ON students
FOR EACH ROW WHEN NEW.room_id IS NOT NULL AND NEW.room_id IS NOT OLD.room_id
BEGIN
    SELECT RAISE(ABORT, 'Room is under maintenance')
     WHERE (SELECT under_maintenance FROM rooms WHERE id = NEW.room_id) = 1;
    SELECT RAISE(ABORT, 'Room is full')
     WHERE (SELECT COUNT(*) FROM students WHERE room_id = NEW.room_id)
        >= (SELECT capacity FROM rooms WHERE id = NEW.room_id);
END;

CREATE TRIGGER IF NOT EXISTS trg_room_capacity_shrink
BEFORE UPDATE OF capacity ON rooms
FOR EACH ROW WHEN NEW.capacity < (SELECT COUNT(*) FROM students WHERE room_id = NEW.id)
BEGIN
    SELECT RAISE(ABORT, 'Capacity is lower than the number of current occupants');
END;

-- =====================================================================
--  VIEWS - derived values are calculated here, never stored twice.
--  (Views are dropped and re-created so an updated definition always applies.)
-- =====================================================================
DROP VIEW IF EXISTS room_overview;
CREATE VIEW room_overview AS
SELECT r.id, r.room_no, r.floor, r.room_type, r.capacity, r.under_maintenance, r.notes,
       COALESCE(o.cnt, 0)                                         AS occupied,
       CASE WHEN r.under_maintenance = 1 THEN 0
            ELSE MAX(r.capacity - COALESCE(o.cnt, 0), 0) END     AS available,
       CASE WHEN r.under_maintenance = 1        THEN 'Maintenance'
            WHEN COALESCE(o.cnt, 0) = 0         THEN 'Available'
            WHEN COALESCE(o.cnt, 0) < r.capacity THEN 'Partially Occupied'
            ELSE 'Full' END                                       AS status
FROM rooms r
LEFT JOIN (SELECT room_id, COUNT(*) AS cnt
             FROM students WHERE room_id IS NOT NULL GROUP BY room_id) o
       ON o.room_id = r.id;

DROP VIEW IF EXISTS fee_overview;
CREATE VIEW fee_overview AS
SELECT f.id, f.student_id, s.student_code, s.full_name AS student_name,
       f.fee_type, f.amount, f.due_date, f.notes,
       COALESCE(p.paid, 0)                                AS paid,
       ROUND(f.amount - COALESCE(p.paid, 0), 2)           AS balance,
       p.last_payment_date,
       CASE WHEN ROUND(f.amount - COALESCE(p.paid, 0), 2) <= 0 THEN 'Paid'
            WHEN f.due_date < date('now','localtime')            THEN 'Overdue'
            WHEN COALESCE(p.paid, 0) > 0                         THEN 'Partial'
            ELSE 'Pending' END                            AS status
FROM fees f
JOIN students s ON s.id = f.student_id
LEFT JOIN (SELECT fee_id, ROUND(SUM(amount), 2) AS paid, MAX(payment_date) AS last_payment_date
             FROM payments GROUP BY fee_id) p
       ON p.fee_id = f.id;
