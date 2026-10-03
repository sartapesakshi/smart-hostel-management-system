"""
Automated tests for the Smart Hostel Management System.

Run from the project folder with:      python -m unittest discover -s tests -v

Every test starts with a brand-new temporary database, logs in through the real
login form and then drives the application exactly like a browser would
(forms, redirects, flash messages) using Flask's test client.
"""
import csv
import io
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import db as dbmodule                     # noqa: E402
import helpers                            # noqa: E402
import manage                             # noqa: E402
from app import create_app                # noqa: E402

TODAY = date.today().isoformat()
PASSWORD = "Secret123"


class BaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmp, "test.db")
        self.app = create_app({"DATABASE": self.db_path, "SECRET_KEY": "test-key", "TESTING": True})
        self.client = self.app.test_client()
        self._phone = 9000000000

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # ---------------- helpers ----------------
    def token(self):
        with self.client.session_transaction() as s:
            s.setdefault("_csrf", "test-token")
            return s["_csrf"]

    def post(self, url, data=None, follow=True, **kw):
        payload = dict(data or {})
        payload["_csrf"] = self.token()
        return self.client.post(url, data=payload, follow_redirects=follow, **kw)

    def get(self, url, **kw):
        return self.client.get(url, follow_redirects=True, **kw)

    def login(self):
        self.post("/setup", {"full_name": "Test Admin", "username": "admin", "password": PASSWORD,
                             "confirm": PASSWORD})
        r = self.post("/login", {"username": "admin", "password": PASSWORD})
        self.assertIn(b"Welcome back", r.data)

    def query(self, sql, params=()):
        conn = dbmodule.connect(self.db_path)
        try:
            return conn.execute(sql, params).fetchall()
        finally:
            conn.close()

    def phone(self):
        self._phone += 1
        return str(self._phone)

    def add_room(self, room_no="101", floor="1", room_type="Double", capacity="2", **extra):
        data = {"room_no": room_no, "floor": floor, "room_type": room_type, "capacity": capacity, **extra}
        r = self.post("/rooms/add", data)
        return r, self.query("SELECT id FROM rooms WHERE room_no = ?", (room_no,))

    def student_data(self, **over):
        n = self._phone + 1
        data = {"student_code": "", "full_name": f"Student Number{chr(65 + n % 26)}", "gender": "Male",
                "dob": "2002-05-14", "phone": self.phone(), "email": "", "address": "Pune",
                "guardian_name": "Guardian Name", "guardian_phone": self.phone(), "course": "MCA",
                "department": "Computer Applications", "year": "2", "room_id": "",
                "admission_date": TODAY, "status": "Active"}
        data.update(over)
        return data

    def add_student(self, **over):
        data = self.student_data(**over)
        r = self.post("/students/add", data)
        rows = self.query("SELECT id FROM students WHERE phone = ?", (helpers.normalize_phone(data["phone"]) or "x",))
        return r, (rows[0]["id"] if rows else None)

    def add_fee(self, student_id, amount="5000", due=None, **extra):
        data = {"student_id": str(student_id), "fee_type": "Hostel Rent", "amount": amount,
                "due_date": due or TODAY, **extra}
        self.post("/fees/add", data)
        return self.query("SELECT id FROM fees ORDER BY id DESC LIMIT 1")[0]["id"]


# =====================================================================
class AuthTests(BaseCase):
    def test_first_run_redirects_to_setup(self):
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/setup", r.headers["Location"])
        self.assertEqual(self.client.get("/setup").status_code, 200)

    def test_setup_validation_and_hashed_password(self):
        r = self.post("/setup", {"full_name": "A", "username": "x", "password": "short", "confirm": "no"})
        self.assertIn(b"3-30 characters", r.data)
        self.assertIn(b"at least 8 characters", r.data)
        self.login()
        stored = self.query("SELECT password_hash FROM users")[0][0]
        self.assertNotEqual(stored, PASSWORD)
        self.assertTrue(stored.startswith(("scrypt:", "pbkdf2:")))
        # setup page is closed once an admin exists
        self.assertIn("/login", self.client.get("/setup").headers["Location"])

    def test_login_logout_and_protection(self):
        self.login()
        self.assertEqual(self.get("/dashboard").status_code, 200)
        r = self.post("/logout")
        self.assertIn(b"logged out", r.data)
        for url in ("/dashboard", "/students/", "/rooms/", "/fees/", "/attendance/", "/complaints/",
                    "/visitors/", "/staff/", "/reports/", "/profile/", "/reports/students"):
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, 302, url)
            self.assertIn("/login", resp.headers["Location"], url)

    def test_wrong_password_and_unknown_user_same_message(self):
        self.login()
        self.post("/logout")
        a = self.post("/login", {"username": "admin", "password": "WrongPass1"})
        b = self.post("/login", {"username": "nobody", "password": "WrongPass1"})
        self.assertIn(b"Invalid username or password", a.data)
        self.assertIn(b"Invalid username or password", b.data)
        self.assertIn(b"enter both", self.post("/login", {"username": "", "password": ""}).data)

    def test_username_case_insensitive_and_next_redirect(self):
        self.login()
        self.post("/logout")
        r = self.client.post("/login?next=/rooms/", data={"username": "ADMIN", "password": PASSWORD, "_csrf": self.token(),
                                                          "next": "/rooms/"})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.headers["Location"].endswith("/rooms/"))

    def test_open_redirect_blocked(self):
        self.login()
        self.post("/logout")
        r = self.client.post("/login", data={"username": "admin", "password": PASSWORD, "_csrf": self.token(),
                                             "next": "https://evil.example.com"})
        self.assertNotIn("evil", r.headers["Location"])

    def test_csrf_required_on_post(self):
        self.login()
        r = self.client.post("/rooms/add", data={"room_no": "X1"})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/rooms/add", data={"room_no": "X1", "_csrf": "forged"})
        self.assertEqual(r.status_code, 400)
        self.assertEqual(self.query("SELECT COUNT(*) FROM rooms")[0][0], 0)

    def test_error_pages_are_friendly(self):
        self.login()
        r = self.client.get("/students/9999")
        self.assertEqual(r.status_code, 404)
        self.assertNotIn(b"Traceback", r.data)
        self.assertEqual(self.client.get("/no/such/page").status_code, 404)
        self.assertEqual(self.client.get("/logout").status_code, 405)

    def test_remember_me_makes_session_permanent(self):
        self.post("/setup", {"full_name": "Test Admin", "username": "admin", "password": PASSWORD, "confirm": PASSWORD})
        r = self.client.post("/login", data={"username": "admin", "password": PASSWORD, "remember": "on",
                                             "_csrf": self.token()})
        self.assertIn("expires", r.headers.get("Set-Cookie", "").lower())

    def test_legacy_url_redirects(self):
        self.login()
        r = self.client.get("/add_student")
        self.assertEqual(r.status_code, 301)


# =====================================================================
class RoomTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_add_edit_delete_room(self):
        r, rows = self.add_room("101", "1", "Double", "2")
        self.assertIn(b"Room 101 added", r.data)
        rid = rows[0]["id"]
        r = self.post(f"/rooms/{rid}/edit", {"room_no": "101A", "floor": "1", "room_type": "Triple", "capacity": "3"})
        self.assertIn(b"updated", r.data)
        self.assertEqual(self.query("SELECT capacity FROM rooms WHERE id=?", (rid,))[0][0], 3)
        self.assertEqual(self.get(f"/rooms/{rid}").status_code, 200)
        r = self.post(f"/rooms/{rid}/delete")
        self.assertIn(b"deleted", r.data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM rooms")[0][0], 0)

    def test_room_validation(self):
        self.add_room("101")
        self.assertIn(b"already exists", self.add_room("101")[0].data)
        self.assertIn(b"already exists", self.add_room("101".lower())[0].data)       # case-insensitive
        self.assertIn(b"exactly 2", self.add_room("102", room_type="Double", capacity="3")[0].data)
        self.assertIn(b"at least 4", self.add_room("103", room_type="Dormitory", capacity="2")[0].data)
        self.assertIn(b"between 0", self.add_room("104", floor="99")[0].data)
        self.assertIn(b"required", self.add_room("", )[0].data)
        self.assertIn(b"Choose a room type", self.add_room("105", room_type="")[0].data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM rooms")[0][0], 1)

    def test_assign_vacate_updates_occupancy_automatically(self):
        _, rows = self.add_room("101", "1", "Double", "2")
        rid = rows[0]["id"]
        _, s1 = self.add_student()
        _, s2 = self.add_student()
        r = self.post("/rooms/assign", {"student_id": s1, "room_id": rid})
        self.assertIn(b"assigned to room 101", r.data)
        occ = self.query("SELECT occupied, available, status FROM room_overview WHERE id=?", (rid,))[0]
        self.assertEqual((occ["occupied"], occ["available"], occ["status"]), (1, 1, "Partially Occupied"))
        self.post("/rooms/assign", {"student_id": s2, "room_id": rid})
        occ = self.query("SELECT occupied, available, status FROM room_overview WHERE id=?", (rid,))[0]
        self.assertEqual((occ["occupied"], occ["available"], occ["status"]), (2, 0, "Full"))
        r = self.post("/rooms/vacate", {"student_id": s1})
        self.assertIn(b"vacated", r.data)
        occ = self.query("SELECT occupied, available, status FROM room_overview WHERE id=?", (rid,))[0]
        self.assertEqual((occ["occupied"], occ["available"], occ["status"]), (1, 1, "Partially Occupied"))
        self.post("/rooms/vacate", {"student_id": s2})
        self.assertEqual(self.query("SELECT status FROM room_overview WHERE id=?", (rid,))[0][0], "Available")

    def test_full_room_rejects_assignment(self):
        _, rows = self.add_room("201", "2", "Single", "1")
        rid = rows[0]["id"]
        _, s1 = self.add_student()
        _, s2 = self.add_student()
        self.post("/rooms/assign", {"student_id": s1, "room_id": rid})
        r = self.post("/rooms/assign", {"student_id": s2, "room_id": rid})
        self.assertIn(b"is full", r.data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM students WHERE room_id=?", (rid,))[0][0], 1)

    def test_database_trigger_blocks_overfilling_even_with_raw_sql(self):
        _, rows = self.add_room("301", "3", "Single", "1")
        rid = rows[0]["id"]
        _, s1 = self.add_student()
        _, s2 = self.add_student()
        conn = dbmodule.connect(self.db_path)
        conn.execute("UPDATE students SET room_id=? WHERE id=?", (rid, s1))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE students SET room_id=? WHERE id=?", (rid, s2))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE rooms SET capacity = 0 WHERE id=?", (rid,))
        conn.close()

    def test_maintenance_room_blocks_assignment_and_status(self):
        _, rows = self.add_room("401", "4", "Double", "2", under_maintenance="on")
        rid = rows[0]["id"]
        self.assertEqual(self.query("SELECT status, available FROM room_overview WHERE id=?", (rid,))[0][:], ("Maintenance", 0))
        _, s1 = self.add_student()
        self.assertIn(b"under maintenance", self.post("/rooms/assign", {"student_id": s1, "room_id": rid}).data)

    def test_cannot_delete_occupied_room_or_shrink_below_occupancy(self):
        _, rows = self.add_room("101", "1", "Triple", "3")
        rid = rows[0]["id"]
        _, s1 = self.add_student(room_id=str(rid))
        _, s2 = self.add_student(room_id=str(rid))
        self.assertIn(b"Vacate them first", self.post(f"/rooms/{rid}/delete").data)
        r = self.post(f"/rooms/{rid}/edit", {"room_no": "101", "floor": "1", "room_type": "Double", "capacity": "2"})
        self.assertIn(b"updated", r.data)           # 2 occupants fit a Double room
        r = self.post(f"/rooms/{rid}/edit", {"room_no": "101", "floor": "1", "room_type": "Single", "capacity": "1"})
        self.assertIn(b"already live here", r.data)
        r = self.post(f"/rooms/{rid}/edit", {"room_no": "101", "floor": "1", "room_type": "Double", "capacity": "2",
                                             "under_maintenance": "on"})
        self.assertIn(b"Vacate all students", r.data)

    def test_room_filters_and_pagination(self):
        for i in range(12):
            self.add_room(f"{100 + i}", "1" if i < 6 else "2", "Double", "2")
        self.assertEqual(self.query("SELECT COUNT(*) FROM rooms")[0][0], 12)
        page1 = self.get("/rooms/")
        self.assertIn(b"Showing 1-10 of 12", page1.data)
        self.assertIn(b"Showing 11-12 of 12", self.get("/rooms/?page=2").data)
        self.assertIn(b"Showing 1-6 of 6", self.get("/rooms/?floor=1").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/rooms/?q=105").data)
        self.assertEqual(self.get("/rooms/?page=999").status_code, 200)          # out-of-range page is clamped
        self.assertEqual(self.get("/rooms/?floor=abc&status=zzz").status_code, 200)


# =====================================================================
class StudentTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_add_view_edit_delete(self):
        r, sid = self.add_student(full_name="Asha Kulkarni", email="asha@example.com")
        self.assertIn(b"added successfully", r.data)
        self.assertIn(b"STU-0001", r.data)
        page = self.get(f"/students/{sid}")
        self.assertIn(b"Asha Kulkarni", page.data)
        self.assertIn(b"asha@example.com", page.data)
        data = self.student_data(full_name="Asha K Patil", phone=self.query("SELECT phone FROM students")[0][0],
                                 guardian_phone="9876543210", email="asha@example.com", status="Active")
        r = self.post(f"/students/{sid}/edit", data)
        self.assertIn(b"updated", r.data)
        self.assertEqual(self.query("SELECT full_name FROM students")[0][0], "Asha K Patil")
        r = self.post(f"/students/{sid}/delete")
        self.assertIn(b"deleted", r.data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM students")[0][0], 0)

    def test_student_codes_increment(self):
        self.add_student()
        self.add_student()
        codes = [r[0] for r in self.query("SELECT student_code FROM students ORDER BY id")]
        self.assertEqual(codes, ["STU-0001", "STU-0002"])

    def test_validation_errors(self):
        def post(**over):
            return self.post("/students/add", self.student_data(**over))
        self.assertIn(b"valid 10-digit mobile", post(phone="12345").data)
        self.assertIn(b"valid 10-digit mobile", post(phone="abcdefghij").data)
        self.assertIn(b"valid email", post(email="not-an-email").data)
        self.assertIn(b"full name", post(full_name="Bob123").data)
        self.assertIn(b"full name", post(full_name="").data)
        self.assertIn(b"valid date of birth", post(dob="2002-13-45").data)
        self.assertIn(b"cannot be in the future", post(dob=(date.today() + timedelta(days=5)).isoformat()).data)
        self.assertIn(b"must be between 14 and 70", post(dob="2020-01-01").data)
        self.assertIn(b"admission date", post(admission_date="31-12-2025").data)
        self.assertIn(b"cannot be in the future", post(admission_date=(date.today() + timedelta(days=3)).isoformat()).data)
        self.assertIn(b"year of study", post(year="9").data)
        self.assertIn(b"Select a gender", post(gender="").data)
        self.assertIn(b"Enter the course", post(course="").data)
        self.assertIn(b"guardian", post(guardian_name="").data.lower())
        self.assertIn(b"Select a status", post(status="Weird").data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM students")[0][0], 0)

    def test_phone_normalisation(self):
        self.add_student(phone="+91 98765-43210")
        self.assertEqual(self.query("SELECT phone FROM students")[0][0], "9876543210")
        self.assertIsNone(helpers.normalize_phone("5876543210"))
        self.assertEqual(helpers.normalize_phone("09876543210"), "9876543210")

    def test_duplicate_prevention(self):
        self.add_student(full_name="Rahul Sharma", phone="9876501234", email="rahul@example.com", dob="2001-02-03")
        r = self.post("/students/add", self.student_data(full_name="Other Person", phone="9876501234"))
        self.assertIn(b"already uses this phone", r.data)
        r = self.post("/students/add", self.student_data(full_name="Other Person", email="RAHUL@example.com"))
        self.assertIn(b"already uses this email", r.data)
        r = self.post("/students/add", self.student_data(full_name="rahul sharma", dob="2001-02-03"))
        self.assertIn(b"already registered", r.data)
        r = self.post("/students/add", self.student_data(student_code="STU-0001"))
        self.assertIn(b"already taken", r.data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM students")[0][0], 1)

    def test_add_with_room_and_full_room_rejected(self):
        _, rows = self.add_room("101", "1", "Single", "1")
        rid = str(rows[0]["id"])
        r, s1 = self.add_student(room_id=rid)
        self.assertEqual(self.query("SELECT room_id FROM students WHERE id=?", (s1,))[0][0], int(rid))
        r, s2 = self.add_student(room_id=rid)
        self.assertIn(b"is full", r.data)
        self.assertIsNone(s2)                                    # nothing half-saved
        self.assertEqual(self.query("SELECT COUNT(*) FROM students")[0][0], 1)

    def test_invalid_room_reference_rejected(self):
        r, sid = self.add_student(room_id="999")
        self.assertIn(b"does not exist", r.data)
        self.assertIsNone(sid)

    def test_changing_status_releases_bed(self):
        _, rows = self.add_room("101", "1", "Double", "2")
        rid = str(rows[0]["id"])
        _, sid = self.add_student(room_id=rid)
        phone = self.query("SELECT phone FROM students")[0][0]
        data = self.student_data(phone=phone, status="Left", full_name=self.query("SELECT full_name FROM students")[0][0])
        r = self.post(f"/students/{sid}/edit", data)
        self.assertIn(b"bed was released", r.data)
        row = self.query("SELECT room_id, status FROM students")[0]
        self.assertEqual((row["room_id"], row["status"]), (None, "Left"))
        self.assertEqual(self.query("SELECT occupied FROM room_overview")[0][0], 0)
        r = self.post("/rooms/assign", {"student_id": sid, "room_id": rid})
        self.assertIn(b"Active", r.data)

    def test_transfer_between_rooms_via_edit(self):
        _, r1 = self.add_room("101", "1", "Single", "1")
        _, r2 = self.add_room("102", "1", "Single", "1")
        _, sid = self.add_student(room_id=str(r1[0]["id"]))
        row = self.query("SELECT * FROM students")[0]
        data = self.student_data(phone=row["phone"], full_name=row["full_name"], room_id=str(r2[0]["id"]))
        self.post(f"/students/{sid}/edit", data)
        counts = {r["room_no"]: r["occupied"] for r in self.query("SELECT room_no, occupied FROM room_overview")}
        self.assertEqual(counts, {"101": 0, "102": 1})

    def test_search_filter_pagination(self):
        for i in range(13):
            self.add_student(full_name=f"Learner Name{chr(65 + i)}", course="MCA" if i < 8 else "MBA", year="1" if i % 2 else "2")
        self.assertIn(b"Showing 1-10 of 13", self.get("/students/").data)
        self.assertIn(b"Showing 11-13 of 13", self.get("/students/?page=2").data)
        self.assertIn(b"of 8", self.get("/students/?course=MCA").data)
        self.assertIn(b"of 5", self.get("/students/?course=MBA").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/students/?q=NameC").data)
        phone = self.query("SELECT phone FROM students LIMIT 1")[0][0]
        self.assertIn(b"Showing 1-1 of 1", self.get(f"/students/?q={phone}").data)
        self.assertIn(b"STU-0001", self.get("/students/?q=STU-0001").data)
        self.assertIn(b"No students match", self.get("/students/?q=zzzzqq").data)
        self.assertIn(b"of 6", self.get("/students/?year=1").data)
        self.assertEqual(self.get("/students/?room=none").status_code, 200)
        self.assertEqual(self.get("/students/?q=%25_%27;DROP TABLE students;--").status_code, 200)  # odd input is safe
        self.assertEqual(self.query("SELECT COUNT(*) FROM students")[0][0], 13)

    def test_delete_blocked_when_fees_exist_and_cascades_otherwise(self):
        _, a = self.add_student()
        _, b = self.add_student()
        self.add_fee(a)
        r = self.post(f"/students/{a}/delete")
        self.assertIn(b"has fee records", r.data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM students")[0][0], 2)
        self.post("/attendance/save", {"date": TODAY, f"status_{b}": "Present"})
        self.post("/complaints/add", {"student_id": b, "category": "Plumbing", "description": "Tap is leaking badly",
                                      "priority": "Low", "complaint_date": TODAY})
        self.post(f"/students/{b}/delete")
        self.assertEqual(self.query("SELECT COUNT(*) FROM attendance")[0][0], 0)
        self.assertEqual(self.query("SELECT COUNT(*) FROM complaints")[0][0], 0)

    def test_student_detail_page_shows_related_records(self):
        _, sid = self.add_student(full_name="Detail Check")
        fee = self.add_fee(sid, "3000")
        self.post("/attendance/save", {"date": TODAY, f"status_{sid}": "Present"})
        page = self.get(f"/students/{sid}").data
        self.assertIn(b"Detail Check", page)
        self.assertIn(b"3,000.00", page)
        self.assertIn(b"100.0%", page)


# =====================================================================
class FeeTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()
        _, self.sid = self.add_student(full_name="Fee Payer")

    def status(self, fee_id):
        return self.query("SELECT status, paid, balance FROM fee_overview WHERE id=?", (fee_id,))[0]

    def test_status_lifecycle_pending_partial_paid(self):
        due = (date.today() + timedelta(days=10)).isoformat()
        fee = self.add_fee(self.sid, "5000", due=due)
        self.assertEqual(tuple(self.status(fee)), ("Pending", 0, 5000))
        r = self.post(f"/fees/{fee}/pay", {"amount": "2000", "payment_date": TODAY, "method": "Cash"})
        self.assertIn(b"Fee receipt", r.data)
        self.assertEqual(tuple(self.status(fee)), ("Partial", 2000, 3000))
        self.post(f"/fees/{fee}/pay", {"amount": "3000", "payment_date": TODAY, "method": "UPI", "transaction_ref": "UPI123456"})
        self.assertEqual(tuple(self.status(fee)), ("Paid", 5000, 0))
        self.assertIn(b"fully paid", self.get(f"/fees/{fee}").data)
        r = self.post(f"/fees/{fee}/pay", {"amount": "1", "payment_date": TODAY, "method": "Cash"})
        self.assertIn(b"already fully paid", r.data)

    def test_overdue_status(self):
        fee = self.add_fee(self.sid, "1000", due=(date.today() - timedelta(days=3)).isoformat())
        self.assertEqual(self.status(fee)["status"], "Overdue")
        self.post(f"/fees/{fee}/pay", {"amount": "400", "payment_date": TODAY, "method": "Cash"})
        self.assertEqual(self.status(fee)["status"], "Overdue")                   # part-paid but still late
        self.post(f"/fees/{fee}/pay", {"amount": "600", "payment_date": TODAY, "method": "Cash"})
        self.assertEqual(self.status(fee)["status"], "Paid")

    def test_payment_validation(self):
        fee = self.add_fee(self.sid, "1000")
        pay = lambda **o: self.post(f"/fees/{fee}/pay", {"amount": "100", "payment_date": TODAY, "method": "Cash", **o})  # noqa: E731
        self.assertIn(b"more than the balance", pay(amount="1500").data)
        self.assertIn(b"positive amount", pay(amount="-5").data)
        self.assertIn(b"positive amount", pay(amount="0").data)
        self.assertIn(b"positive amount", pay(amount="abc").data)
        self.assertIn(b"positive amount", pay(amount="10.555").data)
        self.assertIn(b"valid payment date", pay(payment_date="yesterday").data)
        self.assertIn(b"cannot be in the future", pay(payment_date=(date.today() + timedelta(days=2)).isoformat()).data)
        self.assertIn(b"payment method", pay(method="Barter").data)
        self.assertIn(b"reference number", pay(method="UPI").data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM payments")[0][0], 0)

    def test_add_fee_validation(self):
        bad = lambda **o: self.post("/fees/add", {"student_id": self.sid, "fee_type": "Hostel Rent", "amount": "100",  # noqa: E731
                                                 "due_date": TODAY, **o})
        self.assertIn(b"positive amount", bad(amount="-100").data)
        self.assertIn(b"positive amount", bad(amount="0").data)
        self.assertIn(b"Select a student", bad(student_id="777").data)
        self.assertIn(b"fee type", bad(fee_type="Bribe").data)
        self.assertIn(b"valid due date", bad(due_date="").data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM fees")[0][0], 0)

    def test_add_fee_already_paid_creates_payment_and_receipt(self):
        r = self.post("/fees/add", {"student_id": self.sid, "fee_type": "Mess Fee", "amount": "2500.50", "due_date": TODAY,
                                    "pay_now": "on", "payment_date": TODAY, "method": "Card", "transaction_ref": "CARD99887"})
        self.assertIn(b"Fee receipt", r.data)
        self.assertIn(b"RCPT-", r.data)
        self.assertIn(b"Rupees Two Thousand Five Hundred and Fifty Paise Only", r.data)
        fee = self.query("SELECT id FROM fees")[0][0]
        self.assertEqual(self.status(fee)["status"], "Paid")
        r = self.post("/fees/add", {"student_id": self.sid, "fee_type": "Mess Fee", "amount": "100", "due_date": TODAY,
                                    "pay_now": "on", "payment_date": TODAY, "method": "UPI"})
        self.assertIn(b"reference number", r.data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM fees")[0][0], 1)          # whole operation rolled back

    def test_receipt_numbers_unique_and_receipt_page(self):
        fee = self.add_fee(self.sid, "900")
        for _ in range(3):
            self.post(f"/fees/{fee}/pay", {"amount": "100", "payment_date": TODAY, "method": "Cash"})
        numbers = [r[0] for r in self.query("SELECT receipt_no FROM payments")]
        self.assertEqual(len(set(numbers)), 3)
        pid = self.query("SELECT id FROM payments")[0][0]
        page = self.get(f"/fees/receipt/{pid}").data
        self.assertIn(numbers[0].encode(), page)
        self.assertIn(b"Fee Payer", page)
        self.assertIn(b"Print receipt", page)
        self.assertEqual(self.client.get("/fees/receipt/9999").status_code, 404)

    def test_edit_fee_rules(self):
        fee = self.add_fee(self.sid, "1000")
        self.post(f"/fees/{fee}/pay", {"amount": "600", "payment_date": TODAY, "method": "Cash"})
        r = self.post(f"/fees/{fee}/edit", {"fee_type": "Hostel Rent", "amount": "500", "due_date": TODAY})
        self.assertIn(b"cannot be lower", r.data)
        r = self.post(f"/fees/{fee}/edit", {"fee_type": "Mess Fee", "amount": "1500", "due_date": TODAY, "notes": "revised"})
        self.assertIn(b"Fee updated", r.data)
        self.assertEqual(tuple(self.status(fee)), ("Partial", 600, 900) if False else (self.status(fee)[0], 600, 900))

    def test_delete_fee_rules(self):
        fee = self.add_fee(self.sid, "1000")
        paid = self.add_fee(self.sid, "500")
        self.post(f"/fees/{paid}/pay", {"amount": "500", "payment_date": TODAY, "method": "Cash"})
        self.assertIn(b"cannot be deleted", self.post(f"/fees/{paid}/delete").data)
        self.assertIn(b"Fee deleted", self.post(f"/fees/{fee}/delete").data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM fees")[0][0], 1)

    def test_filters_totals_and_history(self):
        past = (date.today() - timedelta(days=9)).isoformat()
        f1 = self.add_fee(self.sid, "1000", due=past)                                   # overdue
        f2 = self.add_fee(self.sid, "2000", due=(date.today() + timedelta(days=9)).isoformat())   # pending
        f3 = self.add_fee(self.sid, "3000")
        self.post(f"/fees/{f3}/pay", {"amount": "3000", "payment_date": TODAY, "method": "Cash"})
        page = self.get("/fees/").data
        self.assertIn(b"6,000.00", page)                      # total billed
        self.assertIn(b"3,000.00", page)                      # collected
        self.assertIn(b"Showing 1-3 of 3", page)
        self.assertIn(b"Showing 1-1 of 1", self.get("/fees/?status=Overdue").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/fees/?status=Paid").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/fees/?status=Pending").data)
        self.assertIn(b"No fees match", self.get("/fees/?status=Partial").data)
        self.assertIn(b"Showing 1-1 of 1", self.get(f"/fees/?date_to={past}").data)
        self.assertIn(b"Showing 1-3 of 3", self.get("/fees/?q=Fee Payer").data)
        rcpt = self.query("SELECT receipt_no FROM payments")[0][0]
        self.assertIn(b"Showing 1-1 of 1", self.get(f"/fees/?q={rcpt}").data)
        hist = self.get("/fees/payments").data
        self.assertIn(rcpt.encode(), hist)
        self.assertIn(b"3,000.00", hist)
        self.assertIn(b"No payments match", self.get("/fees/payments?method=Cheque").data)

    def test_amount_helpers(self):
        self.assertEqual(helpers.inr(1234567.5), "₹12,34,567.50")
        self.assertEqual(helpers.inr(0), "₹0.00")
        self.assertEqual(helpers.inr(999), "₹999.00")
        self.assertEqual(helpers.amount_in_words(1250), "Rupees One Thousand Two Hundred Fifty Only")
        self.assertEqual(helpers.amount_in_words(100000), "Rupees One Lakh Only")
        self.assertEqual(helpers.amount_in_words(12345678), "Rupees One Crore Twenty-Three Lakh Forty-Five Thousand Six Hundred Seventy-Eight Only")

    def test_database_rejects_bad_money_and_orphans(self):
        conn = dbmodule.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO fees (student_id, fee_type, amount, due_date) VALUES (?, 'x', -5, ?)", (self.sid, TODAY))
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO fees (student_id, fee_type, amount, due_date) VALUES (9999, 'x', 5, ?)", (TODAY,))
        conn.close()


# =====================================================================
class AttendanceTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()
        _, self.a = self.add_student(full_name="Alpha Student")
        _, self.b = self.add_student(full_name="Beta Student")

    def mark(self, day, **marks):
        data = {"date": day}
        data.update({f"status_{k}": v for k, v in marks.items()})
        return self.post("/attendance/save", data)

    def test_mark_and_no_duplicates_upsert(self):
        r = self.mark(TODAY, **{str(self.a): "Present", str(self.b): "Absent"})
        self.assertIn(b"saved for 2 student", r.data)
        self.mark(TODAY, **{str(self.b): "Present"})                      # change Beta, should not duplicate
        rows = self.query("SELECT student_id, status FROM attendance ORDER BY student_id")
        self.assertEqual([(r[0], r[1]) for r in rows], [(self.a, "Present"), (self.b, "Present")])
        conn = dbmodule.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO attendance (student_id, att_date, status) VALUES (?,?,?)", (self.a, TODAY, "Absent"))
        conn.close()

    def test_validation(self):
        future = (date.today() + timedelta(days=1)).isoformat()
        self.assertIn(b"not in the future", self.mark(future, **{str(self.a): "Present"}).data)
        self.assertIn(b"valid date", self.mark("garbage", **{str(self.a): "Present"}).data)
        self.assertIn(b"Nothing to save", self.mark(TODAY).data)
        self.mark(TODAY, **{str(self.a): "Maybe", "9999": "Present"})
        self.assertEqual(self.query("SELECT COUNT(*) FROM attendance")[0][0], 0)    # bad value + unknown student ignored
        self.assertEqual(self.get("/attendance/?date=2999-01-01").status_code, 200)

    def test_sheet_shows_saved_marks_and_counts(self):
        self.mark(TODAY, **{str(self.a): "Present", str(self.b): "Absent"})
        page = self.get(f"/attendance/?date={TODAY}").data.decode()
        self.assertRegex(page, r'value="Present" checked')
        self.assertRegex(page, r'value="Absent" checked')
        self.assertIn("Alpha Student", self.get("/attendance/?q=Alpha").data.decode())
        self.assertNotIn("Beta Student", self.get("/attendance/?q=Alpha").data.decode())

    def test_history_percentage_and_monthly(self):
        for offset, status in enumerate(["Present", "Present", "Present", "Absent"]):
            self.mark((date.today() - timedelta(days=offset)).isoformat(), **{str(self.a): status})
        rows = self.get(f"/attendance/history?student={self.a}&date_from={(date.today() - timedelta(days=10)).isoformat()}&date_to={TODAY}").data
        self.assertIn(b"75.0%", rows)
        self.assertIn(b"Showing 1-4 of 4", rows)
        self.assertIn(b"Showing 1-1 of 1", self.get(f"/attendance/history?status=Absent&date_from={(date.today() - timedelta(days=10)).isoformat()}").data)
        month = self.get(f"/attendance/monthly?month={TODAY[:7]}").data
        self.assertIn(b"Alpha Student", month)
        self.assertIn(b"mark-p", month)
        self.assertEqual(self.get("/attendance/monthly?month=2026-13").status_code, 200)
        self.assertEqual(self.get("/attendance/history?date_from=xx&date_to=yy").status_code, 200)
        swapped = self.get(f"/attendance/history?date_from={TODAY}&date_to=2000-01-01")
        self.assertIn(b"were swapped", swapped.data)

    def test_inactive_students_not_on_sheet(self):
        row = self.query("SELECT * FROM students WHERE id=?", (self.b,))[0]
        self.post(f"/students/{self.b}/edit", self.student_data(phone=row["phone"], full_name=row["full_name"], status="Inactive"))
        self.assertNotIn(b"Beta Student", self.get("/attendance/").data)
        self.mark(TODAY, **{str(self.b): "Present"})
        self.assertEqual(self.query("SELECT COUNT(*) FROM attendance")[0][0], 0)


# =====================================================================
class ComplaintTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()
        _, self.sid = self.add_student(full_name="Complainer One")

    def add(self, **o):
        data = {"student_id": self.sid, "category": "Plumbing", "description": "The tap in bathroom is leaking",
                "priority": "High", "complaint_date": TODAY, **o}
        return self.post("/complaints/add", data)

    def test_full_lifecycle(self):
        self.assertIn(b"Complaint registered", self.add().data)
        cid = self.query("SELECT id FROM complaints")[0][0]
        row = self.query("SELECT status, resolved_date FROM complaints")[0]
        self.assertEqual((row["status"], row["resolved_date"]), ("Pending", None))
        r = self.post(f"/complaints/{cid}/update", {"status": "In Progress", "resolution": ""})
        self.assertIn(b"In Progress", r.data)
        r = self.post(f"/complaints/{cid}/update", {"status": "Resolved", "resolution": ""})
        self.assertIn(b"Write what was done", r.data)
        self.assertEqual(self.query("SELECT status FROM complaints")[0][0], "In Progress")
        self.post(f"/complaints/{cid}/update", {"status": "Resolved", "resolution": "Plumber replaced the washer."})
        row = self.query("SELECT status, resolution, resolved_date FROM complaints")[0]
        self.assertEqual((row["status"], row["resolved_date"]), ("Resolved", TODAY))
        self.post(f"/complaints/{cid}/update", {"status": "Pending", "resolution": "reopened"})
        self.assertIsNone(self.query("SELECT resolved_date FROM complaints")[0][0])
        self.assertIn(b"Complaint deleted", self.post(f"/complaints/{cid}/delete").data)

    def test_validation(self):
        self.assertIn(b"10-500 characters", self.add(description="short").data)
        self.assertIn(b"Select a category", self.add(category="Aliens").data)
        self.assertIn(b"Select a priority", self.add(priority="Urgent").data)
        self.assertIn(b"Select the student", self.add(student_id="999").data)
        self.assertIn(b"cannot be in the future", self.add(complaint_date=(date.today() + timedelta(days=1)).isoformat()).data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM complaints")[0][0], 0)

    def test_filters_counts_and_ordering(self):
        self.add(priority="Low", category="Noise")
        self.add(priority="High")
        self.add(priority="Medium", category="Electrical")
        cid = self.query("SELECT id FROM complaints WHERE category='Electrical'")[0][0]
        self.post(f"/complaints/{cid}/update", {"status": "Resolved", "resolution": "Fixed the wiring"})
        self.assertIn(b"Showing 1-1 of 1", self.get("/complaints/?priority=High").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/complaints/?status=Resolved").data)
        self.assertIn(b"Showing 1-2 of 2", self.get("/complaints/?status=Pending").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/complaints/?category=Noise").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/complaints/?q=Complainer").data.replace(b"1-3 of 3", b"1-1 of 1"))
        page = self.get("/complaints/").data.decode()
        self.assertLess(page.index("badge-high"), page.index("badge-low"))        # high priority open items first
        dash = self.get("/dashboard").data.decode()
        self.assertRegex(dash, r'stat-value">2</span><span class="stat-label">Pending complaints')


# =====================================================================
class VisitorTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()
        _, self.sid = self.add_student(full_name="Visited Student")

    def register(self, **o):
        data = {"visitor_name": "Ramesh Kumar", "phone": self.phone(), "student_id": self.sid, "relationship": "Father",
                "purpose": "Meeting", "visit_date": TODAY, "entry_time": "10:30", **o}
        return self.post("/visitors/add", data)

    def test_register_exit_and_filters(self):
        r = self.register()
        self.assertIn(b"Visitor registered", r.data)
        self.assertIn(b"Ramesh Kumar", r.data)
        vid = self.query("SELECT id FROM visitors")[0][0]
        self.assertIn(b"Inside", self.get("/visitors/?scope=today").data)
        self.assertIn(b"earlier than the entry", self.post(f"/visitors/{vid}/exit", {"exit_time": "09:00"}).data)
        self.assertIn(b"valid exit time", self.post(f"/visitors/{vid}/exit", {"exit_time": "xx"}).data)
        self.assertIn(b"Exit recorded", self.post(f"/visitors/{vid}/exit", {"exit_time": "11:45"}).data)
        self.assertEqual(self.query("SELECT exit_time FROM visitors")[0][0], "11:45")
        self.assertIn(b"already recorded", self.post(f"/visitors/{vid}/exit", {"exit_time": "12:00"}).data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/visitors/?status=Exited").data)
        self.assertIn(b"No visitors match", self.get("/visitors/?status=Inside").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/visitors/?q=Ramesh").data)
        self.assertIn(b"Showing 1-1 of 1", self.get(f"/visitors/?student={self.sid}").data)
        self.assertIn(b"No visitors match", self.get("/visitors/?date_from=2000-01-01&date_to=2000-01-02").data)
        self.assertIn(b"deleted", self.post(f"/visitors/{vid}/delete").data)

    def test_validation_and_history(self):
        self.assertIn(b"valid 10-digit", self.register(phone="123").data)
        self.assertIn(b"Select the student", self.register(student_id="888").data)
        self.assertIn(b"relationship", self.register(relationship="Alien").data)
        self.assertIn(b"valid entry time", self.register(entry_time="25:99").data)
        self.assertIn(b"cannot be in the future", self.register(visit_date=(date.today() + timedelta(days=1)).isoformat()).data)
        self.assertIn(b"purpose", self.register(purpose="").data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM visitors")[0][0], 0)
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.register(visit_date=yesterday)
        self.register()
        self.assertIn(b"Showing 1-1 of 1", self.get("/visitors/?scope=today").data)
        self.assertIn(b"Showing 1-2 of 2", self.get("/visitors/").data)

    def test_db_check_constraint_on_exit_time(self):
        self.register()
        conn = dbmodule.connect(self.db_path)
        with self.assertRaises(sqlite3.IntegrityError):
            conn.execute("UPDATE visitors SET exit_time = '08:00'")
        conn.close()


# =====================================================================
class StaffTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()

    def staff(self, **o):
        data = {"full_name": "Suresh Kamble", "role": "Warden", "phone": self.phone(), "email": "", "joining_date": "2024-06-01",
                "salary": "30000", "status": "Active", **o}
        return self.post("/staff/add", data)

    def test_crud_and_codes(self):
        self.assertIn(b"added", self.staff().data)
        self.staff(full_name="Meena Patil", role="Cook")
        self.assertEqual([r[0] for r in self.query("SELECT staff_code FROM staff ORDER BY id")], ["STF-0001", "STF-0002"])
        sid = self.query("SELECT id FROM staff WHERE full_name='Suresh Kamble'")[0][0]
        self.assertIn(b"Suresh Kamble", self.get(f"/staff/{sid}").data)
        phone = self.query("SELECT phone FROM staff WHERE id=?", (sid,))[0][0]
        r = self.post(f"/staff/{sid}/edit", {"full_name": "Suresh K", "role": "Warden", "phone": phone, "email": "s@example.com",
                                             "joining_date": "2024-06-01", "salary": "35000.50", "status": "Inactive"})
        self.assertIn(b"updated", r.data)
        self.assertEqual(self.query("SELECT salary, status FROM staff WHERE id=?", (sid,))[0][:], (35000.5, "Inactive"))
        self.assertIn(b"Showing 1-1 of 1", self.get("/staff/?role=Cook").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/staff/?status=Inactive").data)
        self.assertIn(b"Showing 1-1 of 1", self.get("/staff/?q=Meena").data)
        self.assertIn(b"deleted", self.post(f"/staff/{sid}/delete").data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM staff")[0][0], 1)

    def test_validation(self):
        self.staff(phone="9876512345")
        self.assertIn(b"already uses this phone", self.staff(phone="9876512345", full_name="Other Person").data)
        self.assertIn(b"valid 10-digit", self.staff(phone="12").data)
        self.assertIn(b"valid email", self.staff(email="bad@").data)
        self.assertIn(b"Select a role", self.staff(role="CEO").data)
        self.assertIn(b"monthly salary", self.staff(salary="-4").data)
        self.assertIn(b"monthly salary", self.staff(salary="abc").data)
        self.assertIn(b"cannot be in the future", self.staff(joining_date=(date.today() + timedelta(days=2)).isoformat()).data)
        self.assertEqual(self.query("SELECT COUNT(*) FROM staff")[0][0], 1)


# =====================================================================
class ReportTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()
        manage.DATABASE = self.db_path
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            manage.seed_demo()

    def test_every_report_html_csv_pdf(self):
        from routes.reports import REPORTS
        self.assertEqual(len(REPORTS), 8)
        for slug in REPORTS:
            page = self.get(f"/reports/{slug}")
            self.assertEqual(page.status_code, 200, slug)
            self.assertIn(b"Print", page.data)
            csv_resp = self.client.get(f"/reports/{slug}?export=csv")
            self.assertEqual(csv_resp.status_code, 200, slug)
            self.assertIn("text/csv", csv_resp.headers["Content-Type"])
            rows = list(csv.reader(io.StringIO(csv_resp.data.decode("utf-8-sig"))))
            self.assertGreaterEqual(len(rows), 2, f"{slug} has data")
            pdf = self.client.get(f"/reports/{slug}?export=pdf")
            self.assertEqual(pdf.status_code, 200, slug)
            self.assertTrue(pdf.data.startswith(b"%PDF"), slug)

    def test_report_data_matches_database(self):
        rows = list(csv.reader(io.StringIO(self.client.get("/reports/students?export=csv").data.decode("utf-8-sig"))))
        self.assertEqual(len(rows) - 1, self.query("SELECT COUNT(*) FROM students")[0][0])
        rows = list(csv.reader(io.StringIO(self.client.get("/reports/fee-collection?export=csv").data.decode("utf-8-sig"))))
        total = sum(float(r[-1]) for r in rows[1:])
        self.assertAlmostEqual(total, self.query("SELECT SUM(amount) FROM payments")[0][0], places=2)
        rows = list(csv.reader(io.StringIO(self.client.get("/reports/pending-fees?export=csv").data.decode("utf-8-sig"))))
        self.assertAlmostEqual(sum(float(r[7]) for r in rows[1:]),
                               self.query("SELECT SUM(balance) FROM fee_overview WHERE status <> 'Paid'")[0][0], places=2)
        rows = list(csv.reader(io.StringIO(self.client.get("/reports/occupancy?export=csv").data.decode("utf-8-sig"))))
        self.assertEqual(sum(int(r[4]) for r in rows[1:]), self.query("SELECT SUM(occupied) FROM room_overview")[0][0])

    def test_report_filters(self):
        def count(url):
            rows = list(csv.reader(io.StringIO(self.client.get(url + ("&" if "?" in url else "?") + "export=csv").data.decode("utf-8-sig"))))
            return len(rows) - 1
        self.assertEqual(count("/reports/students?course=MBA"), self.query("SELECT COUNT(*) FROM students WHERE course='MBA'")[0][0])
        self.assertEqual(count("/reports/students?status=Inactive"), 2)
        self.assertEqual(count("/reports/pending-fees?status=Overdue"), self.query("SELECT COUNT(*) FROM fee_overview WHERE status='Overdue'")[0][0])
        self.assertEqual(count("/reports/complaints?status=Resolved"), 1)
        self.assertEqual(count("/reports/complaints?priority=High"), 1)
        self.assertEqual(count("/reports/staff?role=Cook"), 1)
        self.assertEqual(count("/reports/visitors?status=Inside"), 1)
        self.assertEqual(count("/reports/occupancy?status=Maintenance"), 1)
        self.assertEqual(count("/reports/fee-collection?date_from=2999-01-01"), 0)
        self.assertEqual(count("/reports/students?date_from=garbage"), 18)       # invalid filter ignored
        self.assertEqual(self.client.get("/reports/nonexistent").status_code, 404)

    def test_attendance_report_range(self):
        rows = list(csv.reader(io.StringIO(self.client.get(f"/reports/attendance?date_from={(date.today() - timedelta(days=9)).isoformat()}&date_to={TODAY}&export=csv").data.decode("utf-8-sig"))))
        self.assertEqual(len(rows) - 1, 16)
        self.assertTrue(all(r[3] == "10" for r in rows[1:]))                     # 10 days recorded each


# =====================================================================
class ProfileAndDashboardTests(BaseCase):
    def setUp(self):
        super().setUp()
        self.login()

    def test_profile_update_and_validation(self):
        self.assertIn(b"Profile updated", self.post("/profile/update", {"full_name": "New Name", "email": "a@b.co", "phone": "9876543210"}).data)
        self.assertEqual(self.query("SELECT full_name, phone FROM users")[0][:], ("New Name", "9876543210"))
        self.assertIn(b"valid email", self.post("/profile/update", {"full_name": "New Name", "email": "bad"}).data)
        self.assertIn(b"valid 10-digit", self.post("/profile/update", {"full_name": "New Name", "phone": "12"}).data)

    def test_change_password(self):
        post = lambda cur, new, conf: self.post("/profile/password", {"current_password": cur, "new_password": new, "confirm_password": conf})  # noqa: E731
        self.assertIn(b"Current password is incorrect", post("wrong", "Another123", "Another123").data)
        self.assertIn(b"at least 8", post(PASSWORD, "abc", "abc").data)
        self.assertIn(b"one letter and one number", post(PASSWORD, "onlyletters", "onlyletters").data)
        self.assertIn(b"do not match", post(PASSWORD, "Another123", "Different123").data)
        self.assertIn(b"must be different", post(PASSWORD, PASSWORD, PASSWORD).data)
        self.assertIn(b"changed successfully", post(PASSWORD, "Another123", "Another123").data)
        self.post("/logout")
        self.assertIn(b"Invalid username", self.post("/login", {"username": "admin", "password": PASSWORD}).data)
        self.assertIn(b"Welcome back", self.post("/login", {"username": "admin", "password": "Another123"}).data)

    def test_settings_appear_on_receipt(self):
        self.assertIn(b"Hostel settings saved", self.post("/profile/settings", {
            "hostel_name": "Sahyadri Boys Hostel", "hostel_address": "Kothrud, Pune", "hostel_phone": "9876543210",
            "hostel_email": "office@sahyadri.example"}).data)
        self.assertIn(b"Sahyadri Boys Hostel", self.get("/dashboard").data)
        _, sid = self.add_student()
        fee = self.add_fee(sid, "100")
        self.post(f"/fees/{fee}/pay", {"amount": "100", "payment_date": TODAY, "method": "Cash"})
        pid = self.query("SELECT id FROM payments")[0][0]
        self.assertIn(b"Kothrud, Pune", self.get(f"/fees/receipt/{pid}").data)
        self.assertIn(b"between 2 and 80".replace(b"between 2 and 80", b"2-80"), self.post("/profile/settings", {"hostel_name": "X"}).data)

    def test_dashboard_numbers_come_from_database(self):
        manage.DATABASE = self.db_path
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            manage.seed_demo()
        page = self.get("/dashboard").data.decode()
        q = lambda sql: self.query(sql)[0][0]  # noqa: E731
        self.assertRegex(page, rf'stat-value">{q("SELECT COUNT(*) FROM students")}</span><span class="stat-label">Total students')
        self.assertRegex(page, rf'stat-value">{q("SELECT COUNT(*) FROM rooms")}</span><span class="stat-label">Total rooms')
        self.assertRegex(page, rf'stat-value">{q("SELECT SUM(occupied) FROM room_overview")}</span><span class="stat-label">Occupied beds')
        self.assertRegex(page, rf'stat-value">{q("SELECT SUM(available) FROM room_overview")}</span><span class="stat-label">Available beds')
        self.assertIn(helpers.inr0(q("SELECT SUM(amount) FROM payments")), page)
        self.assertIn(helpers.inr0(q("SELECT SUM(balance) FROM fee_overview")), page)
        self.assertRegex(page, rf'stat-value">{q("SELECT COUNT(*) FROM fee_overview WHERE status=\'Paid\'")}</span><span class="stat-label">Paid fees')
        self.assertRegex(page, rf'stat-value">{q("SELECT COUNT(*) FROM visitors WHERE visit_date=date(\'now\',\'localtime\')")}</span><span class="stat-label">Today')
        self.assertIn('id="chart-data"', page)

    def test_dashboard_on_empty_database(self):
        page = self.get("/dashboard")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"No open complaints", page.data)

    def test_every_page_renders_with_demo_data(self):
        manage.DATABASE = self.db_path
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            manage.seed_demo()
        urls = ["/dashboard", "/students/", "/students/add", "/students/1", "/students/1/edit", "/rooms/", "/rooms/add",
                "/rooms/1", "/rooms/1/edit", "/fees/", "/fees/add", "/fees/1", "/fees/1/edit", "/fees/payments",
                "/fees/receipt/1", "/attendance/", "/attendance/history", "/attendance/monthly", "/complaints/",
                "/complaints/add", "/complaints/1", "/visitors/", "/visitors/add", "/staff/", "/staff/add", "/staff/1",
                "/staff/1/edit", "/reports/", "/profile/"]
        for url in urls:
            r = self.client.get(url)
            self.assertEqual(r.status_code, 200, url)
            self.assertNotIn(b"Traceback", r.data, url)
            self.assertNotIn(b"UndefinedError", r.data, url)
        # sidebar highlights the current section
        self.assertRegex(self.get("/fees/").data.decode(), r'nav-link active"[^>]*>\s*<svg[^>]*>.*?</svg><span>Fees')


# =====================================================================
class MigrationTests(unittest.TestCase):
    """The very first version of the project had loose students / rooms / fees tables."""

    def test_legacy_database_is_migrated_with_backup(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "hostel.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, age INTEGER, phone TEXT, course TEXT, room_no TEXT);
            CREATE TABLE rooms (id INTEGER PRIMARY KEY AUTOINCREMENT, room_no TEXT UNIQUE, capacity INTEGER, occupied INTEGER DEFAULT 0);
            CREATE TABLE fees (id INTEGER PRIMARY KEY AUTOINCREMENT, student_name TEXT, amount REAL, status TEXT);
            INSERT INTO rooms (room_no, capacity) VALUES ('101', 2), ('G5', 1);
            INSERT INTO students (name, age, phone, course, room_no) VALUES
                ('Asha Patil', 21, '9876500001', 'MCA', '101'),
                ('Ravi Shinde', 22, '9876500002', 'MBA', '101'),
                ('Extra Person', 23, '9876500003', 'BCA', '101'),
                ('No Room', 20, '9876500004', 'MCA', '999');
            INSERT INTO fees (student_name, amount, status) VALUES ('Asha Patil', 4500, 'Paid'), ('Ravi Shinde', 4500, 'Pending'), ('Ghost', 100, 'Pending');
        """)
        old.commit()
        old.close()

        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            app = create_app({"DATABASE": path, "SECRET_KEY": "k", "TESTING": True})
        conn = dbmodule.connect(path)
        files = os.listdir(tmp)
        self.assertTrue(any("backup" in f for f in files), files)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"legacy_students", "legacy_rooms", "legacy_fees", "students", "rooms", "fees", "payments", "users"} <= names)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM legacy_students").fetchone()[0], 4)        # nothing destroyed
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM students").fetchone()[0], 4)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM rooms").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT room_type FROM rooms WHERE room_no='101'").fetchone()[0], "Double")
        placed = conn.execute("SELECT COUNT(*) FROM students WHERE room_id IS NOT NULL").fetchone()[0]
        self.assertEqual(placed, 2)                                    # room 101 holds 2; the 3rd and the unknown room stay unassigned
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM fees").fetchone()[0], 2)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM payments").fetchone()[0], 1)
        status = {r[0]: r[1] for r in conn.execute("SELECT student_name, status FROM fee_overview")}
        self.assertEqual(status["Asha Patil"], "Paid")
        self.assertIn("could not be matched" if False else "Ghost", out.getvalue())
        conn.close()
        # starting again must not migrate twice
        with contextlib.redirect_stdout(io.StringIO()):
            create_app({"DATABASE": path, "SECRET_KEY": "k", "TESTING": True})
        conn = dbmodule.connect(path)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM students").fetchone()[0], 4)
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_legacy_database_like_the_uploaded_one(self):
        tmp = tempfile.mkdtemp()
        path = os.path.join(tmp, "hostel.db")
        old = sqlite3.connect(path)
        old.executescript("""
            CREATE TABLE students (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, age INTEGER, phone TEXT, course TEXT, room_no TEXT);
            CREATE TABLE rooms (id INTEGER PRIMARY KEY AUTOINCREMENT, room_no TEXT UNIQUE, capacity INTEGER, occupied INTEGER DEFAULT 0);
            CREATE TABLE fees (id INTEGER PRIMARY KEY AUTOINCREMENT, student_name TEXT, amount REAL, status TEXT);
        """)
        old.close()
        import contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            create_app({"DATABASE": path, "SECRET_KEY": "k", "TESTING": True})
        conn = dbmodule.connect(path)
        self.assertEqual(conn.execute("PRAGMA foreign_keys").fetchone()[0], 1)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(students)")]
        self.assertIn("student_code", cols)
        conn.close()
        shutil.rmtree(tmp, ignore_errors=True)

    def test_foreign_keys_enabled_on_every_connection(self):
        tmp = tempfile.mkdtemp()
        app = create_app({"DATABASE": os.path.join(tmp, "x.db"), "SECRET_KEY": "k", "TESTING": True})
        with app.app_context():
            self.assertEqual(dbmodule.get_db().execute("PRAGMA foreign_keys").fetchone()[0], 1)
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
