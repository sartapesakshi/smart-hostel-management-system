"""
helpers.py - small reusable pieces used by every module.

  1. constants       (dropdown values)
  2. validators      (phone, email, dates, money)
  3. pagination
  4. security        (CSRF token, login check)
  5. Jinja filters and template helpers (rupee format, dates, icons)
"""
import math
import re
import secrets
from datetime import date, datetime

from flask import abort, g, request, session, url_for
from markupsafe import Markup

import db

# =============================================================== 1. CONSTANTS
GENDERS = ["Male", "Female", "Other"]
STUDENT_STATUSES = ["Active", "Inactive", "Left"]
COURSES = ["MCA", "MBA", "BCA", "BBA", "B.Tech", "M.Tech", "B.Com", "M.Com", "B.Sc", "M.Sc", "BA", "MA"]
DEPARTMENTS = ["Computer Applications", "Computer Science", "Information Technology", "Management",
               "Commerce", "Electronics", "Mechanical", "Civil", "Science", "Arts"]
ROOM_TYPES = {"Single": 1, "Double": 2, "Triple": 3, "Dormitory": 4}      # type -> (minimum) beds
FEE_TYPES = ["Hostel Rent", "Mess Fee", "Security Deposit", "Electricity Charges",
             "Maintenance Charges", "Late Fine", "Other"]
PAYMENT_METHODS = ["Cash", "UPI", "Card", "Bank Transfer", "Cheque"]
FEE_STATUSES = ["Paid", "Pending", "Partial", "Overdue"]
COMPLAINT_CATEGORIES = ["Maintenance", "Electrical", "Plumbing", "Cleanliness", "Mess / Food",
                        "Internet / Wi-Fi", "Security", "Noise", "Other"]
COMPLAINT_STATUSES = ["Pending", "In Progress", "Resolved"]
PRIORITIES = ["Low", "Medium", "High"]
RELATIONSHIPS = ["Father", "Mother", "Brother", "Sister", "Guardian", "Relative", "Friend", "Other"]
STAFF_ROLES = ["Warden", "Assistant Warden", "Security Guard", "Cook", "Cleaner",
               "Maintenance", "Accountant", "Other"]
STAFF_STATUSES = ["Active", "Inactive"]


# ============================================================== 2. VALIDATORS
def clean(value):
    """Trim whitespace; None becomes an empty string."""
    return (value or "").strip()


def normalize_phone(raw):
    """Accept an Indian mobile number (optionally +91 / 0 prefix); return 10 digits or None."""
    digits = re.sub(r"[\s\-()]", "", raw or "")
    digits = re.sub(r"^(\+91|91|0)(?=\d{10}$)", "", digits)
    return digits if re.fullmatch(r"[6-9]\d{9}", digits) else None


EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


def valid_email(value):
    return bool(EMAIL_RE.fullmatch(value)) and len(value) <= 120


def parse_date(value):
    """'2026-10-01' -> date, or None when empty/invalid."""
    try:
        return datetime.strptime(clean(value), "%Y-%m-%d").date()
    except ValueError:
        return None


def parse_time(value):
    try:
        return datetime.strptime(clean(value), "%H:%M").strftime("%H:%M")
    except ValueError:
        return None


def parse_amount(value, allow_zero=False, maximum=10_000_000):
    """'1500' / '1500.50' -> float with 2 decimals, or None when invalid."""
    value = clean(value).replace(",", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", value):
        return None
    amount = round(float(value), 2)
    if amount > maximum or (amount == 0 and not allow_zero):
        return None
    return amount


def parse_int(value, low=None, high=None):
    try:
        number = int(clean(value))
    except ValueError:
        return None
    if (low is not None and number < low) or (high is not None and number > high):
        return None
    return number


def today():
    return date.today().isoformat()


def calc_age(dob_text):
    born = parse_date(dob_text)
    if not born:
        return None
    t = date.today()
    return t.year - born.year - ((t.month, t.day) < (born.month, born.day))


def valid_person_name(name):
    return 2 <= len(name) <= 100 and not re.search(r"\d", name)


# ============================================================== 3. PAGINATION
PER_PAGE = 10


def paginate(sql, params, page, per_page=PER_PAGE):
    """Run `sql` one page at a time. Returns (rows, info-dict for the pager)."""
    database = db.get_db()
    total = database.execute(f"SELECT COUNT(*) FROM ({sql})", params).fetchone()[0]
    pages = max(1, math.ceil(total / per_page))
    page = min(max(page, 1), pages)
    rows = database.execute(f"{sql} LIMIT ? OFFSET ?",
                            (*params, per_page, (page - 1) * per_page)).fetchall()
    first = (page - 1) * per_page + 1 if total else 0
    return rows, {"page": page, "pages": pages, "total": total,
                  "first": first, "last": first + len(rows) - 1 if total else 0}


def page_number():
    return parse_int(request.args.get("page", "1"), low=1) or 1


def where(conditions):
    """['a = ?', 'b = ?'] -> ' WHERE a = ? AND b = ?'  (or '' when empty)."""
    return " WHERE " + " AND ".join(conditions) if conditions else ""


def like(text):
    """Escape LIKE wildcards typed by the user and wrap for a 'contains' search."""
    return "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


# ================================================================ 4. SECURITY
def csrf_token():
    """One random token per session; every POST form must send it back."""
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


def check_csrf():
    sent = request.form.get("_csrf") or request.headers.get("X-CSRFToken")
    if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
        abort(400, "Your session token is missing or expired. Please go back, reload the page and try again.")


def safe_next_url(target):
    """Only allow redirects to our own pages (prevents open-redirect attacks)."""
    if target and target.startswith("/") and not target.startswith("//"):
        return target
    return None


# =========================================== 5. TEMPLATE FILTERS / FUNCTIONS
def inr(value):
    """1234567.5 -> ₹12,34,567.50 (Indian digit grouping)."""
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return "₹0.00"
    sign = "-" if number < 0 else ""
    whole, frac = f"{abs(number):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        whole = ",".join(parts) + "," + tail
    return f"{sign}₹{whole}.{frac}"


def inr0(value):
    """Whole rupees for compact dashboard cards: 122500 -> ₹1,22,500."""
    return inr(round(float(value or 0))).rsplit(".", 1)[0]


def fmt_date(value):
    d = parse_date(value) if value else None
    return d.strftime("%d %b %Y") if d else "-"


def fmt_datetime(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").strftime("%d %b %Y, %I:%M %p")
    except (TypeError, ValueError):
        return "-"


def fmt_time(value):
    try:
        return datetime.strptime(value, "%H:%M").strftime("%I:%M %p")
    except (TypeError, ValueError):
        return "-"


def student_age(row):
    """Age is recalculated from the date of birth, so it never goes stale."""
    return calc_age(row["dob"]) if row["dob"] else row["age"]


_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven",
         "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _below_thousand(n):
    words = []
    if n >= 100:
        words.append(_ONES[n // 100] + " Hundred")
        n %= 100
    if n >= 20:
        words.append(_TENS[n // 10] + ("-" + _ONES[n % 10] if n % 10 else ""))
    elif n > 0:
        words.append(_ONES[n])
    return " ".join(words)


def amount_in_words(value):
    """1250.50 -> 'Rupees One Thousand Two Hundred Fifty and Fifty Paise Only'."""
    rupees, paise = divmod(int(round(float(value) * 100)), 100)
    if rupees == 0 and paise == 0:
        return "Rupees Zero Only"
    parts = []
    for name, size in (("Crore", 10_000_000), ("Lakh", 100_000), ("Thousand", 1_000)):
        if rupees >= size:
            parts.append(_below_thousand(rupees // size) + " " + name)
            rupees %= size
    if rupees:
        parts.append(_below_thousand(rupees))
    text = "Rupees " + " ".join(parts) if parts else "Rupees Zero"
    if paise:
        text += f" and {_below_thousand(paise)} Paise"
    return text + " Only"


# Feather-style outline icons, inlined so the app works without internet.
_ICONS = {
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    "users": '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/>',
    "user": '<path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/>',
    "key": '<path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/>',
    "bed": '<path d="M2 20v-9a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v9"/><path d="M2 16h20"/><path d="M6 9V6a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v3"/>',
    "card": '<rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/>',
    "check-square": '<polyline points="9 11 12 14 22 4"/><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"/>',
    "alert": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/>',
    "login": '<path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/>',
    "briefcase": '<rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/>',
    "chart": '<line x1="18" y1="20" x2="18" y2="10"/><line x1="12" y1="20" x2="12" y2="4"/><line x1="6" y1="20" x2="6" y2="14"/>',
    "logout": '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "search": '<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>',
    "edit": '<path d="M12 20h9"/><path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z"/>',
    "trash": '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    "eye": '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
    "eye-off": '<path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19m-6.72-1.07a3 3 0 1 1-4.24-4.24"/><line x1="1" y1="1" x2="23" y2="23"/>',
    "printer": '<polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "menu": '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
    "x": '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "check-circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    "arrow-left": '<line x1="19" y1="12" x2="5" y2="12"/><polyline points="12 19 5 12 12 5"/>',
    "calendar": '<rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/>',
    "clock": '<circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/>',
    "mail": '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    "lock": '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    "sliders": '<line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/>',
    "building": '<path d="M3 21V9l9-6 9 6v12"/><path d="M9 21v-6h6v6"/><line x1="3" y1="21" x2="21" y2="21"/>',
    "wallet": '<path d="M20 12V8H6a2 2 0 0 1-2-2c0-1.1.9-2 2-2h12v4"/><path d="M4 6v12c0 1.1.9 2 2 2h14v-4"/><path d="M18 12a2 2 0 0 0-2 2c0 1.1.9 2 2 2h4v-4h-4z"/>',
    "phone": '<path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07 19.5 19.5 0 0 1-6-6 19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 4.11 2h3a2 2 0 0 1 2 1.72c.13.96.36 1.9.7 2.81a2 2 0 0 1-.45 2.11L8.09 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45c.91.34 1.85.57 2.81.7A2 2 0 0 1 22 16.92z"/>',
}


def icon(name, size=18):
    path = _ICONS.get(name, _ICONS["file"])
    return Markup(f'<svg class="icon" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
                  f'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                  f'stroke-linejoin="round" aria-hidden="true">{path}</svg>')


def url_with(**changes):
    """Current URL with some query parameters changed (None removes one). Used by pager & exports."""
    args = request.args.to_dict()
    for key, value in changes.items():
        if value is None:
            args.pop(key, None)
        else:
            args[key] = value
    return url_for(request.endpoint, **(request.view_args or {}), **args)


def student_pairs(rows):
    """Rows -> [(id, 'Name (STU-0001)')] for dropdowns."""
    return [(r["id"], f"{r['full_name']} ({r['student_code']})") for r in rows]


def room_pairs(rows):
    """Room rows -> [(id, '101 - Double, floor 1 (1 free)')] for dropdowns."""
    return [(r["id"], f"{r['room_no']} - {r['room_type']}, floor {r['floor']} ({r['available']} free)")
            for r in rows]


def init_app(app):
    app.jinja_env.filters.update(inr0=inr0, student_pairs=student_pairs, room_pairs=room_pairs, inr=inr, fmt_date=fmt_date, fmt_datetime=fmt_datetime,
                                 fmt_time=fmt_time, student_age=student_age,
                                 amount_in_words=amount_in_words)
    app.jinja_env.globals.update(icon=icon, csrf_token=csrf_token, url_with=url_with,
                                 GENDERS=GENDERS, today=today)


def search_clause(columns, text):
    """Build '(col1 LIKE ? OR col2 LIKE ?)' for a free-text search box."""
    condition = "(" + " OR ".join(f"{c} LIKE ? ESCAPE '\\'" for c in columns) + ")"
    return condition, [like(text)] * len(columns)


def password_problem(password):
    """Return a message when the password is too weak, otherwise None."""
    if len(password) < 8:
        return "Password must be at least 8 characters long."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Password must contain at least one letter and one number."
    return None


USERNAME_RE = re.compile(r"[A-Za-z0-9_.]{3,30}")
