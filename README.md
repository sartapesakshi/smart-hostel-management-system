# Smart Hostel Management System

**MCA Final Year Project** · Python · Flask · SQLite3 · HTML5 · CSS3 · JavaScript

---

## 1. Abstract

The Smart Hostel Management System is a web application that replaces the registers and spreadsheets a hostel office normally uses. One administrator can register students, allot beds, bill and collect fees (with printable receipts), take daily attendance, track complaints, log visitors, manage staff and produce eight printable / exportable reports. Occupancy, fee balances and dashboard figures are never typed in by hand: they are calculated from the database every time a page opens, so they cannot disagree with the underlying records.

## 2. Problem statement

Small and medium hostels still keep student details, room allotment, fee payments and complaints in separate notebooks or Excel files. This causes: double allotment of beds, fees recorded against the wrong person, lost receipts, no overdue-fee warning, no attendance history, and hours spent preparing monthly reports. There is no single trustworthy source of information.

## 3. Objectives

1. Keep all hostel data in one relational database with enforced integrity.
2. Make it impossible to over-fill a room or record a payment larger than the amount due.
3. Show live statistics and charts on a dashboard.
4. Provide secure, role-protected access (hashed passwords, sessions, CSRF protection).
5. Generate receipts and reports (print, CSV, PDF) from real data.
6. Be simple enough to install in minutes and explain line by line.

## 4. Existing system vs proposed system

| Existing (manual / first version of this project) | Proposed (this project) |
|---|---|
| Paper registers or loose tables | 8 related tables with primary/foreign keys |
| Room occupancy typed by hand | Occupancy is counted by the database (view) and guarded by triggers |
| Fees linked to a student *name* | Fees and payments linked to the student by ID; part-payments supported |
| Hard-coded `admin / admin123`, no session, pages open to anyone | Hashed passwords, session login, every page protected |
| Delete through a plain link | Delete only through confirmed POST forms with CSRF tokens |
| No search, filters or reports | Search, filters, pagination, 8 reports with CSV/PDF export |

## 5. Features

* Professional responsive dashboard (laptop / tablet / mobile), sidebar navigation, toast notifications, delete-confirmation dialog
* Students: add, edit, delete, search, filter, details page (fees, attendance, complaints, visitors)
* Rooms & beds: Single / Double / Triple / Dormitory, assign, vacate, transfer, maintenance mode, automatic occupancy
* Fees: bill, part-payments, payment history, overdue detection, receipt with amount in words, printable
* Attendance: daily sheet, history, student-wise %, monthly grid, no duplicates
* Complaints: priority, status workflow, resolution notes
* Visitors: register, record exit, today / inside-now / history
* Staff: CRUD, payroll total
* Reports: student, occupancy, fee collection, pending fees, attendance, complaints, visitors, staff
* Profile: change password (hashed), edit profile, hostel name/address used on receipts

## 6. Technologies used

| Layer | Technology |
|---|---|
| Back end | Python 3.10+, Flask 3 (blueprints, Jinja2 templates) |
| Database | SQLite 3 (foreign keys, CHECK, UNIQUE, triggers, views) |
| Front end | HTML5, CSS3 (hand-written, no framework), vanilla JavaScript |
| Charts | Chart.js 4 (loaded from CDN, optional local copy) |
| PDF export | ReportLab |
| Security | Werkzeug password hashing, Flask sessions, CSRF tokens |

## 7. System requirements

* Any OS (Windows / Linux / macOS), 2 GB RAM, Python 3.10 or newer, a modern browser (Chrome, Edge, Firefox).
* Internet is needed only to load Chart.js for the dashboard charts (see "Offline charts").

## 8. Installation and running

```bash
cd smartHostelmanagement
python -m venv venv
venv\Scripts\activate          # Windows      (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
python app.py
```

Open **http://127.0.0.1:5000**.

### Default admin setup

The project ships **without any password** (nothing is hard-coded). The first time you open the site you are taken to a **"Create the administrator account"** page: choose a username and password (min. 8 characters with a letter and a number). It is stored hashed. That page disappears once an account exists.

Command-line alternatives:

```bash
python manage.py create-admin     # create an administrator
python manage.py reset-password   # forgotten password
python manage.py seed-demo        # add sample data to an EMPTY database (for demonstrations)
```

The supplied `hostel.db` already contains **demo data** (10 rooms, 18 students, fees, attendance, complaints, visitors, staff). To start clean, delete `hostel.db` and run the app again: an empty database is created automatically.

### Running the automated tests

```bash
python -m unittest discover -s tests -v
```

### Offline charts

Download `https://cdn.jsdelivr.net/npm/chart.js@4.4.3/dist/chart.umd.min.js` once and save it as `static/js/chart.umd.min.js`. The dashboard uses it automatically when the CDN is unreachable.

### Migrating from the first version of the project

Nothing to do manually. On start-up, if the old `students / rooms / fees` tables are found, the app (1) saves a backup copy `hostel_backup_<date>.db`, (2) renames the old tables to `legacy_students / legacy_rooms / legacy_fees` (nothing is deleted), (3) creates the new schema and (4) copies what can be copied: rooms (floor and type are *inferred* from room number and capacity), students (gender is set to "Other", admission date to the migration date: edit these), and fees matched to students by name (paid fees get a cash payment). Anything that cannot be matched stays in the `legacy_*` tables and is listed in the console.

---

## 9. System architecture

```
 Browser (HTML + CSS + JS)
        │  HTTP request / form POST
        ▼
 Flask application  (app.py → create_app)
   ├─ before_request: CSRF check + "is the user logged in?"
   ├─ Blueprints (routes/*.py): auth, dashboard, students, rooms, fees,
   │                            attendance, complaints, visitors, staff, reports, profile
   ├─ helpers.py: validators, pagination, formatting, icons
   ├─ db.py: connection, schema creation, migration
   └─ Jinja2 templates (templates/*.html)  → HTML response
        │  SQL (parameterised)
        ▼
 SQLite  hostel.db  (tables + views + triggers, schema.sql)
```

It follows the **MVC idea**: *Model* = SQLite schema + queries, *View* = Jinja templates, *Controller* = the blueprint functions.

## 10. Modules

| Module | File | Purpose |
|---|---|---|
| Authentication | `routes/auth.py` | setup, login, logout |
| Dashboard | `routes/dashboard.py` | statistics and chart data from SQL |
| Students | `routes/students.py` | CRUD, validation, details |
| Rooms & beds | `routes/rooms.py` | CRUD, `assign_student`, `vacate_student` |
| Fees | `routes/fees.py` | fees, payments, receipts |
| Attendance | `routes/attendance.py` | sheet, history, monthly report |
| Complaints | `routes/complaints.py` | register, update, resolve |
| Visitors | `routes/visitors.py` | register, exit |
| Staff | `routes/staff.py` | CRUD |
| Reports | `routes/reports.py` | 8 reports + CSV + PDF |
| Profile | `routes/profile.py` | profile, password, settings |

## 11. Database design

### ER description

* **rooms** 1 ──── ∞ **students** (a room holds many students; a student has at most one room)
* **students** 1 ──── ∞ **fees** (RESTRICT: a student with fees cannot be deleted)
* **fees** 1 ──── ∞ **payments** (a fee can be paid in parts)
* **students** 1 ──── ∞ **attendance** (UNIQUE per student per date; deleted with the student)
* **students** 1 ──── ∞ **complaints**, **students** 1 ──── ∞ **visitors**
* **users** 1 ──── ∞ **payments / attendance** (who received / marked: `received_by`, `marked_by`)
* **staff**, **settings** are stand-alone.

```
rooms ──< students ──< fees ──< payments >── users
              ├──< attendance >── users
              ├──< complaints
              └──< visitors
```

### Table description

| Table | Important columns | Rules |
|---|---|---|
| `users` | username (unique, case-insensitive), password_hash, full_name | passwords hashed |
| `rooms` | room_no UNIQUE, floor, room_type, capacity, under_maintenance | CHECK: type ↔ capacity (Single 1, Double 2, Triple 3, Dormitory ≥ 4) |
| `students` | student_code UNIQUE, name, gender, dob, phone UNIQUE, email UNIQUE, course, year, room_id FK, status | CHECK: only an **Active** student may have a room |
| `fees` | student_id FK, fee_type, amount, due_date | CHECK amount > 0 |
| `payments` | fee_id FK, amount, payment_date, method, transaction_ref, receipt_no UNIQUE | CHECK amount > 0 |
| `attendance` | student_id FK, att_date, status | UNIQUE(student_id, att_date) |
| `complaints` | student_id FK, category, priority, status, resolution, resolved_date | CHECK: resolved_date present **iff** status = Resolved |
| `visitors` | student_id FK, visitor_name, entry_time, exit_time | CHECK exit ≥ entry |
| `staff` | staff_code UNIQUE, role, phone UNIQUE, salary, status | CHECK salary ≥ 0 |
| `settings` | key, value | hostel name, address |

**Views** (derived data, never stored twice): `room_overview` (occupied / available / status) and `fee_overview` (paid / balance / status).
**Triggers**: refuse a student entering a full or maintenance room, and refuse reducing capacity below the number of occupants.

Fee status rules: **Paid** (balance 0) · **Overdue** (balance > 0 and due date passed, even if part-paid) · **Partial** (some paid, not yet due) · **Pending** (nothing paid, not yet due).

## 12. Important Flask routes

| URL | Method | Function |
|---|---|---|
| `/login`, `/logout`, `/setup` | GET/POST | authentication |
| `/dashboard` | GET | statistics + chart data |
| `/students/`, `/students/add`, `/students/<id>`, `/students/<id>/edit`, `/students/<id>/delete` | GET/POST | student module |
| `/rooms/`, `/rooms/add`, `/rooms/<id>`, `/rooms/<id>/edit`, `/rooms/<id>/delete` | GET/POST | room module |
| `/rooms/assign`, `/rooms/vacate` | POST | allot / release a bed |
| `/fees/`, `/fees/add`, `/fees/<id>`, `/fees/<id>/pay`, `/fees/payments`, `/fees/receipt/<payment_id>` | GET/POST | fee module |
| `/attendance/`, `/attendance/save`, `/attendance/history`, `/attendance/monthly` | GET/POST | attendance |
| `/complaints/`, `/complaints/add`, `/complaints/<id>`, `/complaints/<id>/update` | GET/POST | complaints |
| `/visitors/`, `/visitors/add`, `/visitors/<id>/exit` | GET/POST | visitors |
| `/staff/`, `/staff/add`, `/staff/<id>`, `/staff/<id>/edit` | GET/POST | staff |
| `/reports/`, `/reports/<name>?export=csv\|pdf` | GET | reports |
| `/profile/`, `/profile/update`, `/profile/password`, `/profile/settings` | GET/POST | profile |

## 13. Project structure

```
smartHostelmanagement/
├── app.py            application factory, security hooks, error pages
├── db.py             connection, schema creation, migration
├── helpers.py        validators, pagination, filters, icons
├── schema.sql        tables, triggers, views
├── manage.py         create-admin / reset-password / seed-demo
├── hostel.db         SQLite database (demo data, no users)
├── requirements.txt
├── routes/           one blueprint per module
├── templates/        Jinja2 pages (base.html, _macros.html, ...)
├── static/css/style.css
├── static/js/script.js
└── tests/test_app.py 67 automated tests
```

## 14. Why Flask and SQLite?

* **Flask** is small and explicit: a route is a Python function, a page is a template. Nothing is hidden behind generated code, so every line can be explained. It is also what the original project already used. Django would add an admin site and ORM that hide the SQL, which is less useful for demonstrating database design.
* **SQLite** needs no server installation, stores everything in one file (easy to copy for a demo and to back up), supports foreign keys, CHECK constraints, triggers and views, and is more than fast enough for one hostel office. Moving to MySQL/PostgreSQL later only needs the connection code and a few SQL functions changed.

## 15. Security measures

* Passwords hashed with Werkzeug (`scrypt`); never stored or shown in plain text
* Server-side session (signed cookie, HttpOnly, SameSite=Lax); "remember me" = 7 days
* Every page except login/setup is blocked by one `before_request` hook (no route can be forgotten)
* CSRF token on every POST form; deletes are POST-only with a confirmation dialog
* Parameterised SQL everywhere (no SQL injection); Jinja auto-escapes output (no XSS)
* Same error message for wrong username and wrong password; open-redirect protection on `next`
* `Cache-Control: no-store`, so the Back button after logout shows nothing
* Friendly error pages; Python tracebacks are never shown (debug is off)

## 16. Future scope

Role-based accounts (warden / accountant / student login); SMS / e-mail reminders for overdue fees and visitor alerts; online payment gateway (UPI / Razorpay); QR-code or biometric attendance; student self-service portal and mobile app; room-change requests with approval; mess menu and meal attendance; backups and audit log; login attempt limiting; migration to MySQL/PostgreSQL for multiple hostels.

---

## 17. Viva questions and answers

**Q1. Why did you split the code into blueprints?**
Each module (students, fees...) has its own file, so the project stays readable and one module can be changed without touching the others. `app.py` only wires them together.

**Q2. How is occupancy updated automatically?**
Occupancy is not stored. The `room_overview` view counts students whose `room_id` equals the room, so assigning or vacating a student instantly changes the numbers. Storing it separately could make it go out of sync.

**Q3. How do you stop a room being over-filled?**
Two layers: the Python function `assign_student` checks availability and shows a friendly message; and a database **trigger** aborts any `INSERT/UPDATE` that would exceed the capacity, even if someone edits the database directly.

**Q4. Why a separate `payments` table?**
A student may pay a fee in instalments. `fees` says what is owed, `payments` stores each payment with its own receipt number. Status and balance are derived, so they can never be inconsistent.

**Q5. How are passwords stored?**
Only a salted hash (`generate_password_hash`). Login uses `check_password_hash`. A hash cannot be reversed, so even the database owner cannot read the password.

**Q6. What is a session and how does login persist?**
After login the user id is stored in Flask's signed session cookie. A `before_request` function reads it on every request and redirects to login if missing or invalid. Logout clears the session.

**Q7. What is CSRF and how did you prevent it?**
A malicious site could make the browser submit a form to our site while the admin is logged in. Each form carries a secret random token stored in the session; the server rejects POSTs without the matching token.

**Q8. What is SQL injection and how is it prevented?**
Injecting SQL through input. All queries use `?` placeholders so input is always treated as data, never as SQL.

**Q9. How do you prevent duplicate attendance?**
`UNIQUE(student_id, att_date)` in the table, plus an *upsert* (`INSERT ... ON CONFLICT DO UPDATE`), so saving a date again updates the earlier mark.

**Q10. What are the constraints you used?**
PRIMARY KEY, FOREIGN KEY (with RESTRICT / CASCADE / SET NULL), UNIQUE, NOT NULL and CHECK (positive amounts, valid status lists, room type ↔ capacity, resolved date iff resolved).

**Q11. Why can't I delete a student who has fees?**
`fees.student_id` uses `ON DELETE RESTRICT` to protect financial records. The student should be marked **Left** instead, which also releases the bed.

**Q12. Why is foreign-key enforcement turned on in `connect()`?**
SQLite ignores foreign keys unless `PRAGMA foreign_keys = ON` is run on every connection.

**Q13. Explain the overdue logic.**
`fee_overview` compares `due_date` with today's date and the balance: balance 0 → Paid; balance > 0 and past due → Overdue; some paid → Partial; else Pending.

**Q14. How does pagination work?**
`paginate()` runs `COUNT(*)` for the total, then the same query with `LIMIT` and `OFFSET` for the current page and returns page information that the `render_pager` macro displays.

**Q15. How did you generate PDF and CSV reports without repeating code?**
Each report is a function returning (columns, rows, summary). One generic route shows it as HTML, or converts the same data to CSV (`csv` module) or PDF (ReportLab).

**Q16. How did you test it?**
67 automated tests in `tests/test_app.py` use Flask's test client with a temporary database: login/logout, protected routes, CSRF, every CRUD module, validation errors, room-full cases, fee lifecycle, duplicates, reports, dashboard numbers and the old-database migration.

**Q17. What happens to an old database?**
It is backed up, old tables are renamed `legacy_*` (never deleted) and usable data is copied into the new schema automatically.

**Q18. What are the limitations?**
Single administrator role, SQLite is not meant for many simultaneous writers, no online payments or notifications. See Future scope.

---

## 18. Feature checklist

- [x] Login / logout, hashed passwords, sessions, protected routes, password toggle, remember me
- [x] Dashboard: 10 live figures + 4 charts
- [x] Students CRUD, search, filters, pagination, details page, validation, duplicate prevention
- [x] Rooms CRUD, assign / vacate / transfer, automatic occupancy, full-room prevention, maintenance
- [x] Fees: add, part-payments, history, pending / paid / overdue, receipt + print, amount in words
- [x] Attendance: daily sheet, history, % per student, monthly report, no duplicates
- [x] Complaints: priority, status workflow, resolution, filters, dashboard count
- [x] Visitors: register, exit time, today / inside / history, filters
- [x] Staff: CRUD, search, filters, details
- [x] Reports: 8 reports, date filters, print, CSV, PDF
- [x] Profile: view, edit, change password, hostel settings
- [x] Toasts, confirm-before-delete, responsive layout, print styles
- [x] SQLite foreign keys, CHECK, UNIQUE, triggers, views, migration
- [x] 67 automated tests
