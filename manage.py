"""
manage.py - small command line tool for administrators.

    python manage.py create-admin        create an administrator account (asks for a password)
    python manage.py reset-password      set a new password for an existing user
    python manage.py seed-demo           fill an EMPTY database with sample data for a demonstration

The web app also offers a one-time /setup page, so create-admin is optional.
"""
import getpass
import os
import random
import sys
from datetime import date, datetime, timedelta

from werkzeug.security import generate_password_hash

import db
import helpers

DATABASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hostel.db")


def ask_password():
    while True:
        password = getpass.getpass("Password: ")
        problem = helpers.password_problem(password)
        if problem:
            print(problem)
        elif password != getpass.getpass("Repeat password: "):
            print("Passwords do not match.")
        else:
            return password


def create_admin():
    db.init_db(DATABASE)
    conn = db.connect(DATABASE)
    username = input("Username: ").strip()
    if not helpers.USERNAME_RE.fullmatch(username):
        sys.exit("Username must be 3-30 letters, numbers, dots or underscores.")
    if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        sys.exit("That username already exists. Use reset-password instead.")
    full_name = input("Full name: ").strip() or username
    conn.execute("INSERT INTO users (username, password_hash, full_name) VALUES (?,?,?)",
                 (username, generate_password_hash(ask_password()), full_name))
    conn.commit()
    print(f"Administrator '{username}' created.")


def reset_password():
    db.init_db(DATABASE)
    conn = db.connect(DATABASE)
    username = input("Username: ").strip()
    if not conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
        sys.exit("No such user.")
    conn.execute("UPDATE users SET password_hash = ? WHERE username = ?",
                 (generate_password_hash(ask_password()), username))
    conn.commit()
    print("Password updated.")


# ------------------------------------------------------------------ demo data
FIRST = ["Aarav", "Vivaan", "Aditya", "Rohan", "Karan", "Siddharth", "Arjun", "Rahul", "Neha", "Priya", "Sneha",
         "Pooja", "Ananya", "Kavya", "Isha", "Riya", "Manish", "Nikhil", "Tejas", "Omkar"]
LAST = ["Patil", "Deshmukh", "Kulkarni", "Joshi", "Shinde", "More", "Jadhav", "Pawar", "Gaikwad", "Kale"]


def seed_demo():
    db.init_db(DATABASE)
    conn = db.connect(DATABASE)
    if conn.execute("SELECT COUNT(*) FROM students").fetchone()[0] or conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0]:
        sys.exit("The database already contains students or rooms. Demo data is only added to an empty database.")
    rnd = random.Random(2026)
    today = date.today()

    rooms = [("101", 1, "Double", 2, 0), ("102", 1, "Double", 2, 0), ("103", 1, "Triple", 3, 0), ("104", 1, "Single", 1, 0),
             ("201", 2, "Double", 2, 0), ("202", 2, "Triple", 3, 0), ("203", 2, "Dormitory", 6, 0),
             ("204", 2, "Double", 2, 1), ("301", 3, "Single", 1, 0), ("302", 3, "Double", 2, 0)]
    for r in rooms:
        conn.execute("INSERT INTO rooms (room_no, floor, room_type, capacity, under_maintenance) VALUES (?,?,?,?,?)", r)

    courses = [("MCA", "Computer Applications", 2), ("MCA", "Computer Applications", 1), ("MBA", "Management", 1),
               ("BCA", "Computer Applications", 3), ("B.Tech", "Computer Science", 2), ("M.Sc", "Science", 1)]
    used_phones, student_ids = set(), []
    for i in range(18):
        gender = "Female" if 8 <= i <= 15 else "Male"      # matches the first names above
        name = f"{FIRST[i]} {LAST[i % len(LAST)]}"
        course, dept, year = courses[i % len(courses)]
        while True:
            phone = str(rnd.choice("6789")) + "".join(str(rnd.randint(0, 9)) for _ in range(9))
            if phone not in used_phones:
                used_phones.add(phone)
                break
        born = date(today.year - rnd.randint(19, 25), rnd.randint(1, 12), rnd.randint(1, 28))
        code = f"STU-{i + 1:04d}"
        cur = conn.execute(
            "INSERT INTO students (student_code, full_name, gender, dob, age, phone, email, address, guardian_name, "
            "guardian_phone, course, department, year, admission_date, status) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (code, name, gender, born.isoformat(), helpers.calc_age(born.isoformat()), phone,
             f"{name.split()[0].lower()}.{i + 1}@example.com", "Pune, Maharashtra",
             f"{rnd.choice(FIRST[:8])} {name.split()[1]}", "9" + "".join(str(rnd.randint(0, 9)) for _ in range(9)),
             course, dept, year, (today - timedelta(days=rnd.randint(40, 300))).isoformat(),
             "Active" if i < 16 else "Inactive"))
        student_ids.append(cur.lastrowid)

    # assign the active students to rooms (the triggers guarantee no room is over-filled)
    room_ids = {r[0]: conn.execute("SELECT id FROM rooms WHERE room_no = ?", (r[0],)).fetchone()[0] for r in rooms}
    layout = ["101", "101", "102", "102", "103", "103", "103", "104", "201", "201", "202", "202", "203", "203", "203", "301"]
    for student_id, room_no in zip(student_ids[:16], layout):
        conn.execute("UPDATE students SET room_id = ? WHERE id = ?", (room_ids[room_no], student_id))

    # fees: four monthly rents per active student, mixed payment states
    receipt = 0
    for student_id in student_ids[:16]:
        for months_back in range(3, -1, -1):
            first = today.replace(day=1)
            for _ in range(months_back):
                first = (first - timedelta(days=1)).replace(day=1)
            due = first.replace(day=5)
            cur = conn.execute("INSERT INTO fees (student_id, fee_type, amount, due_date, notes) VALUES (?,?,?,?,?)",
                               (student_id, "Hostel Rent", 4500.0, due.isoformat(), first.strftime("%B %Y") + " rent"))
            fee_id, state = cur.lastrowid, rnd.random()
            if months_back == 0 and today.day < 5:
                state = 0.9                                      # not due yet: leave unpaid
            if state < 0.6 or (months_back > 0 and state < 0.8):
                amounts = [4500.0]
            elif state < 0.8:
                amounts = [2000.0]                                # part-payment
            else:
                amounts = []
            for amount in amounts:
                paid_on = min(due + timedelta(days=rnd.randint(0, 6)), today)
                receipt += 1
                method = rnd.choice(["Cash", "UPI", "UPI", "Bank Transfer", "Card"])
                conn.execute("INSERT INTO payments (fee_id, amount, payment_date, method, transaction_ref, receipt_no) "
                             "VALUES (?,?,?,?,?,?)",
                             (fee_id, amount, paid_on.isoformat(), method,
                              None if method == "Cash" else f"TXN{rnd.randint(10**8, 10**9 - 1)}",
                              f"RCPT-{paid_on.year}-{receipt:05d}"))
    conn.execute("INSERT INTO fees (student_id, fee_type, amount, due_date, notes) VALUES (?,?,?,?,?)",
                 (student_ids[0], "Security Deposit", 10000.0, (today + timedelta(days=20)).isoformat(), "Refundable deposit"))

    # attendance for the last 10 days (about 90% present)
    for offset in range(10):
        day = (today - timedelta(days=offset)).isoformat()
        for student_id in student_ids[:16]:
            conn.execute("INSERT INTO attendance (student_id, att_date, status) VALUES (?,?,?)",
                         (student_id, day, "Present" if rnd.random() < 0.9 else "Absent"))

    complaints = [("Plumbing", "Tap in the bathroom is leaking continuously.", "High", "Pending"),
                  ("Electrical", "Ceiling fan makes a loud noise at night.", "Medium", "In Progress"),
                  ("Internet / Wi-Fi", "Wi-Fi is very slow on the second floor.", "Medium", "Pending"),
                  ("Cleanliness", "Corridor is not cleaned on weekends.", "Low", "Resolved"),
                  ("Mess / Food", "Dinner is often served cold.", "Low", "Pending")]
    for i, (category, text, priority, status) in enumerate(complaints):
        raised = today - timedelta(days=rnd.randint(1, 15))
        resolved = (raised + timedelta(days=2)).isoformat() if status == "Resolved" else None
        conn.execute("INSERT INTO complaints (student_id, category, description, complaint_date, priority, status, "
                     "resolution, resolved_date) VALUES (?,?,?,?,?,?,?,?)",
                     (student_ids[i], category, text, raised.isoformat(), priority, status,
                      "Housekeeping schedule corrected." if status == "Resolved" else None, resolved))

    visitors = [("Ramesh Patil", "Father", "Monthly visit"), ("Sunita Deshmukh", "Mother", "Brought food"),
                ("Amit Joshi", "Friend", "Project discussion"), ("Kiran Shinde", "Brother", "Collect documents")]
    for i, (name, relation, purpose) in enumerate(visitors):
        visit_day = today if i < 3 else today - timedelta(days=1)
        entry = f"{9 + i * 2:02d}:15"
        exit_time = None if i == 1 else f"{10 + i * 2:02d}:30"
        conn.execute("INSERT INTO visitors (visitor_name, phone, student_id, relationship, purpose, visit_date, entry_time, "
                     "exit_time) VALUES (?,?,?,?,?,?,?,?)",
                     (name, "98" + str(rnd.randint(10**7, 10**8 - 1)), student_ids[i + 2], relation, purpose,
                      visit_day.isoformat(), entry, exit_time))

    staff = [("Suresh Kamble", "Warden", 32000), ("Meena Patil", "Assistant Warden", 24000),
             ("Ganesh Pawar", "Security Guard", 16000), ("Lata More", "Cook", 18000),
             ("Dattu Jadhav", "Cleaner", 13000), ("Ravi Kale", "Maintenance", 20000)]
    for i, (name, role, salary) in enumerate(staff):
        conn.execute("INSERT INTO staff (staff_code, full_name, role, phone, email, joining_date, salary, status) "
                     "VALUES (?,?,?,?,?,?,?,?)",
                     (f"STF-{i + 1:04d}", name, role, "97" + str(rnd.randint(10**7, 10**8 - 1)),
                      f"{name.split()[0].lower()}@example.com", (today - timedelta(days=rnd.randint(200, 900))).isoformat(),
                      salary, "Active"))
    conn.commit()
    print("Demo data added: 10 rooms, 18 students, fees, payments, attendance, complaints, visitors, staff.")


COMMANDS = {"create-admin": create_admin, "reset-password": reset_password, "seed-demo": seed_demo}

if __name__ == "__main__":
    if len(sys.argv) != 2 or sys.argv[1] not in COMMANDS:
        sys.exit(__doc__)
    COMMANDS[sys.argv[1]]()
